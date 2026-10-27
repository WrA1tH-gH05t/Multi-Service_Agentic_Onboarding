"""
Collection agent routes — document submission, live questions, service changes, and validation.

Role in Project:
    This module bridges the HTTP API and the `CollectionAgent` — the stateful AI component
    that tracks which documents have been submitted for an onboarding application and decides
    what is still needed. It exposes the CollectionAgent's session management, document
    submission, mid-conversation question answering, service switching, and final validation
    trigger as RESTful endpoints.

Cross-File Interconnections:
    - `agents.collection_agent.CollectionAgent` — the primary orchestrator called by every
      endpoint in this module:
        * `CollectionAgent.list_sessions` — /collection/sessions GET
        * `CollectionAgent.get_session` — /collection/session/{id} GET
        * `CollectionAgent.submit_document` — /collection/session/{id}/submit POST
        * `CollectionAgent.handle_question` — /collection/session/{id}/question POST
        * `CollectionAgent.handle_service_change` — /collection/session/{id}/change-service POST
    - `agents.validation_agent.ValidationAgent.validate_application` — the /collection/validate
      endpoint triggers a full cross-document validation run and persists the result.
    - `services.database.DatabaseService.log_event` — audit trail events are emitted for
      every submission and validation outcome.
    - `app.main.app_state` — service instances (collection_agent, validation_agent, database)
      are all fetched from the shared app state.

Ownership / Security:
    - `list_collection_sessions` requires user_id as a query param.
    - `get_collection_session` verifies `coll_session.user_id == user_id` before returning data.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state dict. Lazy import prevents circular dependencies."""
    from app.main import app_state
    return app_state

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

# --- Collection Agent Actions ---

@router.get("/collection/sessions")
async def list_collection_sessions(user_id: str = Query(...)):
    """List all CollectionAgent sessions belonging to a specific user.

    Delegates to `CollectionAgent.list_sessions(user_id)` which filters the in-memory
    session store. Returns session id, service_id, status, and document completion counts.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.list_sessions`

    Args:
        user_id: The user whose sessions to list.

    Returns:
        `{"success": True, "data": [<session_summary>, ...]}`

    Phase 3: Returns session list with status, service_id, and creation date.
    """
    state = get_state()
    collection_agent = state.get("collection_agent")
    if not collection_agent:
        raise HTTPException(status_code=503, detail="Collection agent not available")
    
    # Get all sessions for this user
    sessions = collection_agent.list_sessions(user_id)
    return {"success": True, "data": sessions}


@router.get("/collection/session/{session_id}")
async def get_collection_session(session_id: str, user_id: str = Query(...)):
    """Get details and document tracking status of a specific CollectionAgent session.

    Verifies session ownership (user_id must match) before returning data.
    The returned `to_dict()` includes the per-document requirement status: whether each
    mandatory document has been submitted, extraction results, and failure counts.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.get_session`
        - `agents.collection_agent.ApplicationSession.to_dict`

    Args:
        session_id: The CollectionAgent session UUID.
        user_id: Must match `coll_session.user_id` — enforces data isolation.

    Returns:
        `{"success": True, "data": <session_detail_dict>}`
        HTTP 403 if user_id does not match the session owner.
        HTTP 404 if the session does not exist.

    Phase 3: Returns session details with status and document requirements.
    """
    state = get_state()
    collection_agent = state.get("collection_agent")
    if not collection_agent:
        raise HTTPException(status_code=503, detail="Collection agent not available")
    
    coll_session = collection_agent.get_session(session_id)
    if not coll_session:
        raise HTTPException(status_code=404, detail="Collection session not found")
    
    # Verify ownership
    if coll_session.user_id != user_id:
        raise HTTPException(status_code=403, detail="Not authorized to access this session")
    
    return {"success": True, "data": coll_session.to_dict()}


