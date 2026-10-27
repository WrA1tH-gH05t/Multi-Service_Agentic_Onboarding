from services.generation import GenerationService
"""Document routes: upload, list, delete, download, presigned-url, extract."""

import os
import uuid
import json
import logging
import io
from datetime import datetime, timedelta
from typing import Optional
from services.file_validation import validate_file_content
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse, Response, FileResponse

import hashlib

router = APIRouter()

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _require_user_id(state, token: Optional[str]):
    """Signed-in user's id, or HTTP 401."""
    auth = state.get("auth")
    user = None
    if token and auth:
        try:
            user = auth.validate_token(token)
        except Exception:
            user = None
    if not user:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return user.user_id


def _owned_document(state, document_id: str, user_id) -> dict:
    """The caller's own document row, or 404. Someone else's document gets the same 404."""
    repo = state.get("repository")
    if repo is None:
        raise HTTPException(status_code=503, detail="Document service is temporarily unavailable.")
    doc = repo.get_document(document_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc

# Shared in-memory stores (legacy compat)
_application_store: dict = {}
_chat_sessions: dict = {}
def _get_session_id(token: Optional[str] = None) -> str:
    if token:
        return f"session_{token[:16]}"
    return "session_anonymous"
def _get_session(session_id: str) -> dict:
    if session_id not in _chat_sessions:
        _chat_sessions[session_id] = {
            "step": "welcome",
            "selected_service": None,*
            "applicant_name": None,
            "application_id": None,
            "uploaded_documents": [],
            "required_documents": [],
        }
    return _chat_sessions[session_id]

def get_state():
    from app.main import app_state
    return app_state

# --- Document Upload (Vision-based extraction) ---
@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    application_id: Optional[str] = None,
    token: Optional[str] = Query(None, alias="token"),
    idempotency_key: Optional[str] = Query(None, alias="Idempotency-Key"),
):
    """Upload a document with AI-powered field extraction via Qwen2.5-VL 7B.
    Requires authentication.
    
    Phase 3: Duplicate detection (SHA-256), atomic uploads, DB persistence,
    cross-service contamination prevention, idempotency key support.
    """
    state = get_state()
    db = state.get("database")
    config = state.get("config", {})
    user_id = _require_user_id(state, token)      # uploads always belong to a signed-in user

    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")

    # Phase 3: Check idempotency key — if this key was already used, return cached result
    repo = state.get("repository")
    if idempotency_key and repo:
        cached = repo.check_idempotency_key(idempotency_key, user_id)
        if cached is not None:
            if isinstance(cached, dict) and cached.get("expired"):
                logger.warning(f"Idempotency key {idempotency_key} expired; allowing re-upload")
            else:
                logger.info(f"Idempotency key {idempotency_key[:16]}... matched — returning cached response")
                return JSONResponse(content=cached)

    # Read file content first (capped), then validate what it actually IS by content — not by
    # extension or client-supplied MIME type. A renamed EXE or a truncated PDF will be caught here.
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="That file is larger than 10 MB. Please send a smaller PDF.")

    is_valid, content_type, detected_fmt, err_msg = validate_file_content(
        content, allowed_types=["application/pdf"], max_pages=10
    )
    if not is_valid:
        raise HTTPException(
            status_code=400,
            detail=err_msg or "Only PDF files are accepted. Please upload a valid PDF."
        )

    # Phase 3: Check for duplicates using SHA-256 hash
    content_hash = ""
    raw_hash = hashlib.sha256(content).hexdigest()
    # documents.content_hash is unique across ALL users; scope it so two users can hold the same file
    content_hash = db.scoped_hash(user_id, raw_hash) if db else raw_hash
    file_size = len(content)
    existing_doc_id = None
    if db and user_id:
        try:
            with db.session_scope() as session:
                from services.database import Document
                existing_doc = session.query(Document).filter_by(
                    user_id=user_id,
                    content_hash=content_hash
                ).first()
                if existing_doc:
                    logger.info(f"Duplicate document detected (hash={content_hash[:16]}...). Existing doc_id: {existing_doc.document_id}")
                    existing_doc_id = existing_doc.document_id
                    # Return existing document instead of creating duplicate
                    return JSONResponse(content={
                        "success": True,
                        "data": {
                            "file_id": existing_doc_id,
                            "filename": existing_doc.filename,
                            "size": existing_doc.file_size,
                            "status": existing_doc.status,
                            "document_type": existing_doc.document_type,
                            "extracted_fields": existing_doc.extracted_fields or {},
                            "extraction_confidence": existing_doc.extraction_confidence,
                            "object_name": existing_doc.object_name,
                            "storage": existing_doc.storage,
                            "validation": None,
                            "collection_agent": None,
                            "duplicate": True,
                            "message": "This document has already been uploaded.",
                        }
                    })
        except Exception as e:
            logger.warning(f"Duplicate check failed: {e}")

    # Phase 3: Atomic upload — write to temp, then finalize
    file_id = str(uuid.uuid4())[:8]
    filename = file.filename or f"{file_id}_upload"
    object_name = f"docs/{file_id}_{filename}"

    # VL validation: check document type and scan quality
    validation_result = None
    required_types = []
    if application_id and application_id in _application_store:
        app = _application_store[application_id]
        required_types = app.get("required_documents", [])

    if state.get("generation") and required_types:
        try:
            gen = state["generation"]
            validation_result = await gen.validate_document(content, required_types)
            detected_type = validation_result.get("detected_type", "unknown")
            is_scanned = validation_result.get("is_scanned", False)
            confidence = validation_result.get("confidence", 0.0)
            
            allowed_lower = [t.lower() for t in required_types]
            type_ok = detected_type.lower() in allowed_lower
            
            if not type_ok:
                logger.warning(f"Document type mismatch: detected={detected_type}, required={required_types}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Please send documentation again. Expected one of: {', '.join(required_types)}, but detected: {detected_type}"
                )
            
            if not is_scanned:
                logger.warning(f"Document appears to be converted/screenshot, not a scan: {detected_type}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Please send documentation again. This appears to be a screenshot or digital conversion — please upload a clear photo or scan of the physical document."
                )
            
            if confidence < 0.3:
                logger.warning(f"Low validation confidence: {confidence}")
                raise HTTPException(
                    status_code=400,
                    detail="Please send documentation again. The image quality was too low to determine the document type."
                )
            
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Document validation failed: {e}. Continuing with extraction anyway.")
            validation_result = None

    # Upload to MinIO (Phase 3: atomic — write to temp first)
    storage = state["storage"]
    if storage:
        try:
            # Upload straight to storage (the object store is the only place the file is kept)
            storage.upload_file(
                file_data=content,
                object_name=object_name,
                content_type=content_type,
                metadata={"application_id": application_id or "", "user_id": user_id or ""},
            )
        except Exception as e:
            logger.error(f"MinIO upload failed: {e}")
            raise HTTPException(status_code=503, detail="File storage is temporarily unavailable. Please try again in a moment.")
    # Determine document type from filename
    filename_lower = file.filename.lower() if file.filename else ""
    if "passport" in filename_lower:
        document_type = "passport"
    elif "eid" in filename_lower or "national_id" in filename_lower or "id_card" in filename_lower or "nationalid" in filename_lower:
        document_type = "national_id"
    else:
        document_type = "national_id"  # default

    # Extract fields using vision model with schema
    extracted_fields = {}
    extraction_confidence = 0.0

    try:
        generation = state["generation"]
        schema = GenerationService.PASSPORT_SCHEMA if document_type == "passport" else GenerationService.NATIONAL_ID_SCHEMA
        raw_json = await generation._extract_fields_from_image(
            content, schema, document_type=document_type
        )

        # Parse the JSON response
        parsed = json.loads(raw_json)
        # Only keep fields that are in the schema (or metadata fields)
        extracted_fields = {k: str(v).strip() if v else "" for k, v in parsed.items()
                          if not k.startswith("_") or k in ("_total_pages", "_front_page", "_back_page", "_note")}
        # Validate: reject if schema says "ERROR" or similar
        if "ERROR" in str(parsed) or "error" in str(parsed).lower():
            extracted_fields = {"_error": "Extraction returned error"}

        # Calculate confidence based on how many required fields are filled
        required = len(schema)
        filled = sum(1 for k, v in extracted_fields.items() if k not in ("_total_pages", "_front_page", "_back_page", "_note") and v)
        extraction_confidence = filled / required if required > 0 else 0.0

        logger.info(f"Extraction successful for {filename}: {len(extracted_fields)} fields, confidence={extraction_confidence:.2f}")

    except Exception as e:
        logger.warning(f"Vision extraction failed: {e}. File saved without extraction.")
        extracted_fields = {"_error": str(e)[:200]}
        extraction_confidence = 0.0

    # Persist to database if available
    doc_id = None
    if db:
        try:
            with db.session_scope() as session:
                from services.database import Document
                # If this was a duplicate detected earlier, use the existing doc
                if existing_doc_id:
                    new_doc = session.query(Document).filter_by(
                        document_id=existing_doc_id
                    ).first()
                    if new_doc:
                        doc_id = new_doc.document_id
                        logger.info(f"Using existing document: id={doc_id}")
                else:
                    new_doc = Document(
                        document_id=file_id,
                        application_id=application_id,
                        user_id=user_id,
                        filename=filename,
                        file_size=file_size,
                        content_hash=content_hash,
                        content_type=content_type,
                        document_type=document_type,
                        extracted_fields=extracted_fields if extracted_fields and not extracted_fields.get("_error") else {},
                        extraction_confidence=extraction_confidence if not extracted_fields.get("_error") else 0.0,
                        status="processed",
                        object_name=object_name,
                        storage="minio" if storage else "local",
                    )
                    session.add(new_doc)
                    session.flush()
                    doc_id = new_doc.document_id
                logger.info(f"Document persisted to DB: id={doc_id}, user_id={user_id}, filename={filename}, duplicate={bool(existing_doc_id)}")
            # Recorded AFTER the transaction above has committed. Writing it from inside the open
            # transaction used a second database connection, which locks up SQLite.
            if idempotency_key and doc_id:
                try:
                    db.register_idempotency_key(
                        idempotency_key,
                        application_id or None,
                        user_id,
                        {"success": True, "document_id": doc_id, "duplicate": bool(existing_doc_id)}
                    )
                except Exception:
                    logger.warning("Could not record the idempotency key", exc_info=True)
        except Exception as e:
            logger.error(f"CRITICAL: Failed to persist document to DB: {type(e).__name__}: {e}", exc_info=True)
            if storage and not existing_doc_id:
                try:
                    storage.delete_file(object_name)      # do not leave an untracked file behind
                except Exception:
                    logger.error(f"Could not remove orphaned object {object_name}")
            raise HTTPException(status_code=503, detail="I couldn't save your document. Nothing was stored, so you can safely try again.")

    # Return the upload result
    response_data = {
        "success": True,
        "data": {
            "file_id": doc_id or file_id,
            "filename": filename,
            "size": file_size,
            "status": "processed" if not existing_doc_id else "already_exists",
            "document_type": document_type,
            "extracted_fields": extracted_fields,
            "extraction_confidence": round(extraction_confidence, 4),
            "object_name": object_name if storage else None,
            "storage": "minio" if storage else "local",
            "duplicate": existing_doc_id is not None,
            "message": "Document already exists" if existing_doc_id else None,
        }
    }
    
    return JSONResponse(content=response_data)


