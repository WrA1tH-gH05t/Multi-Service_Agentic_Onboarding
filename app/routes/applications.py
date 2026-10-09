"""Application routes: create, list, get applications."""

import re
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import ChatMessage, ChatResponse

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

# In-memory store for created applications (application_id -> data)
_application_store: dict = {}

@router.post("/applications")
async def create_application(
    service_id: str = Query(...),
    applicant_name: str = Query(...),
    token: Optional[str] = Query(None, alias="token"),
):
    """Create a new onboarding application.
    
    Phase 3: Persists to database, supports user app history.
    WP8: User-scoped repository layer.
    """
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
        }
    }

@router.get("/applications")
async def list_applications(user_id: Optional[str] = None):
    """List applications, optionally filtered by user.
    
    Phase 3: Queries persistent database instead of in-memory store.
    WP8: Repository layer enforces user_id on all queries.
    """
    state = get_state()
    repo = state.get("repository")
    
    # Try repository first (WP8)
    if repo and user_id:
        try:
            apps = repo.list_user_applications(user_id)
            return {"data": {"applications": apps, "total": len(apps)}}
        except Exception as e:
            logger.warning(f"Failed to fetch from repository: {e}")
    
    # Fallback to in-memory store
    return {"data": {"applications": list(_application_store.values()), "total": len(_application_store)}}

@router.get("/user/applications")
async def get_user_applications(user_id: str = Query(...)):
    """Get applications for a specific user."""
    return await list_applications(user_id)

@router.get("/applications/{app_id}")
async def get_application(app_id: str, user_id: str = Query(...)):
    """Get application details.
    
    WP8: Requires user_id — ownership enforced by repository layer.
    """
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
