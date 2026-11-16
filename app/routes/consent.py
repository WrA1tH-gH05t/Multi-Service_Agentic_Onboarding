"""Consent routes — Application-specific Document Review Consent (Agree, Decline, Withdraw) and Agency Routing."""

import re
import secrets
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Body

from app.schemas import DocumentReviewConsentRequest
from services.security import DocumentAccessControl

router = APIRouter()
logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

def _require_user(state, token: Optional[str]):
    if not token:
        raise HTTPException(status_code=401, detail="Authentication token required.")
    auth = state.get("auth")
    if not auth:
        raise HTTPException(status_code=503, detail="Auth service unavailable.")
    user = auth.validate_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return user


AGENCY_SERVICE_MAPPING = {
    "basic_registration": {
        "agency_id": "identity_authority",
        "agency_name": "Identity & Onboarding Review Authority",
        "description": "Authorized reviewing body for standard identity document inspection."
    },
    "premium_crossborder": {
        "agency_id": "crossborder_authority",
        "agency_name": "Cross-Border Inspection Authority",
        "description": "Authorized reviewing body for dual-document cross-border assessment."
    },
    "mobility_rental": {
        "agency_id": "mobility_rta",
        "agency_name": "Roads & Transport Authority (RTA) Review Branch",
        "description": "Designated mobility authority for driving licence verification."
    }
}


@router.get("/applications/{application_id}/consent-info")
async def get_consent_info(application_id: str, token: Optional[str] = Query(None, alias="token")):
    """Get the application-specific consent disclosure details and designated reviewing agency."""
    state = get_state()
    user = _require_user(state, token)
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.session_scope() as session:
        from services.database import Application, ApplicationConsent, Document
        app = session.query(Application).filter_by(application_id=application_id, user_id=user.user_id).first()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found or unauthorized.")

        agency_info = AGENCY_SERVICE_MAPPING.get(app.service_id, {
            "agency_id": "general_authority",
            "agency_name": "Designated Onboarding Review Authority",
            "description": "Authorized service review team."
        })

        consent = session.query(ApplicationConsent).filter_by(application_id=application_id).order_by(ApplicationConsent.created_at.desc()).first()
        docs = session.query(Document).filter_by(application_id=application_id).all()

        return {
            "success": True,
            "data": {
                "application_id": app.application_id,
                "service_id": app.service_id,
                "applicant_name": app.applicant_name,
                "designated_agency_id": agency_info["agency_id"],
                "designated_agency_name": agency_info["agency_name"],
                "designated_agency_description": agency_info["description"],
                "consent_screen_title": "DOCUMENT REVIEW CONSENT",
                "consent_text": (
                    "Your application is ready for review by the designated authorized reviewing body.\n\n"
                    f"To proceed, Docintake needs to route your application and make the documents you submitted available to the {agency_info['agency_name']} responsible for reviewing this service.\n\n"
                    "By providing your consent, you authorize Docintake to make the documents associated with this application available to the designated authorized reviewers solely for purposes of document inspection, identity-document assessment, verification of submitted information, resolving discrepancies, and processing your application.\n\n"
                    "Your documents will remain within Docintake's approved on-premise infrastructure. Authorized reviewers will access them through the designated secure application interface.\n\n"
                    "Your documents will not be made available to application developers or unrelated personnel.\n\n"
                    "The processing and handling of your information will be subject to the Docintake Privacy Policy and applicable UAE legal requirements."
                ),
                "checkbox_wording": (
                    f"I authorize Docintake to make the documents submitted with this specific application available to the designated authorized {agency_info['agency_name']} reviewers for document inspection and application-processing purposes, in accordance with the Docintake Privacy Policy and applicable terms."
                ),
                "current_consent_status": consent.status if consent else "pending",
                "can_withdraw": consent.status == "agreed" if consent else False,
                "document_count": len(docs),
            }
        }


