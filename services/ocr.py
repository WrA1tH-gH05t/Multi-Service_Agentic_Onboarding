"""
OCR Service — Text extraction fallback for non-image PDFs.

Note: In the primary flow, documents go through the vision model (services/generation.py).
OCR is only used as a fallback for edge cases.
"""

import os
from typing import Optional, Dict, Any


class OCRService:
    """Handles text extraction from PDFs and images (fallback mode).

    Primary extraction is done by Qwen2.5-VL 3B vision model.
    This service exists for edge cases where the vision model fails.
    """

    def __init__(self, config: dict):
        self.engine = config.get("engine", "tesseract")
        self.confidence_threshold = config.get("confidence_threshold", 0.7)
        self.languages = config.get("languages", ["eng"])

    async def extract_text(self, file_path: str) -> Dict[str, Any]:
        """Extract text from a document (fallback — not the primary extraction path)."""
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
        """Extract text from a PDF (fallback using PyMuPDF)."""
        try:
            import fitz
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
        """Extract text from an image (fallback using pytesseract)."""
        return {
            "type": "image",
            "fields": {},
            "confidence": 0.5,
            "note": "Image OCR requires pytesseract + tesseract-ocr (not the primary extraction path)"
        }

    def identify_document_type(self, file_path: str) -> str:
        """Identify the type of document (placeholder — vision model handles this)."""
        return "unknown"

    def extract_fields(self, text: str, document_type: str) -> Dict[str, str]:
        """Extract named fields from extracted text (placeholder)."""
        return {}
