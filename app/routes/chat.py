"""
Chat session (wizard state) routes — create, read, update, and reset conversational sessions.

Role in Project:
    This module manages the conversational wizard state that drives the multi-step document
    onboarding UI. Each chat session represents a user's current position in the onboarding
    wizard (e.g., which service they picked, what name they gave, which documents have been
    uploaded). Sessions are shared between the Streamlit UI (`app.py`) and the FastAPI backend.

    NOTE: The *chat message* endpoint (where the LLM responds to a user's typed message) lives
    in `app.routes.chat_message`. This module only handles wizard-session CRUD.

Cross-File Interconnections:
    - `services.wizard.WizardStateManager` — persistent wizard session management backed by
      PostgreSQL. Falls back to the module-level `_chat_sessions` dict if unavailable.
    - `services.repository.Repository` — WP8 user-scoped session read/write/reset.
    - `agents.collection_agent.CollectionAgent` — the GET session endpoint enriches the
      response with the linked CollectionAgent session status so the UI can show document
      checklist progress without a separate round-trip.
    - `app.main.app_state` — all service instances fetched lazily via `get_state()`.

Session Schema (in-memory fallback):
    {
        "step": str,                   # Wizard step name (e.g. "welcome", "upload", "review")
        "selected_service": str|None,  # service_id chosen by the user
        "applicant_name": str|None,    # Name entered by the user
        "application_id": str|None,    # Linked application_id once created
        "uploaded_documents": list,    # List of uploaded file metadata
        "required_documents": list,    # Documents required for the chosen service
    }
"""

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
    """Return the shared application state. Imported lazily to avoid circular imports."""
    from app.main import app_state
    return app_state

# In-memory chat session store (legacy compat)
_chat_sessions: dict = {}

def _get_session_id(token: Optional[str] = None) -> str:
    """Derive a deterministic session key from the bearer token prefix.
    Used only in the legacy in-memory fallback path.
    """
    if token:
        return f"session_{token[:16]}"
    return "session_anonymous"

def _get_session(session_id: str) -> dict:
    """Get or create a blank wizard session in the in-memory fallback store.
    Called when the repository/wizard_manager is unavailable.
    """
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
    """Create a new wizard chat session.

    The frontend uses a GET (not POST) to idempotently start a session.
    If the WizardStateManager is available, it creates a server-side persisted session.
    Otherwise, a fresh dict is inserted into the local `_chat_sessions` fallback.

    Interconnections:
        - `services.wizard.WizardStateManager.create_session` — primary path.

    Args:
        user_id: Unique identifier for the authenticated user (or 'anonymous').
        service_id: Pre-selected service_id (passed when deep-linking to a specific service).

    Returns:
        `{"success": True, "data": {"session_id": ..., "step": "welcome", "service_id": ...}}`
    """
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
    """Get the current wizard session state, enriched with CollectionAgent progress.

    Workflow:
        1. Tries `Repository.get_chat_session(session_id, user_id)` — enforces ownership.
        2. If the session has a linked `collection_session_id`, fetches the CollectionAgent
           session and attaches its `to_dict()` output as `collection_status` so the UI
           can render the document checklist without an extra API call.
        3. Falls back to the in-memory `_chat_sessions` dict.

    Interconnections:
        - `services.repository.Repository.get_chat_session` — WP8 user-scoped fetch.
        - `agents.collection_agent.CollectionAgent.get_session` — document tracking status.

    Args:
        session_id: UUID of the chat/wizard session.
        user_id: Must match the session owner — enforced by the repository.

    Returns:
        `{"data": <session_dict_with_optional_collection_status>}`

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
    """Update wizard session state with new key-value pairs.

    Merges the supplied `data` dict into the existing session record.
    Used by the frontend to persist wizard-step transitions (e.g. service selected,
    name entered, document uploaded).

    Interconnections:
        - `services.repository.Repository.update_chat_session` — primary DB write.
        - Falls back to updating the in-memory `_chat_sessions[session_id]` dict.

    Args:
        session_id: Target session UUID.
        data: Partial dict of session fields to update.
        user_id: Ownership guard — only the session owner may update it.

    Returns:
        `{"success": True, "data": <merged_session_dict>}`

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
    """Reset a wizard session back to the initial 'welcome' state.

    Clears the session's selected service, applicant name, application_id, and all
    uploaded document references. Called when a user wants to start a new application
    from scratch within the same browser session.

    Interconnections:
        - `services.repository.Repository.update_chat_session` — persists the blank state.
        - Also resets the in-memory fallback `_chat_sessions[session_id]` dict.

    Args:
        session_id: Target session UUID.
        user_id: Ownership guard.

    Returns:
        `{"success": True, "data": <blank_session_dict>}`

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