@router.post("/collection/session/{session_id}/submit")
async def collection_submit(session_id: str, data: dict):
    """Submit an extracted document result to the CollectionAgent.

    Called by `app.routes.documents.upload_document` after a file has been uploaded to
    MinIO and extracted by the ExtractionLadder. Updates the CollectionAgent's per-document
    state and determines the next prompt (e.g. "great, now upload your driving licence").

    Workflow:
        1. Looks up the chat session to find its `collection_session_id`.
        2. Delegates to `CollectionAgent.submit_document` with the doc_type, file_id,
           extraction success flag, extracted fields, and confidence score.
        3. Logs an audit event to `DatabaseService.log_event` with doc_type and result.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.submit_document` — core logic.
        - `services.database.DatabaseService.log_event` — audit trail.

    Args:
        session_id: The wizard chat session id (used to look up `collection_session_id`).
        data: Dict containing: doc_type, file_id, extraction_ok, extraction_fields,
              extraction_confidence, and optionally application_id.

    Returns:
        `{"success": True, "data": <collection_agent_response>}`

    Phase 3: Persists submission to database, emits audit trail events.
    """
    state = get_state()
    db = state.get("database")
    collection_agent = state.get("collection_agent")
    if not collection_agent:
        raise HTTPException(status_code=503, detail="Collection agent not available")
    
    session = _get_session(session_id)
    coll_session_id = session.get("collection_session_id")
    
    if not coll_session_id:
        raise HTTPException(status_code=400, detail="No collection session found. Start an application first.")
    
    coll_session = collection_agent.get_session(coll_session_id)
    if not coll_session:
        raise HTTPException(status_code=404, detail="Collection session not found")
    
    doc_type = data.get("doc_type", "")
    file_id = data.get("file_id", "")
    extraction_ok = data.get("extraction_ok", True)
    extraction_fields = data.get("extraction_fields", {})
    extraction_confidence = data.get("extraction_confidence", 0.0)
    
    response = collection_agent.submit_document(
        session_id=coll_session_id,
        doc_type=doc_type,
        file_id=file_id,
        extraction_ok=extraction_ok,
        extraction_fields=extraction_fields,
        extraction_confidence=extraction_confidence,
    )
    
    # Update application store
    if application_id := data.get("application_id"):
        if application_id in data:
            pass  # App store update handled in documents.py
    
    # Phase 3: Emit audit trail event
    if db and application_id:
        try:
            db.log_event(
                event_type=f"collection_{response.get('action', 'submit')}",
                user_id=session.get("user_id"),
                application_id=application_id,
                details={"doc_type": doc_type, "file_id": file_id, "extraction_ok": extraction_ok},
                stage="collection",
            )
        except Exception as e:
            logger.warning(f"Failed to log collection audit event: {e}")
    
    return {"success": True, "data": response}

@router.post("/collection/session/{session_id}/question")
async def collection_question(session_id: str, data: dict):
    """Handle a user question during an active collection session without losing wizard state.

    Routes off-topic or clarification questions (e.g. 'what documents do I need?') through
    the CollectionAgent's question handler, which can answer based on service requirements
    without resetting the current document-collection state machine.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.handle_question`

    Args:
        session_id: The wizard chat session id.
        data: Dict containing `question` (str).

    Returns:
        `{"success": True, "data": <collection_agent_answer>}`
    """
    collection_agent = get_state().get("collection_agent")
    if not collection_agent:
        raise HTTPException(status_code=503, detail="Collection agent not available")
    
    session = _get_session(session_id)
    coll_session_id = session.get("collection_session_id")
    
    if not coll_session_id:
        raise HTTPException(status_code=400, detail="No collection session found")
    
    response = collection_agent.handle_question(
        session_id=coll_session_id,
        question=data.get("question", ""),
    )
    
    return {"success": True, "data": response}

