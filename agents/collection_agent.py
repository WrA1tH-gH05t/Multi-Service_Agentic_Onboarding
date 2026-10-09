"""
Collection Agent - Phase 2

Responsible for collecting a complete submission as a reasoning component,
not just a script that asks for the next item on a list.

Design Decision: Uses a state machine with reasoning steps, not a flat
list. The agent tracks what's submitted vs what's missing, reasons about
alternatives, and handles mid-conversation interruptions without losing
state.
"""

from typing import Dict, List, Optional, Tuple, Set
from datetime import datetime, timezone

def _utcnow():
    return datetime.now(timezone.utc)
import uuid


class DocumentRequirement:
    """Represents a single document requirement for a service."""

    def __init__(self, doc_type: str, mandatory: bool = True):
        self.doc_type = doc_type
        self.mandatory = mandatory
        self.submitted = False
        self.submitted_file_id: Optional[str] = None
        self.submitted_at: Optional[datetime] = None
        self.extraction_ok = False
        self.extraction_fields: Dict = {}
        self.extraction_confidence: float = 0.0
        self.upload_failures: int = 0
        self.last_failure_reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "doc_type": self.doc_type,
            "mandatory": self.mandatory,
            "submitted": self.submitted,
            "submitted_file_id": self.submitted_file_id,
            "extraction_ok": self.extraction_ok,
            "extraction_confidence": self.extraction_confidence,
            "upload_failures": self.upload_failures,
            "last_failure_reason": self.last_failure_reason,
        }


class ApplicationSession:
    """
    Represents a user's application session, tracking what has been
    collected and what remains.
    """

    def __init__(self, session_id: str, user_id: str, service_id: str):
        self.session_id = session_id
        self.user_id = user_id
        self.service_id = service_id
        self.service_name: str = ""
        self.service_description: str = ""
        self.processing_time: str = ""
        self.created_at: datetime = datetime.now(timezone.utc)
        self.last_updated: datetime = datetime.now(timezone.utc)
        self.status: str = "collecting"  # collecting, incomplete, complete, interrupted, exception
        self.document_requirements: Dict[str, DocumentRequirement] = {}
        self.submitted_file_ids: List[str] = []
        self.conversation_history: List[dict] = []
        self.notes: List[str] = []

    def add_document_requirement(self, doc_type: str, mandatory: bool = True):
        """Add a document requirement for this application."""
        self.document_requirements[doc_type] = DocumentRequirement(doc_type, mandatory)

    def get_next_required_document(self) -> Optional[str]:
        """
        Determine the next document to ask for.

        Design Decision: Asks for the first missing mandatory document,
        then any missing optional documents. This avoids asking the user
        to guess which document they should upload next.
        """
        # First, mandatory missing
        for doc_type, req in self.document_requirements.items():
            if req.mandatory and not req.submitted:
                return doc_type

        # Then optional
        for doc_type, req in self.document_requirements.items():
            if not req.submitted:
                return doc_type

        return None

    def mark_document_submitted(self, doc_type: str, file_id: str,
                                 extraction_ok: bool = True,
                                 extraction_fields: Dict = None,
                                 extraction_confidence: float = 0.0):
        """Mark a document as submitted with extraction results."""
        if doc_type in self.document_requirements:
            req = self.document_requirements[doc_type]
            req.submitted = True
            req.submitted_file_id = file_id
            req.submitted_at = datetime.now(timezone.utc)
            req.extraction_ok = extraction_ok
            req.extraction_fields = extraction_fields or {}
            req.extraction_confidence = extraction_confidence
            if file_id not in self.submitted_file_ids:
                self.submitted_file_ids.append(file_id)

        self.last_updated = _utcnow()

    def record_upload_failure(self, doc_type: str, reason: str):
        """Record an upload failure and reason."""
        if doc_type in self.document_requirements:
            req = self.document_requirements[doc_type]
            req.upload_failures += 1
            req.last_failure_reason = reason
            self.last_updated = _utcnow()

    def check_completeness(self) -> Tuple[bool, List[str]]:
        """
        Check if all required documents have been submitted.

        Returns:
            (is_complete, list_of_missing_docs)
        """
        missing = []
        for doc_type, req in self.document_requirements.items():
            if req.mandatory and not req.submitted:
                missing.append(doc_type)

        return (len(missing) == 0, missing)

    def get_required_count(self) -> int:
        """Get total number of required documents (immutable)."""
        return len(self.document_requirements)

    def get_submitted_count(self) -> int:
        """Get number of submitted documents."""
        return sum(1 for r in self.document_requirements.values() if r.submitted)

    def is_ready_for_validation(self) -> bool:
        """Check if the application has all required documents and is ready for validation."""
        complete, _ = self.check_completeness()
        # Also check that extracted documents are readable
        for doc_type, req in self.document_requirements.items():
            if req.submitted and not req.extraction_ok:
                return False
        return complete

    def get_status_message(self) -> str:
        """Get a human-readable status message."""
        if self.status == "complete":
            return "Application complete. Ready for validation."
        elif self.status == "exception":
            return "An issue has occurred. A human validator has been notified."
        elif self.status == "interrupted":
            return "Application paused. You can resume or start over."

        # Count submitted vs total
        total = len(self.document_requirements)
        submitted = sum(1 for r in self.document_requirements.values() if r.submitted)

        if submitted > 0:
            return f"Progress: {submitted}/{total} documents submitted. " \
                   f"Next: please upload {self.get_next_required_document()}."
        else:
            first_req = next(iter(self.document_requirements))
            return f"Please upload your {first_req} to begin."

    def handle_interruption(self):
        """Handle a user interrupting mid-submission (e.g., asks a question or changes service)."""
        self.status = "interrupted"
        self.notes.append(f"Session interrupted at {_utcnow().isoformat()}")

    def resume(self):
        """Resume an interrupted session."""
        self.status = "collecting"
        self.notes.append(f"Session resumed at {_utcnow().isoformat()}")

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "service_id": self.service_id,
            "service_name": self.service_name,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "document_requirements": {k: v.to_dict() for k, v in self.document_requirements.items()},
            "submitted_file_ids": self.submitted_file_ids,
            "notes": self.notes,
        }


