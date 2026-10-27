"""
Authentication routes: login, register, logout, current user.

Module Purpose & Role in the Project:
-------------------------------------
This module exposes endpoints for user lifecycle and session management, including:
- User login (`POST /auth/login`) with credential validation and session token issuance.
- User registration (`POST /auth/register` and alias `POST /auth/signup`) supporting database synchronization.
- Session invalidation (`POST /auth/logout`).
- User profile resolution (`GET /auth/me`) validating bearer tokens and querying linked applications.

Interconnections with Other Files:
-----------------------------------
- `app/schemas.py`: Imports Pydantic schemas: `AuthenticationRequest`, `TokenResponse`, `UserRegistrationRequest`.
- `services/auth.py`: Invokes `AuthService` for cryptographic password hashing, token validation, and session stores.
- `services/database.py`: Synchronizes user state with the relational `users` table via `User` ORM model.
- `app/main.py`: Accesses `app_state` to obtain shared database and authentication service singletons.
- Consumed directly by frontend authentication components (login modal, signup modal, protected route guards).
"""

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
    """
    Retrieve the singleton application state dictionary from the main module.

    Returns:
        dict: The shared `app_state` dictionary from `app.main`.

    Interconnections:
        - Avoids circular import cycles at module load time by importing `app_state` lazily.
    """
    from app.main import app_state
    return app_state

@router.post("/auth/login")
async def login(req: AuthenticationRequest):
    """
    Authenticate a user and return an active session token.

    Detailed Behavior:
    - Calls `state["auth"].authenticate(username, password)`.
    - If authentication fails, raises an HTTP 401 Unauthorized exception.
    - If successful, validates the generated token to retrieve the user record.
    - Updates `last_login` timestamp in the database (`users` table) in a managed transaction scope.
    - Returns structured user metadata including `user_id`, `token`, and `email`.

    Parameters:
        req (AuthenticationRequest): JSON payload containing `username` and `password`.

    Returns:
        dict: Standard JSON response containing success flag, `user_id`, `token`, and `email`.

    Raises:
        HTTPException: 401 Unauthorized if credentials do not match.

    Interconnections:
        - `services.auth.AuthService:authenticate`: Validates password hash.
        - `services.database.User`: Updates `last_login` in the database.
        - Frontend client: Stores returned token in browser storage for authenticated API calls.
    """
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
    """
    Register a new user account and automatically issue a session token.

    Detailed Behavior:
    - Normalizes email address (falls back to `<username>@example.com` if absent).
    - Delegates registration to `state["auth"].register_user()`, ensuring unique username.
    - If successful, persists user account into the relational database (`User` ORM model).
    - Automatically authenticates the newly created user to generate a valid session token.
    - Returns user details along with the new session token.

    Parameters:
        req (UserRegistrationRequest): JSON payload with `username`, `password`, `email`, and `name`.

    Returns:
        dict: Registration confirmation containing `user_id`, `email`, `username`, and `token`.

    Raises:
        HTTPException: 400 Bad Request if username already exists or validation fails.

    Interconnections:
        - `services.auth.AuthService:register_user`: Enforces user creation and file storage.
        - `services.database.User`: Inserts new user record into the database.
    """
    state = get_state()
    db = state.get("database")
    email = req.email.strip() if req.email and req.email.strip() else (req.username if "@" in req.username else f"{req.username}@example.com")
    success, message, user = state["auth"].register_user(req.username, req.password, email)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    # Persist user to database (Phase 3)
    if db:
        try:
            with db.session_scope() as session:
                if not session.query(User).filter_by(user_id=user.user_id).first():
                    db_user = User(
                        user_id=user.user_id,
                        username=user.username,
                        email=user.email,
                        hashed_password=user.hashed_password,
                    )
                    session.add(db_user)
        except Exception as e:
            logger.warning(f"Failed to persist user to DB: {e}")

    # Automatically authenticate newly registered user
    _, _, token = state["auth"].authenticate(req.username, req.password)

    return {
        "success": True,
        "message": message,
        "data": {
            "user_id": user.user_id,
            "email": user.email,
            "username": user.username,
            "token": token
        }
    }

@router.post("/auth/signup")
async def signup(req: UserRegistrationRequest):
    """
    Alias for register — supports both /signup and /register API paths.

    Parameters:
        req (UserRegistrationRequest): Registration request payload.

    Returns:
        dict: Result of `register(req)`.
    """
    return await register(req)

@router.post("/auth/logout")
async def logout(token: str = Query(..., alias="token")):
    """
    Invalidate an active user session token.

    Detailed Behavior:
    - Calls `state["auth"].logout(token)` to remove session mapping from memory.
    - Future API calls presenting this token will fail with HTTP 401.

    Parameters:
        token (str): Session token to invalidate (passed as query param or alias).

    Returns:
        dict: Success message acknowledging logout.

    Interconnections:
        - Calls `services.auth.AuthService:logout`.
    """
    state = get_state()
    state["auth"].logout(token)
    return {"message": "Logged out successfully"}

@router.get("/auth/me")
async def get_me(token: str = Query(None, alias="token"), authorization: str = Query(None)):
    """
    Get current user profile information and linked application references.

    Detailed Behavior:
    - Accepts authentication token from either `token` query param or `Authorization: Bearer <token>`.
    - Validates token against `AuthService`; rejects with HTTP 401 if missing or invalid.
    - If database is available, enriches profile with linked user applications from `User.applications`.
    - Sanitizes the user dictionary by stripping sensitive attributes (`hashed_password`, `sessions`).
    - Returns safe user profile data to client.

    Parameters:
        token (Optional[str]): Token passed via query string.
        authorization (Optional[str]): Authorization header string (e.g. 'Bearer <token>').

    Returns:
        dict: User dictionary with `user_id`, `username`, `email`, and `applications`.

    Raises:
        HTTPException: 401 Unauthorized if token is missing, expired, or invalid.

    Interconnections:
        - `services.auth.AuthService:validate_token`: Resolves user token.
        - `services.database.User`: Fetches associated applications.
    """
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
    
    # Never expose hashed_password to the frontend
    user_dict.pop("hashed_password", None)
    user_dict.pop("sessions", None)

    return {
        "success": True,
        "user": user_dict
    }