# --- List Documents ---
@router.get("/documents")
async def list_documents(token: Optional[str] = Query(None, alias="token")):
    """List documents for the authenticated user."""
    state = get_state()
    db = state.get("database")
    repo = state.get("repository")
    auth = state.get("auth")
    
    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id
    
    if not user_id:
        return {"data": {"documents": [], "total": 0}}
    
    # Primary: read from DB (where documents are persisted)
    if db:
        try:
            with db.session_scope() as session:
                from services.database import Document, Application
                docs_db = session.query(Document).filter_by(user_id=user_id).order_by(Document.uploaded_at.desc()).all()
                docs = []
                service_names = {
                    "basic_registration": "Basic Registration",
                    "premium_crossborder": "Premium Cross-Border",
                    "mobility_rental": "Mobility & Rental",
                }
                for d in docs_db:
                    service_id = None
                    if d.application and d.application.service_id:
                        service_id = d.application.service_id
                    elif isinstance(d.extracted_fields, dict) and d.extracted_fields.get("_service_id"):
                        service_id = d.extracted_fields.get("_service_id")
                    
                    service_name = service_names.get(
                        service_id,
                        service_id.replace("_", " ").title() if service_id else "Basic Registration"
                    )
                    if not service_id:
                        service_id = "basic_registration"

                    docs.append({
                        "id": d.document_id,
                        "filename": d.filename,
                        "file_size": d.file_size,
                        "status": d.status,
                        "upload_date": d.uploaded_at.isoformat() if d.uploaded_at else None,
                        "storage": d.storage,
                        "object_name": d.object_name,
                        "document_type": d.document_type,
                        "service_id": service_id,
                        "service_name": service_name,
                        "extracted_fields": {k: v for k, v in d.extracted_fields.items() if not k.startswith("_")} if isinstance(d.extracted_fields, dict) else {},
                        "extraction_confidence": d.extraction_confidence or 0.0,
                    })
                return {"data": {"documents": docs, "total": len(docs)}}
        except Exception as e:
            logger.warning(f"Failed to fetch documents from DB: {e}")
    
    # Fallback: read from repository
    if repo:
        try:
            docs = repo.list_user_documents(user_id)
            return {"data": {"documents": docs, "total": len(docs)}}
        except Exception as e:
            logger.warning(f"Failed to fetch documents from repository: {e}")
    
    raise HTTPException(status_code=503, detail="Your documents are temporarily unavailable. Please try again shortly.")


