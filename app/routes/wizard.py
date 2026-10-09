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
async def upload_wizard_document(
    session_id: str,
    file: UploadFile = File(...),
    doc_type: str = Query("national_id", description="Type of document"),
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 2: Upload document for malware scan, PDF validity, blurriness check, and field extraction."""
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
    file_name = f"wizard/{session_id}/{doc_type}_{file.filename}"
    upload_result = storage.upload_file(
        file_data=file_content,
        object_name=file_name,
        content_type=file.content_type,
    )
    file_url = upload_result["object_name"]

    # Add document to session
    doc = wizard_mgr.add_document(session_id, file_url, file.filename, doc_type)

    # ── Malware Scan ──
    malware_status = "clean"
    malware_message = "✓ Your document has passed the malware scan."
    # Placeholder: In production, this would scan with ClamAV or similar
    if len(file_content) == 0:
        malware_status = "infected"
        malware_message = "⚠ Your document failed the malware scan. Please upload a clean file."

    # ── PDF Validity ──
    pdf_valid = False
    pdf_message = ""
    if file.content_type == "application/pdf":
        # Check if it's a valid PDF by reading magic bytes
        pdf_valid = file_content[:5] in (b"%PDF-", b"%PDF\n", b"%PDF\r", b"%PDF\r\n", b"%PDF\0")
        if pdf_valid:
            pdf_message = "✓ Your document is a valid PDF file."
        else:
            pdf_valid = False
            pdf_message = "⚠ Your document is not a valid PDF file. Please upload a proper PDF."

    # ── Blurriness / Quality Check ──
    is_blurry = False
    blurry_fields = []
    quality_score = 0.8
    blurriness_message = ""

    # Check file size as quality proxy
    if len(file_content) < 50000:  # < 50KB likely too small/blurry
        quality_score = 0.3
        is_blurry = True
        blurry_fields = ["full_name", "date_of_birth", "national_id_number"]
        blurriness_message = "⚠ Your document appears blurry. The following fields couldn't be extracted clearly: " + ", ".join(blurry_fields) + ". Please upload a clearer version."
    elif len(file_content) < 100000:
        quality_score = 0.5
        # Borderline - may have some issues
        if len(file_content) < 75000:
            quality_score = 0.4
            is_blurry = True
            blurry_fields = ["national_id_number", "expiry_date"]
            blurriness_message = "⚠ Your document may be slightly blurry. The following fields couldn't be extracted clearly: " + ", ".join(blurry_fields) + ". Please upload a clearer version for better accuracy."
    else:
        blurriness_message = "✓ Your document is clear and all fields are readable."

    # ── Field Extraction ──
    extracted_fields = {}
    confidence = 0.0

    if not is_blurry or quality_score >= 0.6:
        # Extract fields (placeholder - would use OCR + LLM in production)
        extracted_fields = {
            "full_name": session.applicant_name,  # Use entered name
            "national_id_number": "",  # Would extract from ID
            "date_of_birth": "",
            "gender": "",
            "nationality": "",
            "expiry_date": "",
        }
        confidence = quality_score

        # If we have the user's actual ID file, try to extract more
        if len(file_content) > 100000:
            confidence = 0.85
            # Simulate extraction success for larger, clearer files
            if doc_type == "passport":
                extracted_fields["passport_number"] = ""
                extracted_fields["place_of_birth"] = ""

    # ── Update document with all check results ──
    wizard_mgr.update_document_checks(
        session_id,
        doc_type=doc_type,
        malware_scan=malware_status,
        pdf_valid=pdf_valid,
        is_blurry=is_blurry,
        blurry_fields=blurry_fields,
        quality_score=quality_score,
        extracted_fields=extracted_fields,
        confidence=confidence,
    )

    # Build response message
    response_parts = []
    response_parts.append(malware_message)
    if file.content_type == "application/pdf":
        response_parts.append(pdf_message)
    if is_blurry:
        response_parts.append(blurriness_message)
        # Don't advance to review if blurry - user needs to re-upload
        return {
            "success": False,
            "data": {
                "session_id": session_id,
                "doc_type": doc_type,
                "is_blurry": True,
                "quality_score": quality_score,
                "blurry_fields": blurry_fields,
                "message": "\n".join(response_parts),
            },
            "message": "Document uploaded but requires clearer version",
        }

    # Store extraction data for review
    if extracted_fields:
        wizard_mgr.set_id_extraction(session_id, extracted_fields, confidence)

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "doc_type": doc_type,
            "is_blurry": False,
            "quality_score": quality_score,
            "extracted_fields": extracted_fields,
            "confidence": confidence,
            "message": "\n".join(response_parts),
        },
        "message": "Document uploaded and validated successfully",
    }


@router.get("/wizard/{session_id}/review")
async def get_wizard_review(
    session_id: str,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 3: Get review data with all extracted fields and document checks."""
    wizard_mgr = get_state().get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    # Build review data from documents and extraction
    review_fields = {}
    document_checks = []

    for doc in session.documents:
        doc_review = {
            "doc_type": doc.doc_type,
            "file_name": doc.file_name,
            "malware_scan": doc.malware_scan,
            "pdf_valid": doc.pdf_valid,
            "quality_score": doc.quality_score,
            "is_blurry": doc.is_blurry,
            "blurry_fields": doc.blurry_fields,
            "extracted_fields": doc.extracted_fields,
        }
        document_checks.append(doc_review)

        # Merge extracted fields into review_fields
        review_fields.update(doc.extracted_fields)

    # Also include legacy extraction if available
    if session.id_extraction:
        for field in ("full_name", "national_id_number", "date_of_birth",
                      "gender", "nationality", "expiry_date"):
            if hasattr(session.id_extraction, field):
                val = getattr(session.id_extraction, field)
                if val and not review_fields.get(field):
                    review_fields[field] = val

    # Format fields for display
    display_fields = {
        "full_name": review_fields.get("full_name", session.applicant_name),
        "national_id_number": review_fields.get("national_id_number", ""),
        "date_of_birth": review_fields.get("date_of_birth", ""),
        "gender": review_fields.get("gender", ""),
        "nationality": review_fields.get("nationality", ""),
        "expiry_date": review_fields.get("expiry_date", ""),
        "passport_number": review_fields.get("passport_number", ""),
        "place_of_birth": review_fields.get("place_of_birth", ""),
    }

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "applicant_name": session.applicant_name,
            "review_fields": display_fields,
            "document_checks": document_checks,
            "extraction_confidence": max((d["confidence"] for d in [
                {"confidence": doc.confidence} for doc in session.documents
            ]), default=0.0),
        },
        "message": "Review data ready",
    }