@router.post("/collection/session/{session_id}/change-service")
async def collection_change_service(session_id: str, data: dict):
    """Handle switching to a different Moro Hub service mid-conversation.

    Delegates to `CollectionAgent.handle_service_change` which creates a new collection
    session for the new service. Also resets the wizard chat session state back to the
    welcome step so the UI reflects the fresh start.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.handle_service_change`
        - Resets the module-level `_chat_sessions[session_id]` dict.

    Args:
        session_id: The wizard chat session id.
        data: Dict containing `new_service_id` (str).

    Returns:
        `{"success": True, "data": <collection_agent_response>}`
        HTTP 400 if `new_service_id` is missing.
    """
    collection_agent = get_state().get("collection_agent")
    if not collection_agent:
        raise HTTPException(status_code=503, detail="Collection agent not available")
    
    session = _get_session(session_id)
    user_id = session.get("user_id", "anonymous")
    new_service_id = data.get("new_service_id", "")
    
    if not new_service_id:
        raise HTTPException(status_code=400, detail="new_service_id is required")
    
    response = collection_agent.handle_service_change(user_id, new_service_id)
    
    # Reset wizard session
    _chat_sessions[session_id] = {
        "step": "welcome",
        "selected_service": new_service_id,
        "applicant_name": None,
        "application_id": None,
        "uploaded_documents": [],
        "required_documents": [],
    }
    
    return {"success": True, "data": response}

@router.post("/collection/validate")
async def collection_validate(data: dict):
    """Trigger a full ValidationAgent run on a complete collection session.

    After all required documents have been submitted, this endpoint assembles the
    application data from the CollectionAgent session and runs the ValidationAgent.
    The validation result is then persisted to the `applications` table and an audit
    event is emitted.

    Workflow:
        1. Loads the CollectionAgent session by `collection_session_id`.
        2. Builds an `app_data` dict with all submitted documents and extracted fields.
        3. Calls `ValidationAgent.validate_application(app_data)` — runs cross-document
           checks (name consistency, DOB match, expiry checks, mandatory field coverage).
        4. Persists the `ValidationReport.to_dict()` to the `Application.validation_result`
           DB column and updates `Application.status`.
        5. Emits a `validation_passed` or `validation_failed` audit event.

    Interconnections:
        - `agents.collection_agent.CollectionAgent.get_session`
        - `agents.validation_agent.ValidationAgent.validate_application`
        - `services.database.DatabaseService.session_scope` — DB write.
        - `services.database.DatabaseService.log_event` — audit trail.

    Args:
        data: Dict containing `collection_session_id` (str).

    Returns:
        `{"success": True, "data": <validation_report_dict>, "message": "Validation passed/failed"}`

    Phase 2+3: Runs ValidationAgent; persists result, emits audit events.
    """
    state = get_state()
    db = state.get("database")
    collection_agent = state.get("collection_agent")
    validation_agent = state.get("validation_agent")
    
    if not collection_agent or not validation_agent:
        raise HTTPException(status_code=503, detail="Agents not available")
    
    coll_session_id = data.get("collection_session_id", "")
    if not coll_session_id:
        raise HTTPException(status_code=400, detail="collection_session_id is required")
    
    coll_session = collection_agent.get_session(coll_session_id)
    if not coll_session:
        raise HTTPException(status_code=404, detail="Collection session not found")
    
    # Build application data from collection session
    app_data = {
        "application_id": coll_session.session_id,
        "service_id": coll_session.service_id,
        "required_documents": coll_session.document_requirements.keys(),
        "documents": [],
    }
    
    for doc_type, req in coll_session.document_requirements.items():
        app_data["documents"].append({
            "doc_type": doc_type,
            "extracted_fields": req.extraction_fields,
            "extraction_confidence": req.extraction_confidence,
        })
    
    report = validation_agent.validate_application(app_data)
    report_dict = report.to_dict()
    
    # Phase 3: Persist validation result to database
    if db:
        # Find application by collection session
        try:
            with db.session_scope() as session:
                from services.database import Application
                app = session.query(Application).filter_by(
                    collection_session_id=coll_session_id
                ).first()
                if app:
                    app.validation_result = report_dict
                    app.status = report_dict["result"]
                    app.updated_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to persist validation result to DB: {e}")
    
    # Phase 3: Emit audit trail event
    if db and coll_session_id:
        try:
            event_type = "validation_passed" if report_dict.get("result") == "pass" else "validation_failed"
            db.log_event(
                event_type=event_type,
                user_id=coll_session.user_id,
                application_id=coll_session.session_id,
                details=report_dict,
                stage="validation",
            )
        except Exception as e:
            logger.warning(f"Failed to log validation audit event: {e}")
    
    return {"success": True, "data": report_dict, "message": f"Validation {'passed' if report.result.value == 'pass' else 'failed'}"}
