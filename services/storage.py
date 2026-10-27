"""
MinIO Storage Service: S3-compatible object storage for document files.

Module Purpose & Role in the Project:
-------------------------------------
Provides high-performance, S3-compatible object storage abstractions for physical document
payloads (PDFs, JPEGs, PNGs, TIFFs) uploaded during customer onboarding flows. It acts as
the immutable object storage substrate for the system, replacing local disk file systems.

Interconnections with Other Subsystems:
- Fast API Routes:
  * `app.routes.documents`: Called by `upload_document` for streaming raw payload bytes into MinIO,
    `delete_document` to prune objects, and `download_document` / `view_document` / presigned URL
    generators to stream file bytes back to clients.
  * `app.routes.wizard`: Called during multi-step wizard application flows to store and remove
    verified identity document payloads (e.g., Emirates ID, Passport).
  * `app.main`: Lifecycle hooks test connectivity (`storage.check_connection()`, `storage.connect()`)
    and periodic health reporting routes expose storage connectivity status.
- Database & Repository Layer:
  * `services.database.DatabaseService.delete_application`: Calls `storage.delete_file` for every
    associated MinIO object key during cascading application deletion.
  * `services.repository.Repository`: Works in tandem with storage by tracking document metadata
    (object_name, content_hash, file_size) in the PostgreSQL `documents` table while binary bytes
    reside in MinIO.
- Validation Pipeline:
  * `services.file_validation`: Validates magic numbers and antivirus checks in-memory before
    dispatching the safe byte stream to `StorageService.upload_file`.

Failure behaviour (fixes the "'NoneType' object has no attribute 'put_object'" crash):
- The constructor never raises and never throws the client away. If MinIO cannot be
  reached it records the reason and stays "disconnected".
- Every operation first calls require(), which retries the connection (rate limited)
  and raises StorageUnavailable if MinIO is still down. Routes turn that into HTTP 503
  with a friendly message instead of a 500 crash.
- There is NO silent fallback to the local filesystem. Identity documents must only
  ever be stored in the encrypted object store.
"""

import io
import os
import time
import logging
import threading
from contextlib import contextmanager
from datetime import timedelta
from typing import Optional, BinaryIO, List, Dict, Any

try:
    import urllib3
    from minio import Minio
    from minio.error import S3Error
    _MINIO_OK = True
except ImportError:  # pragma: no cover
    urllib3 = None  # type: ignore
    Minio = None  # type: ignore
    _MINIO_OK = False

    class S3Error(Exception):  # type: ignore
        """Placeholder so except clauses still work when minio is missing."""
        code = "MinioNotInstalled"

logger = logging.getLogger(__name__)

_RECONNECT_COOLDOWN_SECONDS = 3.0
_NETWORK_ERRORS = ((urllib3.exceptions.HTTPError, OSError) if _MINIO_OK else (OSError,))


class StorageError(Exception):
    """Storage is reachable but the operation failed."""


class StorageNotFound(StorageError):
    """The requested object does not exist in MinIO object storage."""


class StorageUnavailable(StorageError):
    """Storage cannot be reached right now. Routes should return HTTP 503."""

    user_message = "File storage is temporarily unavailable. Please try again in a moment."


