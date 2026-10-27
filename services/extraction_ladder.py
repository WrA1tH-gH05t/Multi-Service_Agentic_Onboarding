"""Extraction Ladder — WP5 + WP7 (Phase 4 + Docling pre-processing)

Attempts a sequence of extraction approaches (“rungs”) for each document
until a satisfactory result is found.  Each rung is recorded in the trace
so the validation agent can see exactly which approach won.

Rungs (in order):
  0. Docling pre-processing (layout parse + deterministic field extraction)
     short-circuits Rung 1 when confidence >= docling.skip_vision_threshold
  1. Direct vision-model field extraction (Qwen2.5-VL 3B)  ← primary
  2. Re-extract cropped region  → MRZ parse                  ← targeted
  3. MRZ-only parse via mrz library                          ← structured
  4. OCR fallback (PyMuPDF text / Tesseract)                 ← last resort

After rungs complete, the ladder compares results across rungs and
selects the highest-confidence consensus for each field.

Config-driven thresholds (from config.yaml):
  validation_rules.<doc_type>.human_review_threshold  — fields below
                                                       this → review
  validation_rules.<doc_type>.pass_threshold           — fields ≥ this → auto-pass
  validation_rules.<doc_type>.reject_threshold         — consecutive
                                                       failures ≥ this → reject
"""

import base64
import io
import json
import logging
import os
import re
import hashlib
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Data classes
# ────────────────────────────────────────────────────────────────────

class Rung(str, Enum):
    """Extraction ladder rung."""
    DOCLING = "docling"        # Rung 0: Docling layout pre-processing
    VISION = "vision_model"    # Rung 1: Qwen2.5-VL vision model
    MRZ_CROP = "mrz_crop"      # Rung 2: MRZ region crop + vision
    MRZ_PARSE = "mrz_parse"    # Rung 3: MRZ parse library
    OCR_TEXT = "ocr_text"      # Rung 4: PyMuPDF / Tesseract fallback


@dataclass
class RungResult:
    """Result from a single ladder rung."""
    rung: Rung
    success: bool
    fields: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    error: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "rung": self.rung.value,
            "success": self.success,
            "fields": {k: v for k, v in self.fields.items() if not k.startswith("_")},
            "confidence": self.confidence,
            "error": self.error,
            "notes": self.notes,
        }


@dataclass
class ExtractionLadderResult:
    """Full extraction-ladder result for one document."""
    document_type: str
    rungs: List[RungResult] = field(default_factory=list)
    consensus: Dict[str, Any] = field(default_factory=dict)
    consensus_confidence: float = 0.0
    rejected_fields: List[str] = field(default_factory=list)
    reviewed_fields: List[str] = field(default_factory=list)
    passed_fields: List[str] = field(default_factory=list)
    source_rung_by_field: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "document_type": self.document_type,
            "rungs": [r.to_dict() for r in self.rungs],
            "consensus": self.consensus,
            "consensus_confidence": self.consensus_confidence,
            "rejected_fields": self.rejected_fields,
            "reviewed_fields": self.reviewed_fields,
            "passed_fields": self.passed_fields,
            "source_rung_by_field": self.source_rung_by_field,
        }


# ────────────────────────────────────────────────────────────────────
#  Thresholds loaded from config.yaml
# ────────────────────────────────────────────────────────────────────

DEFAULT_THRESHOLDS = {
    "national_id": {
        "pass_threshold": 0.8,
        "human_review_threshold": 0.5,
        "reject_threshold": 3,
        "extraction_threshold": 0.5,
        "mandatory_fields": [
            "name", "national_id_number", "date_of_birth",
            "gender", "expiry_date",
        ],
        "optional_fields": ["address", "issuing_country"],
    },
    "passport": {
        "pass_threshold": 0.8,
        "human_review_threshold": 0.5,
        "reject_threshold": 3,
        "extraction_threshold": 0.5,
        "mandatory_fields": [
            "name", "passport_number", "date_of_birth",
            "nationality", "expiry_date", "issue_date",
        ],
        "optional_fields": ["place_of_birth", "place_of_issue"],
    },
    "driving_license": {
        "pass_threshold": 0.8,
        "human_review_threshold": 0.5,
        "reject_threshold": 3,
        "extraction_threshold": 0.5,
        "mandatory_fields": [
            "name", "license_number", "license_no", "date_of_birth",
            "expiry_date", "issue_date", "nationality", "licensing_authority",
            "traffic_code_no", "gear_type", "glasses_requirement",
        ],
        "optional_fields": ["license_class", "address", "restrictions", "place_of_issue"],
    },
    "visa": {
        "pass_threshold": 0.75,
        "human_review_threshold": 0.45,
        "reject_threshold": 3,
        "extraction_threshold": 0.45,
        "mandatory_fields": [
            "name", "visa_number", "date_of_birth",
            "nationality", "expiry_date", "issue_date",
        ],
        "optional_fields": ["entry_type", "duration_days"],
    },
}


