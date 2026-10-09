"""Application wizard state management.

Manages the 4-step Basic Registration wizard flow:
1. Name - User enters full name
2. National ID upload - System validates clarity, extracts fields
3. Review - User sees extracted data (masked), confirms/edits
4. Submitted - Final submission with reference ID
"""
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


@dataclass
class DocumentUpload:
    """Stores upload and validation result for a single document."""
    file_url: str = ""
    file_name: str = ""
    doc_type: str = ""  # "national_id", "passport", "other"
    malware_scan: str = "pending"  # "clean", "infected", "pending"
    pdf_valid: bool = False
    is_blurry: bool = False
    blurry_fields: List[str] = field(default_factory=list)  # fields that couldn't be extracted
    quality_score: float = 0.0
    extracted_fields: Dict[str, str] = field(default_factory=dict)
    confidence: float = 0.0
    uploaded_at: Optional[datetime] = None


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


@dataclass
class WizardSession:
    """Complete wizard session state for one applicant."""
    session_id: str
    user_id: Optional[str] = None
    current_step: WizardStep = WizardStep.NAME
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Step 1: Name
    applicant_name: str = ""

    # Step 2: Document uploads (can be multiple: national_id, passport, etc.)
    documents: List[DocumentUpload] = field(default_factory=list)
    id_clarity_check: Optional[DocumentClarityCheck] = None  # legacy, kept for compat
    id_extraction: Optional[IDFieldExtraction] = None  # legacy, kept for compat
    id_validation_status: IDValidationStatus = IDValidationStatus.PENDING

    # Step 3: Review
    reviewed_fields: Dict[str, bool] = field(default_factory=dict)  # field_name -> confirmed
    edit_requested_fields: List[str] = field(default_factory=list)

    # Step 4: Submission
    submitted_at: Optional[datetime] = None
    reference_id: str = ""
    status: str = "draft"
    application_id: str = ""

    # Metadata
    service_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def update_step(self, step: WizardStep):
        """Advance wizard to next step."""
        self.current_step = step
        self.updated_at = datetime.now(timezone.utc)

    def confirm_field(self, field_name: str, confirmed: bool = True):
        """Mark a field as confirmed during review."""
        self.reviewed_fields[field_name] = confirmed
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize wizard state."""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "current_step": self.current_step.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "applicant_name": self.applicant_name,
            "id_file_url": self.id_file_url,
            "id_file_name": self.id_file_name,
            "id_clarity": self.id_clarity_check.status.value if self.id_clarity_check else None,
            "id_clarity_score": self.id_clarity_check.quality_score if self.id_clarity_check else None,
            "id_clarity_issues": self.id_clarity_check.issues if self.id_clarity_check else [],
            "id_fields": self.id_extraction.__dict__ if self.id_extraction else {},
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
    """Manages all wizard sessions."""

    def __init__(self):
        self._sessions: Dict[str, WizardSession] = {}
        self._user_sessions: Dict[str, str] = {}  # user_id -> session_id

    def create_session(
        self,
        user_id: Optional[str] = None,
        service_id: str = "basic_registration",
    ) -> WizardSession:
        """Create a new wizard session."""
        session_id = str(uuid.uuid4())[:8]
        session = WizardSession(
            session_id=session_id,
            user_id=user_id,
            service_id=service_id,
        )
        self._sessions[session_id] = session
        if user_id:
            self._user_sessions[user_id] = session_id
        logger.info(f"Created wizard session {session_id} for user {user_id}")
        return session

    def get_session(self, session_id: str) -> Optional[WizardSession]:
        """Get a wizard session by ID."""
        return self._sessions.get(session_id)

    def get_user_session(self, user_id: str) -> Optional[WizardSession]:
        """Get the active wizard session for a user."""
        session_id = self._user_sessions.get(user_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def advance_step(self, session_id: str, step: WizardStep) -> Optional[WizardSession]:
        """Advance the wizard to the next step."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.update_step(step)
        return session

    def set_name(self, session_id: str, name: str) -> Optional[WizardSession]:
        """Set applicant name (Step 1)."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.applicant_name = name
        session.update_step(WizardStep.ID_UPLOAD)
        return session

    def add_document(
        self,
        session_id: str,
        file_url: str,
        file_name: str,
        doc_type: str = "national_id",
    ) -> Optional[DocumentUpload]:
        """Add a new document upload (Step 2)."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        doc = DocumentUpload(
            file_url=file_url,
            file_name=file_name,
            doc_type=doc_type,
        )
        session.documents.append(doc)
        session.updated_at = datetime.now(timezone.utc)
        return doc

    def get_document_by_type(self, session_id: str, doc_type: str) -> Optional[DocumentUpload]:
        """Get the first document of a given type."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        for doc in session.documents:
            if doc.doc_type == doc_type:
                return doc
        return None

    def update_document_checks(
        self,
        session_id: str,
        doc_type: str,
        malware_scan: str = "clean",
        pdf_valid: bool = False,
        is_blurry: bool = False,
        blurry_fields: Optional[List[str]] = None,
        quality_score: float = 0.0,
        extracted_fields: Optional[Dict[str, str]] = None,
        confidence: float = 0.0,
    ) -> Optional[DocumentUpload]:
        """Update validation and extraction results for a document."""
        doc = self.get_document_by_type(session_id, doc_type)
        if not doc:
            return None
        doc.malware_scan = malware_scan
        doc.pdf_valid = pdf_valid
        doc.is_blurry = is_blurry
        doc.blurry_fields = blurry_fields or []
        doc.quality_score = quality_score
        doc.extracted_fields = extracted_fields or {}
        doc.confidence = confidence
        doc.uploaded_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)
        return doc

    def update_clarity_check(
        self,
        session_id: str,
        status: ClarityStatus,
        quality_score: float,
        issues: Optional[List[str]] = None,
    ) -> Optional[WizardSession]:
        """Update clarity check result (Step 2)."""
        session = self._sessions.get(session_id)
        if not session or not session.id_clarity_check:
            return None
        session.id_clarity_check.status = status
        session.id_clarity_check.quality_score = quality_score
        session.id_clarity_check.issues = issues or []
        session.id_clarity_check.checked_at = datetime.now(timezone.utc)
        session.id_validation_status = (
            IDValidationStatus.PASS if status == ClarityStatus.PASS
            else IDValidationStatus.FAIL
        )
        session.updated_at = datetime.now(timezone.utc)
        return session

    def set_id_extraction(
        self,
        session_id: str,
        fields: Dict[str, str],
        confidence: float,
    ) -> Optional[WizardSession]:
        """Set extracted ID fields (Step 2 -> Step 3)."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.id_extraction = IDFieldExtraction(
            full_name=fields.get("full_name", ""),
            national_id_number=fields.get("national_id_number", ""),
            date_of_birth=fields.get("date_of_birth", ""),
            gender=fields.get("gender", ""),
            nationality=fields.get("nationality", ""),
            expiry_date=fields.get("expiry_date", ""),
            confidence=confidence,
            raw_fields=fields,
        )
        # Auto-advance to review
        session.update_step(WizardStep.REVIEW)
        session.updated_at = datetime.now(timezone.utc)
        return session

    def apply_field_edit(self, session_id: str, field_name: str, new_value: str) -> Optional[WizardSession]:
        """Apply an inline edit to a field during review (Step 3)."""
        session = self._sessions.get(session_id)
        if not session:
            return None

        # Update the field in the extracted data
        if session.id_extraction:
            if field_name in ("full_name", "national_id_number", "date_of_birth",
                            "gender", "nationality", "expiry_date"):
                setattr(session.id_extraction, field_name, new_value)
                session.id_extraction.raw_fields[field_name] = new_value
            else:
                session.id_extraction.raw_fields[field_name] = new_value

        # Also update extracted_fields for all documents
        for doc in session.documents:
            if field_name in doc.extracted_fields:
                doc.extracted_fields[field_name] = new_value

        session.updated_at = datetime.now(timezone.utc)
        return session

    def set_application_id(
        self,
        session_id: str,
        app_id: str,
    ) -> Optional[WizardSession]:
        """Link wizard session to application."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.application_id = app_id
        session.updated_at = datetime.now(timezone.utc)
        return session

    def submit_wizard(
        self,
        session_id: str,
        reference_id: str,
        status: str = "submitted",
    ) -> Optional[WizardSession]:
        """Finalize wizard submission (Step 4)."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.submitted_at = datetime.now(timezone.utc)
        session.reference_id = reference_id
        session.status = status
        session.update_step(WizardStep.SUBMITTED)
        return session

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all wizard sessions (for admin/monitoring)."""
        return [s.to_dict() for s in self._sessions.values()]

    def get_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of wizard progress."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        return {
            "session_id": session_id,
            "step": session.current_step.value,
            "name_set": bool(session.applicant_name),
            "id_uploaded": bool(session.id_file_url),
            "clarity_checked": session.id_clarity_check is not None,
            "id_validated": session.id_validation_status == IDValidationStatus.PASS,
            "fields_confirmed": len(session.reviewed_fields),
            "submitted": session.status == "submitted",
        }
