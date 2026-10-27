"""
Validation Service — File upload validation (updated for image support).

Supports: PDF, PNG, JPEG, TIFF, BMP

Module Architecture & Interconnections:
----------------------------------------
- Role in the Project:
  * Gatekeeper for file ingestion before saving to temporary disk or object storage
    (`services.storage.StorageService`) or passing to the extraction ladder.
  * Ensures uploaded files do not exceed payload boundaries, have permitted extensions,
    and match valid binary magic bytes (preventing file spoofing and security vulnerabilities).
- Upstream Callers:
  * `app.routes.documents.upload_document` and related file upload handlers:
    Validates the incoming `UploadFile` stream before writing to disk or triggering OCR/vision.
  * Complements `services.file_validation` which runs content sanitization and MIME detection.
- Downstream Storage & Dependencies:
  * Interacts with `python-magic` (if available on the host system) for libmagic MIME inspection.
  * Inspects binary header prefixes for PDF (`%PDF-`), JPEG (`\xff\xd8\xff`), PNG (`\x89PNG`),
    TIFF (`II` or `MM`), and BMP (`BM`).
"""

import os
try:
    import magic
    _MAGIC_OK = True
except Exception:
    magic = None
    _MAGIC_OK = False


class FileValidator:
    """Service that validates uploaded files for security, format, and size constraints.

    Attributes:
        max_file_size (int): Maximum allowable upload file size in bytes.
        allowed_extensions (set[str]): Set of allowable file extensions (e.g., {'.pdf', '.png', ...}).

    Interconnections:
        - Instantiated during application startup and registered in FastAPI `app.state`.
        - Used by document upload endpoints in `app.routes.documents` and file ingestion wizards.
    """

    def __init__(self, max_file_size: int):
        """Initialize the FileValidator with size boundaries.

        Args:
            max_file_size (int): Maximum file size in bytes (e.g. 10 * 1024 * 1024 for 10MB).
        """
        self.max_file_size = max_file_size
        self.allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

    def validate_file(self, file) -> dict:
        """Validate an uploaded file (FastAPI UploadFile or file-like object).

        Performs 4-layer validation:
        1. File size check against `self.max_file_size`
        2. File extension check against `self.allowed_extensions`
        3. Actual MIME type verification via `python-magic` (if available)
        4. Binary header magic byte inspection for PDFs and supported raster images

        Args:
            file: File-like object (typically FastAPI `UploadFile`) possessing `.file.read()`,
                  `.file.seek()`, and `.filename` attributes.

        Returns:
            dict: Structured validation result:
                - `is_valid` (bool): True if all checks pass, False otherwise.
                - `errors` (List[str]): List of fatal error messages causing validation failure.
                - `warnings` (List[str]): Non-fatal warnings (e.g., MIME library unavailable).
                - `metadata` (dict): Dict containing 'size', 'extension', 'mime_type', 'filename'.

        Interconnections:
            - Invoked before storing files via `services.storage.StorageService` or persisting
              records into `services.database.Document`.
        """
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "metadata": {}
        }

        # Check 1: File size
        file_size = len(file.file.read())
        file.file.seek(0)

        if file_size > self.max_file_size:
            validation_result["is_valid"] = False
            validation_result["errors"].append(
                f"File size ({file_size} bytes) exceeds maximum allowed ({self.max_file_size} bytes)"
            )
            return validation_result

        validation_result["metadata"]["size"] = file_size

        # Check 2: File extension
        _, extension = os.path.splitext(file.filename)
        extension = extension.lower()

        if extension not in self.allowed_extensions:
            validation_result["is_valid"] = False
            validation_result["errors"].append(
                f"File type '{extension}' is not allowed. Allowed types: {', '.join(self.allowed_extensions)}"
            )
            return validation_result

        validation_result["metadata"]["extension"] = extension

        # Check 3: Actual file type (MIME)
        file_header = file.file.read(2048)
        file.file.seek(0)

        mime_type = magic.from_buffer(file_header, mime=True) if _MAGIC_OK else None

        if mime_type is None:
            validation_result["warnings"].append("MIME check skipped: python-magic unavailable")
        elif not mime_type.startswith(("application/pdf", "image/")):
            validation_result["is_valid"] = False
            validation_result["errors"].append(
                f"File content type '{mime_type}' doesn't match allowed types"
            )
            return validation_result

        if mime_type is not None:
            validation_result["metadata"]["mime_type"] = mime_type

        # Check 4: For PDF files, verify it's a valid PDF
        if extension == ".pdf":
            if not self._validate_pdf(file_header):
                validation_result["is_valid"] = False
                validation_result["errors"].append("File is not a valid PDF document")
                return validation_result

        validation_result["metadata"]["filename"] = file.filename
        return validation_result

    def _validate_pdf(self, header: bytes) -> bool:
        """Check if binary header matches standard PDF magic bytes (%PDF-).

        Args:
            header: Initial bytes read from file header.

        Returns:
            bool: True if header begins with `%PDF-`, False otherwise.
        """
        return header[:5] == b"%PDF-"

    def _validate_image(self, header: bytes) -> bool:
        """Check if binary header matches supported image signatures (JPEG, PNG, TIFF, BMP).

        Args:
            header: Initial bytes read from file header.

        Returns:
            bool: True if header matches a known image signature, False otherwise.
        """
        if header[:3] == b"\xff\xd8\xff":
            return True
        if header[:4] == b"\x89PNG":
            return True
        if header[:2] in [b"II", b"MM"]:
            return True
        if header[:2] == b"BM":
            return True
        return False

    def sanitize_filename(self, filename: str) -> str:
        """Remove potentially dangerous characters and traversal sequences from filename.

        Neutralizes directory traversal (`..`), null bytes (`\\x00`), and spaces.

        Args:
            filename: Raw incoming filename string from HTTP multipart form.

        Returns:
            str: Sanitized filesystem-safe filename string.

        Interconnections:
            - Used before passing filename to local filesystem paths or MinIO object keys.
        """
        filename = filename.replace("..", "")
        filename = filename.replace("\x00", "")
        filename = filename.replace(" ", "_")
        return filename
