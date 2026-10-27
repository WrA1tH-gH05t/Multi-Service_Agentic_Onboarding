"""Application wizard state management.

Manages the 4-step wizard flow:
1. Name - User enters full name
2. Document upload - System validates clarity, extracts fields
3. Review - User sees extracted data (masked), confirms/edits
4. Submitted - Final submission with reference ID

Fixes in this version
- to_dict() / get_summary() referenced id_file_url / id_file_name, which do not exist on the
  dataclass, so they raised AttributeError. They now read from the documents list.
- update_document_checks() set `self.updated_at` on the manager instead of the session, so the
  session's own timestamp never changed after an upload. Fixed.
- A re-upload appended a second document but the checks were written to the FIRST one, so the
  new file stayed unvalidated. A re-upload now replaces the earlier document of that type.
- malware_scan defaulted to "clean" although no scan runs. It now defaults to "not_scanned".
- update_clarity_check() silently did nothing because nothing ever created the clarity record.
- set_id_extraction() always jumped to REVIEW, even for a blurry document.
- Session ids are full UUIDs (were 8 characters) and lookups can be scoped to the owner.
- Serialisation masks personal data.

NOTE: sessions still live in memory. They are lost on restart and are not shared between
workers. Persist them through the Repository (see the notes that came with this patch).
"""
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SENSITIVE_KEY = re.compile(
    r"(^|_)(id|eid|passport|dob|birth|phone|mobile|email|address|iban|account|licen[sc]e)(_|$)|number",
    re.IGNORECASE,
)


def mask_value(key: str, value: Any) -> str:
    """Mask personal data for anything that is returned or logged."""
    text = "" if value is None else str(value)
    if not text or not _SENSITIVE_KEY.search(key):
        return text
    if re.search(r"birth|dob", key, re.IGNORECASE):
        return "••/••/••••"
    return "••••" if len(text) <= 4 else "•" * (len(text) - 3) + text[-3:]


def _mask_dict(fields: Dict[str, Any], mask: bool = True) -> Dict[str, str]:
    return {k: (mask_value(k, v) if mask else ("" if v is None else str(v))) for k, v in (fields or {}).items()}


def _first(fields: Dict[str, Any], *keys: str) -> str:
    """First non-empty value among alias keys (extraction output keys vary)."""
    for k in keys:
        v = fields.get(k)
        if v not in (None, ""):
            return str(v)
    return ""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class WizardStep(str, Enum):
    NAME = "name"
    ID_UPLOAD = "id_upload"
    REVIEW = "review"
    SUBMITTED = "submitted"


class ClarityStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"


class IDValidationStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    PENDING = "pending"


@dataclass
class DocumentClarityCheck:
    """Stores clarity check result for an uploaded document."""
    doc_type: str
    status: ClarityStatus
    quality_score: float = 0.0
    issues: List[str] = field(default_factory=list)
    checked_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doc_type": self.doc_type,
            "status": self.status.value,
            "quality_score": self.quality_score,
            "issues": self.issues,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
        }


@dataclass
class DocumentUpload:
    """Stores upload and validation result for a single document."""
    file_url: str = ""          # object name in MinIO
    file_name: str = ""
    doc_type: str = ""          # "national_id", "passport", "other"
    malware_scan: str = "not_scanned"  # "clean", "infected", "pending", "not_scanned"
    pdf_valid: bool = False
    is_blurry: bool = False
    blurry_fields: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    extracted_fields: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    uploaded_at: Optional[datetime] = None
    # Added so the route's calls match (it passes these on every upload)
    malware_details: str = ""
    malware_risk_score: float = 0.0
    pdf_pages: int = 0
    quality_details: str = ""
    extraction_success: bool = False
    sha256: str = ""
    accepted: bool = False          # passed every check (or was escalated to human review)
    needs_review: bool = False      # stored for a human reviewer after repeated failures
    review_reason: str = ""

    def to_dict(self, mask_pii: bool = True) -> Dict[str, Any]:
        return {
            "file_name": self.file_name,
            "pdf_pages": self.pdf_pages,
            "accepted": self.accepted,
            "needs_review": self.needs_review,
            "review_reason": self.review_reason,
            "quality_details": self.quality_details,
            "extraction_success": self.extraction_success,
            "doc_type": self.doc_type,
            "malware_scan": self.malware_scan,
            "pdf_valid": self.pdf_valid,
            "is_blurry": self.is_blurry,
            "blurry_fields": self.blurry_fields,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "extracted_fields": _mask_dict(self.extracted_fields, mask_pii),
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
        }