# --- Delete Document ---
@router.post("/documents/{document_id}/delete")
async def delete_document(document_id: str, token: Optional[str] = Query(None, alias="token")):
    """Delete one of the caller's own documents (file and database row)."""
    state = get_state()
    user_id = _require_user_id(state, token)
    doc = _owned_document(state, document_id, user_id)
    storage, db = state.get("storage"), state.get("database")
    if doc.get("object_name"):
        if not storage:
            raise HTTPException(status_code=503, detail="File storage is temporarily unavailable. Please try again in a moment.")
        try:
            storage.delete_file(doc["object_name"])
        except Exception:
            logger.error("Failed to delete document from storage", exc_info=True)
            raise HTTPException(status_code=503, detail="I couldn't delete that document. Please try again.")
    try:
        from services.database import Document, AuditLog
        with db.session_scope() as session:
            session.query(Document).filter_by(document_id=document_id, user_id=user_id).delete()
            session.add(AuditLog(log_id=f"audit_{uuid.uuid4().hex[:12]}", user_id=user_id,
                                 application_id=doc.get("application_id"), event_type="document_deleted",
                                 details={"document_id": document_id}))
    except Exception:
        logger.error("Failed to delete document row", exc_info=True)
        raise HTTPException(status_code=503, detail="I couldn't delete that document. Please try again.")
    return {"success": True, "message": "Document deleted"}