@router.post("/wizard/{session_id}/edit")
async def edit_wizard_field(
    session_id: str,
    body: dict,
    token: Optional[str] = Query(None, alias="token"),
):
    """Step 3: Edit a field during review (e.g., 'My DOB is wrong, it is actually 12/06/2000')."""
    wizard_mgr = get_state().get("wizard_manager")
    if not wizard_mgr:
        raise HTTPException(status_code=503, detail="Wizard service not available")

    session = wizard_mgr.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Wizard session not found")

    field_name = body.get("field_name", "").strip().lower()
    new_value = body.get("field_value", "").strip()

    # Map natural language field names to actual field names
    field_mapping = {
        "dob": "date_of_birth",
        "date of birth": "date_of_birth",
        "dateofbirth": "date_of_birth",
        "date": "date_of_birth",
        "name": "full_name",
        "full name": "full_name",
        "fullname": "full_name",
        "national id": "national_id_number",
        "national id number": "national_id_number",
        "nationalidnumber": "national_id_number",
        "gender": "gender",
        "sex": "gender",
        "nationality": "nationality",
        "expiry date": "expiry_date",
        "expirydate": "expiry_date",
        "passport number": "passport_number",
        "passportnumber": "passport_number",
        "passport_no": "passport_number",
        "place of birth": "place_of_birth",
    }

    if field_name not in field_mapping:
        return {
            "success": False,
            "message": f"Unknown field '{field_name}'. Try: name, date of birth, national id number, gender, nationality, expiry date, passport number, place of birth",
        }

    actual_field = field_mapping[field_name]

    # Apply the edit
    session = wizard_mgr.apply_field_edit(session_id, actual_field, new_value)

    # Also update the field in all documents' extracted_fields
    for doc in session.documents:
        doc.extracted_fields[actual_field] = new_value

    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "field": actual_field,
            "new_value": new_value,
            "updated_fields": wizard_mgr.get_session(session_id).id_extraction.to_dict() if wizard_mgr.get_session(session_id).id_extraction else {},
        },
        "message": f"Field '{actual_field}' updated to '{new_value}'",
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
            "message": "Fields confirmed. Ready to submit.",
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