@dataclass
class IDFieldExtraction:
    """Stores extracted fields from ID document."""
    full_name: str = ""
    national_id_number: str = ""
    date_of_birth: str = ""
    gender: str = ""
    nationality: str = ""
    expiry_date: str = ""
    confidence: float = 0.0
    raw_fields: Dict[str, str] = field(default_factory=dict)

    def to_dict(self, mask_pii: bool = True) -> Dict[str, Any]:
        return {
            "full_name": self.full_name,
            "national_id_number": mask_value("national_id_number", self.national_id_number) if mask_pii else self.national_id_number,
            "date_of_birth": mask_value("date_of_birth", self.date_of_birth) if mask_pii else self.date_of_birth,
            "gender": self.gender,
            "nationality": self.nationality,
            "expiry_date": self.expiry_date,
            "confidence": self.confidence,
            "raw_fields": _mask_dict(self.raw_fields, mask_pii),
        }


@dataclass
class WizardSession:
    """Complete wizard session state for one applicant."""
    session_id: str
    user_id: Optional[str] = None
    current_step: WizardStep = WizardStep.NAME
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    applicant_name: str = ""

    documents: List[DocumentUpload] = field(default_factory=list)
    id_clarity_check: Optional[DocumentClarityCheck] = None
    id_extraction: Optional[IDFieldExtraction] = None
    id_validation_status: IDValidationStatus = IDValidationStatus.PENDING

    reviewed_fields: Dict[str, bool] = field(default_factory=dict)
    edit_requested_fields: List[str] = field(default_factory=list)

    submitted_at: Optional[datetime] = None
    reference_id: str = ""
    status: str = "draft"
    application_id: str = ""

    service_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_step(self, step: WizardStep):
        self.current_step = step
        self.updated_at = _now()

    def confirm_field(self, field_name: str, confirmed: bool = True):
        self.reviewed_fields[field_name] = confirmed
        self.updated_at = _now()

    def is_validated(self) -> bool:
        """True when there is at least one document and every document passed its checks."""
        return bool(self.documents) and all(
            d.accepted and d.pdf_valid and not d.is_blurry and d.malware_scan == "clean"
            for d in self.documents
        )

    def primary_document(self) -> Optional[DocumentUpload]:
        """The national ID if present, else the first document."""
        for d in self.documents:
            if d.doc_type == "national_id":
                return d
        return self.documents[0] if self.documents else None

    def to_dict(self, mask_pii: bool = True) -> Dict[str, Any]:
        primary = self.primary_document()
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "current_step": self.current_step.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "applicant_name": self.applicant_name,
            "id_file_url": primary.file_url if primary else "",
            "id_file_name": primary.file_name if primary else "",
            "documents": [d.to_dict(mask_pii) for d in self.documents],
            "id_clarity": self.id_clarity_check.status.value if self.id_clarity_check else None,
            "id_clarity_score": self.id_clarity_check.quality_score if self.id_clarity_check else None,
            "id_clarity_issues": self.id_clarity_check.issues if self.id_clarity_check else [],
            "id_fields": self.id_extraction.to_dict(mask_pii) if self.id_extraction else {},
            "id_validation_status": self.id_validation_status.value,
            "reviewed_fields": self.reviewed_fields,
            "edit_requested": self.edit_requested_fields,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "reference_id": self.reference_id,
            "status": self.status,
            "application_id": self.application_id,
            "service_id": self.service_id,
            "metadata": self.metadata,
        }


