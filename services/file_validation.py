"""File content detection and structural validation.

Role in Project:
    This module performs strict content-based MIME inspection and structural validation
    for uploaded binary files (PDFs and images) BEFORE they are saved to storage or passed
    to OCR/Vision extraction.

Cross-File Interconnections:
    - Called by `app.routes.documents.upload_document` and `app.routes.wizard.wizard_upload_document`
      to reject corrupt files, renamed binaries (e.g. .exe masquerading as .pdf), or unsupported formats.
    - Works with `services.storage.StorageService` ensuring only verified safe payloads are uploaded to MinIO.
    - Complements `services.security` which inspects text fields for prompt injections.

Catches:
1. Renamed files (e.g., an EXE or text file renamed to .pdf or .jpg).
2. Files that look fine on the outside (valid extension / header) but are broken inside.
3. Unsupported file formats.
"""

import io
import logging
from typing import Tuple, Optional, List
from PIL import Image
import pymupdf as fitz

logger = logging.getLogger(__name__)

# Standard MIME types supported by the system
SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/tiff": "tiff",
    "image/bmp": "bmp",
}

# Dangerous executable / archive signatures that must be rejected immediately
DANGEROUS_SIGNATURES = [
    (b"MZ", "Windows executable (EXE/DLL)"),
    (b"\x7fELF", "Linux executable (ELF)"),
    (b"\xca\xfe\xba\xbe", "Mach-O / Java class binary"),
    (b"PK\x03\x04", "ZIP / Office archive"),
    (b"Rar!\x1a\x07", "RAR archive"),
    (b"7z\xbc\xaf\x27\x1c", "7-Zip archive"),
    (b"<!DOCTYPE", "HTML document"),
    (b"<html", "HTML document"),
    (b"<?xml", "XML document"),
    (b"{\\rtf", "RTF document"),
]


def detect_file_type(content: bytes) -> Tuple[Optional[str], Optional[str]]:
    """Detect actual MIME type and format from content magic bytes.
    
    Examines the initial binary header bytes to determine whether the uploaded file
    is genuinely a PDF or recognized image format (JPEG, PNG, TIFF, BMP).

    Interconnections:
        - Used by `validate_file_content()` as the first triage step in the upload pipeline.
        - Used by upload endpoints (`app.routes.documents`, `app.routes.wizard`) to verify client assertions.

    Args:
        content: Raw byte stream of the uploaded document.

    Returns:
        (mime_type, format_name) or (None, None) if unrecognized.
    """
    if not content or len(content) < 4:
        return None, None

    # Check for dangerous signatures first
    for sig, desc in DANGEROUS_SIGNATURES:
        if content.startswith(sig) or (sig.startswith(b"<") and content.lstrip().lower().startswith(sig)):
            return None, f"dangerous_or_unsupported:{desc}"

    # PDF: begins with %PDF-
    if content.startswith(b"%PDF-"):
        return "application/pdf", "pdf"

    # PNG: \x89PNG\r\n\x1a\n
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"

    # JPEG: \xff\xd8\xff
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpeg"

    # TIFF: II*\x00 (little-endian) or MM\x00* (big-endian)
    if content.startswith(b"II*\x00") or content.startswith(b"MM\x00*"):
        return "image/tiff", "tiff"

    # BMP: BM
    if content.startswith(b"BM"):
        return "image/bmp", "bmp"

    return None, "unknown"


def validate_file_content(
    content: bytes,
    allowed_types: Optional[List[str]] = None,
    max_pages: int = 10,
) -> Tuple[bool, str, str, Optional[str]]:
    """Examine file content deeply to verify it is valid and structurally intact.
    
    Performs a 2-stage verification:
    1. Magic-byte detection (checks for dangerous signatures like EXEs/scripts and recognized MIME types).
    2. Deep raster/structural verification:
       - For PDFs: PyMuPDF opens the document, checks encryption status, page limits, and rasterizes page 0.
       - For Images: PIL performs `verify()` and `load()` to catch truncated raster streams.

    Interconnections:
        - Called by `app.routes.documents.upload_document` and `app.routes.wizard.wizard_upload_document`
          at the earliest boundary before storing in MinIO or passing to docling/vision models.
        - Returns error messages rendered back to the user via FastAPI JSON responses.

    Args:
        content: Raw bytes of the uploaded file.
        allowed_types: List of allowed MIME types (defaults to SUPPORTED_MIME_TYPES keys).
        max_pages: Maximum allowed pages for PDF files.
        
    Returns:
        Tuple of (is_valid, detected_mime, detected_format, error_message)
    """
    if not content:
        return False, "", "", "The uploaded file is empty (0 bytes)."

    allowed = allowed_types or list(SUPPORTED_MIME_TYPES.keys())
    mime_type, format_name = detect_file_type(content)

    if not mime_type:
        if format_name and format_name.startswith("dangerous_or_unsupported:"):
            desc = format_name.split(":", 1)[1]
            return False, "", "", f"File content rejected: detected as {desc}. Only identity documents (PDF, JPEG, PNG, TIFF) are accepted."
        return False, "", "", "File content does not match any accepted document format. Renamed or corrupted files cannot be processed."

    if mime_type not in allowed:
        return False, mime_type, format_name, f"File format '{mime_type}' is not accepted for this operation. Expected one of: {', '.join(allowed)}."

    # Deep structural validation
    if mime_type == "application/pdf":
        # Check PDF structural integrity using PyMuPDF
        try:
            doc = fitz.open(stream=content, filetype="pdf")
            try:
                if doc.is_encrypted:
                    return False, mime_type, format_name, "The PDF file is password protected or encrypted. Please upload an unencrypted document."
                
                page_count = len(doc)
                if page_count == 0:
                    return False, mime_type, format_name, "The PDF file has 0 pages or contains no readable content."
                
                if page_count > max_pages:
                    return False, mime_type, format_name, f"The PDF has too many pages ({page_count}). Maximum allowed is {max_pages} pages."

                # Verify first page can actually be rendered/read without crashing
                page = doc[0]
                rect = page.rect
                if rect.width <= 0 or rect.height <= 0:
                    return False, mime_type, format_name, "The PDF contains broken page dimensions."
                
                # Test pixmap rendering on page 0 to ensure content stream is not corrupt
                pix = page.get_pixmap(dpi=72)
                if pix.width <= 0 or pix.height <= 0:
                    return False, mime_type, format_name, "The PDF content could not be rendered."
            finally:
                doc.close()
        except Exception as e:
            logger.warning(f"PDF structural validation failed: {e}")
            return False, mime_type, format_name, f"Corrupted or broken PDF file: looks like a PDF header but is broken inside ({type(e).__name__})."

    elif mime_type.startswith("image/"):
        # Check Image structural integrity using PIL
        try:
            buf = io.BytesIO(content)
            img = Image.open(buf)
            img.verify()  # Verifies header and stream integrity
            
            # Re-open after verify() (PIL verify invalidates the image instance)
            buf.seek(0)
            img2 = Image.open(buf)
            img2.load()  # Forces full raster decoding to catch truncated streams
            
            if img2.width <= 0 or img2.height <= 0:
                return False, mime_type, format_name, "Image has invalid dimensions."
        except Exception as e:
            logger.warning(f"Image structural validation failed: {e}")
            return False, mime_type, format_name, f"Corrupted or broken image file: cannot decode image content ({type(e).__name__})."

    return True, mime_type, format_name, None
