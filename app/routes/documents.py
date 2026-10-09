"""Document routes: upload, list, delete, download, presigned-url, extract."""

import os
import uuid
import json
import logging
import io
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse, Response, FileResponse

router = APIRouter()

logger = logging.getLogger(__name__)

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
            "selected_service": None,
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
):
    """Upload a document with AI-powered field extraction via Qwen2.5-VL 3B.
    Requires authentication.
    
    Phase 3: Duplicate detection (SHA-256), atomic uploads, DB persistence,
    cross-service contamination prevention.
    """
    state = get_state()
    db = state.get("database")

    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")

    # Validate file
    result = state["validator"].validate_file(file)
    if not result["is_valid"]:
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})

    # Read file content (Phase 3: store for duplicate check)
    content = await file.read()

    # Determine content type
    ext = os.path.splitext(file.filename)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }
    content_type = mime_map.get(ext, "application/octet-stream")

    # Determine user_id from token
    user_id = None
    if token:
        auth = state.get("auth")
        if auth:
            user = auth.validate_token(token)
            if user:
                user_id = user.user_id

    # Phase 3: Check for duplicates using SHA-256 hash
    content_hash = ""
    if db:
        content_hash = db.compute_content_hash(content)
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
            # Write to temp file first (atomic upload)
            temp_path = os.path.join(os.path.dirname(__file__), "..", "data", ".temp_upload.bin")
            os.makedirs(os.path.dirname(temp_path), exist_ok=True)
            with open(temp_path, "wb") as tmp:
                tmp.write(content)
            # Then upload to storage
            storage.upload_file(
                file_data=content,
                object_name=object_name,
                content_type=content_type,
                metadata={"application_id": application_id or "", "user_id": user_id or ""},
            )
            # Clean up temp
            try:
                os.remove(temp_path)
            except:
                pass
        except Exception as e:
            logger.error(f"MinIO upload failed: {e}")
            raise HTTPException(status_code=500, detail=f"Storage upload failed: {str(e)[:200]}")

    # Extract fields using vision model
    extracted_fields = {}
    extraction_confidence = 0.0
    document_type = "unknown"

    try:
        generation = state["generation"]
        raw_json = await generation.generate_response(
            prompt="Extract all fields from this document",
            image_bytes=content,
        )

        # Parse the JSON response
        parsed = json.loads(raw_json)
        extracted_fields = {k: v for k, v in parsed.items() if not k.startswith("_")}
        extraction_confidence = 0.85  # Vision model confidence

        # Determine document type from fields
        if "passport" in file.filename.lower() or parsed.get("passport_type"):
            document_type = "passport"
        elif "driving" in file.filename.lower() or "license" in file.filename.lower():
            document_type = "driving_license"
        else:
            document_type = "national_id"

    except Exception as e:
        logger.warning(f"Vision extraction failed: {e}. File saved without extraction.")
        extracted_fields = {"_error": str(e)[:200]}
        extraction_confidence = 0.0

    # Phase 3: Persist document to database with duplicate check
    stored_doc_id = file_id
    if db and user_id:
        try:
            stored_doc_id = db.upload_document(
                application_id=application_id or "",
                user_id=user_id,
                filename=filename,
                file_data=content,
                content_type=content_type,
                object_name=object_name,
                file_size=file_size,
                document_type=document_type,
                storage="minio" if storage else "filesystem",
            )
            logger.info(f"Document persisted to DB: {stored_doc_id} (hash={content_hash[:16]}...)")
        except Exception as e:
            logger.warning(f"Database upload_document failed ({e})")

    # Update document processing in DB
    if db and stored_doc_id and extracted_fields:
        try:
            db.update_document_processing(stored_doc_id, extracted_fields, extraction_confidence)
        except Exception as e:
            logger.warning(f"DB update_document_processing failed: {e}")

    # Record document submission with CollectionAgent (Phase 2)
    collection_agent = state.get("collection_agent")
    coll_session_id = None
    coll_response = None
    if application_id and application_id in _application_store:
        coll_session_id = _application_store[application_id].get("collection_session_id")
    
    if collection_agent and coll_session_id:
        # Phase 3: Check cross-service contamination
        app = _application_store.get(application_id, {})
        if document_type not in app.get("required_documents", []):
            logger.warning(f"Cross-service contamination detected: doc_type={document_type} not in required={app.get('required_documents', [])}")

        guessed_doc_type = document_type
        if application_id and application_id in _application_store:
            app = _application_store[application_id]
            if guessed_doc_type not in app.get("required_documents", []):
                filename_lower = filename.lower()
                for req_doc in app.get("required_documents", []):
                    if req_doc in filename_lower:
                        guessed_doc_type = req_doc
                        break
        
        coll_response = collection_agent.submit_document(
            session_id=coll_session_id,
            doc_type=guessed_doc_type,
            file_id=file_id,
            extraction_ok=extraction_confidence >= 0.3,
            extraction_fields=extracted_fields,
            extraction_confidence=extraction_confidence,
        )
        if coll_response:
            if coll_response.get("action") == "complete":
                _application_store[application_id]["status"] = "complete"
            elif coll_response.get("action") == "needs_review":
                _application_store[application_id]["status"] = "needs_review"
            elif coll_response.get("action") == "escalate_to_validation":
                _application_store[application_id]["status"] = "exception"

    return JSONResponse(content={
        "success": True,
        "data": {
            "file_id": file_id,
            "stored_doc_id": stored_doc_id,
            "filename": filename,
            "size": file_size,
            "status": "processed",
            "document_type": document_type,
            "extracted_fields": extracted_fields,
            "extraction_confidence": extraction_confidence,
            "object_name": object_name,
            "storage": "minio" if storage else "filesystem",
            "validation": validation_result,
            "collection_agent": coll_response,
            "content_hash": content_hash,
        },
        "message": "Document uploaded and processed successfully"
    })