@router.post("/applications/{application_id}/consent")
async def submit_application_consent(
    application_id: str,
    req: DocumentReviewConsentRequest,
    token: Optional[str] = Query(None, alias="token")
):
    """Process application-specific Document Review Consent (Agree or Decline)."""
    state = get_state()
    user = _require_user(state, token)
    db = state.get("database")
    storage = state.get("storage")
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.session_scope() as session:
        from services.database import Application, ApplicationConsent, Document, AuditLog
        app = session.query(Application).filter_by(application_id=application_id, user_id=user.user_id).first()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found or unauthorized.")

        if app.status in ("rejected", "cancelled", "rejected_consent_declined", "cancelled_consent_withdrawn"):
            raise HTTPException(status_code=409, detail="This application has already been closed and cannot be modified.")

        agency_info = AGENCY_SERVICE_MAPPING.get(app.service_id, {
            "agency_id": "general_authority",
            "agency_name": "Designated Onboarding Review Authority",
        })

        docs = session.query(Document).filter_by(application_id=application_id).all()
        doc_ids = [d.document_id for d in docs]

        # ── CASE 1: USER AGREES AND GIVES CONSENT ──
        if req.agreed:
            consent_record = ApplicationConsent(
                consent_id=f"cons_{secrets.token_hex(8)}",
                application_id=application_id,
                user_id=user.user_id,
                service_id=app.service_id,
                designated_agency=agency_info["agency_id"],
                status="agreed",
                consent_text_version=req.consent_version or "1.0",
                consent_text=f"Authorized document inspection by {agency_info['agency_name']}",
                staged_documents_scope=doc_ids,
                agreed_at=datetime.now(timezone.utc),
            )
            session.add(consent_record)

            # Route application to agency review queue
            app.status = "under_agency_review"
            app.updated_at = datetime.now(timezone.utc)

            # Audit log
            session.add(AuditLog(
                log_id=f"audit_{secrets.token_hex(8)}",
                user_id=user.user_id,
                application_id=application_id,
                event_type="document_review_consent_agreed",
                details={
                    "service_id": app.service_id,
                    "designated_agency": agency_info["agency_id"],
                    "document_scope": doc_ids,
                    "consent_version": req.consent_version or "1.0",
                }
            ))

            return {
                "success": True,
                "message": f"Consent granted. Application successfully routed to {agency_info['agency_name']}.",
                "data": {
                    "application_id": application_id,
                    "status": "under_agency_review",
                    "designated_agency": agency_info["agency_id"],
                    "agency_name": agency_info["agency_name"],
                    "agreed_at": consent_record.agreed_at.isoformat(),
                }
            }

        # ── CASE 2: USER DECLINES CONSENT ──
        else:
            consent_record = ApplicationConsent(
                consent_id=f"cons_{secrets.token_hex(8)}",
                application_id=application_id,
                user_id=user.user_id,
                service_id=app.service_id,
                designated_agency=agency_info["agency_id"],
                status="declined",
                consent_text_version=req.consent_version or "1.0",
                consent_text="Applicant declined document review consent.",
                staged_documents_scope=doc_ids,
                declined_at=datetime.now(timezone.utc),
            )
            session.add(consent_record)

            # Close application (status column max length 20: "rejected")
            app.status = "rejected"
            app.updated_at = datetime.now(timezone.utc)

            # PURGE STAGED DOCUMENT BINARIES FROM STORAGE & MEMORY
            purged_objects = []
            for d in docs:
                if d.object_name and storage:
                    try:
                        storage.delete_file(d.object_name)
                        purged_objects.append(d.object_name)
                    except Exception as e:
                        logger.warning(f"Error purging staged document binary {d.object_name}: {e}")
                # Clear extracted sensitive personal fields
                d.extracted_fields = {"_purged": "Staged document contents purged following consent refusal."}
                d.status = "purged"

            # Audit log (immutable minimal compliance record)
            session.add(AuditLog(
                log_id=f"audit_{secrets.token_hex(8)}",
                user_id=user.user_id,
                application_id=application_id,
                event_type="document_review_consent_declined",
                details={
                    "service_id": app.service_id,
                    "designated_agency": agency_info["agency_id"],
                    "purged_documents_count": len(docs),
                    "action": "application_closed_binaries_purged"
                }
            ))

            return {
                "success": True,
                "message": "Consent declined. Application closed and staged document binaries purged from system storage.",
                "data": {
                    "application_id": application_id,
                    "status": "rejected",
                    "purged_documents_count": len(docs),
                }
            }


