"""Application management routes — create, list, retrieve, and cancel onboarding applications."""

import re
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import ChatMessage, ChatResponse

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared application state dict from app.main."""
    from app.main import app_state
    return app_state

# In-memory store for created applications (application_id -> data)
_application_store: dict = {}

@router.post("/applications")
async def create_application(
    service_id: str = Query(...),
    applicant_name: str = Query(...),
    token: Optional[str] = Query(None, alias="token"),
    child_profile_id: Optional[str] = Query(None),
    applicant_type: Optional[str] = Query("adult"),
):
    """Create a new onboarding application and initialise all downstream tracking."""
    state = get_state()
    db = state.get("database")
    repo = state.get("repository")

    # Auth check
    user_id = None
    if token:
        auth = state.get("auth")
        if auth:
            user = auth.validate_token(token)
            if not user:
                raise HTTPException(status_code=401, detail="Invalid or expired token. Please sign in again.")
            user_id = user.user_id

    # Enforce Child Dependent Profile Service Eligibility
    if child_profile_id:
        if not user_id or user_id == "anonymous":
            raise HTTPException(status_code=401, detail="Sign-in is required to submit an application on behalf of a child profile.")
        if db:
            eligibility = db.check_service_eligibility_for_child(child_profile_id, user_id, service_id)
            if not eligibility.get("eligible"):
                raise HTTPException(
                    status_code=400,
                    detail=eligibility.get("reason", f"Service '{service_id}' is not available for this child dependent profile.")
                )
            child = db.get_child_profile(child_profile_id, user_id)
            if child and not applicant_name:
                applicant_name = child.get("full_name")
        applicant_type = "child_dependent"

    # Also directly reject mobility_rental for child dependent applicants
    if service_id == "mobility_rental" and (child_profile_id or applicant_type == "child_dependent"):
        raise HTTPException(
            status_code=400,
            detail="Mobility / Rental is unavailable for dependent profiles under 18 because applicants must meet the minimum driving-licence age requirements. (Note: This service remains active for eligible adult applicants)."
        )

    catalog = state["catalog"]
    service = catalog.get_service(service_id)
    if not service or service.status.value == "coming_soon":
        raise HTTPException(status_code=400, detail=f"Service '{service_id}' not available")

    # Validate name
    if not applicant_name or not applicant_name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")
    
    if len(applicant_name.strip()) < 2:
        raise HTTPException(status_code=400, detail="Name must be at least 2 characters.")
    if not re.match(r'^[A-Za-zÀ-ÖØ-öø-ÿ\u00C0-\u024F]+(?: [A-Za-zÀ-ÖØ-öø-ÿ\u00C0-\u024F]+)*$', applicant_name.strip()):
        raise HTTPException(status_code=400, detail="Name can only contain letters and spaces.")

    # Collect user_id
    user_id = user_id or "anonymous"

    # Initialize CollectionAgent session (Phase 2)
    collection_agent = state.get("collection_agent")
    coll_session_id = None
    if collection_agent:
        coll_session_id = collection_agent.create_session(
            user_id=user_id,
            service_id=service_id,
            service_name=service.name,
            service_description=service.description,
            processing_time=service.processing_time,
            required_documents=service.required_documents,
            allowed_alternatives=service.allowed_alternatives,
        )

    # Phase 3 + WP8: Persist to database via repository layer
    app_id = None
    if repo:
        try:
            app_id = repo.create_application(
                user_id=user_id,
                service_id=service_id,
                applicant_name=applicant_name.strip(),
                required_documents=service.required_documents,
                collection_session_id=coll_session_id,
                child_profile_id=child_profile_id,
                applicant_type=applicant_type or "adult",
            )
        except Exception as e:
            logger.warning(f"Repository create_application failed ({e}), falling back to in-memory")
    
    if not app_id:
        app_id = f"app_{str(uuid.uuid4())[:8]}"

    # Also keep in-memory for backward compat
    _application_store[app_id] = {
        "service_id": service_id,
        "applicant_name": applicant_name.strip(),
        "required_documents": service.required_documents,
        "status": "incomplete",
        "user_id": user_id,
        "collection_session_id": coll_session_id,
        "child_profile_id": child_profile_id,
        "applicant_type": applicant_type,
    }

    return {
        "success": True,
        "data": {
            "id": app_id,
            "service_id": service_id,
            "applicant_name": applicant_name.strip(),
            "status": "incomplete",
            "required_documents": service.required_documents,
            "collection_session_id": coll_session_id,
            "child_profile_id": child_profile_id,
            "applicant_type": applicant_type,
        }
    }

@router.get("/applications")
async def list_applications(user_id: Optional[str] = None, token: Optional[str] = Query(None, alias="token")):
    """List all applications, optionally scoped to the authenticated user."""
    state = get_state()
    repo = state.get("repository")
    db = state.get("database")
    auth = state.get("auth")

    if token and auth and not user_id:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    # Try repository first
    if repo and user_id:
        try:
            apps = repo.list_user_applications(user_id)
            if apps:
                return {"data": {"applications": apps, "total": len(apps)}}
        except Exception as e:
            logger.warning(f"Failed to fetch from repository: {e}")

    # Direct DB query
    if db and user_id:
        try:
            with db.session_scope() as session:
                from services.database import Application
                db_apps = session.query(Application).filter_by(user_id=user_id).order_by(Application.created_at.desc()).all()
                res = []
                catalog = state.get("catalog")
                for a in db_apps:
                    svc_obj = catalog.get_service(a.service_id) if catalog else None
                    svc_name = svc_obj.name if svc_obj else (a.service_id or "General Application").replace("_", " ").title()
                    res.append({
                        "id": a.application_id,
                        "application_id": a.application_id,
                        "service_id": a.service_id,
                        "service_type": a.service_id,
                        "service_name": svc_name,
                        "applicant_name": a.applicant_name,
                        "child_profile_id": a.child_profile_id,
                        "applicant_type": a.applicant_type or ("child_dependent" if a.child_profile_id else "adult"),
                        "status": a.status,
                        "created_at": a.created_at.isoformat() if a.created_at else None,
                        "validation_result": a.validation_result or {},
                        "documents": [d.document_id for d in (a.documents or [])],
                    })
                return {"data": {"applications": res, "total": len(res)}}
        except Exception as e:
            logger.warning(f"Failed to query DB applications: {e}")

    # Fallback to in-memory store
    in_mem = []
    catalog = state.get("catalog")
    for app_id, a in _application_store.items():
        sid = a.get("service_id", "")
        svc_obj = catalog.get_service(sid) if catalog else None
        svc_name = svc_obj.name if svc_obj else sid.replace("_", " ").title()
        item = dict(a)
        item["id"] = app_id
        item["service_type"] = sid
        item["service_name"] = svc_name
        in_mem.append(item)
    return {"data": {"applications": in_mem, "total": len(in_mem)}}

@router.get("/user/applications")
async def get_user_applications(user_id: str = Query(...)):
    """Convenience alias for list_applications filtered to a specific user_id."""
    return await list_applications(user_id)

@router.get("/applications/{app_id}")
async def get_application(app_id: str, user_id: str = Query(...)):
    """Retrieve a single application's details, enforcing user ownership."""
    state = get_state()
    repo = state.get("repository")
    
    # Try repository first (WP8)
    if repo:
        try:
            app = repo.get_application(app_id, user_id)
            if app:
                return {"data": app}
        except Exception as e:
            logger.warning(f"Failed to fetch app {app_id} from repository: {e}")
    
    # Fallback to in-memory store
    if app_id in _application_store:
        return {"data": _application_store[app_id]}
    
    return {"error": "not_found", "message": f"Application not found: {app_id}"}