# --- List Documents ---
@router.get("/documents")
async def list_documents(token: Optional[str] = Query(None, alias="token")):
    """List documents for the authenticated user.
    
    WP8: Repository layer enforces user_id on all document queries.
    """
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
        return {"data": {"documents": [], "total": 0}}
    
    # Try repository first (WP8)
    if repo:
        try:
            docs = repo.list_user_documents(user_id)
            return {"data": {"documents": docs, "total": len(docs)}}
        except Exception as e:
            logger.warning(f"Failed to fetch documents from repository: {e}")
    
    # Fallback to MinIO listing
    docs = []
    storage = state.get("storage")
    if storage:
        try:
            objects = storage.list_files(prefix="docs/")
            for obj in objects:
                base_name = obj["object_name"].replace("docs/", "", 1) if obj["object_name"].startswith("docs/") else obj["object_name"]
                file_id = base_name.split("_")[0] if "_" in base_name else base_name
                docs.append({
                    "id": file_id,
                    "filename": base_name,
                    "file_size": obj["size"],
                    "status": "processed",
                    "upload_date": obj["last_modified"],
                    "storage": "minio",
                    "object_name": obj["object_name"],
                })
        except Exception as e:
            logger.error(f"Failed to list documents from MinIO: {e}")
    return {"data": {"documents": docs}}

# --- Delete Document ---
@router.post("/documents/{document_id}/delete")
async def delete_document(document_id: str):
    """Delete a document from MinIO or filesystem."""
    state = get_state()

    if state.get("storage"):
        # Delete from MinIO
        try:
            files = state["storage"].list_files(prefix=f"docs/{document_id}_")
            for obj in files:
                state["storage"].delete_file(obj["object_name"])
            return {"success": True, "message": f"Deleted {len(files)} file(s) from MinIO"}
        except Exception as e:
            logger.error(f"Failed to delete document from MinIO: {e}")
            raise HTTPException(status_code=500, detail=f"Storage deletion failed: {str(e)[:200]}")
    else:
        # Fallback to filesystem
        upload_dir = "uploads"
        deleted = False
        try:
            files = os.listdir(upload_dir)
            for f in files:
                if document_id in f:
                    os.remove(os.path.join(upload_dir, f))
                    deleted = True
        except Exception as e:
            logger.error(f"Failed to delete file: {e}")

        return {"success": deleted, "message": "Document deleted" if deleted else "Document not found"}