# --- Download Document ---
@router.get("/documents/{document_id}/download")
async def download_document(document_id: str, token: Optional[str] = Query(None, alias="token")):
    """Download one of the caller's own documents."""
    state = get_state()
    user_id = _require_user_id(state, token)
    doc = _owned_document(state, document_id, user_id)
    storage = state.get("storage")
    if not doc.get("object_name") or not storage:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        data = storage.download_file(doc["object_name"])
    except Exception:
        logger.error("Failed to download from storage", exc_info=True)
        raise HTTPException(status_code=503, detail="I couldn't fetch that document. Please try again.")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in (doc.get("filename") or "document.pdf"))[:80]
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"'})


# --- Presigned URL ---
@router.get("/documents/{document_id}/presigned-url")
async def get_presigned_url(document_id: str, token: Optional[str] = Query(None, alias="token")):
    """Short-lived download link for one of the caller's own documents (10 minutes)."""
    state = get_state()
    user_id = _require_user_id(state, token)
    doc = _owned_document(state, document_id, user_id)
    storage = state.get("storage")
    if not doc.get("object_name") or not storage:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        url = storage.generate_presigned_url(doc["object_name"], expires=timedelta(minutes=10))
    except Exception:
        logger.error("Failed to generate presigned URL", exc_info=True)
        raise HTTPException(status_code=503, detail="I couldn't create a download link. Please try again.")
    return {"success": True, "url": url}


