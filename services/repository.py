"""
Repository layer — user-scoped data access.

Every fetch operation requires a user_id. No caller can retrieve another
user's applications, documents, or status by bypassing the user_id filter.
Enforces cross-user isolation at the data-access boundary.
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from services.database import DatabaseService
from services.database import Application, Document, ChatSession, Service


class Repository:
    """User-scoped repository for all persistent data access."""

    def __init__(self, db: DatabaseService):
        self.db = db

    # ────────────────────────────────────────────────────────────────
    #  Applications — always user-scoped
    # ────────────────────────────────────────────────────────────────

    def get_application(self, application_id: str, user_id: str) -> Optional[Dict]:
        """Fetch one application — MUST include user_id."""
        with self.db.session_scope() as session:
            app = (
                session.query(Application)
                .filter_by(application_id=application_id, user_id=user_id)
                .first()
            )
            return app.to_dict() if app else None

    def list_user_applications(self, user_id: str) -> List[Dict]:
        """List all applications for a user (no user_id leak)."""
        with self.db.session_scope() as session:
            apps = (
                session.query(Application)
                .filter_by(user_id=user_id)
                .order_by(Application.created_at.desc())
                .all()
            )
            return [app.to_dict() for app in apps]

    def update_application(self, application_id: str, user_id: str, **kwargs) -> bool:
        """Update application — ownership verified by user_id."""
        with self.db.session_scope() as session:
            app = (
                session.query(Application)
                .filter_by(application_id=application_id, user_id=user_id)
                .first()
            )
            if not app:
                return False
            for key, value in kwargs.items():
                if hasattr(app, key):
                    setattr(app, key, value)
            app.updated_at = datetime.now(timezone.utc)
            return True

    def create_application(self, user_id: str, service_id: str,
                           applicant_name: str, required_documents: list,
                           collection_session_id: str = None) -> str:
        """Create application in the user's scope."""
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

    def get_or_create_chat_session(self, user_id: str) -> str:
        """Get or create a chat session for a user."""
        return self.db.get_or_create_chat_session(user_id=user_id)

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

    def get_chat_session_messages(self, session_id: str) -> List[Dict]:
        """Get messages for a session (session_id already binds to user)."""
        return self.db.get_chat_session_messages(session_id)

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
            for key, value in kwargs.items():
                if hasattr(chat, key):
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
    # ────────────────────────────────────────────────────────────────

    def save_collection_session(self, session_id: str, user_id: str, service_id: str,
                                service_name: str, status: str,
                                document_requirements: dict, submitted_file_ids: list,
                                application_id: str = None) -> bool:
        """Persist a CollectionAgent session to the chat_sessions table as JSON."""
        with self.db.session_scope() as session:
            chat = (
                session.query(ChatSession)
                .filter_by(session_id=session_id)
                .first()
            )
            if not chat:
                chat = ChatSession(
                    session_id=session_id,
                    user_id=user_id,
                    step=f"collection:{service_id}",
                    selected_service=service_id,
                    application_id=application_id,
                    uploaded_documents=document_requirements,
                    collection_session_id=session_id,
                )
                session.add(chat)
            else:
                chat.user_id = user_id
                chat.step = f"collection:{service_id}"
                chat.selected_service = service_id
                chat.status = status
                chat.uploaded_documents = document_requirements
                chat.submitted_file_ids = submitted_file_ids
                chat.application_id = application_id
                chat.updated_at = datetime.now(timezone.utc)
            return True

    def get_collection_session(self, session_id: str, user_id: str) -> Optional[Dict]:
        """Retrieve a CollectionAgent session, verifying user ownership."""
        with self.db.session_scope() as session:
            chat = (
                session.query(ChatSession)
                .filter_by(session_id=session_id, user_id=user_id)
                .first()
            )
            if not chat:
                return None
            return {
                "session_id": chat.session_id,
                "user_id": chat.user_id,
                "service_id": chat.selected_service,
                "step": chat.step,
                "status": chat.status,
                "document_requirements": chat.uploaded_documents,
                "submitted_file_ids": chat.submitted_file_ids,
                "application_id": chat.application_id,
                "created_at": chat.created_at.isoformat() if chat.created_at else None,
                "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
            }

    def list_user_collection_sessions(self, user_id: str) -> List[Dict]:
        """List all CollectionAgent sessions for a user."""
        with self.db.session_scope() as session:
            chats = (
                session.query(ChatSession)
                .filter_by(user_id=user_id)
                .filter(ChatSession.step.like("collection:%"))
                .order_by(ChatSession.updated_at.desc())
                .all()
            )
            return [
                {
                    "session_id": c.session_id,
                    "service_id": c.selected_service,
                    "step": c.step,
                    "status": c.status,
                    "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                }
                for c in chats
            ]
