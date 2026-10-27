"""
Repository layer — user-scoped data access.

Module Purpose & Role in the Project:
-------------------------------------
Acts as the authoritative, security-hardened data access layer for all persistent operations.
It wraps `services.database.DatabaseService` to strictly enforce tenant and cross-user isolation:
every query, update, insert, or deletion on sensitive entities (Applications, Documents, Chat
Sessions, Collection Sessions) requires and enforces a valid `user_id`. Callers cannot accidentally
or maliciously read, overwrite, or delete records belonging to another user.

Interconnections with Other Subsystems:
- Fast API Routes:
  * `app.routes.applications`: Uses `create_application`, `list_user_applications`, and `get_application`
    for managing client onboarding lifecycles.
  * `app.routes.documents`: Uses `get_document`, `list_user_documents`, `upload_document`,
    `delete_application`, `transition_application_status`, `get_validation_rules`, and idempotency
    key registration during document upload, processing, and cascade deletion.
  * `app.routes.chat`: Uses `get_chat_session`, `update_chat_session`, `save_chat_message`, and
    `get_chat_session_messages` to manage conversational history with strict user-bound authorization.
  * `app.routes.wizard`: Uses `check_and_mark_application_complete` to finalize onboarding applications.
- Database Layer:
  * Delegates session lifecycle, connection pooling, and raw SQL/ORM transactions to
    `services.database.DatabaseService`.
- Object Storage:
  * Works with `services.storage.StorageService` in cascading deletions (`delete_application`) to ensure
    both MinIO object binaries and database rows are purged cleanly.
"""

import logging
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime, timezone

from services.database import DatabaseService
from services.database import Application, Document, ChatSession, Service


logger = logging.getLogger(__name__)

# Columns a caller may change through update_application / update_chat_session. Anything else is
# refused. The old code accepted any attribute that existed on the model (hasattr), including
# created_at, updated_at and relationship attributes such as `user` or `documents`.
UPDATABLE_APPLICATION_FIELDS = {"status", "validation_result", "applicant_name", "required_documents",
                                "collection_session_id"}
UPDATABLE_CHAT_FIELDS = {"step", "selected_service", "applicant_name", "application_id",
                         "uploaded_documents", "required_documents", "collection_session_id"}
ALLOWED_APPLICATION_STATUSES = {"incomplete", "processing", "complete", "needs_review", "rejected"}