class WizardStateManager:
    """Manages all wizard sessions.

    Every method accepts an optional keyword `user_id`. When given, the session is returned only
    if it belongs to that user (a different user gets None, as if it did not exist). Routes
    should always pass the authenticated user's id.
    """

    def __init__(self):
        self._sessions: Dict[str, WizardSession] = {}
        self._user_sessions: Dict[str, str] = {}

    # -- lookup -------------------------------------------------------- #

    def _get(self, session_id: str, user_id: Optional[str] = None) -> Optional[WizardSession]:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if user_id is not None and str(session.user_id) != str(user_id):
            return None
        return session

    def get_session(self, session_id: str, user_id: Optional[str] = None) -> Optional[WizardSession]:
        return self._get(session_id, user_id)

    def get_user_session(self, user_id: str) -> Optional[WizardSession]:
        session_id = self._user_sessions.get(user_id)
        return self._sessions.get(session_id) if session_id else None

    def create_session(self, user_id: Optional[str] = None, service_id: str = "basic_registration") -> WizardSession:
        session_id = uuid.uuid4().hex
        session = WizardSession(session_id=session_id, user_id=user_id, service_id=service_id)
        self._sessions[session_id] = session
        if user_id:
            self._user_sessions[user_id] = session_id
        logger.info(f"Created wizard session {session_id[:8]} for service {service_id}")
        return session

    def remove_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        session = self._get(session_id, user_id)
        if not session:
            return False
        del self._sessions[session_id]
        if session.user_id and self._user_sessions.get(session.user_id) == session_id:
            del self._user_sessions[session.user_id]
        return True

    # -- steps --------------------------------------------------------- #

    def advance_step(self, session_id: str, step: WizardStep, *, user_id: Optional[str] = None) -> Optional[WizardSession]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        session.update_step(step)
        return session

    def set_name(self, session_id: str, name: str, *, user_id: Optional[str] = None) -> Optional[WizardSession]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        session.applicant_name = name
        session.update_step(WizardStep.ID_UPLOAD)
        return session

    def add_document(self, session_id: str, file_url: str, file_name: str, doc_type: str = "national_id",
                     *, sha256: str = "", user_id: Optional[str] = None) -> Optional[DocumentUpload]:
        """Register an uploaded document. A new upload of the same type replaces the old one."""
        session = self._get(session_id, user_id)
        if not session:
            return None
        previous = [d for d in session.documents if d.doc_type == doc_type]
        if previous:
            session.metadata.setdefault("superseded_files", []).extend(d.file_url for d in previous if d.file_url)
            session.documents = [d for d in session.documents if d.doc_type != doc_type]
        doc = DocumentUpload(file_url=file_url, file_name=file_name, doc_type=doc_type, sha256=sha256)
        session.documents.append(doc)
        session.updated_at = _now()
        return doc

    def get_document_by_type(self, session_id: str, doc_type: str, *, user_id: Optional[str] = None) -> Optional[DocumentUpload]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        for doc in reversed(session.documents):
            if doc.doc_type == doc_type:
                return doc
        return None

    def update_document_checks(
        self,
        session_id: str,
        doc_type: str,
        malware_scan: str = "not_scanned",
        pdf_valid: bool = False,
        is_blurry: bool = False,
        blurry_fields: Optional[List[str]] = None,
        quality_score: float = 0.0,
        extracted_fields: Optional[Dict[str, str]] = None,
        confidence: float = 0.0,
        malware_details: str = "",
        malware_risk_score: float = 0.0,
        pdf_pages: int = 0,
        quality_details: str = "",
        extraction_success: bool = False,
        accepted: bool = False,
        needs_review: bool = False,
        review_reason: str = "",
        *,
        user_id: Optional[str] = None,
    ) -> Optional[DocumentUpload]:
        """Save validation and extraction results for a document."""
        session = self._get(session_id, user_id)
        if not session:
            return None
        doc = self.get_document_by_type(session_id, doc_type, user_id=user_id)
        if not doc:
            return None
        doc.malware_scan = malware_scan
        doc.pdf_valid = pdf_valid
        doc.is_blurry = is_blurry
        doc.blurry_fields = blurry_fields or []
        doc.quality_score = quality_score
        doc.extracted_fields = extracted_fields or {}
        doc.confidence = confidence
        doc.malware_details = malware_details
        doc.malware_risk_score = malware_risk_score
        doc.pdf_pages = pdf_pages
        doc.quality_details = quality_details
        doc.extraction_success = extraction_success
        doc.accepted = accepted
        doc.needs_review = needs_review
        doc.review_reason = review_reason
        doc.uploaded_at = _now()
        session.updated_at = _now()
        return doc

    def update_clarity_check(self, session_id: str, status: ClarityStatus, quality_score: float,
                             issues: Optional[List[str]] = None, *, user_id: Optional[str] = None,
                             doc_type: str = "national_id") -> Optional[WizardSession]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        if session.id_clarity_check is None:
            session.id_clarity_check = DocumentClarityCheck(doc_type=doc_type, status=status)
        check = session.id_clarity_check
        check.status = status
        check.quality_score = quality_score
        check.issues = issues or []
        check.checked_at = _now()
        session.id_validation_status = IDValidationStatus.PASS if status == ClarityStatus.PASS else IDValidationStatus.FAIL
        session.updated_at = _now()
        return session

    def set_id_extraction(self, session_id: str, fields: Dict[str, str], confidence: float,
                          *, user_id: Optional[str] = None, advance_to_review: bool = True) -> Optional[WizardSession]:
        """Store extracted ID fields. Moves to REVIEW only if nothing is blurry or failed."""
        session = self._get(session_id, user_id)
        if not session:
            return None
        session.id_extraction = IDFieldExtraction(
            full_name=_first(fields, "full_name", "name"),
            national_id_number=_first(fields, "national_id_number", "id_number", "document_number"),
            date_of_birth=_first(fields, "date_of_birth", "dob"),
            gender=_first(fields, "gender", "sex"),
            nationality=_first(fields, "nationality"),
            expiry_date=_first(fields, "expiry_date", "date_of_expiry"),
            confidence=confidence,
            raw_fields=dict(fields or {}),
        )
        blocked = (session.id_validation_status == IDValidationStatus.FAIL
                   or any(d.is_blurry for d in session.documents))
        if advance_to_review and not blocked:
            session.update_step(WizardStep.REVIEW)
        session.updated_at = _now()
        return session

    def apply_field_edit(self, session_id: str, field_name: str, new_value: str,
                         *, user_id: Optional[str] = None) -> Optional[WizardSession]:
        """Apply an inline edit during review. Edited fields are recorded so they can be audited."""
        session = self._get(session_id, user_id)
        if not session:
            return None
        if session.id_extraction:
            if field_name in ("full_name", "national_id_number", "date_of_birth",
                              "gender", "nationality", "expiry_date"):
                setattr(session.id_extraction, field_name, new_value)
            session.id_extraction.raw_fields[field_name] = new_value
        for doc in session.documents:
            if field_name in doc.extracted_fields:
                doc.extracted_fields[field_name] = new_value
        edited = session.metadata.setdefault("edited_fields", [])
        if field_name not in edited:
            edited.append(field_name)
        session.updated_at = _now()
        return session

    def set_application_id(self, session_id: str, app_id: str, *, user_id: Optional[str] = None) -> Optional[WizardSession]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        session.application_id = app_id
        session.updated_at = _now()
        return session

    def submit_wizard(self, session_id: str, reference_id: str, status: str = "submitted",
                      *, user_id: Optional[str] = None) -> Optional[WizardSession]:
        """Finalize submission. Safe to call twice: a submitted session is returned unchanged."""
        session = self._get(session_id, user_id)
        if not session:
            return None
        if session.submitted_at is not None:
            return session
        session.submitted_at = _now()
        session.reference_id = reference_id
        session.status = status
        session.update_step(WizardStep.SUBMITTED)
        return session

    # -- reporting ----------------------------------------------------- #

    def list_sessions(self, mask_pii: bool = True) -> List[Dict[str, Any]]:
        return [s.to_dict(mask_pii) for s in self._sessions.values()]

    def get_summary(self, session_id: str, *, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        session = self._get(session_id, user_id)
        if not session:
            return None
        primary = session.primary_document()
        return {
            "session_id": session_id,
            "step": session.current_step.value,
            "name_set": bool(session.applicant_name),
            "id_uploaded": primary is not None,
            "clarity_checked": session.id_clarity_check is not None,
            "id_validated": session.id_validation_status == IDValidationStatus.PASS,
            "fields_confirmed": len(session.reviewed_fields),
            "submitted": session.submitted_at is not None,
        }