# ────────────────────────────────────────────────────────────────────
#  Extraction Ladder
# ────────────────────────────────────────────────────────────────────

class ExtractionLadder:
    """Attempt extraction via a sequence of rungs, then merge results.

    Args:
        config: Full app config dict (ollama section, validation_rules section).
        ollama_config: Sub-dict with host/port/model/embedding_model.
        image_bytes: Raw document image/PDF bytes (may be None if only OCR is wanted).
        text_only: Skip vision-model rung (OCR-only mode).
    """

    def __init__(
        self,
        config: dict,
        image_bytes: bytes = b"",
        text_only: bool = False,
    ):
        self._image_bytes = image_bytes
        self._text_only = text_only
        self._config = config

        # Load thresholds
        self._doc_config = config.get("validation_rules", {}) or {}
        self._thresholds: Dict[str, dict] = {}
        for doc_type, tc in DEFAULT_THRESHOLDS.items():
            self._thresholds[doc_type] = dict(tc)
        # Override with config.yaml values
        if isinstance(self._doc_config, dict):
            for doc_type, cfg in self._doc_config.items():
                if isinstance(cfg, dict):
                    merged = dict(self._thresholds.get(doc_type, {}))
                    merged.update(cfg)
                    self._thresholds[doc_type] = merged

        # Ollama config
        oc = config.get("ollama", {})
        self._ollama_host = oc.get("host", "localhost")
        self._ollama_port = oc.get("port", 11434)
        self._model = oc.get("model", "qwen2.5vl:3b")
        self._embed_model = oc.get("embedding_model", "nomic-embed-text")

        # Docling pre-processing service (Rung 0)
        from services.docling_service import DoclingService
        self._docling = DoclingService(config)
        # Cache for parsed Docling output (populated by _rung_docling, reusable by other rungs)
        self._docling_parsed: Optional[dict] = None

    # ──────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────

    def run(self, document_type: str = "id") -> ExtractionLadderResult:
        """Execute the full extraction ladder.

        Returns an ExtractionLadderResult with rung-by-rung results,
        consensus fields, and per-field source-tracking.
        """
        result = ExtractionLadderResult(document_type=document_type)

        # Rung 0: Docling pre-processing (layout + deterministic extraction)
        # Runs first; can short-circuit the expensive vision-model rung when
        # it extracts enough mandatory fields at sufficient confidence.
        skip_vision = False
        rung0 = self._rung_docling(document_type)
        result.rungs.append(rung0)
        if (
            rung0.success
            and rung0.confidence >= self._docling.skip_vision_threshold
        ):
            logger.info(
                "Docling rung confidence %.2f >= skip threshold %.2f "
                "-- skipping vision-model rung for %s",
                rung0.confidence,
                self._docling.skip_vision_threshold,
                document_type,
            )
            skip_vision = True

        # Rung 1: Vision model (Qwen2.5-VL)
        if skip_vision:
            result.rungs.append(RungResult(
                rung=Rung.VISION, success=False,
                error="skipped (Docling confidence sufficient)",
            ))
        elif not self._text_only and self._image_bytes:
            rung1 = self._rung_vision(document_type)
            result.rungs.append(rung1)
        else:
            result.rungs.append(RungResult(
                rung=Rung.VISION, success=False,
                error="skipped (text_only or no image)",
            ))

        # Rung 2: MRZ crop & re-extract
        if self._image_bytes:
            rung2 = self._rung_mrz_crop(document_type)
            result.rungs.append(rung2)

        # Rung 3: MRZ parse (mrz library / passporteye fallback)
        if self._image_bytes:
            rung3 = self._rung_mrz_parse(document_type)
            result.rungs.append(rung3)

        # Rung 4: OCR text extraction
        rung4 = self._rung_ocr_text(document_type)
        result.rungs.append(rung4)

        # Merge: select best field value per field
        result.consensus, result.consensus_confidence = self._merge_results(
            result.rungs, document_type
        )
        result.source_rung_by_field = self._track_source(result.rungs)

        # Classify fields
        thresholds = self._thresholds.get(document_type, DEFAULT_THRESHOLDS.get(document_type, {}))
        pass_thresh = thresholds.get("pass_threshold", 0.8)
        review_thresh = thresholds.get("human_review_threshold", 0.5)
        reject_count = thresholds.get("reject_threshold", 3)

        for field_name, conf in self._get_field_confidences(result.rungs):
            if conf >= pass_thresh:
                result.passed_fields.append(field_name)
            elif conf >= review_thresh:
                result.reviewed_fields.append(field_name)
            else:
                # Count consecutive failures
                failures = sum(1 for r in result.rungs if not r.success)
                if failures >= reject_count:
                    result.rejected_fields.append(field_name)

        return result

    # ──────────────────────────────────────────────────────────────
    #  Rung 1 — Vision model (Qwen2.5-VL 3B)
    # ──────────────────────────────────────────────────────────────


    # ──────────────────────────────────────────────────────────────
    #  Rung 0 — Docling document pre-processing
    # ──────────────────────────────────────────────────────────────

    def _rung_docling(self, document_type: str) -> RungResult:
        """Rung 0: Parse document with Docling for layout-aware text extraction.

        Advantages over raw vision-model prompting:
        - Deterministic: no token sampling, no hallucinations
        - Cheap: runs locally without GPU
        - Structured: reading order, tables, bounding boxes
        - Feeds clean markdown to Rung 1 (vision model) when not skipping it

        Short-circuit behaviour:
        - If Docling extracts enough mandatory fields at high confidence
          (>= docling.skip_vision_threshold) Rung 1 is skipped entirely.
        - The parsed markdown is cached on self._docling_parsed so that
          downstream rungs (e.g. MRZ parse) can reuse it.
        """
        if not self._docling.is_available():
            return RungResult(
                rung=Rung.DOCLING,
                success=False,
                error="Docling not available (not installed or disabled)",
            )

        try:
            # Detect file format from magic bytes
            fmt = "pdf"
            if self._image_bytes:
                header = self._image_bytes[:8]
                if header[:4] == b"\x89PNG":
                    fmt = "png"
                elif header[:2] in (b"\xff\xd8", b"\xff\xe0", b"\xff\xe1"):
                    fmt = "jpg"
                elif header[:4] == b"PK\x03\x04":
                    fmt = "docx"

            parsed = self._docling.parse(self._image_bytes, file_format=fmt)
            self._docling_parsed = parsed  # cache for other rungs

            if not parsed.get("success"):
                return RungResult(
                    rung=Rung.DOCLING,
                    success=False,
                    error=parsed.get("error", "Docling parse returned failure"),
                )

            text = parsed.get("text", "") or parsed.get("markdown", "")
            if not text.strip():
                return RungResult(
                    rung=Rung.DOCLING,
                    success=False,
                    error="Docling returned empty text (likely pure-image document)",
                    notes="Will fall through to vision-model rung",
                )

            candidates = self._docling.extract_field_candidates(
                text, document_type=document_type
            )
            confidence = self._docling.compute_confidence(
                candidates, document_type=document_type
            )

            notes_parts = [
                f"pages={parsed.get('pages', '?')}",
                f"tables={len(parsed.get('tables', []))}",
                f"has_mrz={parsed.get('has_mrz', False)}",
                f"fields_found={len(candidates)}",
            ]

            return RungResult(
                rung=Rung.DOCLING,
                success=True,
                fields=candidates,
                confidence=confidence,
                notes="Docling: " + ", ".join(notes_parts),
            )

        except Exception as exc:
            logger.warning("Docling rung failed: %s", exc)
            return RungResult(
                rung=Rung.DOCLING,
                success=False,
                error=str(exc),
            )
    def _rung_vision(self, document_type: str) -> RungResult:
        """Rung 1: Qwen2.5-VL 3B direct extraction.
        
        For PDFs: renders page with fitz → converts to base64 for vision model.
        """
        try:
            # Render PDF to image if it's a PDF
            if b"%PDF" in self._image_bytes[:5]:
                try:
                    import pymupdf as fitz
                    doc = fitz.open(stream=self._image_bytes, filetype="pdf")
                    page = doc[0]
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(matrix=mat)
                    doc.close()
                    image_bytes = pix.tobytes("png")
                except Exception:
                    image_bytes = self._image_bytes
            else:
                image_bytes = self._image_bytes
            b64_img = self._file_to_base64_jpg(image_bytes, max_dim=800)
            field_list = "\n".join(
                f'  "{f}": "{d}"'
                for f, d in self._field_schema(document_type).items()
            )
            system_msg = (
                "You are a document data extraction engine. Extract key-value information from the document image and return ONLY valid JSON.\n\n"
                "JSON SCHEMA TO USE:\n"
                f"{{\n{field_list}\n}}\n\n"
                "CRITICAL RULES:\n"
                "1. Return ONLY a JSON object - no markdown, no code fences, no explanation, no preamble\n"
                "2. Extract ALL fields in the schema - every single one\n"
                "3. If a field cannot be read, use empty string \"\" (not null)\n"
                "4. For dates, preserve the exact format from the document (DD/MM/YYYY, DD-MM-YYYY, etc.)\n"
                "5. Copy values verbatim - do not translate or reformat\n"
                "6. Look for labels like: Name, ID No, DOB, Nationality, Gender, Expiry, Issue Date\n"
                "7. For passports: extract given_name and surname separately\n"
                "8. For national IDs: extract full_name, and if visible also card_number, occupation, issue_place\n"
                "9. The model will receive this as an image - look carefully at all text regions\n"
            )

            fields, raw = self._call_ollama_vision(
                b64_img,
                "Extract all fields from this document. Return JSON.",
                system_msg=system_msg,
                num_predict=1024,
            )
            if fields:
                return RungResult(
                    rung=Rung.VISION,
                    success=True,
                    fields=fields,
                    confidence=0.85,
                    notes="Vision model extraction successful",
                )
            return RungResult(
                rung=Rung.VISION,
                success=False,
                error="Vision model did not return valid JSON",
                notes="Non-JSON response from vision model",
            )
        except httpx.TimeoutException:
            return RungResult(rung=Rung.VISION, success=False, error="Vision model timeout")
        except httpx.ConnectError:
            return RungResult(
                rung=Rung.VISION, success=False,
                error=f"Cannot connect to Ollama at {self._ollama_host}:{self._ollama_port}",
            )
        except Exception as e:
            return RungResult(rung=Rung.VISION, success=False, error=str(e))

    # ──────────────────────────────────────────────────────────────
    #  Rung 2 — MRZ crop & re-extract
    # ──────────────────────────────────────────────────────────────

    def _rung_mrz_crop(self, document_type: str) -> RungResult:
        """Rung 2: Crop the MRZ region and re-extract with vision model.
        
        For PDFs: renders page → crops MRZ region → vision model reads MRZ text.
        """
        try:
            # Render PDF to image if it's a PDF
            img_bytes = self._image_bytes
            if b"%PDF" in self._image_bytes[:5]:
                try:
                    import pymupdf as fitz
                    doc = fitz.open(stream=self._image_bytes, filetype="pdf")
                    page = doc[0]
                    mat = fitz.Matrix(2, 2)
                    pix = page.get_pixmap(matrix=mat)
                    doc.close()
                    img_bytes = pix.tobytes("png")
                except Exception as e:
                    return RungResult(rung=Rung.MRZ_CROP, success=False, error=f"PDF render failed: {e}")
            
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")

            # Crop bottom 20% (MRZ is usually at the bottom of passports/IDs)
            height = img.height
            crop_bottom = int(height * 0.85)
            mrz_crop = img.crop((0, crop_bottom, img.width, height))

            # Resize for the vision model
            max_dim = 800
            if max(mrz_crop.size) > max_dim:
                ratio = max_dim / max(mrz_crop.size)
                mrz_crop = mrz_crop.resize((int(mrz_crop.width * ratio), int(mrz_crop.height * ratio)), Image.LANCZOS)

            buf = io.BytesIO()
            mrz_crop.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            field_list = "\n".join(
                f"  - {f}: {d}"
                for f, d in self._mrz_field_schema(document_type).items()
            )
            system_msg = (
                "You are extracting the Machine Readable Zone (MRZ) from a document. "
                "The MRZ is the two or three lines of text with '<' characters at the bottom. "
                f"Extract these fields:\n{field_list}\n"
                "Rules:\n"
                "- Return ONLY valid JSON\n"
                "- For MRZ text, preserve exact characters including '<'\n"
                "- Parse MRZ fields: name components, document number, nationality, DOB, sex, expiry\n"
                "- Use null for any field not present\n"
            )

            fields, raw = self._call_ollama_vision(
                b64,
                "Extract MRZ fields from this cropped region. Return JSON.",
                system_msg=system_msg,
                num_predict=512,
                temperature=0.05,
            )
            if fields:
                return RungResult(
                    rung=Rung.MRZ_CROP,
                    success=True,
                    fields=fields,
                    confidence=0.75,
                    notes="MRZ crop re-extraction successful",
                )
            return RungResult(
                rung=Rung.MRZ_CROP,
                success=False,
                error="MRZ crop did not return valid JSON",
            )
        except Exception as e:
            return RungResult(rung=Rung.MRZ_CROP, success=False, error=str(e))

    # ──────────────────────────────────────────────────────────────
    #  Rung 3 — MRZ parse (mrz library)
    # ──────────────────────────────────────────────────────────────

    def _rung_mrz_parse(self, document_type: str) -> RungResult:
        """Rung 3: Parse MRZ text using the `mrz` library if available.
        
        For scanned PDFs: renders page → crops MRZ region → vision model reads MRZ text → mrz library parses.
        """
        try:
            import mrz  # pip install python-mrz
            import pymupdf as fitz
            
            # Render first page of PDF to image
            doc = fitz.open(stream=self._image_bytes, filetype="pdf")
            page = doc[0]
            mat = fitz.Matrix(2, 2)  # 2x zoom for clarity
            pix = page.get_pixmap(matrix=mat)
            doc.close()
            img_bytes = pix.tobytes("png")
            
            img = Image.open(io.BytesIO(img_bytes))
            height = img.height
            crop_bottom = int(height * 0.85)
            mrz_crop = img.crop((0, crop_bottom, img.width, height))
            buf = io.BytesIO()
            mrz_crop.save(buf, format="JPEG", quality=85)
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            raw_text, _ = self._call_ollama_vision(
                b64,
                "Read ONLY the MRZ lines from this image. Return raw text only, one line per MRZ line. Use < for blanks.",
                system_msg="Extract the MRZ text exactly as it appears. Return only the raw MRZ lines, one per line. Use < for missing characters. Do not include any other text.",
                num_predict=256,
                temperature=0.0,
            )
            if not raw_text:
                return RungResult(
                    rung=Rung.MRZ_PARSE,
                    success=False,
                    error="vision model did not return MRZ text",
                )

            # Parse with mrz library
            lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
            if len(lines) >= 2:
                # Try parsing as TD1 (ID card), TD2 (passport), or TD3 (passport)
                for line in lines:
                    try:
                        parsed = mrz.decode(line)
                        fields = {}
                        if hasattr(parsed, "document_code") and parsed.document_code:
                            fields["document_code"] = parsed.document_code
                        if hasattr(parsed, "surname") and parsed.surname:
                            fields["surname"] = parsed.surname
                        if hasattr(parsed, "given_names") and parsed.given_names:
                            fields["given_name"] = parsed.given_names
                        if hasattr(parsed, "nationality") and parsed.nationality:
                            fields["nationality"] = parsed.nationality
                        if hasattr(parsed, "document_number") and parsed.document_number:
                            fields["document_number"] = parsed.document_number
                        if hasattr(parsed, "date_of_birth") and parsed.date_of_birth:
                            fields["date_of_birth"] = str(parsed.date_of_birth)
                        if hasattr(parsed, "sex") and parsed.sex:
                            fields["sex"] = str(parsed.sex)
                        if hasattr(parsed, "expiry_date") and parsed.expiry_date:
                            fields["expiry_date"] = str(parsed.expiry_date)
                        if hasattr(parsed, "optional_data1") and parsed.optional_data1:
                            fields["mrz_line2"] = str(parsed.optional_data1)
                        if fields:
                            return RungResult(
                                rung=Rung.MRZ_PARSE,
                                success=True,
                                fields=fields,
                                confidence=0.90,
                                notes=f"MRZ parsed via python-mrz library from line: {line[:60]}",
                            )
                    except Exception:
                        continue

            return RungResult(
                rung=Rung.MRZ_PARSE,
                success=False,
                error="mrz library parsing failed or no valid MRZ lines found",
            )
        except ImportError:
            return RungResult(
                rung=Rung.MRZ_PARSE,
                success=False,
                error="mrz library not installed (pip install python-mrz)",
                notes="MRZ parsing skipped — install python-mrz",
            )
        except Exception as e:
            return RungResult(rung=Rung.MRZ_PARSE, success=False, error=str(e))

    # ──────────────────────────────────────────────────────────────
    #  Rung 4 — OCR text extraction
    # ──────────────────────────────────────────────────────────────

    def _rung_ocr_text(self, document_type: str) -> RungResult:
        """Rung 4: OCR via PyMuPDF text extraction or Tesseract."""
        # Try PyMuPDF first (handles PDF and rasterized images)
        try:
            import pymupdf as fitz
            try:
                doc = fitz.open(stream=self._image_bytes, filetype="pdf")
                text = ""
                for page in doc:
                    text += page.get_text()
                doc.close()
                if text.strip():
                    fields = self._regex_extract_fields(text, document_type)
                    if fields:
                        return RungResult(
                            rung=Rung.OCR_TEXT,
                            success=True,
                            fields=fields,
                            confidence=0.60,
                            notes="PyMuPDF text extraction successful",
                        )
            except Exception:
                pass  # Not a PDF, try image OCR
        except ImportError:
            pass

        # Try Tesseract
        try:
            import pytesseract
            from PIL import Image as PILImage
            img = PILImage.open(io.BytesIO(self._image_bytes))
            text = pytesseract.image_to_string(img, lang="eng")
            if text.strip():
                fields = self._regex_extract_fields(text, document_type)
                if fields:
                    return RungResult(
                        rung=Rung.OCR_TEXT,
                        success=True,
                        fields=fields,
                        confidence=0.55,
                        notes="Tesseract OCR successful",
                    )
        except ImportError:
            pass
        except Exception:
            pass

        return RungResult(
            rung=Rung.OCR_TEXT,
            success=False,
            error="No OCR engine available or no text extracted",
            notes="PyMuPDF and Tesseract both failed — install fitz + pytesseract",
        )

    # ──────────────────────────────────────────────────────────────
    #  Merge: consensus building across rungs
    # ──────────────────────────────────────────────────────────────

    def _merge_results(
        self, rungs: List[RungResult], document_type: str
    ) -> Tuple[Dict[str, Any], float]:
        """Merge results from all successful rungs into a consensus.

        Strategy:
        - Each field gets the value from the highest-confidence successful rung
        - If two rungs agree, that increases confidence
        - Fields present in all rungs → highest confidence
        - Only fields with confidence >= threshold are included in consensus

        Returns: (consensus_dict, overall_confidence)
        """
        field_scores: Dict[str, List[Tuple[float, Any]]] = {}

        for rung in rungs:
            if not rung.success:
                continue
            for fname, fval in rung.fields.items():
                if fval is None or fval == "":
                    continue
                field_scores.setdefault(fname, []).append((rung.confidence, fval))

        consensus = {}
        total_conf = 0.0
        field_count = 0

        for fname, scores in field_scores.items():
            # Sort by confidence descending
            scores.sort(key=lambda x: x[0], reverse=True)
            best_conf, best_val = scores[0]

            # Boost confidence if multiple rungs agree
            if len(scores) > 1:
                # Check how many agree (within fuzzy match for strings)
                agree = sum(1 for c, v in scores if self._values_match(best_val, v))
                if agree >= 2:
                    best_conf = min(1.0, best_conf * (1 + 0.05 * agree))

            # Only include if above extraction threshold
            thresholds = self._thresholds.get(document_type, {})
            extraction_thresh = thresholds.get("extraction_threshold", 0.5)
            if best_conf >= extraction_thresh:
                consensus[fname] = best_val
                total_conf += best_conf
                field_count += 1

        overall_conf = total_conf / field_count if field_count > 0 else 0.0
        return consensus, round(overall_conf, 4)

    @staticmethod
    def _track_source(rungs: List[RungResult]) -> Dict[str, str]:
        """Build a map of field_name → source_rung for the winning value."""
        source_map: Dict[str, str] = {}
        for rung in rungs:
            if not rung.success:
                continue
            for fname, fval in rung.fields.items():
                if fval is None or fval == "":
                    continue
                # Keep the highest-confidence source (first in sorted order)
                if fname not in source_map:
                    source_map[fname] = rung.rung.value
        return source_map

    def _get_field_confidences(self, rungs: List[RungResult]) -> List[Tuple[str, float]]:
        """Get (field_name, confidence) pairs from successful rungs.

        For each field, uses the highest confidence from any successful rung.
        """
        field_best: Dict[str, float] = {}
        for rung in rungs:
            if not rung.success:
                continue
            for fname, fval in rung.fields.items():
                if fval is None or fval == "":
                    continue
                if fname not in field_best or rung.confidence > field_best[fname]:
                    field_best[fname] = rung.confidence
        return list(field_best.items())

    # ──────────────────────────────────────────────────────────────
    #  Helpers
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _values_match(v1: Any, v2: Any) -> bool:
        """Check if two values are considered a match (fuzzy for strings)."""
        s1 = str(v1).strip().lower()
        s2 = str(v2).strip().lower()
        if s1 == s2:
            return True
        # Levenshtein within 2 edits
        if len(s1) > 0 and len(s2) > 0:
            dist = ExtractionLadder._levenshtein_distance(s1, s2)
            max_len = max(len(s1), len(s2))
            if dist / max_len < 0.15:
                return True
        return False

    @staticmethod
    def _levenshtein_distance(a: str, b: str) -> int:
        if len(a) < len(b):
            return ExtractionLadder._levenshtein_distance(b, a)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a):
            curr = [i + 1]
            for j, cb in enumerate(b):
                curr.append(min(
                    prev[j + 1] + 1,  # insertion
                    curr[j] + 1,       # deletion
                    prev[j] + (ca != cb),  # substitution
                ))
            prev = curr
        return prev[-1]

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """Extract JSON from response text, handling markdown fences."""
        if not text:
            return None
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass
        # Try finding JSON object in text
        match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _file_to_base64_jpg(self, file_bytes: bytes, max_dim: int = 800) -> str:
        """Convert file bytes to base64 JPEG for the vision model.
        
        Handles both raw image files and PDFs (renders first page).
        Uses JPEG to keep payload under 500K chars for Ollama reliability.
        """
        try:
            # If this is a PDF, render first page to PNG
            img_bytes = file_bytes
            if b"%PDF" in file_bytes[:5]:
                import pymupdf as fitz
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                page = doc[0]
                mat = fitz.Matrix(2, 2)  # 2x zoom for clarity
                pix = page.get_pixmap(matrix=mat)
                doc.close()
                img_bytes = pix.tobytes("png")
            
            img = Image.open(io.BytesIO(img_bytes))
            if img.mode not in ("RGB",):
                img = img.convert("RGB")
            if max(img.size) > max_dim:
                ratio = max_dim / max(img.size)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except ImportError as e:
            raise ValueError(f"Missing required library: {e}")
        except Exception as e:
            raise ValueError(f"Failed to convert to JPEG: {e}")

    def _call_ollama_vision(self, b64_img: str, prompt: str, system_msg: str = None,
                           num_predict: int = 512, temperature: float = 0.1) -> tuple:
        """Call qwen2.5vl:3b using the native 'images' parameter.
        
        Returns (dict_fields, raw_text) tuple.
        """
        messages = [{"role": "user", "content": prompt, "images": [b64_img]}]
        if system_msg:
            messages.insert(0, {"role": "system", "content": system_msg})
        
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": 8192,
                "repetition_penalty": 1.1,
                "repeat_penalty": 1.1,
            },
        }
        
        resp = httpx.post(
            f"http://{self._ollama_host}:{self._ollama_port}/api/chat",
            json=payload,
            timeout=300,
        )
        
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code}: {resp.text[:500]}"
        
        data = resp.json()
        raw = data.get("message", {}).get("content", "")
        
        # Strip markdown code fences
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0]
        
        fields = self._extract_json(raw)
        return fields, raw

    def _field_schema(self, document_type: str) -> Dict[str, str]:
        """Return field → description schema for the vision model, specific to document type."""
        if document_type == "national_id":
            return {
                "full_name": "Full name as printed on document",
                "national_id_number": "Unique ID number",
                "date_of_birth": "Date of birth (DD/MM/YYYY)",
                "nationality": "Country of citizenship",
                "date_of_issue": "Date document was issued",
                "date_of_expiry": "Date document expires",
                "gender": "M / F",
                "card_number": "Card serial number",
                "occupation": "Occupation",
                "place_of_issue": "Place of issue",
            }
        elif document_type == "passport":
            return {
                "given_name": "First name / given names",
                "surname": "Last name / family name",
                "passport_number": "Passport document number",
                "date_of_birth": "Date of birth (DD/MM/YYYY)",
                "nationality": "Country of citizenship",
                "sex": "M / F",
                "date_of_issue": "Date passport was issued",
                "date_of_expiry": "Date passport expires",
            }
        else:
            return {
                "document_type": "Type: national_id, passport, driving_license, visa, residence_permit, other",
                "issuing_country": "Full country name",
                "name": "Full name as printed on document",
                "surname": "Last name / family name",
                "given_name": "First name / given name",
                "nationality": "Country of citizenship",
                "date_of_birth": "Date of birth (preserve original format)",
                "place_of_birth": "City, region, or country",
                "sex": "M / F / other",
                "date_of_issue": "Date document was issued",
                "date_of_expiry": "Date document expires",
                "authority": "Issuing authority",
                "document_number": "Main document number",
                "mrz": "Machine Readable Zone text (if present)",
                "address": "Residential address (if shown)",
                "signature": "yes / no",
                "photo": "yes / no",
            }

    def _mrz_field_schema(self, document_type: str) -> Dict[str, str]:
        """Return field schema specifically for MRZ extraction."""
        return {
            "mrz_line1": "First MRZ line (raw text)",
            "mrz_line2": "Second MRZ line (raw text)",
            "document_code": "TD1 / TD2 / TD3",
            "surname": "Last name from MRZ",
            "given_name": "Given names from MRZ",
            "nationality": "Country code from MRZ",
            "date_of_birth": "DOB from MRZ",
            "sex": "M / F / X from MRZ",
            "expiry_date": "Expiry from MRZ",
            "document_number": "Doc number from MRZ",
            "optional_data": "Optional data from MRZ",
            "personal_number": "Personal number from MRZ",
        }

    @staticmethod
    def _regex_extract_fields(text: str, document_type: str) -> Dict[str, str]:
        """Extract fields from OCR text using regex patterns.

        This is a fallback when no AI model is available.
        """
        fields: Dict[str, str] = {}
        text_lower = text.lower()

        # Common patterns
        name_match = re.search(r'(?:name|full\s*name|surname|last\s*name|given\s*name)[:\s]+([^\n|/]{2,80})', text, re.IGNORECASE)
        if name_match:
            fields["name"] = name_match.group(1).strip()

        dob_match = re.search(r'(?:date\s*of\s*birth|dob|birth\s*date|date\s*of\s*birth)[:\s]+([\d/]{6,15})', text, re.IGNORECASE)
        if dob_match:
            fields["date_of_birth"] = dob_match.group(1).strip()

        expiry_match = re.search(r'(?:expiry|expires|date\s*of\s*expiry|valid\s*until)[:\s]+([\d/]{6,15})', text, re.IGNORECASE)
        if expiry_match:
            fields["expiry_date"] = expiry_match.group(1).strip()

        doc_num_match = re.search(r'(?:document\s*number|doc\s*no|id\s*number|passport\s*number)[:\s]+([A-Z0-9]{5,20})', text, re.IGNORECASE)
        if doc_num_match:
            fields["document_number"] = doc_num_match.group(1).strip()

        nationality_match = re.search(r'(?:nationality|citizenship|country)[:\s]+([A-Z]{2,3})', text, re.IGNORECASE)
        if nationality_match:
            fields["nationality"] = nationality_match.group(1).strip()

        sex_match = re.search(r'(?:sex|gender)[:\s]+([MF])', text, re.IGNORECASE)
        if sex_match:
            fields["sex"] = sex_match.group(1).upper()

        return fields





