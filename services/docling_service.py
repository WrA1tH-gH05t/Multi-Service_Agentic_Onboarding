"""Docling Document Preprocessing Service — WP5 pre-processing step.

Runs BEFORE the vision-model rungs in the ExtractionLadder to offload
structural text/table parsing from the multimodal LLM (qwen2.5-vl).

What it does
------------
1. Converts PDFs, DOCX, and rasterised images to clean markdown + plain text
   via IBM Docling (layout analysis, reading-order, embedded OCR).
2. Attempts deterministic field-candidate extraction (regex + label heuristics)
   from the clean text.
3. Returns a confidence-scored RungResult.  If confidence is high enough the
   ExtractionLadder short-circuits the expensive vision-model rung.

Design decisions
----------------
- Lazy-initialised: the Docling DocumentConverter is only loaded on first use
   so that the service can be imported without penalty when Docling is absent.
- Graceful degradation: if Docling is not installed the rung skips silently.
- All logic is side-effect-free; this module does NOT mutate external state.

Module Architecture & Interconnections:
----------------------------------------
- Role in the Project:
  * Rung 0 pre-processor in the hierarchical document extraction ladder (`services.extraction_ladder.ExtractionLadder`).
  * Accelerates and streamlines extraction by executing deterministic parsing before invoking
    computational vision LLM inference.
- Upstream Callers:
  * `services.extraction_ladder.ExtractionLadder`:
    Invokes `DoclingService.parse()` and `extract_field_candidates()` on incoming documents.
    If calculated confidence exceeds `skip_vision_threshold` (default 0.80), the expensive vision rung is bypassed.
- Downstream Dependencies:
  * IBM Docling (`docling.document_converter.DocumentConverter`, `docling.datamodel.base_models.DocumentStream`).
  * Reads `DEFAULT_THRESHOLDS` from `services.extraction_ladder` for mandatory field checking.
"""

from __future__ import annotations

import io
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Regex helpers for deterministic field extraction from clean text
# ────────────────────────────────────────────────────────────────────

# Date patterns (DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, etc.)
_DATE_RE = re.compile(
    r"\b(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}"
    r"|\d{4}[/\-\.]\d{1,2}[/\-\.]\d{1,2})\b"
)

# UAE Emirates ID: 784-YYYY-NNNNNNN-C  (spaces or hyphens)
_EID_RE = re.compile(r"\b784[\s\-]?\d{4}[\s\-]?\d{7}[\s\-]?\d\b")

# Passport number: ICAO spec (letter + 8 alphanumerics, no O/0 ambiguity handled upstream)
_PASSPORT_RE = re.compile(r"\b[A-PR-WYa-pr-wy][1-9A-Z]\d{6,7}\b")

# Generic MRZ line detector (used to flag MRZ-bearing docs for the MRZ rungs)
_MRZ_LINE_RE = re.compile(r"[A-Z0-9<]{30,}")


def _extract_dates_with_labels(text: str) -> Dict[str, str]:
    """Map date values to field names using surrounding label context.

    Inspects each line for date patterns and checks for contextual cues such as
    'birth'/'dob', 'expir'/'valid until', and 'issue'/'issued'.

    Args:
        text: Plaintext document string.

    Returns:
        Dict[str, str]: Mapped date fields (e.g., 'date_of_birth', 'expiry_date', 'issue_date').
    """
    result: Dict[str, str] = {}
    for line in text.splitlines():
        ll = line.lower()
        dates = _DATE_RE.findall(line)
        if not dates:
            continue
        d = dates[0]
        if any(k in ll for k in ("birth", "dob", "date of birth", "born")):
            result.setdefault("date_of_birth", d)
        if any(k in ll for k in ("expir", "valid until", "val.", "exp.")):
            result.setdefault("expiry_date", d)
            result.setdefault("date_of_expiry", d)
        if any(k in ll for k in ("issue", "issued", "date of issue")):
            result.setdefault("issue_date", d)
            result.setdefault("date_of_issue", d)
    return result


def _extract_labelled_field(text: str, *labels: str) -> Optional[str]:
    """Return the value that follows any of *labels* on the same line.

    Splits the line on delimiters (':', '-', '|') after identifying any of the label prefixes.

    Args:
        text: Plaintext string of the document.
        *labels: Tuple of string label patterns to match (e.g., 'name', 'nationality').

    Returns:
        Optional[str]: Extracted and stripped value following the label delimiter, or None.
    """
    for line in text.splitlines():
        ll = line.lower()
        for label in labels:
            if label in ll:
                # Split on common delimiters after the label
                remainder = re.split(r"[:\-\|]", line, maxsplit=1)
                if len(remainder) > 1:
                    val = remainder[1].strip()
                    if val:
                        return val
    return None


