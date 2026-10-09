"""Collection agent routes: submit, question, change-service, validate."""

import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
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
    """List all collection sessions for a user.
    
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
    """Get details of a specific collection session.
    
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
    """Submit a document to the CollectionAgent.
    
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
    """Handle a question during collection without losing state."""
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
    """Handle switching services mid-conversation."""
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
    """Run ValidationAgent on a complete application (Phase 2).
    
    Phase 3: Persists validation result to database, emits audit events.
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