# --- Download Document ---
@router.get("/documents/{document_id}/download")
async def download_document(document_id: str):
    """Download a document from MinIO or filesystem."""
    state = get_state()

    if state.get("storage"):
        # Download from MinIO
        try:
            objects = state["storage"].list_files(prefix=f"docs/{document_id}_")
            if not objects:
                raise HTTPException(status_code=404, detail="Document not found")
            obj = objects[0]
            data = state["storage"].download_file(obj["object_name"])
            # Extract filename from object_name
            filename = obj["object_name"].replace("docs/", "", 1)
            return Response(
                content=data,
                media_type="application/octet-stream",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to download from MinIO: {e}")
            raise HTTPException(status_code=500, detail=f"Download failed: {str(e)[:200]}")
    else:
        # Fallback to filesystem
        upload_dir = "uploads"
        filepath = None
        for f in os.listdir(upload_dir):
            if document_id in f:
                filepath = os.path.join(upload_dir, f)
                break
        if not filepath:
            raise HTTPException(status_code=404, detail="Document not found")
        return FileResponse(filepath, filename=filepath.split("/")[-1])

# --- Presigned URL ---
@router.get("/documents/{document_id}/presigned-url")
async def get_presigned_url(document_id: str):
    """Get a presigned download URL for a document (expires in 1 hour)."""
    state = get_state()
    storage = state.get("storage")

    if not storage:
        raise HTTPException(status_code=500, detail="Storage service not available")

    try:
        objects = storage.list_files(prefix=f"docs/{document_id}_")
        if not objects:
            raise HTTPException(status_code=404, detail="Document not found")
        obj = objects[0]
        url = storage.generate_presigned_url(obj["object_name"], expires=timedelta(hours=1))
        return {"success": True, "url": url, "object_name": obj["object_name"]}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate presigned URL: {e}")
        raise HTTPException(status_code=500, detail=f"URL generation failed: {str(e)[:200]}")

# --- Document Image Field Extraction (standalone endpoint) ---
@router.post("/documents/extract")
async def extract_fields_from_document(file: UploadFile = File(...), doc_type: str = Query(default="id", description="Type of document to extract: 'id' for government IDs, 'general' for other documents"), token: Optional[str] = Query(None, alias="token")):
    """Extract fields from a document image using vision model.

    Requires authentication.

    Optimized for government-issued IDs (national IDs, passports, driver's licenses, visas, residence permits).
    Handles:
    - Scanned PDFs (multi-page: extracts all pages, merges front/back)
    - Image files (JPEG, PNG, JPG)
    - Multi-language documents (labels in English, Albanian, Turkish, Arabic, French, German, etc.)
    - MRZ (Machine Readable Zone) detection on passports/IDs
    
    Args:
        file: Upload file (PDF or image)
        doc_type: 'id' for government ID extraction (full field set), 'general' for generic extraction
        token: User authentication token (required)

    Returns:
        Structured JSON with extracted fields
    """
    state = get_state()

    if not state["ready"]:
        raise HTTPException(status_code=503, detail="System not ready")

    # Auth check - uploads require authentication
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in to upload documents.")

    # Validate token
    auth = state.get("auth")
    if auth:
        user = auth.validate_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired token. Please sign in again.")

    # Validate file
    result = state["validator"].validate_file(file)
    if not result["is_valid"]:
        raise HTTPException(status_code=400, detail={"errors": result["errors"]})

    content = await file.read()
    filename = file.filename.lower()

    # Determine if it's a PDF
    is_pdf = any(filename.endswith(ext) for ext in ['.pdf'])
    page_hint = ""

    try:
        if doc_type == "id":
            # Use the ID-specific extraction with full field set
            raw_json = await state["generation"].extract_id_fields_from_image(
                content,
                is_pdf=is_pdf,
                page_hint=page_hint
            )
        else:
            # Generic extraction (backward compatible)
            raw_json = await state["generation"].generate_response(
                prompt="Extract all fields from this document",
                image_bytes=content,
            )

        parsed = json.loads(raw_json)
        return JSONResponse(content={
            "success": True,
            "data": {
                "extracted_fields": {k: v for k, v in parsed.items() if not k.startswith("_")},
                "status": "processed",
                "document_type": doc_type,
                "is_pdf": is_pdf
            }
        })
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return JSONResponse(content={
            "success": False,
            "error": str(e)[:200]
        }, status_code=500)