def _has_mrz(text: str) -> bool:
    """Check whether text contains lines resembling Machine Readable Zones (MRZ).

    Args:
        text: Plaintext document string.

    Returns:
        bool: True if an MRZ string pattern (30+ uppercase/digits/'<') is detected.
    """
    return bool(_MRZ_LINE_RE.search(text))


# ────────────────────────────────────────────────────────────────────
#  DoclingService
# ────────────────────────────────────────────────────────────────────

class DoclingService:
    """Wraps IBM Docling for document layout parsing and pre-extraction.

    Usage (from ExtractionLadder):
        svc = DoclingService(config)
        parsed = svc.parse(file_bytes, file_format="pdf")
        if parsed["success"]:
            candidates = svc.extract_field_candidates(
                parsed["text"], document_type="passport"
            )

    Attributes:
        _config (Dict[str, Any]): Full application configuration dictionary.
        _docling_cfg (Dict[str, Any]): Sub-dictionary for 'docling' settings.
        _enabled (bool): Whether Docling preprocessing is enabled.
        _field_confidence (float): Base confidence awarded to deterministically extracted fields.
        skip_vision_threshold (float): Threshold above which ladder skips the vision model rung.

    Interconnections:
        - Invoked as Rung 0 by `services.extraction_ladder.ExtractionLadder`.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize DoclingService with configuration settings.

        Args:
            config (Optional[Dict[str, Any]]): Application configuration dict. Reads
                `docling.enabled` (default: True), `docling.field_confidence` (default: 0.72),
                and `docling.skip_vision_threshold` (default: 0.80).
        """
        self._config = config or {}
        self._docling_cfg = self._config.get("docling", {})
        self._enabled: bool = self._docling_cfg.get("enabled", True)
        # Confidence awarded to fields found deterministically by Docling
        self._field_confidence: float = float(
            self._docling_cfg.get("field_confidence", 0.72)
        )
        # If consensus confidence across Docling-extracted fields reaches this
        # threshold the vision rung is skipped entirely.
        self.skip_vision_threshold: float = float(
            self._docling_cfg.get("skip_vision_threshold", 0.80)
        )
        self._converter = None        # lazy-loaded
        self._init_attempted = False

    # ── Lifecycle ──────────────────────────────────────────────────

    def _init_converter(self):
        """Lazy-init the Docling DocumentConverter (heavy import).

        Avoids slow import penalties and startup crashes when Docling is absent.

        Returns:
            Optional[DocumentConverter]: Initialized converter or None if unavailable/disabled.
        """
        if self._init_attempted:
            return self._converter
        self._init_attempted = True
        if not self._enabled:
            logger.debug("Docling preprocessing disabled in config.")
            return None
        try:
            from docling.document_converter import DocumentConverter
            self._converter = DocumentConverter()
            logger.info("Docling DocumentConverter ready.")
        except ImportError:
            logger.warning(
                "docling not installed — Docling rung will be skipped. "
                "Run: pip install docling"
            )
        except Exception as exc:
            logger.warning("Docling init failed: %s", exc)
        return self._converter

    def is_available(self) -> bool:
        """Return True if Docling is installed, enabled, and successfully initialized.

        Returns:
            bool: Availability status flag.
        """
        return self._init_converter() is not None

    # ── Core parse ─────────────────────────────────────────────────

    def parse(
        self,
        source: bytes | str,
        file_format: str = "pdf",
    ) -> Dict[str, Any]:
        """Convert a document to structured text using Docling.

        Args:
            source: Raw bytes of the document OR a filesystem path string.
            file_format: Lowercase extension hint (``"pdf"``, ``"png"``,
                ``"jpg"``, ``"docx"`` …).

        Returns:
            Dict[str, Any] with keys:
                - `success` (bool): True if conversion completed without error
                - `markdown` (str): Layout-aware markdown output
                - `text` (str): Plain reading-order text
                - `tables` (list[list[dict]]): Extracted tables as lists of record dicts
                - `pages` (int): Document page count
                - `has_mrz` (bool): Whether an MRZ pattern was detected in extracted text
                - `error` (str | None): Failure description if unsuccessful

        Interconnections:
            - Called by `services.extraction_ladder.ExtractionLadder._run_docling_rung()`.
        """
        converter = self._init_converter()
        if converter is None:
            return _fail("Docling not available")

        try:
            from docling.datamodel.base_models import DocumentStream

            if isinstance(source, (bytes, bytearray)):
                stream = DocumentStream(
                    name=f"document.{file_format}",
                    stream=io.BytesIO(source),
                )
                conv_input = stream
            else:
                conv_input = str(source)   # file path

            result = converter.convert(conv_input)
            doc = result.document

            markdown: str = doc.export_to_markdown()
            text: str = (
                doc.export_to_text()
                if hasattr(doc, "export_to_text")
                else markdown
            )

            # Tables as list-of-dicts per table
            tables: List[List[Dict]] = []
            if hasattr(doc, "tables"):
                for tbl in doc.tables:
                    try:
                        df = tbl.export_to_dataframe()
                        tables.append(df.to_dict(orient="records"))
                    except Exception:
                        pass

            pages = len(doc.pages) if hasattr(doc, "pages") else 1

            return {
                "success": True,
                "markdown": markdown,
                "text": text,
                "tables": tables,
                "pages": pages,
                "has_mrz": _has_mrz(text),
                "error": None,
            }

        except Exception as exc:
            logger.warning("Docling conversion failed: %s", exc)
            return _fail(str(exc))

    # ── Field extraction ───────────────────────────────────────────

    def extract_field_candidates(
        self,
        text: str,
        document_type: str = "id",
    ) -> Dict[str, Any]:
        """Extract field candidates deterministically from clean Docling text.

        Applies regex detectors for Emirates ID, passports, contextual dates, names,
        nationalities, and genders.

        Args:
            text: Plain text extracted by Docling.
            document_type: Document classification hint (e.g. 'passport', 'national_id').

        Returns:
            Dict[str, Any]: Dictionary of field_name -> extracted value. Only includes
            fields where regex or label heuristics match confidently. The downstream
            vision rung completes missing fields.

        Interconnections:
            - Fed into `compute_confidence()` and merged into `RungResult` within `ExtractionLadder`.
        """
        if not text:
            return {}

        candidates: Dict[str, Any] = {}

        # ── Document-number patterns ───────────────────────────────
        eid = _EID_RE.search(text)
        if eid:
            val = re.sub(r"[\s]", "-", eid.group(0))
            candidates["national_id_number"] = val
            candidates["id_number"] = val

        pp = _PASSPORT_RE.search(text)
        if pp and "passport" in document_type.lower():
            candidates["passport_number"] = pp.group(0).strip()

        # ── Dates with label context ───────────────────────────────
        candidates.update(_extract_dates_with_labels(text))

        # ── Free-text label fields ─────────────────────────────────
        name = _extract_labelled_field(text, "name", "full name", "surname")
        if name:
            candidates.setdefault("full_name", name)
            candidates.setdefault("name", name)

        nat = _extract_labelled_field(
            text, "nationality", "citizen", "country"
        )
        if nat:
            candidates["nationality"] = nat

        gender = _extract_labelled_field(text, "gender", "sex")
        if gender:
            g = gender.strip().upper()
            if g in ("M", "F", "MALE", "FEMALE"):
                candidates["gender"] = g
                candidates["sex"] = g

        return candidates

    def compute_confidence(
        self,
        candidates: Dict[str, Any],
        document_type: str,
    ) -> float:
        """Estimate extraction confidence based on how many mandatory fields were found.

        Uses the DEFAULT_THRESHOLDS mandatory_fields list from `services.extraction_ladder`
        where available. Scales confidence between 0.50 and configured `_field_confidence`.

        Args:
            candidates: Dict of candidate field extractions.
            document_type: Document classification key (e.g. 'passport', 'national_id').

        Returns:
            float: Estimated confidence score between 0.0 and 1.0.

        Interconnections:
            - Used by `ExtractionLadder` to decide whether to short-circuit the vision rung.
        """
        # Import lazily to avoid circular dependency
        try:
            from services.extraction_ladder import DEFAULT_THRESHOLDS
        except ImportError:
            return self._field_confidence if candidates else 0.0

        mandatory = DEFAULT_THRESHOLDS.get(
            document_type, {}
        ).get("mandatory_fields", [])
        if not mandatory:
            return self._field_confidence if candidates else 0.0

        found = sum(
            1 for f in mandatory
            if candidates.get(f) not in (None, "", [])
        )
        ratio = found / len(mandatory)
        # Scale between 0.5 and the configured field_confidence
        return round(0.5 + ratio * (self._field_confidence - 0.5), 4)


# ────────────────────────────────────────────────────────────────────
#  Internal helpers
# ────────────────────────────────────────────────────────────────────

def _fail(error: str) -> Dict[str, Any]:
    """Construct a standardized failure response dictionary.

    Args:
        error: Descriptive error message string.

    Returns:
        Dict[str, Any]: Pre-populated failure structure with success=False.
    """
    return {
        "success": False,
        "error": error,
        "markdown": "",
        "text": "",
        "tables": [],
        "pages": 0,
        "has_mrz": False,
    }