# --- Document Image Field Extraction (standalone endpoint) ---
@router.post("/documents/extract")
async def extract_fields_from_document(file: UploadFile = File(...), doc_type: str = Query(default="id", description="Type of document to extract"), token: Optional[str] = Query(None, alias="token")):
    """Extract fields from a document using vision model. Requires authentication."""
    state = get_state()

    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")

    if not token:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in to upload documents.")

    auth = state.get("auth")
    if auth:
        user = auth.validate_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please sign in again.")

    allowed_types = ["application/pdf"]
    allowed_extensions = ['.pdf']
    ext = os.path.splitext(file.filename)[1].lower()
    
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Got: {file.content_type}. Please upload a PDF or scanned PDF."
        )
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are accepted. Extension '{ext}' is not valid. Please upload a .pdf file."
        )

    content = await file.read()
    filename = file.filename.lower()

    # Determine document type
    if "passport" in filename:
        document_type = "passport"
    else:
        document_type = "national_id"

    try:
        generation = state["generation"]
        schema = GenerationService.PASSPORT_SCHEMA if document_type == "passport" else GenerationService.NATIONAL_ID_SCHEMA
        raw_json = await generation._extract_fields_from_image(
            content, schema, document_type=document_type
        )

        parsed = json.loads(raw_json)
        cleaned = {k: str(v).strip() if v else "" for k, v in parsed.items() 
                   if not k.startswith("_")}
        return JSONResponse(content={
            "success": True,
            "data": {
                "extracted_fields": cleaned,
                "status": "processed",
                "document_type": document_type,
            }
        })
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return JSONResponse(content={
            "success": False,
            "error": "I couldn't read that document. Please try again with a clearer scan."
        }, status_code=500)



# ────────────────────────────────────────────────────────────────────
#  Phase 3: New endpoints for delete application, status transition,
#  validation rules, and collection sessions
# ────────────────────────────────────────────────────────────────────