@router.post("/applications/{application_id}/withdraw-consent")
async def withdraw_application_consent(
    application_id: str,
    withdrawal_reason: Optional[str] = Body(None, embed=True),
    token: Optional[str] = Query(None, alias="token")
):
    """Formally withdraw previously given Document Review Consent under UAE legal data protection standards."""
    state = get_state()
    user = _require_user(state, token)
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    with db.session_scope() as session:
        from services.database import Application, ApplicationConsent, AuditLog
        app = session.query(Application).filter_by(application_id=application_id, user_id=user.user_id).first()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found or unauthorized.")

        consent = session.query(ApplicationConsent).filter_by(application_id=application_id, status="agreed").first()
        if not consent:
            raise HTTPException(status_code=400, detail="No active consent found to withdraw.")

        # Update consent record
        consent.status = "withdrawn"
        consent.withdrawn_at = datetime.now(timezone.utc)
        consent.withdrawal_reason = withdrawal_reason or "Applicant exercised legal right of consent withdrawal."

        # Halt processing and close application (status max length 20: "cancelled")
        app.status = "cancelled"
        app.updated_at = datetime.now(timezone.utc)

        # Audit log
        session.add(AuditLog(
            log_id=f"audit_{secrets.token_hex(8)}",
            user_id=user.user_id,
            application_id=application_id,
            event_type="document_review_consent_withdrawn",
            details={
                "consent_id": consent.consent_id,
                "service_id": app.service_id,
                "designated_agency": consent.designated_agency,
                "withdrawal_reason": consent.withdrawal_reason,
            }
        ))

        return {
            "success": True,
            "message": "Consent has been withdrawn. Application processing halted and reviewer access revoked.",
            "data": {
                "application_id": application_id,
                "status": "cancelled",
                "withdrawn_at": consent.withdrawn_at.isoformat(),
            }
        }


# ──────────────────────────────────────────────────────────────────────
# Government Agency Inspection Portal Endpoints
# ──────────────────────────────────────────────────────────────────────

@router.get("/agency/applications")
async def list_agency_assigned_applications(token: Optional[str] = Query(None, alias="token")):
    """List applications available for review restricted to the authenticated government reviewer's assigned agency."""
    state = get_state()
    user = _require_user(state, token)
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable")

    role_name, assigned_agency = DocumentAccessControl.get_user_role(db, user.user_id)

    if role_name != "government_reviewer":
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: You do not have an authorized government agency reviewer role."
        )

    if not assigned_agency:
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: No government agency is mapped to your reviewer account."
        )

    with db.session_scope() as session:
        from services.database import Application, ApplicationConsent, Document
        # Find applications whose active consent is designated to this reviewer's agency
        consents = session.query(ApplicationConsent).filter_by(designated_agency=assigned_agency, status="agreed").all()
        app_ids = [c.application_id for c in consents]

        apps = session.query(Application).filter(Application.application_id.in_(app_ids)).all()
        result = []
        for a in apps:
            docs = session.query(Document).filter_by(application_id=a.application_id).all()
            result.append({
                "application_id": a.application_id,
                "applicant_name": a.applicant_name,
                "service_id": a.service_id,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "documents": [{
                    "document_id": d.document_id,
                    "document_type": d.document_type,
                    "filename": d.filename,
                    "file_size": d.file_size,
                    "uploaded_at": d.uploaded_at.isoformat() if d.uploaded_at else None,
                } for d in docs],
            })

        return {
            "success": True,
            "agency_id": assigned_agency,
            "data": result,
            "total": len(result),
        }
