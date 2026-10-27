"""
Phase 3: Database persistence layer.

Replaces in-memory _application_store and _chat_sessions with a persistent
PostgreSQL (or SQLite fallback) database. Provides:

- Application lifecycle persistence (create, read, update, delete)
- User application history
- Chat session persistence
- Document metadata tracking (content_hash for dedup)
- Audit trail for all processing events
- Session isolation (user-scoped queries)
- Concurrency-safe transactions
"""

import os
import logging
import hashlib
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, String, Text, Integer, DateTime, Boolean, JSON,
    ForeignKey, Index, event, text, Float, func
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)
Base = declarative_base()


# ──────────────────────────────────────────────────────────────────────
#  Models
# ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    user_id = Column(String(36), primary_key=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, server_default=func.now())
    is_active = Column(Boolean, default=True)
    last_login = Column(DateTime, nullable=True)

    applications = relationship("Application", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user")

    def to_dict(self):
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "is_active": self.is_active,
            "last_login": self.last_login.isoformat() if self.last_login else None,
        }


class Application(Base):
    __tablename__ = "applications"

    application_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    service_id = Column(String(100), nullable=False, index=True)
    applicant_name = Column(String(255), nullable=False)
    required_documents = Column(JSON, nullable=True)
    status = Column(String(20), default="incomplete", index=True)  # incomplete, processing, complete, needs_review, rejected
    collection_session_id = Column(String(36), nullable=True)
    validation_result = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="applications")
    documents = relationship("Document", back_populates="application", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="application", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "application_id": self.application_id,
            "user_id": self.user_id,
            "service_id": self.service_id,
            "applicant_name": self.applicant_name,
            "required_documents": self.required_documents,
            "status": self.status,
            "collection_session_id": self.collection_session_id,
            "validation_result": self.validation_result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Document(Base):
    __tablename__ = "documents"

    document_id = Column(String(36), primary_key=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    object_name = Column(String(500), nullable=True)  # MinIO/S3 object key
    file_size = Column(Integer, nullable=False)
    content_hash = Column(String(64), unique=True, nullable=True)
    content_type = Column(String(100), nullable=False)
    document_type = Column(String(50), nullable=True, index=True)  # national_id, passport, etc.
    status = Column(String(20), default="uploaded")  # uploaded, processed, failed
    extracted_fields = Column(JSON, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    storage = Column(String(20), default="minio")  # minio, filesystem
    uploaded_at = Column(DateTime, server_default=func.now())
    processed_at = Column(DateTime, nullable=True)

    application = relationship("Application", back_populates="documents")
    user = relationship("User")

    def to_dict(self):
        return {
            "document_id": self.document_id,
            "application_id": self.application_id,
            "user_id": self.user_id,
            "filename": self.filename,
            "object_name": self.object_name,
            "file_size": self.file_size,
            "content_hash": self.content_hash,
            "content_type": self.content_type,
            "document_type": self.document_type,
            "status": self.status,
            "extracted_fields": self.extracted_fields,
            "extraction_confidence": self.extraction_confidence,
            "storage": self.storage,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None,
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
        }


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    step = Column(String(50), default="welcome")
    selected_service = Column(String(100), nullable=True)
    applicant_name = Column(String(255), nullable=True)
    application_id = Column(String(36), nullable=True, index=True)
    uploaded_documents = Column(JSON, nullable=True)
    required_documents = Column(JSON, nullable=True)
    collection_session_id = Column(String(36), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="chat_sessions")
    messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "step": self.step,
            "selected_service": self.selected_service,
            "applicant_name": self.applicant_name,
            "application_id": self.application_id,
            "uploaded_documents": self.uploaded_documents,
            "required_documents": self.required_documents,
            "collection_session_id": self.collection_session_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    message_id = Column(String(36), primary_key=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.session_id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    role = Column(String(20), nullable=False)  # user, assistant, system
    content = Column(Text, nullable=False)
    intent = Column(String(50), nullable=True)  # apply, faq, unknown
    matched_service = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    session = relationship("ChatSession", back_populates="messages")
    user = relationship("User")

    def to_dict(self):
        return {
            "message_id": self.message_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "matched_service": self.matched_service,
            "confidence": self.confidence,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=True, index=True)
    event_type = Column(String(50), nullable=False, index=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User")
    application = relationship("Application", back_populates="audit_logs")

    def to_dict(self):
        return {
            "log_id": self.log_id,
            "user_id": self.user_id,
            "application_id": self.application_id,
            "event_type": self.event_type,
            "details": self.details,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Service(Base):
    __tablename__ = "services"

    service_id = Column(String(100), primary_key=True)
    name = Column(String(255), unique=True, nullable=False, index=True)
    status = Column(String(20), default="available")  # available | coming_soon
    description = Column(Text, nullable=True)
    required_documents = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    def to_dict(self):
        return {
            "service_id": self.service_id,
            "name": self.name,
            "status": self.status,
            "description": self.description,
            "required_documents": self.required_documents,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class ServiceDocument(Base):
    __tablename__ = "service_documents"

    service_id = Column(String(100), ForeignKey("services.service_id"), primary_key=True)
    slot = Column(String(50), primary_key=True)
    accepted_types = Column(JSON, nullable=True)
    mandatory = Column(Boolean, default=True)

    service = relationship("Service")


class ServiceDefinition(Base):
    __tablename__ = "service_definitions"

    id = Column(String(36), primary_key=True)
    service_id = Column(String(100), ForeignKey("services.service_id"), nullable=False, index=True)
    source_file = Column(String(500), nullable=True)
    chunks = Column(JSON, nullable=True)  # text chunks for RAG
    embeddings = Column(JSON, nullable=True)  # pgvector embeddings
    created_at = Column(DateTime, server_default=func.now())

    service = relationship("Service")


class ExtractedField(Base):
    __tablename__ = "extracted_fields"

    id = Column(String(36), primary_key=True)
    document_id = Column(String(36), ForeignKey("documents.document_id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    value_encrypted = Column(Text, nullable=False)
    confidence = Column(Float, nullable=True)
    source_rung = Column(String(20), nullable=True)  # extraction ladder rung
    checksum_ok = Column(Boolean, nullable=True)

    document = relationship("Document")


class ReviewItem(Base):
    __tablename__ = "review_items"

    id = Column(String(36), primary_key=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    reason = Column(Text, nullable=False)
    evidence = Column(Text, nullable=True)
    state = Column(String(20), default="pending")  # pending | approved | rejected

    application = relationship("Application")


class TraceEvent(Base):
    __tablename__ = "trace_events"

    id = Column(String(36), primary_key=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=False, index=True)
    stage = Column(String(50), nullable=False)  # routing, faq, upload, extraction, validation
    inputs = Column(JSON, nullable=True)
    scores = Column(JSON, nullable=True)
    rule = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    application = relationship("Application")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(String(36), primary_key=True)
    test_case_id = Column(String(100), nullable=False, index=True)
    service_id = Column(String(100), nullable=True)
    status = Column(String(20), default="running")  # running | passed | failed
    routing_accuracy = Column(Float, nullable=True)
    extraction_accuracy = Column(Float, nullable=True)
    latency_ms = Column(Float, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id = Column(String(36), primary_key=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=False, index=True)
    event_type = Column(String(50), nullable=False)  # started, completed, etc.
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    application = relationship("Application")


# ── Phase 3: Collection sessions, validation rules, idempotency ──────

class CollectionSession(Base):
    """DB-backed collection agent session state — replaces in-memory dict."""
    __tablename__ = "collection_sessions"

    session_id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=True, index=True)
    service_id = Column(String(100), nullable=False)
    service_name = Column(String(255), nullable=True)
    status = Column(String(20), default="collecting")  # collecting | incomplete | complete | interrupted | exception
    document_requirements = Column(JSON, nullable=True)  # {doc_type: {mandatory, submitted, extraction_ok, …}}
    submitted_file_ids = Column(JSON, nullable=True)     # list of file_ids
    conversation_history = Column(JSON, nullable=True)   # chat turns array
    notes = Column(JSON, nullable=True)                  # free-form notes
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User")

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "application_id": self.application_id,
            "service_id": self.service_id,
            "service_name": self.service_name,
            "status": self.status,
            "document_requirements": self.document_requirements,
            "submitted_file_ids": self.submitted_file_ids,
            "conversation_history": self.conversation_history,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ValidationRule(Base):
    """Per-document-type validation rules stored in DB (loaded from config.yaml)."""
    __tablename__ = "validation_rules"

    id = Column(String(36), primary_key=True)
    service_id = Column(String(100), nullable=False, index=True)
    document_type = Column(String(50), nullable=False)
    mandatory_fields = Column(JSON, nullable=True)  # list of field names
    optional_fields = Column(JSON, nullable=True)
    field_rules = Column(JSON, nullable=True)  # {field_name: {regex, min_length, …}}
    extraction_threshold = Column(Float, nullable=True, default=0.5)
    human_review_threshold = Column(Float, nullable=True, default=0.7)
    reject_threshold = Column(Integer, nullable=True, default=3)
    source = Column(String(500), nullable=True)  # config.yaml path or "inline"
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (Index("ix_validation_rules_service_doc", "service_id", "document_type"),)

    def to_dict(self):
        return {
            "id": self.id,
            "service_id": self.service_id,
            "document_type": self.document_type,
            "mandatory_fields": self.mandatory_fields,
            "optional_fields": self.optional_fields,
            "field_rules": self.field_rules,
            "extraction_threshold": self.extraction_threshold,
            "human_review_threshold": self.human_review_threshold,
            "reject_threshold": self.reject_threshold,
            "source": self.source,
        }


class IdempotencyKey(Base):
    """Stores idempotency keys to prevent duplicate uploads on retry."""
    __tablename__ = "idempotency_keys"

    idempotency_key = Column(String(64), primary_key=True)
    application_id = Column(String(36), ForeignKey("applications.application_id"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.user_id"), nullable=True, index=True)
    response_json = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True, default=200)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


# ──────────────────────────────────────────────────────────────────────
#  Engine & Session management
# ──────────────────────────────────────────────────────────────────────

class DatabaseService:
    """Database persistence service for Phase 3."""

    def __init__(self, config: dict):
        self.config = config
        self.engine = None
        self.SessionLocal = None
        self._connected = False

    def connect(self):
        """Initialize database connection."""
        db_config = self.config.get("database", {})
        host = db_config.get("host", "127.0.0.1")
        port = db_config.get("port", 5432)
        name = db_config.get("name", "doc_intake")
        user = db_config.get("user", "intake")
        password = db_config.get("password", "intake_secret_2026")
        pool_size = db_config.get("pool_size", 10)
        max_overflow = db_config.get("max_overflow", 20)

        # PostgreSQL is the database of record. SQLite is used ONLY when explicitly allowed
        # (database.allow_sqlite_fallback: true), because a silent fallback sends every write to a
        # local file while everything else believes it is talking to PostgreSQL.
        pg_url = f"postgresql://{user}:{password}@{host}:{port}/{name}"
        allow_fallback = bool(db_config.get("allow_sqlite_fallback", False))
        sqlite_path = db_config.get("sqlite_path") or os.path.join(os.path.dirname(__file__), '..', 'data', 'app.db')
        sqlite_url = f"sqlite:///{sqlite_path}"

        try:
            self.engine = create_engine(pg_url, pool_pre_ping=True, echo=False)
            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            self._connected = True
            logger.info(f"Connected to PostgreSQL at {host}:{port}/{name}")
        except Exception as e:
            if not allow_fallback:
                self.engine = None
                self._connected = False
                raise RuntimeError(
                    f"PostgreSQL connection failed at {host}:{port}/{name} ({type(e).__name__}). "
                    "Not falling back to SQLite. For local development only, set "
                    "database.allow_sqlite_fallback: true in config.yaml."
                ) from e
            logger.warning(f"PostgreSQL connection failed ({type(e).__name__}). Falling back to SQLite (allowed by config).")
            self.engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})
            self._connected = True
            logger.info("Connected to SQLite database")

        # Enable WAL mode for SQLite (better concurrency)
        if "sqlite" in str(self.engine.url):
            @event.listens_for(self.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        # The old code ran DROP SCHEMA public CASCADE here on EVERY start, which deleted all users,
        # applications and documents each time the server restarted. It now runs only when you
        # explicitly ask for it, once, to clear legacy tables from init_db.sql:
        #     database:
        #       reset_schema_on_start: true     # then set it back to false
        if db_config.get("reset_schema_on_start", False) and "postgresql" in str(self.engine.url):
            logger.warning("database.reset_schema_on_start is true: DROPPING ALL TABLES AND DATA in schema public")
            try:
                with self.engine.connect() as conn:
                    conn.execute(text("DROP SCHEMA public CASCADE"))
                    conn.execute(text("CREATE SCHEMA public"))
                    conn.commit()
                logger.warning("Schema reset complete. Set database.reset_schema_on_start back to false.")
            except Exception as e:
                logger.error(f"Schema reset failed: {type(e).__name__}: {e}")

        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)

        logger.info("Database tables created/verified")

    def get_session(self) -> Session:
        """Get a new database session."""
        if not self._connected:
            raise RuntimeError("Database not connected")
        return self.SessionLocal()

    @contextmanager
    def session_scope(self):
        """Provide a transactional scope around a series of operations."""
        session = self.get_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    # ────────────────────────────────────────────────────────────────
    #  Content hashing for duplicate detection
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def compute_content_hash(file_data: bytes) -> str:
        """Compute SHA-256 hash of file content for duplicate detection."""
        return hashlib.sha256(file_data).hexdigest()

    @staticmethod
    def scoped_hash(user_id: Optional[str], raw_hash: str) -> str:
        """Compute a user-scoped content hash so two users can upload identical files.
        
        If user_id is provided, returns sha256(f"{user_id}:{raw_hash}").
        Otherwise returns the raw hash.
        """
        if not user_id:
            return raw_hash
        return hashlib.sha256(f"{user_id}:{raw_hash}".encode("utf-8")).hexdigest()

    @staticmethod
    def is_duplicate(session: Session, content_hash: str, user_id: Optional[str] = None) -> Optional[str]:
        """Check if a document with this hash already exists.

        Returns:
            document_id if duplicate found, None otherwise
        """
        q = session.query(Document).filter_by(content_hash=content_hash)
        if user_id:
            q = q.filter_by(user_id=user_id)
        doc = q.first()
        return doc.document_id if doc else None

    # ────────────────────────────────────────────────────────────────
    #  Application CRUD
    # ────────────────────────────────────────────────────────────────

    def create_application(self, user_id: str, service_id: str, applicant_name: str,
                          required_documents: list, collection_session_id: str = None) -> str:
        """Create a new application and persist it."""
        with self.session_scope() as session:
            app_id = f"app_{session.query(text('upper(hex(randomblob(4)))')).scalar()}" if "sqlite" in str(self.engine.url) else f"app_{os.urandom(4).hex()}"
            app = Application(
                application_id=app_id,
                user_id=user_id,
                service_id=service_id,
                applicant_name=applicant_name.strip(),
                required_documents=required_documents,
                collection_session_id=collection_session_id,
                status="incomplete",
            )
            session.add(app)
            session.flush()  # Get app_id

            # Audit trail
            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=user_id,
                application_id=app_id,
                event_type="application_created",
                details={"service_id": service_id, "applicant_name": applicant_name.strip()},
            )
            session.add(audit)
            return app_id

    def get_application(self, application_id: str) -> Optional[Dict]:
        """Get application details by ID."""
        with self.session_scope() as session:
            app = session.query(Application).filter_by(application_id=application_id).first()
            if not app:
                return None
            return app.to_dict()

    def update_application(self, application_id: str, **kwargs) -> bool:
        """Update application fields."""
        with self.session_scope() as session:
            app = session.query(Application).filter_by(application_id=application_id).first()
            if not app:
                return False
            for key, value in kwargs.items():
                if hasattr(app, key):
                    setattr(app, key, value)
            app.updated_at = datetime.now(timezone.utc)
            return True

    def get_user_applications(self, user_id: str) -> List[Dict]:
        """Get all applications for a user (with isolation)."""
        with self.session_scope() as session:
            apps = session.query(Application).filter_by(user_id=user_id).order_by(Application.created_at.desc()).all()
            return [app.to_dict() for app in apps]

    # ────────────────────────────────────────────────────────────────
    #  Document CRUD
    # ────────────────────────────────────────────────────────────────

    def upload_document(self, application_id: str, user_id: str, filename: str,
                       file_data: bytes, content_type: str, object_name: str,
                       file_size: int, document_type: str, storage: str) -> str:
        """Upload a document with duplicate detection and atomic tracking."""
        content_hash = self.compute_content_hash(file_data)

        with self.session_scope() as session:
            # Check for duplicates
            existing_id = self.is_duplicate(session, content_hash)
            if existing_id:
                logger.info(f"Duplicate document detected (hash={content_hash[:16]}...). Returning existing document ID: {existing_id}")
                return existing_id  # Return existing, don't create duplicate

            doc_id = f"doc_{os.urandom(4).hex()}"
            doc = Document(
                document_id=doc_id,
                application_id=application_id,
                user_id=user_id,
                filename=filename,
                object_name=object_name,
                file_size=file_size,
                content_hash=content_hash,
                content_type=content_type,
                document_type=document_type,
                status="uploaded",
                storage=storage,
            )
            session.add(doc)
            session.flush()

            # Audit trail
            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=user_id,
                application_id=application_id,
                event_type="document_uploaded",
                details={"document_id": doc_id, "filename": filename, "content_hash": content_hash[:16], "is_duplicate": False},
            )
            session.add(audit)
            return doc_id

    def update_document_processing(self, document_id: str, extracted_fields: dict,
                                  extraction_confidence: float) -> bool:
        """Update document with extraction results."""
        with self.session_scope() as session:
            doc = session.query(Document).filter_by(document_id=document_id).first()
            if not doc:
                return False
            doc.status = "processed"
            doc.extracted_fields = extracted_fields
            doc.extraction_confidence = extraction_confidence
            doc.processed_at = datetime.now(timezone.utc)

            # Audit trail
            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=doc.user_id,
                application_id=doc.application_id,
                event_type="extraction_completed",
                details={"document_id": document_id, "confidence": extraction_confidence},
            )
            session.add(audit)
            return True

    def get_user_documents(self, user_id: str) -> List[Dict]:
        """Get all documents for a user (with isolation)."""
        with self.session_scope() as session:
            docs = session.query(Document).filter_by(user_id=user_id).order_by(Document.uploaded_at.desc()).all()
            return [doc.to_dict() for doc in docs]

    # ────────────────────────────────────────────────────────────────
    #  Chat session CRUD
    # ────────────────────────────────────────────────────────────────

    def get_or_create_chat_session(self, user_id: str = None, force_new: bool = False) -> str:
        """Get or create a chat session. If force_new=False and active session exists for user, reuse it."""
        with self.session_scope() as session:
            if user_id and not force_new:
                existing = session.query(ChatSession).filter_by(user_id=user_id).order_by(ChatSession.created_at.desc()).first()
                if existing:
                    return existing.session_id
            session_id = f"chat_{os.urandom(4).hex()}"
            chat = ChatSession(
                session_id=session_id,
                user_id=user_id,
            )
            session.add(chat)
            return session_id

    def save_chat_message(self, session_id: str, user_id: str, role: str,
                         content: str, intent: str = None, matched_service: str = None,
                         confidence: float = None) -> str:
        """Save a chat message to the session."""
        with self.session_scope() as session:
            msg_id = f"msg_{os.urandom(4).hex()}"
            msg = ChatMessage(
                message_id=msg_id,
                session_id=session_id,
                user_id=user_id,
                role=role,
                content=content,
                intent=intent,
                matched_service=matched_service,
                confidence=confidence,
            )
            session.add(msg)
            session.flush()

            # Update session if user message
            if role == "user":
                chat = session.query(ChatSession).filter_by(session_id=session_id).first()
                if chat:
                    chat.updated_at = datetime.now(timezone.utc)

            # Audit trail
            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=user_id,
                event_type="chat_sent",
                details={"session_id": session_id, "role": role, "intent": intent},
            )
            session.add(audit)
            return msg_id

    def get_chat_session_messages(self, session_id: str) -> List[Dict]:
        """Get all messages for a chat session."""
        with self.session_scope() as session:
            msgs = session.query(ChatMessage).filter_by(session_id=session_id).order_by(ChatMessage.created_at).all()
            return [msg.to_dict() for msg in msgs]

    # ────────────────────────────────────────────────────────────────
    #  Audit trail
    # ────────────────────────────────────────────────────────────────

    def get_audit_trail(self, user_id: str = None, application_id: str = None,
                       event_type: str = None, limit: int = 100) -> List[Dict]:
        """Get audit trail with optional filters."""
        with self.session_scope() as session:
            query = session.query(AuditLog)
            if user_id:
                query = query.filter_by(user_id=user_id)
            if application_id:
                query = query.filter_by(application_id=application_id)
            if event_type:
                query = query.filter_by(event_type=event_type)
            query = query.order_by(AuditLog.created_at.desc()).limit(limit)
            logs = query.all()
            return [log.to_dict() for log in logs]

    def log_event(self, event_type: str, user_id: str = None, application_id: str = None,
                  details: Dict = None, stage: str = None) -> str:
        """Log an audit trail event."""
        log_id = f"audit_{os.urandom(4).hex()}"
        with self.session_scope() as session:
            audit = AuditLog(
                log_id=log_id,
                user_id=user_id,
                application_id=application_id,
                event_type=event_type,
                details=details or {},
            )
            session.add(audit)
            return log_id

    # ────────────────────────────────────────────────────────────────
    #  Health check
    # ────────────────────────────────────────────────────────────────

    def log_trace_event(self, application_id: str, stage: str, inputs: Dict,
                        scores: Dict, rule: str, confidence: float) -> str:
        """Log a trace event for deterministic routing & other stages."""
        import uuid
        event_id = str(uuid.uuid4())
        with self.session_scope() as session:
            trace = TraceEvent(
                id=event_id,
                application_id=application_id,
                stage=stage,
                inputs=inputs,
                scores=scores,
                rule=rule,
                confidence=confidence,
            )
            session.add(trace)
            return event_id

    def get_trace_events(self, application_id: str, stage: str = None, limit: int = 100) -> List[Dict]:
        """Retrieve trace events, optionally filtered by stage."""
        with self.session_scope() as session:
            query = session.query(TraceEvent).filter_by(application_id=application_id)
            if stage:
                query = query.filter_by(stage=stage)
            query = query.order_by(TraceEvent.created_at.desc()).limit(limit)
            events = query.all()
            return [
                {
                    "id": e.id,
                    "stage": e.stage,
                    "inputs": e.inputs,
                    "scores": e.scores,
                    "rule": e.rule,
                    "confidence": e.confidence,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ]

    def check_connection(self) -> str:
        """Check if database connection is healthy."""
        if not self._connected:
            return "unavailable (not connected)"
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return "healthy"
        except Exception as e:
            return f"error: {str(e)[:100]}"

    @staticmethod
    def compute_content_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hash of file content for deduplication."""
        return hashlib.sha256(file_bytes).hexdigest()

    def check_duplicate_upload(self, application_id: str, document_slot: str, content_hash: str) -> Optional[dict]:
        """Check if this exact document has already been uploaded.
        
        Returns None if no duplicate, or dict with existing doc info if duplicate.
        Uses the unique (application_id, document_slot, content_hash) constraint.
        """
        with self.session_scope() as session:
            row = (
                session.query(Document)
                .filter_by(
                    application_id=application_id,
                    document_type=document_slot,
                    content_hash=content_hash
                )
                .first()
            )
            if row:
                return {
                    "document_id": row.document_id,
                    "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
                    "filename": row.filename,
                    "file_size": row.file_size,
                }
            return None

    def get_service_for_slot(self, application_id: str, document_slot: str) -> Optional[str]:
        """Get the assigned service for a given document slot in an application."""
        with self.session_scope() as session:
            row = (
                session.query(Document)
                .filter_by(
                    application_id=application_id,
                    document_type=document_slot
                )
                .first()
            )
            return row.document_type if row else None

    def log_collection_event(self, application_id: str, event_type: str,
                            document_slot: str = None, session_id: str = None,
                            details: dict = None) -> str:
        """Log a collection agent event (scan detected, human_review, etc.)."""
        import uuid
        event_id = str(uuid.uuid4())
        with self.session_scope() as session:
            app_event = ApplicationEvent(
                id=event_id,
                application_id=application_id,
                event_type=f"collection.{event_type}",
                details=details or {},
                created_at=datetime.now(timezone.utc),
            )
            session.add(app_event)
            return event_id

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Collection session persistence (DB-backed agent)
    # ────────────────────────────────────────────────────────────────

    def save_collection_session(self, session_id: str, user_id: str, service_id: str,
                               service_name: str, status: str,
                               document_requirements: dict, submitted_file_ids: list,
                               conversation_history: list = None, notes: list = None,
                               application_id: str = None) -> bool:
        """Persist or update a CollectionAgent session in DB."""
        from datetime import datetime, timezone
        with self.session_scope() as session:
            coll = (
                session.query(CollectionSession)
                .filter_by(session_id=session_id)
                .first()
            )
            if not coll:
                coll = CollectionSession(
                    session_id=session_id,
                    user_id=user_id,
                    application_id=application_id,
                    service_id=service_id,
                    service_name=service_name,
                    status=status,
                    document_requirements=document_requirements,
                    submitted_file_ids=submitted_file_ids,
                    conversation_history=conversation_history or [],
                    notes=notes or [],
                )
                session.add(coll)
            else:
                coll.user_id = user_id
                coll.application_id = application_id
                coll.service_id = service_id
                coll.service_name = service_name
                coll.status = status
                coll.document_requirements = document_requirements
                coll.submitted_file_ids = submitted_file_ids
                if conversation_history is not None:
                    coll.conversation_history = conversation_history
                if notes is not None:
                    coll.notes = notes
                coll.updated_at = datetime.now(timezone.utc)
            return True

    def get_collection_session(self, session_id: str, user_id: str = None) -> Optional[Dict]:
        """Retrieve a CollectionAgent session, optionally verifying user ownership."""
        with self.session_scope() as session:
            q = session.query(CollectionSession).filter_by(session_id=session_id)
            if user_id:
                q = q.filter_by(user_id=user_id)
            coll = q.first()
            if not coll:
                return None
            return coll.to_dict()

    def list_user_collection_sessions(self, user_id: str) -> List[Dict]:
        """List all collection sessions for a user."""
        with self.session_scope() as session:
            rows = (
                session.query(CollectionSession)
                .filter_by(user_id=user_id)
                .order_by(CollectionSession.updated_at.desc())
                .all()
            )
            return [r.to_dict() for r in rows]

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Validation rule registry (from config.yaml)
    # ────────────────────────────────────────────────────────────────

    def get_validation_rules(self, service_id: str, document_type: str = None) -> List[Dict]:
        """Fetch validation rules for a service/doc_type combo."""
        with self.session_scope() as session:
            q = session.query(ValidationRule).filter_by(service_id=service_id)
            if document_type:
                q = q.filter_by(document_type=document_type)
            return [r.to_dict() for r in q.all()]

    def load_default_validation_rules(self):
        """Load default validation rules from config.yaml → DB (idempotent)."""
        from datetime import datetime, timezone
        import uuid
        rules = self._build_default_rules()
        if not rules:
            return
        with self.session_scope() as session:
            for rule_data in rules:
                existing = (
                    session.query(ValidationRule)
                    .filter_by(service_id=rule_data["service_id"],
                               document_type=rule_data["document_type"])
                    .first()
                )
                if not existing:
                    rid = str(uuid.uuid4())
                    entry = ValidationRule(id=rid, **{k: v for k, v in rule_data.items() if k != "id"})
                    session.add(entry)

    def _build_default_rules(self) -> List[Dict]:
        """Build default validation rules from config.yaml or hardcoded defaults."""
        try:
            config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                import yaml
                config = yaml.safe_load(f) or {}
        except Exception:
            config = {}

        rules = []
        # Read per-document-type config
        doc_config = config.get("validation_rules", {})
        if not doc_config:
            # Hardcoded defaults if config.yaml has no validation_rules key
            doc_config = {
                "national_id": {
                    "mandatory_fields": ["name", "national_id_number", "date_of_birth",
                                         "gender", "expiry_date"],
                    "optional_fields": ["address", "issuing_country"],
                    "extraction_threshold": 0.5,
                    "human_review_threshold": 0.7,
                    "reject_threshold": 3,
                },
                "passport": {
                    "mandatory_fields": ["name", "passport_number", "date_of_birth",
                                         "nationality", "expiry_date", "issue_date"],
                    "optional_fields": ["place_of_birth", "place_of_issue"],
                    "extraction_threshold": 0.5,
                    "human_review_threshold": 0.7,
                    "reject_threshold": 3,
                },
                "driving_license": {
                    "mandatory_fields": ["name", "license_number", "date_of_birth",
                                         "expiry_date", "license_class"],
                    "optional_fields": ["address", "restrictions"],
                    "extraction_threshold": 0.5,
                    "human_review_threshold": 0.7,
                    "reject_threshold": 3,
                },
            }

        for doc_type, fields in doc_config.items():
            rules.append({
                "service_id": "all",  # applies to all services unless overridden
                "document_type": doc_type,
                "mandatory_fields": fields.get("mandatory_fields", []),
                "optional_fields": fields.get("optional_fields", []),
                "field_rules": fields.get("field_rules", {}),
                "extraction_threshold": fields.get("extraction_threshold", 0.5),
                "human_review_threshold": fields.get("human_review_threshold", 0.7),
                "reject_threshold": fields.get("reject_threshold", 3),
                "source": "config.yaml",
            })
        return rules

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Idempotency key support
    # ────────────────────────────────────────────────────────────────

    def register_idempotency_key(self, key: str, application_id: str,
                                 user_id: str, response: dict,
                                 expires_seconds: int = 3600) -> bool:
        """Register an idempotency key for future dedup on retry."""
        from datetime import datetime, timezone, timedelta
        with self.session_scope() as session:
            entry = IdempotencyKey(
                idempotency_key=key,
                application_id=application_id,
                user_id=user_id,
                response_json=response,
                response_status=200,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
            )
            session.add(entry)
            return True

    def check_idempotency_key(self, key: str, user_id: Optional[str] = None) -> Optional[Dict]:
        """Check if an idempotency key has already been used.
        
        Returns the stored response if found and not expired, else None.
        """
        with self.session_scope() as session:
            q = session.query(IdempotencyKey).filter_by(idempotency_key=key)
            if user_id:
                q = q.filter_by(user_id=user_id)
            entry = q.first()
            if not entry:
                return None
            if entry.expires_at:
                exp = entry.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                if exp < datetime.now(timezone.utc):
                    return {"expired": True}
            return entry.response_json

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Delete application (cascade delete all related data)
    # ────────────────────────────────────────────────────────────────

    def delete_application(self, application_id: str, storage, user_id: str = None) -> Dict:
        """Delete an application and all associated data atomically.
        
        Removes:
        - All documents (rows in documents table + MinIO objects)
        - All extracted fields
        - All review items
        - All trace events
        - All application events
        - All audit logs
        - The application row itself
        
        Args:
            application_id: The application to delete
            storage: StorageService instance for MinIO cleanup
            user_id: Optional user ownership check
            
        Returns:
            Dict with counts of deleted items and any errors
        """
        from datetime import datetime, timezone
        result = {
            "deleted": False,
            "application_id": application_id,
            "deleted_documents": 0,
            "deleted_minio_objects": 0,
            "deleted_extracted_fields": 0,
            "deleted_review_items": 0,
            "deleted_trace_events": 0,
            "deleted_application_events": 0,
            "deleted_audit_logs": 0,
            "deleted_idempotency_keys": 0,
            "errors": [],
        }

        try:
            with self.session_scope() as session:
                # 0. Check application existence and ownership
                app_q = session.query(Application).filter_by(application_id=application_id)
                if user_id:
                    app_q = app_q.filter_by(user_id=user_id)
                app = app_q.first()
                if not app:
                    result["errors"].append("Application not found or unauthorized")
                    return result

                # 1. Get all documents for this application
                docs = session.query(Document).filter_by(application_id=application_id).all()
                result["deleted_documents"] = len(docs)

                # 2. Collect MinIO object names for deletion
                minio_objects = []
                for doc in docs:
                    if doc.object_name:
                        minio_objects.append(doc.object_name)

                # 3. Delete MinIO objects
                if storage and minio_objects:
                    for obj_name in minio_objects:
                        try:
                            storage.delete_file(obj_name)
                            result["deleted_minio_objects"] += 1
                        except Exception as e:
                            result["errors"].append(f"MinIO delete {obj_name}: {str(e)}")

                # 4. Delete extracted fields
                ext_ids = [
                    ef.id for ef in session.query(ExtractedField)
                    .join(Document).filter(Document.application_id == application_id).all()
                ]
                result["deleted_extracted_fields"] = len(ext_ids)
                if ext_ids:
                    session.query(ExtractedField).filter(ExtractedField.id.in_(ext_ids)).delete(synchronize_session=False)

                # 5. Delete review items
                ri_ids = [
                    ri.id for ri in session.query(ReviewItem)
                    .filter_by(application_id=application_id).all()
                ]
                result["deleted_review_items"] = len(ri_ids)

                # 6. Delete trace events
                te_ids = [
                    te.id for te in session.query(TraceEvent)
                    .filter_by(application_id=application_id).all()
                ]
                result["deleted_trace_events"] = len(te_ids)

                # 7. Delete application events
                ae_ids = [
                    ae.id for ae in session.query(ApplicationEvent)
                    .filter_by(application_id=application_id).all()
                ]
                result["deleted_application_events"] = len(ae_ids)

                # 8. Delete audit logs
                al_ids = [
                    al.log_id for al in session.query(AuditLog)
                    .filter_by(application_id=application_id).all()
                ]
                result["deleted_audit_logs"] = len(al_ids)

                # 9. Delete idempotency keys
                ik_count = session.query(IdempotencyKey).filter_by(application_id=application_id).delete(synchronize_session="fetch")
                result["deleted_idempotency_keys"] = ik_count

                # 10. Clear ChatSession application_id references
                session.query(ChatSession).filter_by(application_id=application_id).update({"application_id": None}, synchronize_session="fetch")

                # 11. Delete documents
                session.query(Document).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 12. Delete review items
                session.query(ReviewItem).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 13. Delete trace events
                session.query(TraceEvent).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 14. Delete application events
                session.query(ApplicationEvent).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 15. Delete audit logs
                session.query(AuditLog).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 16. Delete collection sessions linked to this application
                session.query(CollectionSession).filter_by(application_id=application_id).delete(synchronize_session="fetch")

                # 17. Delete the application itself
                session.delete(app)

        except Exception as e:
            result["errors"].append(f"Database error: {str(e)}")

        result["deleted"] = len(result["errors"]) == 0
        return result

    # ────────────────────────────────────────────────────────────────
    #  Phase 3: Race-safe status transition (SELECT FOR UPDATE + compare-and-set)
    # ────────────────────────────────────────────────────────────────

    def transition_application_status(self, application_id: str,
                                      current_status: str, new_status: str, user_id: str = None) -> bool:
        """Atomically transition application status if it matches current_status.
        
        Uses SELECT FOR UPDATE + compare-and-set to prevent race conditions
        when multiple threads/processes try to update status simultaneously.
        
        Returns True if transition succeeded, False if status didn't match.
        """
        with self.session_scope() as session:
            # Lock the row (FOR UPDATE in PG; no-op in SQLite but still serializes)
            q = session.query(Application).filter_by(application_id=application_id)
            if user_id:
                q = q.filter_by(user_id=user_id)
            app = q.with_for_update().first()
            if not app:
                return False
            if app.status != current_status:
                return False  # Someone else changed it
            app.status = new_status
            app.updated_at = datetime.now(timezone.utc)
            return True

    def check_and_mark_application_complete(self, application_id: str, user_id: str = None) -> Tuple[bool, str]:
        """Atomically check if all required documents are present and mark complete ONCE.

        Uses SELECT FOR UPDATE on the application row to prevent race conditions when two
        documents arrive nearly at the same time:
        - Locks the application row.
        - Retrieves required document slots (e.g. ['national_id', 'passport']).
        - Counts distinct valid document types attached to this application.
        - If distinct document types count >= required document types count and all required types are met:
          - If app.status == 'complete':
            returns (False, 'already_complete') -> Does NOT mark complete twice!
          - If app.status != 'complete':
            app.status = 'complete'
            app.updated_at = datetime.now(timezone.utc)
            # Log single audit event
            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=app.user_id,
                application_id=application_id,
                event_type="application_completed",
                details={
                    "application_id": application_id,
                    "service_id": app.service_id,
                    "status": "complete"
                },
            )
            session.add(audit)
            return (True, "marked_complete")
        - If document count is incomplete (e.g. 1 out of 2):
          return (False, f"incomplete: missing {missing}")
        """
        with self.session_scope() as session:
            q = session.query(Application).filter_by(application_id=application_id)
            if user_id:
                q = q.filter_by(user_id=user_id)
            app = q.with_for_update().first()
            if not app:
                return False, "application_not_found"

            required_docs = app.required_documents or []
            if not required_docs:
                fallback_map = {
                    "basic_registration": ["national_id"],
                    "premium_crossborder": ["national_id", "passport"],
                    "mobility_rental": ["driving_license"],
                }
                required_docs = fallback_map.get(app.service_id, ["national_id"])

            docs = session.query(Document).filter_by(application_id=application_id).all()
            submitted_types = {d.document_type for d in docs if d.status in ("uploaded", "processed") and d.document_type}

            missing = [rd for rd in required_docs if rd not in submitted_types]

            # Count check: wrong number of documents must NOT be marked complete
            if missing or len(submitted_types) < len(required_docs):
                return False, f"incomplete: missing {missing}"

            if app.status == "complete":
                return False, "already_complete"

            app.status = "complete"
            app.updated_at = datetime.now(timezone.utc)

            audit = AuditLog(
                log_id=f"audit_{os.urandom(4).hex()}",
                user_id=app.user_id,
                application_id=application_id,
                event_type="application_completed",
                details={
                    "application_id": application_id,
                    "service_id": app.service_id,
                    "status": "complete",
                },
            )
            session.add(audit)
            return True, "marked_complete"

