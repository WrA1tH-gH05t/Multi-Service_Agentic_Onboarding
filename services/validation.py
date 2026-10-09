"""
Validation Service — File upload validation (updated for image support).

Supports: PDF, PNG, JPEG, TIFF, BMP
"""

import os
try:
    import magic
    _MAGIC_OK = True
except Exception:
    magic = None
    _MAGIC_OK = False


class FileValidator:
    """Service that validates uploaded files."""

    def __init__(self, max_file_size: int):
        self.max_file_size = max_file_size
        self.allowed_extensions = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}

    def validate_file(self, file) -> dict:
        """Validate an uploaded file."""
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
        """Check if a file is a valid PDF."""
        return header[:5] == b"%PDF-"

    def _validate_image(self, header: bytes) -> bool:
        """Check if a file is a valid image."""
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
        """Remove potentially dangerous characters from filename."""
        filename = filename.replace("..", "")
        filename = filename.replace("\x00", "")
        filename = filename.replace(" ", "_")
        return filename