@router.post("/applications/{application_id}/delete")
async def delete_application(application_id: str, token: Optional[str] = Query(None, alias="token")):
    """Delete an application and all associated data atomically.
    
    Removes: all documents (rows + MinIO objects), extracted fields,
    review items, trace events, application events, audit logs,
    collection sessions, and the application row itself.
    """
    state = get_state()
    db = state.get("database")
    repo = state.get("repository")
    storage = state.get("storage")
    auth = state.get("auth")
    
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")
    
    user_id = _require_user_id(state, token)      # 401 unless a valid user (a token with no auth service no longer passes)
    
    if not db or not repo:
        raise HTTPException(status_code=503, detail="Database service not available")
    
    # Verify application ownership
    app = repo.get_application(application_id, user_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Perform cascade delete
    result = repo.delete_application(application_id, storage, user_id=user_id)
    
    if result["deleted"]:
        # Also remove from in-memory store if present
        if application_id in _application_store:
            del _application_store[application_id]
        
        return JSONResponse(content={
            "success": True,
            "deleted": True,
            "application_id": application_id,
            "files_pending_removal": len(result.get("orphaned_objects", [])),
            "counts": {
                "documents": result["deleted_documents"],
                "minio_objects": result["deleted_minio_objects"],
                "extracted_fields": result["deleted_extracted_fields"],
                "review_items": result["deleted_review_items"],
                "trace_events": result["deleted_trace_events"],
                "application_events": result["deleted_application_events"],
                "audit_logs": result["deleted_audit_logs"],
            }
        })
    else:
        logger.error("Application delete failed: %s", result["errors"])
        raise HTTPException(status_code=500, detail="I couldn't delete that application. Nothing was removed, so you can safely try again.")


@router.post("/applications/{application_id}/transition-status")
async def transition_application_status(
    application_id: str,
    from_status: str = Query(..., alias="from"),
    to_status: str = Query(..., alias="to"),
    token: Optional[str] = Query(None, alias="token")
):
    """Atomically transition application status using SELECT FOR UPDATE + compare-and-set.
    
    Prevents race conditions when multiple threads/processes try to update status.
    Returns 200 if transition succeeded, 409 if status didn't match (concurrent update).
    """
    state = get_state()
    db = state.get("database")
    repo = state.get("repository")
    auth = state.get("auth")
    
    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")
    
    user_id = _require_user_id(state, token)      # 401 unless a valid user (a token with no auth service no longer passes)
    
    if not db or not repo:
        raise HTTPException(status_code=503, detail="Database service not available")
    
    # Verify application ownership
    app = repo.get_application(application_id, user_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Only known statuses, and a user cannot mark their own application complete or rejected:
    # those outcomes come from validation and review, not from the applicant.
    if to_status not in ("incomplete", "processing", "needs_review"):
        raise HTTPException(status_code=403, detail="That status can't be set from here.")
    if from_status not in ("incomplete", "processing", "complete", "needs_review", "rejected"):
        raise HTTPException(status_code=400, detail="Unknown status.")

    # Verify current status matches
    if app["status"] != from_status:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "Status conflict",
                "current_status": app["status"],
                "expected_status": from_status,
                "message": f"Application is currently '{app['status']}', expected '{from_status}'. "
                          f"A concurrent update may have occurred. Please refresh and retry."
            }
        )
    
    # Perform race-safe transition
    success = repo.transition_application_status(application_id, from_status, to_status, user_id)
    
    if success:
        # Also update in-memory store if present
        if application_id in _application_store:
            _application_store[application_id]["status"] = to_status
        
        return JSONResponse(content={
            "success": True,
            "application_id": application_id,
            "old_status": from_status,
            "new_status": to_status
        })
    else:
        # Shouldn't happen if ownership check passed, but be safe
        raise HTTPException(
            status_code=500,
            detail="Status transition failed unexpectedly"
        )


@router.get("/validation-rules")
async def get_validation_rules(
    service_id: str = Query("all", description="Service ID to filter rules"),
    document_type: Optional[str] = Query(None, description="Document type to filter rules")
):
    """Fetch validation rules for a service/doc_type combo.
    
    Rules are loaded from config.yaml into the DB at startup.
    """
    state = get_state()
    repo = state.get("repository")
    
    if not repo:
        raise HTTPException(status_code=503, detail="Repository service not available")
    
    rules = repo.get_validation_rules(service_id, document_type=document_type)
    
    return JSONResponse(content={
        "success": True,
        "rules": rules,
        "count": len(rules)
    })


@router.get("/collection-sessions")
async def list_collection_sessions(token: Optional[str] = Query(None, alias="token")):
    """List all collection sessions for the authenticated user."""
    state = get_state()
    repo = state.get("repository")
    auth = state.get("auth")
    
    # Resolve user_id from token
    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id
    
    if not user_id:
        return JSONResponse(content={
            "success": True,
            "sessions": [],
            "count": 0
        })
    
    if not repo:
        raise HTTPException(status_code=503, detail="Repository service not available")
    
    sessions = repo.list_user_collection_sessions(user_id)
    
    return JSONResponse(content={
        "success": True,
        "sessions": sessions,
        "count": len(sessions)
    })


@router.get("/collection-sessions/{session_id}")
async def get_collection_session(
    session_id: str,
    token: Optional[str] = Query(None, alias="token")
):
    """Get a specific collection session, verifying user ownership."""
    state = get_state()
    repo = state.get("repository")
    auth = state.get("auth")
    
    # Resolve user_id from token
    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id
    
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    if not repo:
        raise HTTPException(status_code=503, detail="Repository service not available")
    
    session = repo.get_collection_session(session_id, user_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Collection session not found")
    
    return JSONResponse(content={
        "success": True,
        "session": session
    })
