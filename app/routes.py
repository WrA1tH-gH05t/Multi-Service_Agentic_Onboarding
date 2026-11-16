"""FastAPI Routes — all API endpoints for the onboarding system."""
import io
import os
import logging
from typing import Optional

import psycopg2
import psycopg2.extras
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Header
from fastapi.responses import JSONResponse

from app.schemas import (
    SignUpRequest, LoginRequest, AuthResponse,
    ChatRequest, ChatResponse,
    ConfirmReviewRequest,
    DocumentResponse, ApplicationResponse,
)
from services.auth import AuthService
from services.generation import GenerationService
from services.validation import ValidationService
from services.service_catalog import ServiceCatalogService
from agents.collection_agent import CollectionAgent
from agents.validation_agent import ValidationAgent

logger = logging.getLogger("app.routes")
router = APIRouter()

DB_DSN = os.getenv("DATABASE_URL", "postgresql://intake:intake@localhost:5432/doc_intake")

auth_svc    = AuthService()
gen_svc     = GenerationService()
val_svc     = ValidationService()
catalog     = ServiceCatalogService()
val_agent   = ValidationAgent()


def _db():
    return psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)


# ------------------------------------------------------------------
# Auth helpers
# ------------------------------------------------------------------
def _get_current_user(authorization: str = Header(...)) -> dict:
    token = authorization.removeprefix("Bearer ").strip()
    user = auth_svc.get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user


# ==================================================================
# AUTH ENDPOINTS
# ==================================================================

@router.post("/auth/signup", response_model=AuthResponse, tags=["Auth"])
def signup(body: SignUpRequest):
    """Register a new user."""
    try:
        result = auth_svc.register(
            email=body.email,
            password=body.password,
            full_name=body.full_name,
            birthday=str(body.birthday),
            gender=body.gender,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    pending = auth_svc.get_pending_applications(result["user_id"])
    return {**result, "pending_applications": pending}


@router.post("/auth/login", response_model=AuthResponse, tags=["Auth"])
def login(body: LoginRequest):
    """Authenticate an existing user."""
    try:
        result = auth_svc.login(email=body.email, password=body.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))

    pending = auth_svc.get_pending_applications(result["user_id"])
    return {**result, "pending_applications": pending}


@router.post("/auth/logout", tags=["Auth"])
def logout(user: dict = Depends(_get_current_user), authorization: str = Header(...)):
    token = authorization.removeprefix("Bearer ").strip()
    auth_svc.logout(token)
    return {"message": "Logged out successfully."}


# ==================================================================
# CHAT ENDPOINT
# Change: returns ONLY `reply` — no confidence_score, no sources.
# ==================================================================

@router.post("/chat/message", response_model=ChatResponse, tags=["Chat"])
def chat_message(body: ChatRequest, user: dict = Depends(_get_current_user)):
    """Send a message to the onboarding agent."""
    agent = CollectionAgent(
        user_id=user["id"],
        full_name=user["full_name"],
        application_id=body.application_id,
    )
    reply = agent.handle_message(body.message)
    # Return ONLY the reply — no confidence, no sources
    return ChatResponse(reply=reply)


# ==================================================================
# DOCUMENT ENDPOINTS
# ==================================================================

