"""
MinIO Storage Service — S3-compatible object storage.

Replaces the old local filesystem uploads/ directory.
Supports: upload, download, delete, list, presigned URLs.
Uses the MinIO Python SDK (boto3-compatible API).
"""

import io
import uuid
import logging
from datetime import timedelta
from typing import Optional, BinaryIO, List, Dict, Any

try:
    from minio import Minio
    from minio.error import S3Error
    _MINIO_OK = True
except ImportError:
    Minio = None  # type: ignore
    _MINIO_OK = False

logger = logging.getLogger(__name__)


class StorageService:
    """MinIO object storage service for document files."""

    def __init__(self, config: dict):
        if not _MINIO_OK:
            raise ImportError(
                "minio package not installed. Run: pip install minio"
            )

        self.endpoint = config.get("endpoint", "127.0.0.1:9000")
        self.access_key = config.get("access_key", "minioadmin")
        self.secret_key = config.get("secret_key", "minioadmin_secret_2026")
        self.bucket_name = config.get("bucket_name", "onboarding-docs")
        self.secure = config.get("secure", False)
        self.part_size = config.get("part_size_mb", 5) * 1024 * 1024  # default 5 MB
        self._connected = False

        self.client = Minio(
            self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )

        # Try to ensure bucket exists; if MinIO is down, stay disconnected
        # but don't crash the app — endpoints fall back to filesystem.
        try:
            self._ensure_bucket()
            self._connected = True
        except Exception as e:
            logger.warning(f"MinIO connection failed ({self.endpoint}): {e}. Storage unavailable; will fall back to filesystem.")
            self.client = None

    # ------------------------------------------------------------------ #
    #  Bucket management                                                   #
    # ------------------------------------------------------------------ #

    def _ensure_bucket(self):
        """Create the bucket if it doesn't already exist."""
        try:
            if not self.client.bucket_exists(self.bucket_name):
                self.client.make_bucket(self.bucket_name)
                logger.info(f"Created MinIO bucket: {self.bucket_name}")
            else:
                logger.info(f"MinIO bucket already exists: {self.bucket_name}")
        except Exception as e:
            logger.error(f"Failed to ensure bucket {self.bucket_name}: {e}")
            raise

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
        """Upload file bytes to MinIO.

        Args:
            file_data: Raw file bytes.
            object_name: Key/path inside the bucket (e.g. 'docs/abc123_filename.pdf').
            content_type: MIME type (e.g. 'application/pdf').
            metadata: Optional custom metadata dict.

        Returns:
            Dict with object_name, size, etag, upload_date.
        """
        try:
            stream = io.BytesIO(file_data)
            etag = self.client.put_object(
                self.bucket_name,
                object_name,
                data=stream,
                length=len(file_data),
                content_type=content_type,
                part_size=self.part_size,
                metadata=metadata or {},
            )
            obj_info = self.client.stat_object(self.bucket_name, object_name)
            logger.info(f"Uploaded {object_name} to MinIO (etag={etag}, size={obj_info.size})")
            return {
                "object_name": object_name,
                "size": obj_info.size,
                "etag": etag,
                "content_type": content_type,
            }
        except S3Error as e:
            logger.error(f"MinIO upload error for {object_name}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  Download                                                            #
    # ------------------------------------------------------------------ #

    def download_file(self, object_name: str) -> bytes:
        """Download file bytes from MinIO.

        Returns:
            Raw file bytes.
        """
        try:
            response = self.client.get_object(self.bucket_name, object_name)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except S3Error as e:
            logger.error(f"MinIO download error for {object_name}: {e}")
            raise

    def download_to_stream(self, object_name: str) -> BinaryIO:
        """Download file as a seekable binary stream.

        Returns:
            io.BytesIO stream.
        """
        data = self.download_file(object_name)
        return io.BytesIO(data)

    # ------------------------------------------------------------------ #
    #  Delete                                                              #
    # ------------------------------------------------------------------ #

    def delete_file(self, object_name: str) -> bool:
        """Delete a file from MinIO.

        Returns:
            True if deleted, raises on error.
        """
        try:
            self.client.remove_object(self.bucket_name, object_name)
            logger.info(f"Deleted {object_name} from MinIO")
            return True
        except S3Error as e:
            logger.error(f"MinIO delete error for {object_name}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  List                                                                #
    # ------------------------------------------------------------------ #

    def list_files(
        self,
        prefix: str = "",
        recursive: bool = True,
    ) -> List[Dict[str, Any]]:
        """List files in the bucket (optionally filtered by prefix).

        Returns:
            List of dicts with object_name, size, last_modified, etag.
        """
        try:
            objects = self.client.list_objects(
                self.bucket_name,
                prefix=prefix,
                recursive=recursive,
            )
            result = []
            for obj in objects:
                result.append({
                    "object_name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
                    "etag": obj.etag,
                })
            return result
        except S3Error as e:
            logger.error(f"MinIO list error with prefix={prefix}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  Presigned URLs                                                      #
    # ------------------------------------------------------------------ #

    def generate_presigned_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
        method: str = "GET",
    ) -> str:
        """Generate a presigned URL for downloading a file.

        Useful for direct frontend downloads without routing through the API.
        """
        try:
            url = self.client.presigned_get_object(
                self.bucket_name,
                object_name,
                expires=expires,
            )
            return url
        except S3Error as e:
            logger.error(f"MinIO presigned URL error for {object_name}: {e}")
            raise

    def generate_presigned_upload_url(
        self,
        object_name: str,
        expires: timedelta = timedelta(hours=1),
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        """Generate a presigned PUT URL for direct frontend upload.

        Returns:
            Dict with url, method, object_name, content_type.
        """
        try:
            url = self.client.presigned_put_object(
                self.bucket_name,
                object_name,
                expires=expires,
                request_headers={"Content-Type": content_type},
            )
            return {
                "url": url,
                "method": "PUT",
                "object_name": object_name,
                "content_type": content_type,
            }
        except S3Error as e:
            logger.error(f"MinIO presigned upload URL error for {object_name}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  Object info                                                         #
    # ------------------------------------------------------------------ #

    def get_object_info(self, object_name: str) -> Dict[str, Any]:
        """Get metadata about an object in MinIO.

        Returns:
            Dict with size, content_type, last_modified, etag.
        """
        try:
            obj_info = self.client.stat_object(self.bucket_name, object_name)
            return {
                "object_name": object_name,
                "size": obj_info.size,
                "content_type": obj_info.content_type or "application/octet-stream",
                "last_modified": obj_info.last_modified.isoformat() if obj_info.last_modified else None,
                "etag": obj_info.etag,
                "metadata": dict(obj_info.metadata) if obj_info.metadata else {},
            }
        except S3Error as e:
            logger.error(f"MinIO stat error for {object_name}: {e}")
            raise

    # ------------------------------------------------------------------ #
    #  Health                                                              #
    # ------------------------------------------------------------------ #

    def check_connection(self) -> str:
        """Check if MinIO connection is healthy.

        Returns:
            "healthy", "unavailable", or "error: <details>".
        """
        if not self._connected or self.client is None:
            return "unavailable (MinIO not connected)"
        try:
            self.client.bucket_exists(self.bucket_name)
            return "healthy"
        except Exception as e:
            logger.warning(f"MinIO health check failed: {e}")
            return f"unavailable ({str(e)[:100]})"

    # ------------------------------------------------------------------ #
    #  Migration helper                                                    #
    # ------------------------------------------------------------------ #

    def migrate_from_filesystem(self, upload_dir: str = "uploads") -> Dict[str, Any]:
        """Migrate existing files from local filesystem to MinIO.

        Scans the uploads/ directory and uploads each file to MinIO.
        Useful when switching from filesystem storage to MinIO.

        Returns:
            Dict with uploaded_count, skipped_count, errors.
        """
        import os
        result = {"uploaded_count": 0, "skipped_count": 0, "errors": []}

        if not os.path.isdir(upload_dir):
            logger.info(f"No uploads directory found at {upload_dir}, skipping migration")
            return result

        for fname in os.listdir(upload_dir):
            fpath = os.path.join(upload_dir, fname)
            if not os.path.isfile(fpath):
                continue

            try:
                with open(fpath, "rb") as f:
                    file_data = f.read()

                # Determine content type from extension
                ext = os.path.splitext(fname)[1].lower()
                mime_map = {
                    ".pdf": "application/pdf",
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".tiff": "image/tiff",
                    ".bmp": "image/bmp",
                }
                content_type = mime_map.get(ext, "application/octet-stream")

                self.upload_file(
                    file_data=file_data,
                    object_name=fname,
                    content_type=content_type,
                )
                result["uploaded_count"] += 1
                # Optionally remove from filesystem after successful upload
                os.remove(fpath)

            except Exception as e:
                logger.error(f"Migration failed for {fname}: {e}")
                result["errors"].append({"file": fname, "error": str(e)})

        logger.info(f"Migration complete: {result}")
        return result
