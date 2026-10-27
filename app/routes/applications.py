"""
Application management routes — create, list, retrieve, and cancel onboarding applications.

Role in Project:
    This module is the primary REST interface for managing the lifecycle of a user's
    onboarding application. An 'application' is the central business entity: it links a
    user to a Moro Hub service, tracks required documents, holds a CollectionAgent session
    reference, and stores the final validation outcome.

Cross-File Interconnections:
    - `services.service_catalog.ServiceCatalogService` — validates that the requested
      service_id exists and is currently available before creating an application.
    - `agents.collection_agent.CollectionAgent` — a CollectionAgent session is initialised
      immediately on application creation so the agent can track document submissions.
    - `services.repository.Repository` — applications are persisted to PostgreSQL via the
      repository layer (WP8 user-scoped isolation).
    - `services.database.DatabaseService` — fallback DB queries and application deletion
      (including cascading MinIO object removal) are delegated here.
    - `services.auth.AuthService` — the bearer token in query params is validated to bind
      an application to an authenticated user_id.
    - `services.storage.StorageService` — cancel_application cascades to delete uploaded
      MinIO objects via `DatabaseService.delete_application`.
    - `app.main.app_state` — all service references are retrieved from the shared app state
      dict rather than module-level globals, avoiding circular imports.
"""

import re
import uuid
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import ChatMessage, ChatResponse

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared application state dict from app.main.

    Imported lazily to avoid circular imports between the routes package
    and the app factory module. All service instances (auth, catalog, repo,
    database, collection_agent, storage) are retrieved from this dict.
    """
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
    """Create a new onboarding application and initialise all downstream tracking.

    Workflow:
        1. Validates the bearer token (if provided) to retrieve the authenticated user_id.
        2. Looks up the service in the ServiceCatalogService — rejects unknown/coming-soon services.
        3. Validates applicant_name: non-empty, min 2 chars, letters/spaces only.
        4. Creates a CollectionAgent session so the agent can track which required documents
           are submitted and flag missing mandatory ones.
        5. Persists the application to PostgreSQL via Repository.create_application (WP8 layer).
           Falls back to an in-memory dict if the DB/repository is unavailable.
        6. Returns the new application_id and the CollectionAgent session_id to the frontend.

    Interconnections:
        - `services.auth.AuthService.validate_token` — token → user_id resolution.
        - `services.service_catalog.ServiceCatalogService.get_service` — service validation.
        - `agents.collection_agent.CollectionAgent.create_session` — starts document tracking.
        - `services.repository.Repository.create_application` — persists to PostgreSQL.

    Args:
        service_id: Identifier of the Moro Hub service being applied for.
        applicant_name: Full legal name of the applicant.
        token: Optional JWT bearer token issued by AuthService.

    Returns:
        JSON with `success: True` and a `data` dict containing id, service_id,
        applicant_name, status, required_documents, and collection_session_id.

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
async def list_applications(user_id: Optional[str] = None, token: Optional[str] = Query(None, alias="token")):
    """List all applications, optionally scoped to the authenticated user.

    Resolution order:
        1. If a bearer token is supplied and no explicit user_id, resolve user_id from the token.
        2. Try `Repository.list_user_applications(user_id)` — fast indexed query.
        3. Fall back to a raw DB query on the `Application` table.
        4. Last resort: iterate the module-level `_application_store` in-memory dict.

    Interconnections:
        - `services.auth.AuthService.validate_token` — token → user_id.
        - `services.repository.Repository.list_user_applications` — primary query path (WP8).
        - `services.database.DatabaseService.session_scope` — fallback SQLAlchemy query.
        - `services.service_catalog.ServiceCatalogService.get_service` — enriches each
          application record with a human-readable service name.

    Returns:
        `{"data": {"applications": [...], "total": N}}`
    """
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
    """Convenience alias for list_applications filtered to a specific user_id.

    Delegates directly to `list_applications(user_id)`.
    Used by the Streamlit frontend sidebar to populate the 'My Applications' panel.
    """
    return await list_applications(user_id)

@router.get("/applications/{app_id}")
async def get_application(app_id: str, user_id: str = Query(...)):
    """Retrieve a single application's details, enforcing user ownership.

    Tries the Repository layer first (WP8 user-scoped), then falls back to the
    in-memory `_application_store` dict if the DB is unavailable.

    Interconnections:
        - `services.repository.Repository.get_application(app_id, user_id)` — ownership-aware fetch.

    Args:
        app_id: The unique application identifier (UUID prefix format).
        user_id: Must match the owner's user_id — enforced by the repository layer.

    Returns:
        `{"data": <application_dict>}` or `{"error": "not_found", "message": ...}`.

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


@router.delete("/applications/{application_id}")
@router.post("/applications/{application_id}/cancel")
async def cancel_application(
    application_id: str,
    token: Optional[str] = Query(None, alias="token"),
):
    """Cancel and permanently delete an application along with all its uploaded documents.

    Workflow:
        1. Resolves the calling user_id from the bearer token (if provided).
        2. Verifies ownership via the repository or a direct DB query — prevents one user
           from cancelling another user's application (returns HTTP 403).
        3. Delegates to `DatabaseService.delete_application` which:
           a. Deletes document records from PostgreSQL.
           b. Removes the corresponding files from MinIO via `StorageService`.
           c. Removes the Application record itself from the DB.
        4. Removes the application from the in-memory `_application_store` if present.

    Interconnections:
        - `services.auth.AuthService.validate_token` — token ownership verification.
        - `services.repository.Repository.get_application` — ownership gate.
        - `services.database.DatabaseService.delete_application` — DB + MinIO cascade delete.
        - `services.storage.StorageService` — object deletion in MinIO (called inside DatabaseService).

    Args:
        application_id: The application to cancel.
        token: Optional bearer token — required for ownership enforcement.

    Returns:
        `{"success": True, "message": ..., "data": {...}}` on success.
        HTTP 403 if user_id does not match the application owner.
        HTTP 404 if the application is not found.
    """
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