class CollectionAgent:
    """
    Collection Agent - Phase 2

    The agent responsible for collecting a complete submission as a
    reasoning component, not just a script that asks for the next item
    on a list.

    Key capabilities:
    - Works out what documents are required for the chosen service
    - Tracks what has been submitted vs what is still missing
    - Asks for the right thing next
    - Reasons about whether an acceptable alternative exists
    - Works out why an upload went wrong before deciding what to ask
    - Handles interruptions without losing state
    """

    def __init__(self, repository=None):
        self.sessions: Dict[str, ApplicationSession] = {}
        self.sessions_by_user: Dict[str, str] = {}  # user_id -> active_session_id
        self.repository = repository

    def _persist_session(self, session: ApplicationSession, application_id: str = None):
        """Persist current session state to PostgreSQL via repository."""
        if self.repository:
            self.repository.save_collection_session(
                session_id=session.session_id,
                user_id=session.user_id,
                service_id=session.service_id,
                service_name=session.service_name,
                status=session.status,
                document_requirements={k: v.to_dict() for k, v in session.document_requirements.items()},
                submitted_file_ids=session.submitted_file_ids,
                application_id=application_id,
            )

    def _restore_session(self, session_id: str, user_id: str) -> Optional[ApplicationSession]:
        """Restore a CollectionAgent session from PostgreSQL."""
        if not self.repository:
            return None
        data = self.repository.get_collection_session(session_id, user_id)
        if not data:
            return None
        session = ApplicationSession(
            session_id=session_id,
            user_id=user_id,
            service_id=data.get("service_id", ""),
        )
        session.service_name = data.get("step", "").replace("collection:", "")
        session.status = data.get("status", "collecting")
        doc_reqs = data.get("document_requirements", {})
        for doc_type, req_data in doc_reqs.items():
            req = DocumentRequirement(doc_type, mandatory=req_data.get("mandatory", True))
            req.submitted = req_data.get("submitted", False)
            req.submitted_file_id = req_data.get("submitted_file_id")
            req.extraction_ok = req_data.get("extraction_ok", False)
            req.extraction_fields = req_data.get("extraction_fields", {})
            req.extraction_confidence = req_data.get("extraction_confidence", 0.0)
            session.document_requirements[doc_type] = req
        session.submitted_file_ids = data.get("submitted_file_ids", [])
        return session

    def create_session(self, user_id: str, service_id: str,
                       service_name: str = "", service_description: str = "",
                       processing_time: str = "",
                       required_documents: List[str] = None,
                       allowed_alternatives: Dict = None) -> str:
        """Create a new application session for a user."""
        session_id = str(uuid.uuid4())

        session = ApplicationSession(session_id, user_id, service_id)
        session.service_name = service_name
        session.service_description = service_description
        session.processing_time = processing_time

        # Store immutable requirements from catalogue
        if required_documents:
            for doc_type in required_documents:
                session.add_document_requirement(doc_type, mandatory=True)

        # Track as active session for this user
        if user_id in self.sessions_by_user:
            prev_id = self.sessions_by_user[user_id]
            if prev_id in self.sessions:
                prev = self.sessions[prev_id]
                prev.handle_interruption()

        self.sessions[session_id] = session
        self.sessions_by_user[user_id] = session_id

        # Persist new session to database
        self._persist_session(session)

        return session_id

    def get_session(self, session_id: str, user_id: str = None) -> Optional[ApplicationSession]:
        """Get a session by ID. If user_id provided, verify ownership."""
        session = self.sessions.get(session_id)
        if session and user_id and session.user_id != user_id:
            return None
        return session

    def get_user_active_session(self, user_id: str) -> Optional[ApplicationSession]:
        """Get the active session for a user."""
        session_id = self.sessions_by_user.get(user_id)
        if session_id:
            return self.sessions.get(session_id)
        return None

    def submit_document(self, session_id: str, doc_type: str, file_id: str,
                        extraction_ok: bool = True,
                        extraction_fields: Dict = None,
                        extraction_confidence: float = 0.0) -> Dict:
        """
        Submit a document for a session and process it.

        Returns a response dict with action taken.
        """
        session = self.get_session(session_id)
        if not session:
            return {"error": "Session not found", "action": "error"}

        # Check if this document type is required for this service
        if doc_type not in session.document_requirements:
            # Maybe it's an alternative?
            service_id = session.service_id
            # We'll handle this in the routing layer
            return {
                "error": f"Document type '{doc_type}' is not a valid document for {session.service_name}",
                "action": "rejected_wrong_type",
                "message": f"This service requires: {', '.join(session.document_requirements.keys())}"
            }

        req = session.document_requirements[doc_type]

        # Check for duplicate upload
        if req.submitted and req.submitted_file_id == file_id:
            return {
                "action": "rejected_duplicate",
                "message": f"You have already uploaded a {doc_type}. Uploading the same document twice is not allowed."
            }

        if extraction_ok:
            session.mark_document_submitted(
                doc_type, file_id, extraction_ok, extraction_fields, extraction_confidence
            )

            # Persist after document submission
            self._persist_session(session, application_id=session_id)  # application_id tied later

            # Check if application is now complete
            is_complete, missing = session.check_completeness()
            if is_complete:
                all_ok = all(r.extraction_ok for r in session.document_requirements.values())
                if all_ok:
                    session.status = "complete"
                else:
                    # Some documents failed extraction
                    session.status = "incomplete"
                    failed = [dt for dt, r in session.document_requirements.items()
                              if not r.extraction_ok]
                # Persist final state
                self._persist_session(session)
                if all_ok:
                    return {
                        "action": "complete",
                        "message": f"All required documents submitted for {session.service_name}. "
                                   f"Your application is ready for validation."
                    }
                else:
                    return {
                        "action": "needs_review",
                        "message": f"All documents received but some need human review due to extraction issues: {', '.join(failed)}"
                    }
            else:
                next_doc = self._suggest_next(session)
                return {
                    "action": "continue",
                    "message": f"Successfully uploaded {doc_type}. {session.get_status_message()}",
                    "next": next_doc
                }
        else:
            # Extraction failed
            session.record_upload_failure(doc_type, "Extraction failed")

            # Check if we've exceeded retry limit
            if req.upload_failures >= 2:
                # Hand off to validation agent
                session.status = "exception"
                return {
                    "action": "escalate_to_validation",
                    "message": f"The {doc_type} could not be read clearly after multiple attempts. "
                               f"I will escalate this to a human validator."
                }

            return {
                "action": "retry",
                "message": f"The {doc_type} image is not clear enough. Please try again with a "
                           f"clearer photo. Make sure the entire document is visible and not blurry.",
                "suggestion": f"Ensure the document is flat on a table, well-lit, and all corners are visible."
            }

    def handle_question(self, session_id: str, question: str) -> Dict:
        """
        Handle a user asking a question during submission.

        The session is NOT interrupted - we answer the question and
        return to the collection flow.
        """
        session = self.get_session(session_id)
        if not session:
            return {"error": "Session not found"}

        session.notes.append(f"Question asked during collection: {question}")

        # For now, return a placeholder - the actual FAQ answer comes from
        # the service catalogue + generation service
        return {
            "action": "answer_question",
            "session_id": session_id,
            "message": f"I've noted your question: '{question}'. "
                       f"Meanwhile, your application status: {session.get_status_message()}"
        }

    def handle_service_change(self, user_id: str, new_service_id: str) -> Dict:
        """
        Handle a user switching services mid-conversation.

        Documents already uploaded must NOT attach to the wrong service.
        """
        current = self.get_user_active_session(user_id)
        if current:
            current.handle_interruption()
            current.notes.append(f"User switched service from {current.service_id} to {new_service_id}")
            # Persist interrupted session
            self._persist_session(current)

        return {
            "action": "service_changed",
            "old_session_status": "interrupted" if current else None,
            "message": f"Your previous application for {current.service_name if current else 'the previous service'} has been paused. "
                       f"Starting a new application for the new service."
        }

    def _suggest_next(self, session: ApplicationSession) -> str:
        """Suggest the next document to ask for."""
        next_doc = session.get_next_required_document()
        if next_doc:
            return f"Please upload your {next_doc}."
        return "All required documents collected!"

    def reason_about_upload_failure(self, session_id: str, file_type: str,
                                     extraction_result: Dict) -> str:
        """
        Reason about why an upload went wrong and give specific advice.

        Design Decision: Categorizes failures into distinct types so the
        agent can give specific, helpful responses instead of generic
        "try again" messages.
        """
        session = self.get_session(session_id)
        if not session:
            return "Session not found."

        doc_type = self._get_document_type_for_upload(session, file_type)

        # Wrong document type entirely
        if doc_type and doc_type not in session.document_requirements:
            return (f"That is not the correct document type. "
                    f"Please upload a {', '.join(session.document_requirements.keys())}.")

        # Right type but unclear image
        if extraction_result.get("confidence", 1.0) < 0.5:
            return (f"The image quality is too low to read the {doc_type}. "
                    f"Please retake the photo ensuring the document is flat, "
                    f"well-lit, and all text is clearly visible.")

        # Document is corrupted or unreadable
        if extraction_result.get("extracted_text") == "":
            return (f"The uploaded file appears to be corrupted or empty. "
                    f"Please try uploading a different file.")

        return "Unknown error with the upload."

    def _get_document_type_for_upload(self, session: ApplicationSession,
                                       file_type: str) -> Optional[str]:
        """Determine what document type was uploaded (for error reasoning)."""
        # Simplified - in production this would use the DocumentClassifier
        return None

    def get_all_sessions_for_user(self, user_id: str) -> List[ApplicationSession]:
        """Get all sessions for a user (including interrupted ones)."""
        return [s for s in self.sessions.values() if s.user_id == user_id]

    def remove_session(self, session_id: str, user_id: str) -> bool:
        """Remove a session, verifying ownership."""
        session = self.sessions.get(session_id)
        if session and session.user_id == user_id:
            del self.sessions[session_id]
            if self.sessions_by_user.get(user_id) == session_id:
                del self.sessions_by_user[user_id]
            return True
        return False