@router.post("/documents/upload", tags=["Documents"])
async def upload_document(
    file: UploadFile = File(...),
    application_id: int = Form(...),
    expected_doc_type: str = Form(...),   # national_id | passport | driving_license
    user: dict = Depends(_get_current_user),
):
    """Upload a document image/PDF."""
    content = await file.read()

    # Validate file
    ok, reason = val_svc.validate_upload(file.filename, file.content_type or "", len(content), content=content)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    # Extract fields with vision model
    extracted = gen_svc.extract_fields(content, file.filename)
    doc_type   = extracted.get("doc_type", "unknown")
    fields     = extracted.get("fields", {})

    # Check doc type matches expectation
    if doc_type != "unknown" and doc_type != expected_doc_type:
        match_ok, msg = val_svc.validate_doc_type_match(expected_doc_type, doc_type)
        if not match_ok:
            raise HTTPException(status_code=422, detail=msg)

    # Determine which fields are non-editable
    non_editable = list(catalog.get_non_editable_fields(doc_type))

    # Store document record
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents
                  (application_id, user_id, doc_type, original_filename,
                   content_type, size_bytes, extracted_fields, validation_status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
                RETURNING id, created_at
                """,
                (
                    application_id, user["id"], doc_type,
                    file.filename, file.content_type, len(content),
                    psycopg2.extras.Json(fields),
                ),
            )
            row = cur.fetchone()
            conn.commit()

    return {
        "document_id": row["id"],
        "doc_type": doc_type,
        "extracted_fields": fields,
        "non_editable_fields": non_editable,
        "created_at": str(row["created_at"]),
    }


@router.post("/documents/extract", tags=["Documents"])
async def extract_only(
    file: UploadFile = File(...),
    user: dict = Depends(_get_current_user),
):
    """Authenticated extraction endpoint — returns JSON fields without saving."""
    content = await file.read()
    ok, reason = val_svc.validate_upload(file.filename or "", file.content_type or "", len(content), content=content)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)

    extracted = gen_svc.extract_fields(content, file.filename or "")
    doc_type   = extracted.get("doc_type", "unknown")
    fields     = extracted.get("fields", {})
    non_editable = list(catalog.get_non_editable_fields(doc_type))
    return {
        "doc_type": doc_type,
        "fields": fields,
        "non_editable_fields": non_editable,
    }


@router.post("/documents/confirm-review", tags=["Documents"])
def confirm_review(body: ConfirmReviewRequest, user: dict = Depends(_get_current_user)):
    """Confirm reviewed/edited fields after extraction."""
    # Load original extracted fields from DB
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT extracted_fields, doc_type FROM documents WHERE id = %s AND user_id = %s",
                (body.document_id, user["id"]),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Document not found.")
            original_fields = row["extracted_fields"] or {}
            stored_doc_type = row["doc_type"] or body.doc_type

    # Merge edits while restoring locked fields from original extraction
    final_fields = CollectionAgent.apply_field_lock(
        doc_type=stored_doc_type,
        submitted_fields=body.edited_fields,
        original_fields=original_fields,
    )

    # Update DB with final merged fields
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE documents
                SET extracted_fields = %s, validation_status = 'reviewed'
                WHERE id = %s AND user_id = %s
                """,
                (psycopg2.extras.Json(final_fields), body.document_id, user["id"]),
            )
            conn.commit()

    return {
        "document_id": body.document_id,
        "final_fields": final_fields,
        "locked_fields": list(catalog.get_non_editable_fields(stored_doc_type)),
        "status": "reviewed",
    }


@router.get("/documents", tags=["Documents"])
def list_documents(
    application_id: Optional[int] = None,
    user: dict = Depends(_get_current_user),
):
    with _db() as conn:
        with conn.cursor() as cur:
            if application_id:
                cur.execute(
                    "SELECT id, doc_type, original_filename, size_bytes, "
                    "extracted_fields, validation_status, created_at "
                    "FROM documents WHERE user_id = %s AND application_id = %s "
                    "ORDER BY created_at DESC",
                    (user["id"], application_id),
                )
            else:
                cur.execute(
                    "SELECT id, doc_type, original_filename, size_bytes, "
                    "extracted_fields, validation_status, created_at "
                    "FROM documents WHERE user_id = %s ORDER BY created_at DESC",
                    (user["id"],),
                )
            rows = cur.fetchall()

    return [
        {
            **dict(r),
            "non_editable_fields": list(catalog.get_non_editable_fields(r["doc_type"] or "")),
            "created_at": str(r["created_at"]),
        }
        for r in rows
    ]


@router.post("/documents/{doc_id}/delete", tags=["Documents"])
def delete_document(doc_id: int, user: dict = Depends(_get_current_user)):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM documents WHERE id = %s AND user_id = %s RETURNING id",
                (doc_id, user["id"]),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Document not found.")
            conn.commit()
    return {"deleted": doc_id}


# ==================================================================
# APPLICATION ENDPOINTS
# ==================================================================

@router.get("/applications", tags=["Applications"])
def list_applications(user: dict = Depends(_get_current_user)):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, service_type, status, current_step, created_at, updated_at "
                "FROM applications WHERE user_id = %s ORDER BY updated_at DESC",
                (user["id"],),
            )
            return [dict(r) for r in cur.fetchall()]


@router.get("/applications/{app_id}", tags=["Applications"])
def get_application(app_id: int, user: dict = Depends(_get_current_user)):
    with _db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, service_type, status, current_step, created_at, updated_at "
                "FROM applications WHERE id = %s AND user_id = %s",
                (app_id, user["id"]),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Application not found.")
            return dict(row)


# ==================================================================
# SERVICES CATALOGUE
# ==================================================================

@router.get("/services", tags=["Services"])
def get_services():
    return catalog.get_all()


# ==================================================================
# HEALTH
# ==================================================================

@router.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": "2.1.0"}