class StorageService:
    """MinIO object storage service for document files.

    Responsibility:
    - Encapsulates low-level S3/MinIO SDK operations (upload, download, delete, presigned URLs).
    - Guarantees resilient fail-soft connection pooling, automatic retries with exponential backoff,
      and strict verification of byte counts on uploads to prevent corrupt or partial storage.
    - Ensures that files are only ever stored in the secure object bucket rather than unsafe local paths.

    State Attributes:
    - endpoint (str): MinIO host:port network endpoint.
    - secure (bool): Flag indicating TLS/HTTPS or plain HTTP connection.
    - access_key (str): S3 access key identity.
    - secret_key (str): S3 secret key credential.
    - bucket_name (str): The target bucket where onboarding files are isolated.
    - part_size (int): Chunk size in bytes for multipart uploads (default 5 MiB).
    - client (Optional[Minio]): Initialized MinIO client instance.
    - _connected (bool): Thread-safe boolean indicating active bucket reachability.
    - _last_error (Optional[str]): Clean descriptive message of the most recent failure.
    - _last_attempt (float): Monotonic timestamp of the last connection or reconnection attempt.
    - _lock (threading.Lock): Mutex guarding concurrent reconnection workflows.

    Interactions:
    - Consumed by `app.routes.documents` during upload, download, and deletion endpoints.
    - Consumed by `app.routes.wizard` during document stage processing.
    - Consumed by `services.database.DatabaseService.delete_application` to cascade object purge.
    - Monitored by `app.main` health checks and readiness probes.
    """

    def __init__(self, config: dict):
        """Initialize the StorageService with configuration and prepare client connection.

        Args:
            config (dict): Configuration dictionary containing storage settings
                ('endpoint', 'secure', 'access_key', 'secret_key', 'bucket_name', 'part_size_mb').
                Falls back to environment variables (`MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, etc.)
                if keys are not present in config.

        Interconnections:
            Called during application factory startup in `app.main:lifespan` or service bootstrap.
        """
        config = config or {}
        endpoint = str(config.get("endpoint") or os.getenv("MINIO_ENDPOINT") or "127.0.0.1:9000").strip()
        secure = config.get("secure", os.getenv("MINIO_SECURE", "false"))
        self.secure = str(secure).lower() in ("1", "true", "yes")

        # MinIO() rejects endpoints that contain a scheme or a path. A very common config slip.
        for scheme, is_secure in (("https://", True), ("http://", False)):
            if endpoint.lower().startswith(scheme):
                endpoint = endpoint[len(scheme):]
                self.secure = is_secure
        self.endpoint = endpoint.rstrip("/")

        self.access_key = config.get("access_key") or os.getenv("MINIO_ACCESS_KEY") or "minioadmin"
        self.secret_key = config.get("secret_key") or os.getenv("MINIO_SECRET_KEY") or "minioadmin_secret_2026"
        if not config.get("access_key") and not os.getenv("MINIO_ACCESS_KEY"):
            logger.warning("MinIO credentials not set in config.yaml or MINIO_ACCESS_KEY/MINIO_SECRET_KEY; "
                           "using development defaults. Set real credentials.")
        self.bucket_name = config.get("bucket_name") or os.getenv("MINIO_BUCKET") or "onboarding-docs"
        self.part_size = int(config.get("part_size_mb", 5)) * 1024 * 1024  # MinIO minimum is 5 MiB

        self.client = None
        self._connected = False
        self._last_error: Optional[str] = None
        self._last_attempt = 0.0
        self._lock = threading.Lock()

        if not _MINIO_OK:
            self._last_error = "minio package not installed (pip install minio)"
            logger.error(self._last_error)
            return

        try:
            http_client = urllib3.PoolManager(
                timeout=urllib3.Timeout(connect=3.0, read=60.0),
                retries=urllib3.Retry(total=2, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504]),
            )
            self.client = Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
                http_client=http_client,
            )
        except Exception as e:
            self._last_error = f"invalid storage configuration: {type(e).__name__}: {e}"
            logger.error(self._last_error)
            return

        self.connect()

    # ------------------------------------------------------------------ #
    #  Connection management                                               #
    # ------------------------------------------------------------------ #

    @property
    def is_connected(self) -> bool:
        """Check whether storage client is initialized and currently marked as connected.

        Returns:
            bool: True if MinIO is configured and reachable, False otherwise.

        Interconnections:
            Queried by `app.main:health_check` to report overall system health.
        """
        return bool(self._connected and self.client is not None)

    @staticmethod
    def _describe(e: Exception) -> str:
        """Produce a sanitized, secret-free description of an exception for logging.

        Args:
            e (Exception): The raw exception raised during an S3/MinIO or network call.

        Returns:
            str: Safe, human-readable error summary without exposing secrets.
        """
        if isinstance(e, S3Error):
            code = getattr(e, "code", "S3Error")
            if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch", "AccessDenied"):
                return f"credentials rejected by MinIO ({code}); check access_key/secret_key"
            return f"MinIO error {code}"
        return f"{type(e).__name__}: {str(e)[:200]}"

    def connect(self) -> bool:
        """(Re)try the connection and make sure the bucket exists. Never raises.

        Attempts to verify bucket existence using `bucket_exists()`, and automatically creates
        the target bucket if it does not yet exist. Updates `_connected` status thread-safely.

        Returns:
            bool: True if connection and bucket verification succeeded, False otherwise.

        Interconnections:
            Called during initialization and retried periodically by `require()` and background
            health pollers in `app.main`.
        """
        if self.client is None:
            return False
        with self._lock:
            self._last_attempt = time.monotonic()
            try:
                if not self.client.bucket_exists(self.bucket_name):
                    self.client.make_bucket(self.bucket_name)
                    logger.info(f"Created MinIO bucket: {self.bucket_name}")
                if not self._connected:
                    logger.info(f"Connected to MinIO at {self.endpoint}, bucket '{self.bucket_name}'")
                self._connected = True
                self._last_error = None
            except Exception as e:
                self._connected = False
                self._last_error = self._describe(e)
                logger.warning(f"MinIO not reachable at {self.endpoint}: {self._last_error}")
            return self._connected

    def require(self) -> None:
        """Make sure storage is usable, retrying the connection if needed.

        Raises:
            StorageUnavailable: When MinIO is unreachable or client unconfigured.

        Interconnections:
            Called at the start of every read/write operation via `_guard()`. FastAPI routes
            catch `StorageUnavailable` and convert it into clean HTTP 503 Service Unavailable responses.
        """
        if self.client is None:
            raise StorageUnavailable(self._last_error or "storage client not configured")
        if not self._connected and time.monotonic() - self._last_attempt >= _RECONNECT_COOLDOWN_SECONDS:
            self.connect()
        if not self._connected:
            raise StorageUnavailable(self._last_error or "MinIO not reachable")

    def _mark_down(self, e: Exception) -> None:
        """Mark storage as offline and record the diagnostic error description.

        Args:
            e (Exception): The exception that caused the connection to drop.
        """
        self._connected = False
        self._last_error = self._describe(e)
        logger.warning(f"MinIO connection lost: {self._last_error}")

    @contextmanager
    def _guard(self, what: str):
        """Context manager translating low-level S3/network errors into domain exceptions.

        Args:
            what (str): Description of the operation being attempted (for logging and errors).

        Yields:
            None: Executes the wrapped storage operation.

        Raises:
            StorageNotFound: When the requested object or bucket is not found.
            StorageUnavailable: When network failure or authentication failure occurs.
            StorageError: On unexpected S3 errors.
        """
        self.require()
        try:
            yield
        except S3Error as e:
            code = getattr(e, "code", "S3Error")
            logger.error(f"MinIO error during {what}: {code}")
            if code in ("NoSuchKey", "NoSuchObject", "NoSuchBucket"):
                raise StorageNotFound(f"{what}: {code}") from e
            if code in ("InvalidAccessKeyId", "SignatureDoesNotMatch"):
                self._mark_down(e)
                raise StorageUnavailable(self._last_error) from e
            raise StorageError(f"{what} failed: {code}") from e
        except _NETWORK_ERRORS as e:
            self._mark_down(e)
            raise StorageUnavailable(self._last_error) from e

    @staticmethod
    def _safe_key(object_name: str) -> str:
        """Sanitize an object key, preventing directory traversal and malformed paths.

        Args:
            object_name (str): Raw object name or key.

        Returns:
            str: Cleaned, normalized object key path.

        Raises:
            ValueError: If object name contains '..' or exceeds maximum allowable length.
        """
        key = (object_name or "").replace("\\", "/").lstrip("/")
        if not key or ".." in key.split("/") or len(key) > 1024:
            raise ValueError("invalid object name")
        return key

    # ------------------------------------------------------------------ #
    #  Upload                                                              #
    # ------------------------------------------------------------------ #

    def upload_file(
        self,
        file_data: bytes,
        object_name: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Upload file bytes to MinIO and verify they arrived intact.

        Stores raw bytes in the configured bucket, queries the object metadata to verify
        that the stored size matches the input size, and removes the object if verification fails.

        Args:
            file_data (bytes): Non-empty raw byte content of the document.
            object_name (str): Destination key within the MinIO bucket (e.g. 'user_id/app_id/doc.pdf').
            content_type (str): MIME type of the payload (e.g. 'application/pdf', 'image/jpeg').
            metadata (Optional[Dict[str, str]]): Custom S3 metadata tags attached to object.

        Returns:
            Dict[str, Any]: Serialisable dictionary containing:
                - 'object_name': Normalized object key
                - 'size': Verified object byte count
                - 'etag': S3 ETag verification hash
                - 'content_type': Upload MIME type

        Raises:
            ValueError: If `file_data` is empty or `object_name` is invalid.
            StorageUnavailable: If MinIO is offline.
            StorageError: On size mismatch or storage write error.

        Interconnections:
            Called by:
            - `app.routes.documents.upload_document`: After passing `file_validation.py` antivirus/type checks.
            - `app.routes.wizard.upload_wizard_document`: When uploading ID documents in wizard mode.
            - `migrate_from_filesystem()`: During migration of legacy disk files.
        """
        if not file_data:
            raise ValueError("refusing to store an empty file")
        key = self._safe_key(object_name)
        meta = {str(k): str(v) for k, v in (metadata or {}).items()}

        with self._guard(f"upload {key}"):
            result = self.client.put_object(
                self.bucket_name,
                key,
                data=io.BytesIO(file_data),
                length=len(file_data),
                content_type=content_type,
                part_size=self.part_size,
                metadata=meta,
            )
            info = self.client.stat_object(self.bucket_name, key)

        if info.size != len(file_data):
            # Never leave a partial object that could be mistaken for the real document
            try:
                self.client.remove_object(self.bucket_name, key)
            except Exception:
                logger.error(f"Could not remove partial object {key}")
            raise StorageError(f"upload verification failed for {key}: size mismatch")

        logger.info(f"Uploaded {key} to MinIO (size={info.size})")
        return {
            "object_name": key,
            "size": info.size,
            "etag": getattr(result, "etag", None) or info.etag,
            "content_type": content_type,
        }

    # ------------------------------------------------------------------ #
    #  Download                                                            #
    # ------------------------------------------------------------------ #

    def download_file(self, object_name: str) -> bytes:
        """Download complete file byte stream from MinIO object storage.

        Args:
            object_name (str): Object key stored in bucket.

        Returns:
            bytes: Binary payload of the requested document.

        Raises:
            StorageNotFound: If the object key does not exist.
            StorageUnavailable: If MinIO is offline.
            StorageError: On read failure.

        Interconnections:
            Called by:
            - `app.routes.documents.download_document`: Returning download attachment to users.
            - `app.routes.documents.view_document`: Returning inline preview to users.
        """
        key = self._safe_key(object_name)
        with self._guard(f"download {key}"):
            response = self.client.get_object(self.bucket_name, key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

    def download_to_stream(self, object_name: str) -> BinaryIO:
        """Download file and return it as a seekable in-memory binary stream.

        Args:
            object_name (str): Object key stored in bucket.

        Returns:
            BinaryIO: Seekable `io.BytesIO` stream containing file bytes.

        Interconnections:
            Used when passing document streams directly to image processors or parsers.
        """
        return io.BytesIO(self.download_file(object_name))

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    def delete_file(self, object_name: str) -> bool:
        """Delete an object file from MinIO storage.

        Args:
            object_name (str): Object key to remove.

        Returns:
            bool: True on successful deletion.

        Raises:
            StorageUnavailable: If MinIO is offline.
            StorageError: On deletion failure.

        Interconnections:
            Called by:
            - `app.routes.documents.delete_document`: When user deletes an uploaded document.
            - `services.database.DatabaseService.delete_application`: During cascade delete of application.
            - `app.routes.wizard.cancel_wizard_session`: Cleaning up discarded drafts.
        """
        key = self._safe_key(object_name)
        with self._guard(f"delete {key}"):
            self.client.remove_object(self.bucket_name, key)
        logger.info(f"Deleted {key} from MinIO")
        return True

    # ------------------------------------------------------------------ #
    #  List                                                                #
    # ------------------------------------------------------------------ #

    def list_files(self, prefix: str = "", recursive: bool = True) -> List[Dict[str, Any]]:
        """List files stored in the bucket, optionally filtered by prefix.

        Args:
            prefix (str): Directory prefix filter (e.g. 'user_123/').
            recursive (bool): Whether to recursively traverse nested folders.

        Returns:
            List[Dict[str, Any]]: List of metadata dicts containing 'object_name',
            'size', 'last_modified', and 'etag'.

        Interconnections:
            Useful for administrative auditing and storage synchronization tasks.
        """
        with self._guard(f"list {prefix!r}"):
            return [
                {
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                    "etag": obj.etag,
                }
                for obj in self.client.list_objects(self.bucket_name, prefix=prefix, recursive=recursive)
            ]

    # ------------------------------------------------------------------ #
    #  Presigned URLs                                                      #
    # ------------------------------------------------------------------ #

    def generate_presigned_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
        method: str = "GET",
    ) -> str:
        """Generate a time-limited presigned GET URL for secure direct client download.

        Args:
            object_name (str): Target object key.
            expires (timedelta): Expiration duration (default 1 hour).
            method (str): HTTP method ('GET').

        Returns:
            str: Presigned HTTPS/HTTP URL allowing authorized access.

        Interconnections:
            Called by `app.routes.documents.get_presigned_url` after verifying that the
            requesting user owns the target application and document.
        """
        key = self._safe_key(object_name)
        with self._guard(f"presign {key}"):
            return self.client.presigned_get_object(self.bucket_name, key, expires=expires)

    def generate_presigned_upload_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        """Generate a presigned PUT URL allowing direct browser-to-bucket upload.

        Args:
            object_name (str): Target object destination key.
            expires (timedelta): Expiration duration (default 1 hour).
            content_type (str): Expected MIME type for uploaded payload.

        Returns:
            Dict[str, Any]: Dictionary containing 'url', 'method', 'object_name', 'content_type'.

        Note:
            Bypasses server-side validation; direct uploads should be accompanied by
            asynchronous validation workers before documents are marked valid.
        """
        key = self._safe_key(object_name)
        with self._guard(f"presign upload {key}"):
            url = self.client.presigned_put_object(self.bucket_name, key, expires=expires)
        return {"url": url, "method": "PUT", "object_name": key, "content_type": content_type}

    # ------------------------------------------------------------------ #
    #  Object info                                                         #
    # ------------------------------------------------------------------ #

    def get_object_info(self, object_name: str) -> Dict[str, Any]:
        """Retrieve metadata attributes for a stored object without downloading its payload.

        Args:
            object_name (str): Object key in storage.

        Returns:
            Dict[str, Any]: Dictionary containing 'object_name', 'size', 'content_type',
            'last_modified', 'etag', and 'metadata'.

        Raises:
            StorageNotFound: If the object does not exist.
            StorageUnavailable: If MinIO is unreachable.
        """
        key = self._safe_key(object_name)
        with self._guard(f"stat {key}"):
            info = self.client.stat_object(self.bucket_name, key)
        return {
            "object_name": key,
            "size": info.size,
            "content_type": info.content_type or "application/octet-stream",
            "last_modified": info.last_modified.isoformat() if info.last_modified else None,
            "etag": info.etag,
            "metadata": dict(info.metadata) if info.metadata else {},
        }

    # ------------------------------------------------------------------ #
    #  Health                                                              #
    # ------------------------------------------------------------------ #

    def check_connection(self) -> str:
        """Perform a live health probe against MinIO.

        Returns:
            str: "healthy" if bucket is reachable, or "unavailable (<reason>)" on error.

        Interconnections:
            Called by `app.main:health_check` endpoint and startup lifecycle checks.
        """
        if self.client is None:
            return f"unavailable ({self._last_error or 'not configured'})"
        try:
            self.client.bucket_exists(self.bucket_name)
            self._connected = True
            self._last_error = None
            return "healthy"
        except Exception as e:
            self._mark_down(e)
            return f"unavailable ({self._last_error})"

    def status(self) -> Dict[str, Any]:
        """Produce safe summary for a health endpoint without leaking credentials or raw errors.

        Returns:
            Dict[str, Any]: Dict with 'connected' (bool) and 'bucket' (str).

        Interconnections:
            Exposed on `/api/health` status outputs.
        """
        return {"connected": self.is_connected, "bucket": self.bucket_name}

    # ------------------------------------------------------------------ #
    #  Migration helper                                                    #
    # ------------------------------------------------------------------ #

    def migrate_from_filesystem(self, upload_dir: str = "uploads") -> Dict[str, Any]:
        """Migrate legacy files from the local filesystem directory into MinIO storage.

        Iterates through files in `upload_dir`, uploads each file using `upload_file`,
        and only removes the local file once the stored object size is verified.

        Args:
            upload_dir (str): Relative or absolute path to the local directory (default 'uploads').

        Returns:
            Dict[str, Any]: Summary containing 'uploaded_count', 'skipped_count', and 'errors'.

        Interconnections:
            Can be invoked during database and storage deployment migration scripts.
        """
        result: Dict[str, Any] = {"uploaded_count": 0, "skipped_count": 0, "errors": []}
        if not os.path.isdir(upload_dir):
            logger.info(f"No uploads directory found at {upload_dir}, skipping migration")
            return result

        mime_map = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".tiff": "image/tiff", ".bmp": "image/bmp"}
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
                if not data:
                    result["skipped_count"] += 1
                    continue
                content_type = mime_map.get(os.path.splitext(fname)[1].lower(), "application/octet-stream")
                stored = self.upload_file(data, fname, content_type)   # verifies size itself
                if stored["size"] == len(data):
                    os.remove(fpath)
                    result["uploaded_count"] += 1
            except Exception as e:
                logger.error(f"Migration failed for {fname}: {e}")
                result["errors"].append({"file": fname, "error": str(e)})
        logger.info(f"Migration complete: {result}")
        return result
        result: Dict[str, Any] = {"uploaded_count": 0, "skipped_count": 0, "errors": []}
        if not os.path.isdir(upload_dir):
            logger.info(f"No uploads directory found at {upload_dir}, skipping migration")
            return result

        mime_map = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".tiff": "image/tiff", ".bmp": "image/bmp"}
        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if not os.path.isfile(fpath):
                continue
            try:
                with open(fpath, "rb") as f:
                    data = f.read()
                if not data:
                    result["skipped_count"] += 1
                    continue
                content_type = mime_map.get(os.path.splitext(fname)[1].lower(), "application/octet-stream")
                stored = self.upload_file(data, fname, content_type)   # verifies size itself
                if stored["size"] == len(data):
                    os.remove(fpath)
                    result["uploaded_count"] += 1
            except Exception as e:
                logger.error(f"Migration failed for {fname}: {e}")
                result["errors"].append({"file": fname, "error": str(e)})
        logger.info(f"Migration complete: {result}")
        return result
