"""Application wizard routes."""

import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from enum import Enum
from fastapi import APIRouter, File, UploadFile, HTTPException, Query

router = APIRouter()

logger = logging.getLogger(__name__)

from fastapi.responses import JSONResponse
from services.database import Application

def get_state():
    from app.main import app_state
    return app_state

from services.wizard import WizardStep

@router.get("/wizard/session")
async def create_wizard_session(
    service_id: str = Query("basic_registration", description="Service type"),
    token: Optional[str] = Query(None, alias="token"),
):
    """Create a new wizard session for an applicant (frontend uses GET)."""
    state = get_state()
    auth = state.get("auth")
    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    wizard_mgr = state.get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.create_session(user_id=user_id, service_id=service_id)
    return {
        "success": True,
        "data": {
            "session_id": session.session_id,
            "step": session.current_step.value,
            "service_id": service_id,
        },
        "message": "Wizard session created"
    }

@router.get("/wizard/status")
async def get_wizard_status(
    session_id: str = Query(..., description="Wizard session ID"),
    token: Optional[str] = Query(None, alias="token"),
):
    """Get current wizard session status."""
    state = get_state()
    auth = state.get("auth")
    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    wizard_mgr = state.get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    return {
        "success": True,
        "data": {
            "session_id": session.session_id,
            "step": session.current_step.value,
            "service_id": session.service_id,
            "applicant_name": session.applicant_name,
            "application_id": session.application_id,
            "id_extraction": session.id_extraction.to_dict() if session.id_extraction else None,
            "id_clarity": session.id_clarity_check.to_dict() if session.id_clarity_check else None,
            "validated": session.is_validated(),
        }
    }


@router.post("/wizard/create")
async def create_wizard_session(
    service_id: str = Query("basic_registration", description="Service type"),
    token: Optional[str] = Query(None, alias="token"),
):
    """Create a new wizard session for an applicant."""
    state = get_state()
    auth = state.get("auth")

    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    wizard_mgr = state.get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.create_session(user_id=user_id, service_id=service_id)
    return {
        "success": True,
        "data": {
            "session_id": session.session_id,
            "step": session.current_step.value,
            "service_id": service_id,
        },
        "message": "Wizard session created"
    }


@router.post("/wizard/{session_id}/name")
async def set_wizard_name(
    session_id: str,
    body: dict,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 1: Set applicant name."""
    wizard_mgr = get_state().get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")

    session = wizard_mgr.set_name(session_id, name)
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "step": session.current_step.value,
            "name": session.applicant_name,
        },
        "message": "Name recorded"
    }


@router.post("/wizard/{session_id}/upload")
async def upload_wizard_id(
    session_id: str,
    file: UploadFile = File(...),
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 2: Upload National ID document for clarity check and extraction."""
    state = get_state()
    wizard_mgr = state.get("wizard_manager")
    storage = state.get("storage")
    if not wizard_mgr or not storage:
        raise HTTPException(status_code=503, detail="Required services not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    # Validate file type
    allowed_types = ["image/png", "image/jpeg", "image/jpg", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {file.content_type}. Allowed: {', '.join(allowed_types)}"
        )

    # Upload to storage
    file_content = await file.read()
    file_name = f"wizard/{session_id}/national_id_{file.filename}"
    file_url = storage.save_file(file_name, file_content, content_type=file.content_type)

    # Record upload
    session = wizard_mgr.set_id_upload(session_id, file_url, file.filename)

    # Check clarity (simple heuristics)
    class ClarityStatus(str, Enum):
        PASS = "pass"
        FAIL = "fail"
        PENDING = "pending"

    clarity_issues = []
    quality_score = 0.8  # Placeholder - would use actual image analysis
    
    # Check file size (basic quality proxy)
    if len(file_content) < 50000:  # < 50KB might be too small/blurry
        quality_score = 0.3
        clarity_issues.append("File may be too low resolution")
    
    clarity_status = ClarityStatus.PASS if quality_score >= 0.6 else ClarityStatus.FAIL
    
    session = wizard_mgr.update_clarity_check(
        session_id, clarity_status, quality_score, clarity_issues
    )
    
    if clarity_status == ClarityStatus.FAIL:
        return {
            "success": False,
            "data": {
                "session_id": session_id,
                "clarity_status": "fail",
                "quality_score": quality_score,
                "issues": clarity_issues,
                "message": "Document clarity check failed. Please upload a clearer image.",
            },
            "message": "Clarity check failed"
        }

    # Extract fields (placeholder - would use OCR + LLM)
    extracted_fields = {
        "full_name": session.applicant_name,  # Use entered name
        "national_id_number": "",  # Would extract from ID
        "date_of_birth": "",
        "gender": "",
        "nationality": "",
        "expiry_date": "",
    }
    
    session = wizard_mgr.set_id_extraction(session_id, extracted_fields, quality_score)

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "step": session.current_step.value,
            "clarity_status": "pass",
            "quality_score": quality_score,
            "next_step": "review",
        },
        "message": "Document uploaded and validated"
    }


