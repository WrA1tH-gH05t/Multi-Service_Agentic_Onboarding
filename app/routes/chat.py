"""Chat / conversation routes: message, session management."""

import re
import json
import logging
import traceback
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from datetime import datetime

from app.schemas import ChatMessage, ChatResponse

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

# In-memory chat session store (legacy compat)
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

# --- Chat Session / Wizard State ---
@router.get("/chat/session")
async def create_chat_session(
    user_id: str = Query("anonymous"),
    service_id: str = Query("default"),
):
    """Create a new chat session (frontend uses GET for creation)."""
    import uuid
    from services.wizard import WizardSession
    state = get_state()
    wizard_mgr = state.get("wizard_manager")
    
    session_id = str(uuid.uuid4())
    
    if wizard_mgr:
        session = wizard_mgr.create_session(user_id=user_id, service_id=service_id)
    else:
        # In-memory fallback
        _chat_sessions[session_id] = {
            "step": "welcome",
            "selected_service": service_id,
            "applicant_name": None,
            "application_id": None,
            "uploaded_documents": [],
            "required_documents": [],
        }
    
    return {
        "success": True,
        "data": {
            "session_id": session_id,
            "step": "welcome",
            "service_id": service_id,
        },
        "message": "Chat session created"
    }

@router.get("/chat/session/{session_id}")
async def get_chat_session(session_id: str, user_id: str = Query(...)):
    """Get current wizard session state, enriched with CollectionAgent data.
    
    WP8: Repository layer enforces user_id on all session fetches.
    """
    state = get_state()
    repo = state.get("repository")
    
    # Try repository first (WP8)
    if repo:
        try:
            session = repo.get_chat_session(session_id, user_id)
            if session:
                # If there's a collection agent session, include its status
                collection_agent = state.get("collection_agent")
                if collection_agent and session.get("collection_session_id"):
                    coll_session = collection_agent.get_session(session["collection_session_id"])
                    if coll_session:
                        session["collection_status"] = coll_session.to_dict()
                return {"data": session}
        except Exception as e:
            logger.warning(f"Failed to fetch session {session_id} from repository: {e}")
    
    # Fallback to in-memory store
    session = _get_session(session_id)
    # If there's a collection agent session, include its status
    collection_agent = state.get("collection_agent")
    if collection_agent and session.get("collection_session_id"):
        coll_session = collection_agent.get_session(session["collection_session_id"])
        if coll_session:
            session["collection_status"] = coll_session.to_dict()
    return {"data": session}

@router.post("/chat/session/{session_id}")
async def update_chat_session(session_id: str, data: dict, user_id: str = Query(...)):
    """Update wizard session state.
    
    WP8: Repository layer enforces user_id on all session updates.
    """
    state = get_state()
    repo = state.get("repository")
    
    # Try repository first (WP8)
    if repo:
        try:
            updated = repo.update_chat_session(session_id, user_id, **data)
            if updated:
                # Also update in-memory for immediate access
                session = _get_session(session_id)
                session.update(data)
                return {"success": True, "data": session}
        except Exception as e:
            logger.warning(f"Failed to update session {session_id} in repository: {e}")
    
    # Fallback to in-memory store
    session = _get_session(session_id)
    session.update(data)
    return {"success": True, "data": session}

@router.post("/chat/session/{session_id}/reset")
async def reset_chat_session(session_id: str, user_id: str = Query(...)):
    """Reset wizard session state.
    
    WP8: Repository layer enforces user_id on session resets.
    """
    state = get_state()
    repo = state.get("repository")
    
    # Try repository first (WP8)
    if repo:
        try:
            repo.update_chat_session(session_id, user_id,
                step="welcome",
                selected_service=None,
                applicant_name=None,
                application_id=None,
                uploaded_documents=[],
                required_documents=[],
            )
        except Exception as e:
            logger.warning(f"Failed to reset session {session_id} in repository: {e}")
    
    # Reset in-memory store
    _chat_sessions[session_id] = {
        "step": "welcome",
        "selected_service": None,
        "applicant_name": None,
        "application_id": None,
        "uploaded_documents": [],
        "required_documents": [],
    }
    return {"success": True, "data": _chat_sessions[session_id]}
