"""
OCR Service — Text extraction fallback for non-image PDFs and edge cases.

Module Architecture & Interconnections:
----------------------------------------
- Role in the Project:
  * Primary document extraction across the system uses the multimodal vision model
    (Qwen2.5-VL 3B via Ollama in `services.generation.GenerationService`) or the
    multi-tiered ladder in `services.extraction_ladder.ExtractionLadder`.
  * `OCRService` acts as a deterministic fallback pipeline when vision extraction is
    unavailable, fails, or when raw non-raster text streams must be extracted from PDFs.
- Upstream Callers:
  * `services.extraction_ladder.ExtractionLadder`:
    Invokes PyMuPDF and OCR extraction as Rung 4 (`OCR_TEXT`) when vision models, Docling,
    and MRZ engines cannot yield sufficient field confidence.
  * `app.routes.health`:
    Monitors `state["ocr"]` to report system readiness and component health.
- External Libraries & System Dependencies:
  * `pymupdf` (`fitz`): High-speed PDF text parsing without image rasterization.
  * `pytesseract` / `tesseract-ocr` (optional): Optical character recognition engine.
"""

import os
from typing import Optional, Dict, Any


class OCRService:
    """Handles text extraction from PDFs and images (fallback mode).

    Primary extraction is done by Qwen2.5-VL 3B vision model.
    This service exists for edge cases where the vision model fails.

    Attributes:
        engine (str): OCR engine identifier (e.g., 'tesseract').
        confidence_threshold (float): Minimum confidence floor for extracted text (default 0.7).
        languages (list[str]): List of language codes configured for OCR (e.g., ['eng']).

    Interconnections:
        - Instantiated in application startup (`app.main`) and placed in `app_state["ocr"]`.
        - Referenced by `services.extraction_ladder.ExtractionLadder` for text parsing rungs.
    """

    def __init__(self, config: dict):
        """Initialize OCRService with configuration parameters.

        Args:
            config (dict): Configuration dictionary containing OCR settings, such as
                `engine` (default: 'tesseract'), `confidence_threshold` (default: 0.7),
                and `languages` (default: ['eng']).
        """
        self.engine = config.get("engine", "tesseract")
        self.confidence_threshold = config.get("confidence_threshold", 0.7)
        self.languages = config.get("languages", ["eng"])

    async def extract_text(self, file_path: str) -> Dict[str, Any]:
        """Extract text from a document (fallback — not the primary extraction path).

        Dispatches extraction to `_extract_pdf` or `_extract_image` based on file extension.

        Args:
            file_path: Local filesystem path to the target PDF or image file.

        Returns:
            Dict[str, Any]: Extraction result containing:
                - `type`: 'pdf', 'image', 'unknown', or 'error'
                - `fields`: Extracted key-value pairs (dict)
                - `confidence`: Confidence score float between 0.0 and 1.0
                - `text`: Extracted plaintext string (truncated to 2000 chars for PDFs)
                - `note` / `error`: Explanatory message or exception string

        Interconnections:
            - Used as fallback in extraction ladders when multimodal models are offline.
        """
        try:
            if file_path.endswith(".pdf"):
                return await self._extract_pdf(file_path)
            elif file_path.endswith((".jpg", ".jpeg", ".png", ".tiff", ".bmp")):
                return await self._extract_image(file_path)
            else:
                return {"type": "unknown", "fields": {}, "confidence": 0.0, "error": "Unsupported format"}
        except Exception as e:
            return {"type": "error", "fields": {}, "confidence": 0.0, "error": str(e)}

    async def _extract_pdf(self, file_path: str) -> Dict[str, Any]:
        """Extract text from a PDF (fallback using PyMuPDF).

        Iterates through all pages in the PDF file via PyMuPDF (`fitz`), accumulating
        extracted text blocks.

        Args:
            file_path: Path to the PDF file on disk.

        Returns:
            Dict[str, Any]: Result dictionary containing type, fields, text snippet,
                and confidence rating (0.5 for successful fallback, 0.0 on failure).
        """
        try:
            import pymupdf as fitz
            doc = fitz.open(file_path)
            text = ""
            for page in doc:
                text += page.get_text()
            doc.close()
            return {
                "type": "pdf",
                "fields": {},
                "confidence": 0.5,
                "text": text[:2000],
                "note": "OCR fallback — primary extraction uses vision model"
            }
        except ImportError:
            return {
                "type": "pdf",
                "fields": {},
                "confidence": 0.0,
                "note": "PyMuPDF not available for OCR fallback"
            }
        except Exception as e:
            return {
                "type": "pdf",
                "fields": {},
                "confidence": 0.0,
                "error": str(e)
            }

    async def _extract_image(self, file_path: str) -> Dict[str, Any]:
        """Extract text from an image (fallback using pytesseract).

        Args:
            file_path: Path to the image file on disk.

        Returns:
            Dict[str, Any]: Result dictionary with type 'image' and explanatory note.
        """
        return {
            "type": "image",
            "fields": {},
            "confidence": 0.5,
            "note": "Image OCR requires pytesseract + tesseract-ocr (not the primary extraction path)"
        }

    def identify_document_type(self, file_path: str) -> str:
        """Identify the type of document (placeholder — vision model handles this).

        Args:
            file_path: Path to document file.

        Returns:
            str: Document type classification, defaulting to 'unknown'.
        """
        return "unknown"

    def extract_fields(self, text: str, document_type: str) -> Dict[str, str]:
        """Extract named fields from extracted text (placeholder).

        Args:
            text: Raw OCR extracted text.
            document_type: Document classification category.

        Returns:
            Dict[str, str]: Map of extracted field names to their values.
        """
        return {}