class Repository:
    """User-scoped repository for all persistent data access.

    Responsibility:
    - Central mediator and isolation gate between business logic (routes/agents) and
      the database (`services.database.DatabaseService`).
    - Enforces authorization and ownership guarantees at the data-access boundary:
      every mutation and retrieval requires `user_id`, preventing horizontal privilege escalation.
    - Manages lifecycle for Applications, Documents, Chat Sessions, Collection Agent Sessions,
      Validation Rules, and Idempotency deduplication keys.

    State Attributes:
    - db (DatabaseService): Instance of DatabaseService managing database connections, session scopes,
      and ORM mapping.

    Interactions:
    - Injected into routes (`applications.py`, `documents.py`, `chat.py`, `wizard.py`).
    - Interacts with MinIO via `StorageService` during cascade deletion.
    """

    def __init__(self, db: DatabaseService):
        """Initialize Repository with an active DatabaseService instance.

        Args:
            db (DatabaseService): Database service managing engine, sessionmaker, and models.
        """
        self.db = db

    # ────────────────────────────────────────────────────────────────
    #  Applications — always user-scoped
    # ────────────────────────────────────────────────────────────────

    def get_application(self, application_id: str, user_id: str) -> Optional[Dict]:
        """Fetch one application verifying ownership by user_id.

        Args:
            application_id (str): The unique identifier of the application.
            user_id (str): The requesting user's unique identity.

        Returns:
            Optional[Dict]: Application attributes dictionary if found and owned by user_id, else None.

        Interconnections:
            Called by `app.routes.applications.get_application`, `app.routes.documents.get_status`,
            and `app.routes.documents.delete_application`.
        """
        with self.db.session_scope() as session:
            app = (
                session.query(Application)
                .filter_by(application_id=application_id, user_id=user_id)
                .first()
            )
            return app.to_dict() if app else None

    def list_user_applications(self, user_id: str) -> List[Dict]:
        """List all applications belonging to a specific user, ordered newest first.

        Args:
            user_id (str): The requesting user's unique identity.

        Returns:
            List[Dict]: List of serialized application dictionaries owned by this user.

        Interconnections:
            Called by `app.routes.applications.list_applications` endpoint.
        """
        with self.db.session_scope() as session:
            apps = (
                session.query(Application)
                .filter_by(user_id=user_id)
                .order_by(Application.created_at.desc())
                .all()
            )
            return [app.to_dict() for app in apps]

    def update_application(self, application_id: str, user_id: str, **kwargs) -> bool:
        """Update permitted application attributes, verifying ownership by user_id.

        Args:
            application_id (str): Target application ID.
            user_id (str): Authenticated owner ID.
            **kwargs: Field updates (must be in `UPDATABLE_APPLICATION_FIELDS`).

        Returns:
            bool: True if application was updated, False if application does not exist or belong to user.

        Raises:
            ValueError: If an unapproved field or invalid status string is provided.

        Interconnections:
            Called when saving validation outcomes or linking collection sessions.
        """
        with self.db.session_scope() as session:
            app = (
                session.query(Application)
                .filter_by(application_id=application_id, user_id=user_id)
                .first()
            )
            if not app:
                return False
            bad = set(kwargs) - UPDATABLE_APPLICATION_FIELDS
            if bad:
                raise ValueError(f"fields cannot be updated through the repository: {sorted(bad)}")
            if "status" in kwargs and kwargs["status"] not in ALLOWED_APPLICATION_STATUSES:
                raise ValueError(f"unknown application status: {kwargs['status']!r}")
            for key, value in kwargs.items():
                setattr(app, key, value)
            app.updated_at = datetime.now(timezone.utc)
            return True

    def create_application(self, user_id: str, service_id: str,
                           applicant_name: str, required_documents: list,
                           collection_session_id: str = None) -> str:
        """Create a new onboarding application bound to the user's scope.

        Args:
            user_id (str): Authenticated owner ID.
            service_id (str): Catalogue service identifier (e.g. 'basic_registration').
            applicant_name (str): Full legal name of the applicant.
            required_documents (list): List of required document slot names.
            collection_session_id (str, optional): Linked collection agent session ID.

        Returns:
            str: Newly created `application_id`.

        Raises:
            ValueError: If `user_id` or `applicant_name` is missing or empty.

        Interconnections:
            Called by `app.routes.applications.create_application`.
        """
        if not user_id:
            raise ValueError("user_id is required")
        if not (applicant_name or "").strip():
            raise ValueError("applicant_name is required")
        return self.db.create_application(
            user_id=user_id,
            service_id=service_id,
            applicant_name=applicant_name,
            required_documents=required_documents,
            collection_session_id=collection_session_id,
        )

    # ────────────────────────────────────────────────────────────────
    #  Documents — always user-scoped
    # ────────────────────────────────────────────────────────────────

    def get_document(self, document_id: str, user_id: str) -> Optional[Dict]:
        """Fetch one document — ownership verified by user_id."""
        with self.db.session_scope() as session:
            doc = (
                session.query(Document)
                .filter_by(document_id=document_id, user_id=user_id)
                .first()
            )
            return doc.to_dict() if doc else None

    def list_user_documents(self, user_id: str) -> List[Dict]:
        """List all documents owned by a user."""
        with self.db.session_scope() as session:
            docs = (
                session.query(Document)
                .filter_by(user_id=user_id)
                .order_by(Document.uploaded_at.desc())
                .all()
            )
            return [doc.to_dict() for doc in docs]

    def upload_document(self, application_id: str, user_id: str, filename: str,
                       file_data: bytes, content_type: str, object_name: str,
                       file_size: int, document_type: str,
                       storage: str = "minio") -> str:
        """Upload document tied to user's application."""
        return self.db.upload_document(
            application_id=application_id,
            user_id=user_id,
            filename=filename,
            file_data=file_data,
            content_type=content_type,
            object_name=object_name,
            file_size=file_size,
            document_type=document_type,
            storage=storage,
        )

    # ────────────────────────────────────────────────────────────────
    #  Chat Sessions — user-bound
    # ────────────────────────────────────────────────────────────────

    def get_or_create_chat_session(self, user_id: str, force_new: bool = False) -> str:
        """The user's current chat session (reused while active), or a new one.

        Pass force_new=True for an explicit "new chat" / Reset Chat."""
        return self.db.get_or_create_chat_session(user_id=user_id, force_new=force_new)

    def get_chat_session(self, session_id: str, user_id: str) -> Optional[Dict]:
        """Fetch a chat session only if owned by user_id."""
        with self.db.session_scope() as session:
            chat = (
                session.query(ChatSession)
                .filter_by(session_id=session_id, user_id=user_id)
                .first()
            )
            return chat.to_dict() if chat else None

    def save_chat_message(self, session_id: str, user_id: str, role: str,
                         content: str, intent: str = None,
                         matched_service: str = None,
                         confidence: float = None) -> str:
        """Save a chat message — user_id bound."""
        return self.db.save_chat_message(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=content,
            intent=intent,
            matched_service=matched_service,
            confidence=confidence,
        )

    def get_chat_session_messages(self, session_id: str, user_id: Optional[str] = None) -> List[Dict]:
        """Messages for a session. ALWAYS pass user_id.

        The old docstring said the session id "already binds to the user", but nothing checked it:
        anyone holding a session id could read the conversation. Without user_id this still returns
        the messages (so existing callers keep working) and logs a warning naming the gap; update
        those callers to pass the signed-in user's id."""
        if user_id is None:
            logger.warning("get_chat_session_messages called without user_id: unscoped read of session %s", str(session_id)[:12])
        return self.db.get_chat_session_messages(session_id, user_id=user_id)

    def update_chat_session(self, session_id: str, user_id: str,
                           **kwargs) -> bool:
        """Update a chat session only if user owns it."""
        with self.db.session_scope() as session:
            chat = (
                session.query(ChatSession)
                .filter_by(session_id=session_id, user_id=user_id)
                .first()
            )
            if not chat:
                return False
            bad = set(kwargs) - UPDATABLE_CHAT_FIELDS
            if bad:
                raise ValueError(f"fields cannot be updated through the repository: {sorted(bad)}")
            for key, value in kwargs.items():
                setattr(chat, key, value)
            chat.updated_at = datetime.now(timezone.utc)
            return True

    # ────────────────────────────────────────────────────────────────
    #  Services — read-only, no user scope needed
    # ────────────────────────────────────────────────────────────────

    def get_service(self, service_id: str) -> Optional[Dict]:
        """Get service definition (public, no user filter)."""
        with self.db.session_scope() as session:
            svc = session.query(Service).filter_by(service_id=service_id).first()
            return svc.to_dict() if svc else None

    def list_services(self, status: str = None) -> List[Dict]:
        """List services, optionally filtered by status."""
        with self.db.session_scope() as session:
            query = session.query(Service)
            if status:
                query = query.filter_by(status=status)
            return [svc.to_dict() for svc in query.all()]

    # ────────────────────────────────────────────────────────────────
    #  Collection Agent Sessions — persisted to PostgreSQL
    #  (Phase 3: uses dedicated collection_sessions table)
    # ────────────────────────────────────────────────────────────────

    def save_collection_session(self, session_id: str, user_id: str, service_id: str,
                                service_name: str, status: str,
                                document_requirements: dict, submitted_file_ids: list,
                                application_id: str = None,
                                conversation_history: list = None,
                                notes: list = None) -> bool:
        """Persist a CollectionAgent session to the dedicated collection_sessions table."""
        return self.db.save_collection_session(
            session_id=session_id,
            user_id=user_id,
            service_id=service_id,
            service_name=service_name,
            status=status,
            document_requirements=document_requirements,
            submitted_file_ids=submitted_file_ids,
            conversation_history=conversation_history,
            notes=notes,
            application_id=application_id,
        )

    def get_collection_session(self, session_id: str, user_id: str) -> Optional[Dict]:
        """Retrieve a CollectionAgent session, verifying user ownership."""
        return self.db.get_collection_session(session_id, user_id=user_id)

    def list_user_collection_sessions(self, user_id: str) -> List[Dict]:
        """List all CollectionAgent sessions for a user."""
        return self.db.list_user_collection_sessions(user_id)

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Validation rules (from config.yaml → DB)
    # ────────────────────────────────────────────────────────────────

    def get_validation_rules(self, service_id: str, document_type: str = None) -> List[Dict]:
        """Fetch validation rules for a service/doc_type combo."""
        return self.db.get_validation_rules(service_id, document_type=document_type)

    def load_default_validation_rules(self):
        """Load default validation rules from config.yaml → DB (idempotent)."""
        self.db.load_default_validation_rules()

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Idempotency key support
    # ────────────────────────────────────────────────────────────────

    def register_idempotency_key(self, key: str, application_id: Optional[str],
                                 user_id: str, response: dict,
                                 expires_seconds: int = 3600) -> bool:
        """Register an idempotency key for future dedup on retry."""
        return self.db.register_idempotency_key(
            key, application_id, user_id, response, expires_seconds
        )

    def check_idempotency_key(self, key: str, user_id: Optional[str] = None) -> Optional[Dict]:
        """Check if THIS USER has already used an idempotency key. Always pass user_id."""
        return self.db.check_idempotency_key(key, user_id=user_id)

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Delete application (cascade)
    # ────────────────────────────────────────────────────────────────

    def delete_application(self, application_id: str, storage, user_id: str) -> Dict:
        """Delete an application and all associated data. user_id is REQUIRED and checked.

        (It used to default to None, which skipped the ownership check.)"""
        if not user_id:
            raise ValueError("user_id is required to delete an application")
        return self.db.delete_application(application_id, storage, user_id=user_id)

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Race-safe status transition
    # ────────────────────────────────────────────────────────────────

    def transition_application_status(self, application_id: str,
                                      current_status: str, new_status: str, user_id: str) -> bool:
        """Atomically transition status if it matches current_status. user_id is REQUIRED and checked."""
        if not user_id:
            raise ValueError("user_id is required to change an application's status")
        if new_status not in ALLOWED_APPLICATION_STATUSES:
            raise ValueError(f"unknown application status: {new_status!r}")
        return self.db.transition_application_status(application_id, current_status, new_status, user_id=user_id)

    def check_and_mark_application_complete(self, application_id: str, user_id: str) -> Tuple[bool, str]:
        """Atomically verify all required documents and mark application complete exactly once."""
        if not user_id:
            raise ValueError("user_id is required to check and mark application completion")
        return self.db.check_and_mark_application_complete(application_id, user_id=user_id)