@router.get("/wizard/{session_id}/review")
async def get_wizard_review(
    session_id: str,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 3: Get review data (masked fields)."""
    wizard_mgr = get_state().get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    # Mask sensitive fields for review
    extraction = session.id_extraction
    masked_fields = {}
    if extraction:
        masked_fields = {
            "full_name": extraction.full_name,
            "national_id_number": extraction.national_id_number[:4] + "****" if extraction.national_id_number else "",
            "date_of_birth": extraction.date_of_birth,
            "gender": extraction.gender,
            "nationality": extraction.nationality,
            "expiry_date": extraction.expiry_date,
            "confidence": extraction.confidence,
        }

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "applicant_name": session.applicant_name,
            "id_fields": masked_fields,
            "clarity_score": session.id_clarity_check.quality_score if session.id_clarity_check else None,
            "id_validation_status": session.id_validation_status.value,
        },
        "message": "Review data ready"
    }


@router.post("/wizard/{session_id}/confirm")
async def confirm_wizard_review(
    session_id: str,
    body: dict,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 3: Confirm review fields."""
    wizard_mgr = get_state().get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    fields = body.get("fields", {})
    for field_name, confirmed in fields.items():
        session.confirm_field(field_name, confirmed)

    # Advance to submission
    session.update_step(WizardStep.SUBMITTED)
    session.updated_at = datetime.now(timezone.utc)

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "step": session.current_step.value,
            "message": "Fields confirmed. Ready to submit."
        }
    }


@router.post("/wizard/{session_id}/submit")
async def submit_wizard_application(
    session_id: str,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 4: Final submission. Creates application, runs validation, returns reference ID."""
    state = get_state()
    wizard_mgr = state.get("wizard_manager")
    validation_agent = state.get("validation_agent")
    auth = state.get("auth")
    db = state.get("database")

    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    # ── Create application record ──
    app_id = str(uuid.uuid4())
    wizard_mgr.set_application_id(session_id, app_id)

    # ── Persist to DB (Phase 3) ──
    ref_id = ""
    status = "submitted"
    if db:
        try:
            with db.session_scope() as sess:
                db_app = Application(
                    id=app_id,
                    service_id=session.service_id,
                    status="submitted",
                    reference_id="",
                    user_id=user_id,
                )
                sess.add(db_app)
                sess.flush()

                # Emit audit event
                db.log_event(
                    event_type="wizard_submitted",
                    user_id=user_id,
                    application_id=app_id,
                    details={"wizard_session": session_id, "service": session.service_id},
                    stage="submission",
                )
        except Exception as e:
            logger.warning(f"Failed to persist submit to DB: {e}")

    # ── Validation agent ──
    if validation_agent:
        try:
            app_data = {
                "application_id": app_id,
                "service_id": session.service_id,
                "required_documents": ["national_id"],
                "documents": [{"docType": "national_id", "url": session.id_file_url}],
                "extracted_fields": session.id_extraction.raw_fields if session.id_extraction else {},
            }
            report = validation_agent.validate_application(app_data)
            if report.result.value == "pass":
                status = "complete"
            elif report.result.value == "exception":
                status = "needs_human_review"
            else:
                status = "incomplete"
        except Exception as e:
            logger.warning(f"Validation failed: {e}")
            status = "incomplete"

    # ── Generate reference ID ──
    prefix_map = {
        "basic_registration": "BR",
        "premium_crossborder": "PCB",
        "mobility_rental": "MR",
    }
    prefix = prefix_map.get(session.service_id, "APP")
    ref_id = f"{prefix}-{datetime.now(timezone.utc).strftime('%Y')}-{str(uuid.uuid4())[:8].upper()}"

    # ── Finalize ──
    wizard_mgr.submit_wizard(session_id, ref_id, status)

    return {
        "success": True,
        "data": {
            "application_id": app_id,
            "reference_id": ref_id,
            "status": status,
            "service_id": session.service_id,
            "processing_time": "2-3 business days" if status == "complete" else "Pending review",
        },
        "message": "Application submitted successfully",
    }