@router.delete("/applications/{application_id}")
@router.post("/applications/{application_id}/cancel")
async def cancel_application(
    application_id: str,
    token: Optional[str] = Query(None, alias="token"),
):
    """Cancel and permanently delete an application along with all its uploaded documents."""
    state = get_state()
    db = state.get("database")
    repo = state.get("repository")
    storage = state.get("storage")
    auth = state.get("auth")

    user_id = None
    if token and auth:
        user = auth.validate_token(token)
        if user:
            user_id = user.user_id

    if not db:
        raise HTTPException(status_code=503, detail="Database service not available")

    # If repo has get_application, verify ownership when user_id is provided
    if repo and user_id:
        app = repo.get_application(application_id, user_id)
        if not app:
            with db.session_scope() as session:
                from services.database import Application
                db_app = session.query(Application).filter_by(application_id=application_id).first()
                if db_app and db_app.user_id != user_id:
                    raise HTTPException(status_code=403, detail="Not authorized to cancel this application")
                elif not db_app and application_id not in _application_store:
                    raise HTTPException(status_code=404, detail="Application not found")

    result = db.delete_application(application_id, storage, user_id=user_id)
    if not result.get("deleted") and not user_id:
        result = db.delete_application(application_id, storage, user_id=None)

    if not result.get("deleted"):
        # Check if it was in-memory only
        if application_id in _application_store:
            del _application_store[application_id]
            return {
                "success": True,
                "message": "Application cancelled and removed.",
                "data": {"application_id": application_id}
            }
        err = "; ".join(result.get("errors", ["Application not found or unauthorized"]))
        raise HTTPException(status_code=400, detail=err)

    if application_id in _application_store:
        del _application_store[application_id]

    return {
        "success": True,
        "message": "Application cancelled successfully. Uploaded documents have been removed.",
        "data": result,
    }

