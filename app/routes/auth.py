"""Authentication routes: login, register, logout, current user."""

import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    AuthenticationRequest, TokenResponse, UserRegistrationRequest
)

from services.database import User
router = APIRouter()

logger = logging.getLogger(__name__)

# --- Helper to access app state ---
def get_state():
    from app.main import app_state
    return app_state

@router.post("/auth/login")
async def login(req: AuthenticationRequest):
    """Authenticate a user and return session token."""
    state = get_state()
    db = state.get("database")
    success, message, token = state["auth"].authenticate(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail=message)
    user = state["auth"].validate_token(token)
    # Track last login in database
    if db and user:
        try:
            with db.session_scope() as session:
                db_user = session.query(User).filter_by(username=req.username).first()
                if db_user:
                    db_user.last_login = datetime.now(timezone.utc)
        except Exception as e:
            logger.warning(f"Failed to update last_login: {e}")
    return {
        "success": True,
        "data": {
            "user_id": user.user_id,
            "token": token,
            "email": user.email if hasattr(user, "email") else req.username
        }
    }

@router.post("/auth/register")
async def register(req: UserRegistrationRequest):
    """Register a new user account."""
    state = get_state()
    db = state.get("database")
    success, message, user = state["auth"].register_user(req.username, req.password, req.email)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Persist user to database (Phase 3)
    if db:
        try:
            with db.session_scope() as session:
                db_user = User(
                    user_id=user.user_id,
                    username=user.username,
                    email=user.email,
                    hashed_password=user.hashed_password,
                )
                session.add(db_user)
        except Exception as e:
            logger.warning(f"Failed to persist user to DB: {e}")

    return {
        "success": True,
        "message": message,
        "data": {
            "user_id": user.user_id,
            "email": user.email,
            "username": user.username
        }
    }

@router.post("/auth/signup")
async def signup(req: UserRegistrationRequest):
    """Alias for register — supports both /signup and /register."""
    return await register(req)

@router.post("/auth/logout")
async def logout(token: str = Query(..., alias="token")):
    """Invalidate a session token."""
    state = get_state()
    state["auth"].logout(token)
    return {"message": "Logged out successfully"}

@router.get("/auth/me")
async def get_me(token: str = Query(None, alias="token"), authorization: str = Query(None)):
    """Get current user info. Accepts token as query param or Authorization: Bearer ***"""
    state = get_state()
    db = state.get("database")
    # Support both query param and Authorization header
    actual_token = token
    if not actual_token and authorization:
        if authorization.startswith("Bearer "):
            actual_token = authorization[7:]
    if not actual_token:
        raise HTTPException(status_code=401, detail="No token provided")
    user = state["auth"].validate_token(actual_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Also get DB record if available
    user_dict = user.to_dict()
    if db:
        try:
            with db.session_scope() as session:
                db_user = session.query(User).filter_by(user_id=user.user_id).first()
                if db_user:
                    user_dict["applications"] = db_user.applications or []
        except Exception as e:
            logger.warning(f"Failed to fetch user DB record: {e}")
    
    return user_dict
