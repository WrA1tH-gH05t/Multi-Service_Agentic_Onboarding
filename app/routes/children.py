"""Child Dependent Profile and Guardian Consent API routes.

Compliant with:
- UAE Federal Decree-Law No. 25 of 2025 (Civil Transactions Law, Art. 84 - Age of Majority at 18)
- UAE Federal Decree-Law No. 26 of 2025 (Child Digital Safety, Art. 7 - Explicit Parental Consent under 13)
- UAE Federal Decree-Law No. 45 of 2021 (Protection of Personal Data - PDPL)
"""

import re
import hashlib
import logging
from datetime import datetime, timezone, date
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Query, Request, Body
from pydantic import BaseModel, Field, field_validator

from services.database import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/children", tags=["children"])


def get_state():
    """Retrieve application state dictionary from the main module."""
    from app.main import app_state
    return app_state


def _require_parent_user(request: Request, token: Optional[str] = None):
    """Authenticate the caller and verify they are a signed-in adult user."""
    state = get_state()
    auth = state.get("auth")
    db = state.get("database")

    # Extract token from query or Authorization header
    actual_token = token
    if not actual_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            actual_token = auth_header[7:].strip()

    if not actual_token or not auth:
        raise HTTPException(status_code=401, detail="Authentication required. Please sign in.")

    user = auth.validate_token(actual_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session token. Please sign in again.")

    # Adult age eligibility check: Federal Decree-Law No. 25 of 2025, Art. 84
    # Adults must be at least 18 Gregorian years old to act as parent/guardian
    if db:
        try:
            with db.session_scope() as session:
                db_user = session.query(User).filter_by(user_id=user.user_id).first()
                if db_user and db_user.birthday:
                    try:
                        dob = date.fromisoformat(str(db_user.birthday).strip())
                        today = date.today()
                        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                        if age < 18:
                            raise HTTPException(
                                status_code=403,
                                detail=f"Guardian eligibility requirement: Account holder must be at least 18 Gregorian years of age to manage child dependent profiles (current age: {age})."
                            )
                    except ValueError:
                        pass
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not verify guardian birth date: {e}")

    return user


# ── Pydantic Request Models ──────────────────────────────────────────────────

class CreateChildProfileRequest(BaseModel):
    full_name: str = Field(..., description="Full legal name of the child")
    date_of_birth: str = Field(..., description="Child date of birth in ISO format YYYY-MM-DD")
    relationship_type: str = Field(..., description="Relationship: parent, legal_guardian, or caregiver")
    nationality: Optional[str] = Field(None, description="Nationality of the child")
    notes: Optional[str] = Field(None, description="Optional profile notes")
    guardian_confirms_authority: bool = Field(False, description="Guardian confirmation of legal authority")
    guardian_consents_to_data_processing: bool = Field(False, description="Explicit consent under Art. 7 for under-13 data")
    guardian_verification_reference: Optional[str] = Field(None, description="Reference to birth certificate or guardianship decree")

    @field_validator("full_name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Child full name is required.")
        v_clean = v.strip()
        if len(v_clean) < 2:
            raise ValueError("Child full name must be at least 2 characters.")
        if not re.match(r"^[A-Za-zÀ-ÖØ-öø-ÿ\u00C0-\u024F\s'-]+$", v_clean):
            raise ValueError("Child full name contains invalid characters.")
        return v_clean

    @field_validator("date_of_birth")
    @classmethod
    def validate_dob(cls, v: str) -> str:
        try:
            dob = date.fromisoformat(v.strip())
        except ValueError:
            raise ValueError("Invalid date of birth format. Use YYYY-MM-DD.")
        today = date.today()
        if dob >= today:
            raise ValueError("Child date of birth must be in the past.")
        age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        if age >= 18:
            raise ValueError("Child profile is for minors under 18 years of age. Adults must register an independent account.")
        return v.strip()

    @field_validator("relationship_type")
    @classmethod
    def validate_relationship(cls, v: str) -> str:
        allowed = {"parent", "legal_guardian", "caregiver", "authorized_caregiver"}
        if v.strip().lower() not in allowed:
            raise ValueError(f"Relationship type must be one of: {', '.join(sorted(allowed))}")
        return v.strip().lower()


class UpdateChildProfileRequest(BaseModel):
    full_name: Optional[str] = None
    date_of_birth: Optional[str] = None
    relationship_type: Optional[str] = None
    nationality: Optional[str] = None
    notes: Optional[str] = None
    profile_status: Optional[str] = None


class GuardianConsentRequest(BaseModel):
    child_profile_id: str
    consent_purpose: str = "child_data_processing"
    privacy_policy_version: str = "v1.1"
    consent_version: str = "v1.1"
    verification_method: str = "checkbox_declaration"
    declaration_text: Optional[str] = None
    accepted: bool = False


class ApplicationReviewConsentRequest(BaseModel):
    application_id: str
    service_id: str
    child_profile_id: Optional[str] = None
    receiving_agency_id: Optional[str] = None
    policy_version: str = "v1.1"
    consent_text_version: str = "v1.1"
    declaration_text: Optional[str] = None
    accepted: bool = False  # False means explicitly declined


# ── Route Handlers ───────────────────────────────────────────────────────────

@router.get("/policy-versions")
async def get_policy_versions():
    """Return currently active draft legal document versions and filenames."""
    state = get_state()
    db = state.get("database")
    versions = {
        "terms_and_conditions": {
            "version": "1.1",
            "status": "DRAFT — PENDING LEGAL APPROVAL",
            "pdf_filename": "Docintake_Terms_and_Conditions_v1.1_DRAFT.pdf",
            "jurisdiction": "United Arab Emirates",
            "effective_date": "Pending Legal Approval",
        },
        "privacy_policy": {
            "version": "1.1",
            "status": "DRAFT — PENDING LEGAL APPROVAL",
            "pdf_filename": "Docintake_Privacy_Policy_v1.1_DRAFT.pdf",
            "jurisdiction": "United Arab Emirates",
            "effective_date": "Pending Legal Approval",
        }
    }
    return {"success": True, "data": versions}


@router.post("/profiles")
async def create_child_profile(
    req: CreateChildProfileRequest,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Create a new child dependent profile linked to the authenticated parent/guardian."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    # 1. Require explicit confirmation of parental / guardian authority
    if not req.guardian_confirms_authority:
        raise HTTPException(
            status_code=400,
            detail="You must confirm that you are the parent or legally authorized caregiver/guardian of this child."
        )

    # 2. Check age category
    dob = date.fromisoformat(req.date_of_birth)
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    # Article 7 of Federal Decree-Law No. 26 of 2025: Explicit parental consent required BEFORE
    # collecting, processing or storing personal data of children under 13 years old
    if age < 13 and not req.guardian_consents_to_data_processing:
        raise HTTPException(
            status_code=400,
            detail="Under Article 7 of UAE Federal Decree-Law No. 26 of 2025 (Child Digital Safety), explicit parental/caregiver consent is required before collecting or processing personal information of children under 13."
        )

    # 3. Create the child profile in DB
    profile = db.create_child_profile(
        parent_user_id=user.user_id,
        full_name=req.full_name,
        date_of_birth=req.date_of_birth,
        relationship_type=req.relationship_type,
        nationality=req.nationality,
        notes=req.notes,
        guardian_verification_reference=req.guardian_verification_reference,
    )

    # 4. Record verifiable guardian consent event
    client_ip = request.client.host if request.client else None
    if age < 13 or req.guardian_consents_to_data_processing:
        consent_text = (
            f"I, {user.username} ({user.user_id}), as parent/authorized guardian, "
            f"explicitly consent to the collection and processing of personal data for child profile "
            f"{profile['profile_id']} ({req.full_name}) for Docintake onboarding intake and processing, "
            f"in accordance with UAE Federal Decree-Law No. 26 of 2025 Article 7 and Docintake Privacy Policy v1.1."
        )
        text_hash = hashlib.sha256(consent_text.encode("utf-8")).hexdigest()
        db.record_guardian_consent(
            guardian_user_id=user.user_id,
            child_profile_id=profile["profile_id"],
            consent_purpose="child_data_processing",
            policy_version="v1.1",
            consent_version="v1.1",
            verification_method="checkbox_declaration" if not req.guardian_verification_reference else "document_referenced",
            consent_text_hash=text_hash,
            status="accepted",
            ip_address=client_ip,
        )

    return {
        "success": True,
        "message": f"Child profile for {req.full_name} created successfully.",
        "data": profile
    }


@router.get("/profiles")
async def list_child_profiles(
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """List all child profiles belonging to the authenticated parent/guardian."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    profiles = db.get_child_profiles(user.user_id)
    return {"success": True, "count": len(profiles), "data": profiles}


@router.get("/profiles/{profile_id}")
async def get_child_profile(
    profile_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Retrieve details of a single child profile, verifying parent ownership."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    profile = db.get_child_profile(profile_id, parent_user_id=user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Child profile not found or access denied.")

    return {"success": True, "data": profile}


@router.put("/profiles/{profile_id}")
async def update_child_profile(
    profile_id: str,
    req: UpdateChildProfileRequest,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Update child profile details. Only the owning parent/guardian may update."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    existing = db.get_child_profile(profile_id, parent_user_id=user.user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Child profile not found or access denied.")

    updates = {k: v for k, v in req.dict().items() if v is not None}
    updated = db.update_child_profile(profile_id, parent_user_id=user.user_id, updates=updates)

    return {"success": True, "message": "Child profile updated successfully.", "data": updated}


@router.delete("/profiles/{profile_id}")
async def delete_child_profile(
    profile_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Soft delete a child profile and log an audit event."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    existing = db.get_child_profile(profile_id, parent_user_id=user.user_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Child profile not found or access denied.")

    deleted = db.delete_child_profile(profile_id, parent_user_id=user.user_id)
    return {"success": deleted, "message": "Child profile removed."}


@router.get("/profiles/{profile_id}/eligibility/{service_id}")
async def check_child_service_eligibility(
    profile_id: str,
    service_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Check child applicant service eligibility.
    
    Mobility / Rental is strictly blocked for child dependent profiles under 18.
    Basic Registration and Premium / Cross Border are available.
    """
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    result = db.check_service_eligibility_for_child(profile_id, user.user_id, service_id)
    return {"success": True, "data": result}


@router.post("/consent/guardian")
async def record_guardian_consent(
    req: GuardianConsentRequest,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Record explicit guardian consent for child data processing."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    profile = db.get_child_profile(req.child_profile_id, parent_user_id=user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Child profile not found or access denied.")

    if not req.accepted:
        raise HTTPException(status_code=400, detail="Consent must be affirmatively accepted.")

    text_hash = hashlib.sha256((req.declaration_text or "guardian_consent_declared").encode()).hexdigest()
    client_ip = request.client.host if request.client else None

    consent = db.record_guardian_consent(
        guardian_user_id=user.user_id,
        child_profile_id=req.child_profile_id,
        consent_purpose=req.consent_purpose,
        policy_version=req.privacy_policy_version,
        consent_version=req.consent_version,
        verification_method=req.verification_method,
        consent_text_hash=text_hash,
        status="accepted",
        ip_address=client_ip,
    )
    return {"success": True, "message": "Guardian consent recorded successfully.", "data": consent}


@router.post("/consent/guardian/{consent_id}/withdraw")
async def withdraw_guardian_consent(
    consent_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Continuously accessible mechanism for straightforward consent withdrawal under Art. 7."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    res = db.withdraw_guardian_consent(consent_id, guardian_user_id=user.user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Consent record not found or access denied.")

    return {
        "success": True,
        "message": "Guardian consent has been withdrawn. Processing for this consent scope is stopped.",
        "data": res
    }


@router.post("/consent/application-review")
async def record_application_review_consent(
    req: ApplicationReviewConsentRequest,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Record application-specific document review consent (Accept or Decline)."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    # Verify application ownership
    app = db.get_application(req.application_id)
    if not app:
        # Check if this is an active wizard session or initialize draft application for guardian's child
        mgr = state.get("wizard_mgr") or state.get("wizard")
        wiz_session = mgr.get_session(req.application_id) if mgr else None
        if wiz_session and (wiz_session.user_id == user.user_id):
            db.create_application(
                application_id=req.application_id,
                user_id=user.user_id,
                service_id=wiz_session.service_id,
                applicant_name=wiz_session.applicant_name or "Child Applicant",
                child_profile_id=req.child_profile_id or getattr(wiz_session, "child_profile_id", None),
                applicant_type=getattr(wiz_session, "applicant_type", "child_dependent"),
                status="draft"
            )
            app = db.get_application(req.application_id)
        elif req.child_profile_id:
            child_p = db.get_child_profile(req.child_profile_id, parent_user_id=user.user_id)
            if child_p:
                child_name = child_p.get("full_name") if isinstance(child_p, dict) else getattr(child_p, "full_name", "Child Applicant")
                db.create_application(
                    application_id=req.application_id,
                    user_id=user.user_id,
                    service_id=req.service_id,
                    applicant_name=child_name,
                    child_profile_id=req.child_profile_id,
                    applicant_type="child_dependent",
                    status="draft"
                )
                app = db.get_application(req.application_id)

    if not app:
        raise HTTPException(status_code=404, detail="Application not found.")

    if app.get("user_id") != user.user_id:
        raise HTTPException(status_code=403, detail="Access denied: You do not own this application.")

    # Agency mapping if not supplied
    agency_map = {
        "basic_registration": "identity_authority",
        "premium_crossborder": "crossborder_authority",
        "mobility_rental": "mobility_rta",
    }
    designated_agency = req.receiving_agency_id or agency_map.get(req.service_id, "identity_authority")

    status = "accepted" if req.accepted else "declined"
    text_hash = hashlib.sha256((req.declaration_text or f"application_review_consent_{status}").encode()).hexdigest()
    client_ip = request.client.host if request.client else None

    consent = db.record_child_application_review_consent(
        guardian_user_id=user.user_id,
        application_id=req.application_id,
        service_id=req.service_id,
        policy_version=req.policy_version,
        consent_text_version=req.consent_text_version,
        child_profile_id=req.child_profile_id or app.get("child_profile_id"),
        receiving_agency_id=designated_agency,
        consent_text_hash=text_hash,
        status=status,
        ip_address=client_ip,
    )

    # If declined: application cannot proceed to government review, update application status
    if not req.accepted:
        db.update_application(req.application_id, status="consent_declined")
        return {
            "success": True,
            "status": "declined",
            "message": "Application review consent declined. Documents will not be made available to government reviewers.",
            "data": consent
        }

    return {
        "success": True,
        "status": "accepted",
        "message": f"Application review consent recorded. Application authorized for inspection by {designated_agency}.",
        "data": consent
    }


@router.post("/consent/application-review/{consent_id}/withdraw")
async def withdraw_application_review_consent(
    consent_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Withdraw application-specific document review consent."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    res = db.withdraw_child_application_review_consent(consent_id, guardian_user_id=user.user_id)
    if not res:
        raise HTTPException(status_code=404, detail="Review consent record not found or access denied.")

    # Update application status
    if res.get("application_id"):
        db.update_application(res["application_id"], status="consent_withdrawn")

    return {
        "success": True,
        "message": "Application review consent withdrawn. Reviewer access revoked.",
        "data": res
    }


@router.get("/audit/{profile_id}")
async def get_child_audit_trail(
    profile_id: str,
    request: Request,
    token: Optional[str] = Query(None, alias="token"),
):
    """Get immutable audit events for a child profile."""
    user = _require_parent_user(request, token)
    state = get_state()
    db = state.get("database")
    if not db:
        raise HTTPException(status_code=503, detail="Database service unavailable.")

    profile = db.get_child_profile(profile_id, parent_user_id=user.user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Child profile not found or access denied.")

    events = db.get_child_audit_events(child_profile_id=profile_id)
    return {"success": True, "count": len(events), "data": events}
