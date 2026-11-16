"""Authentication routes: login, register, logout, current user."""

import re
import secrets
import hashlib
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
    """Retrieve the singleton application state dictionary from the main module."""
    from app.main import app_state
    return app_state

@router.post("/auth/login")
async def login(req: AuthenticationRequest):
    """Authenticate a user and return an active session token."""
    state = get_state()
    db = state.get("database")
    success, message, token = state["auth"].authenticate(req.username, req.password)
    if not success:
        raise HTTPException(status_code=401, detail=message)
    user = state["auth"].validate_token(token)
    # Track last login in database
    pending_apps = []
    if db and user:
        try:
            with db.session_scope() as session:
                db_user = session.query(User).filter_by(username=req.username).first()
                if db_user:
                    db_user.last_login = datetime.now(timezone.utc)
            # Find any pending applications
            all_apps = db.get_user_applications(user.user_id)
            pending_apps = [a for a in all_apps if a.get("status") in ("incomplete", "in_progress", "pending", "collecting")]
        except Exception as e:
            logger.warning(f"Failed to update last_login or fetch pending apps: {e}")
    return {
        "success": True,
        "data": {
            "user_id": user.user_id,
            "token": token,
            "username": getattr(user, "username", req.username),
            "email": user.email if hasattr(user, "email") else req.username,
            "full_name": getattr(user, "full_name", None) or getattr(user, "username", req.username),
            "pending_applications": pending_apps
        }
    }

@router.post("/auth/register")
async def register(req: UserRegistrationRequest):
    """Register a new user account and automatically issue a session token."""
    state = get_state()
    db = state.get("database")
    full_name = req.full_name or req.name or req.username
    birthday = req.birthday
    gender = req.gender

    email = req.email.strip() if req.email and req.email.strip() else (req.username if "@" in req.username else f"{req.username}@example.com")
    success, message, user = state["auth"].register_user(
        req.username, req.password, email,
        full_name=full_name, birthday=birthday, gender=gender
    )
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
                        full_name=full_name,
                        birthday=birthday,
                        gender=gender,
                    )
                    session.add(db_user)
        except Exception as e:
            logger.warning(f"Failed to persist user to DB: {e}")

    # Automatically authenticate newly registered user
    _, _, token = state["auth"].authenticate(req.username, req.password)

    # Check for pending applications if any match this user's identity details
    pending_apps = []
    if db and user:
        try:
            all_apps = db.get_user_applications(user.user_id)
            pending_apps = [a for a in all_apps if a.get("status") in ("incomplete", "in_progress", "pending", "collecting")]
        except Exception as e:
            logger.warning(f"Failed to query pending apps: {e}")

    return {
        "success": True,
        "message": message,
        "data": {
            "user_id": user.user_id,
            "email": user.email,
            "username": user.username,
            "full_name": full_name,
            "token": token,
            "pending_applications": pending_apps
        }
    }

@router.post("/auth/signup")
async def signup(req: UserRegistrationRequest):
    """Alias for register — supports both /signup and /register API paths."""
    return await register(req)

@router.post("/auth/logout")
async def logout(token: str = Query(..., alias="token")):
    """Invalidate an active user session token."""
    state = get_state()
    state["auth"].logout(token)
    return {"message": "Logged out successfully"}

@router.get("/auth/me")
async def get_me(token: str = Query(None, alias="token"), authorization: str = Query(None)):
    """Get current user profile information and linked application references."""
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
                    if db_user.full_name:
                        user_dict["full_name"] = db_user.full_name
                    if db_user.birthday:
                        user_dict["birthday"] = db_user.birthday
                    if db_user.gender:
                        user_dict["gender"] = db_user.gender
        except Exception as e:
            logger.warning(f"Failed to fetch user DB record: {e}")

    user_dict.pop("hashed_password", None)
    user_dict.pop("sessions", None)

    return {
        "success": True,
        "user": user_dict
    }
    
@router.post("/auth/profile")
async def update_profile(body: dict, token: Optional[str] = Query(None, alias="token"), authorization: str = Query(None)):
    """Update profile information (full_name, birthday, gender, username, email, password) for the authenticated user."""
    state = get_state()
    db = state.get("database")
    storage = state.get("storage")
    actual_token = token
    if not actual_token and authorization:
        if authorization.startswith("Bearer "):
            actual_token = authorization[7:]
    if not actual_token:
        raise HTTPException(status_code=401, detail="No token provided")
    user = state["auth"].validate_token(actual_token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    store = state["auth"]._store
    store_user = store.get_user_by_id(user.user_id)

    # Immutable once set: full_name, birthday, gender
    # Can only be set if previously unset/empty
    new_full_name = body.get("full_name")
    new_birthday = body.get("birthday")
    new_gender = body.get("gender")

    if new_full_name and str(new_full_name).strip():
        stripped_name = str(new_full_name).strip()
        existing_val = getattr(user, "full_name", None) or (getattr(store_user, "full_name", None) if store_user else None)
        if existing_val and existing_val.strip() and existing_val.strip() != stripped_name:
            raise HTTPException(status_code=400, detail="Full legal name cannot be modified once set.")
        user.full_name = stripped_name

    if new_birthday and str(new_birthday).strip():
        stripped_bday = str(new_birthday).strip()
        existing_val = getattr(user, "birthday", None) or (getattr(store_user, "birthday", None) if store_user else None)
        if existing_val and existing_val.strip() and existing_val.strip() != stripped_bday:
            raise HTTPException(status_code=400, detail="Date of birth cannot be modified once set.")
        user.birthday = stripped_bday

    if new_gender and str(new_gender).strip():
        stripped_gender = str(new_gender).strip()
        existing_val = getattr(user, "gender", None) or (getattr(store_user, "gender", None) if store_user else None)
        if existing_val and existing_val.strip() and existing_val.strip() != stripped_gender:
            raise HTTPException(status_code=400, detail="Gender cannot be modified once set.")
        user.gender = stripped_gender

    # Mutable fields: username, email, password
    new_username = body.get("username")
    new_email = body.get("email")
    new_password = body.get("password")

    old_username = user.username
    username_changed = False

    if new_username and str(new_username).strip():
        clean_user = str(new_username).strip()
        if clean_user != old_username:
            # Validate username
            is_valid_u, u_err = state["auth"].validate_username(clean_user)
            if not is_valid_u:
                raise HTTPException(status_code=400, detail=u_err)
            # Check uniqueness in persistent store and DB
            existing_u = store.get_user_by_name(clean_user)
            if existing_u and existing_u.user_id != user.user_id:
                raise HTTPException(status_code=400, detail="Username is already taken.")
            username_changed = True
            user.username = clean_user

    if new_email and str(new_email).strip():
        clean_email = str(new_email).strip().lower()
        if clean_email != (user.email or "").lower():
            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", clean_email):
                raise HTTPException(status_code=400, detail="Invalid email format.")
            existing_e = store.get_user_by_email(clean_email)
            if existing_e and existing_e.user_id != user.user_id:
                raise HTTPException(status_code=400, detail="Email is already in use by another account.")
            user.email = clean_email

    new_hashed_pwd = None
    if new_password and str(new_password).strip():
        clean_pwd = str(new_password).strip()
        is_valid_p, p_err = state["auth"].validate_password(clean_pwd)
        if not is_valid_p:
            raise HTTPException(status_code=400, detail=p_err)
        salt = secrets.token_hex(16)
        new_hashed_pwd = hashlib.sha256(f"{salt}{clean_pwd}".encode()).hexdigest() + "$" + salt
        user.hashed_password = new_hashed_pwd

    # Update persistent file store
    if store_user:
        if user.full_name:
            store_user.full_name = user.full_name
        if user.birthday:
            store_user.birthday = user.birthday
        if user.gender:
            store_user.gender = user.gender
        if user.email:
            # Update index
            if store_user.email in store._user_by_email:
                del store._user_by_email[store_user.email]
            store_user.email = user.email
            store._user_by_email[user.email] = user.user_id
        if username_changed:
            if old_username in store._user_by_name:
                del store._user_by_name[old_username]
            store_user.username = user.username
            store._user_by_name[user.username] = user.user_id
        if new_hashed_pwd:
            store_user.hashed_password = new_hashed_pwd
        store._save()

    # Update in SQL Database
    if db:
        try:
            with db.session_scope() as session:
                from services.database import User as DBUser, Application as DBApplication, Document as DBDocument
                db_user = session.query(DBUser).filter_by(user_id=user.user_id).first()
                if db_user:
                    if user.full_name:
                        db_user.full_name = user.full_name
                    if user.birthday:
                        db_user.birthday = user.birthday
                    if user.gender:
                        db_user.gender = user.gender
                    if user.email:
                        db_user.email = user.email
                    if username_changed:
                        db_user.username = user.username
                    if new_hashed_pwd:
                        db_user.hashed_password = new_hashed_pwd

                # If username changed, update document object names & applications
                if username_changed:
                    # Update applications for this user
                    user_apps = session.query(DBApplication).filter_by(user_id=user.user_id).all()
                    for app in user_apps:
                        # If applicant_name was the old username, update it
                        if app.applicant_name == old_username:
                            app.applicant_name = user.username

                    # Update documents and rename MinIO objects
                    user_docs = session.query(DBDocument).filter_by(user_id=user.user_id).all()
                    for doc in user_docs:
                        old_key = doc.object_name
                        if old_key and storage:
                            # Reformat key using new username: <username>_<idnumber>_<date>.<ext>
                            clean_old_u = re.sub(r"[^a-zA-Z0-9]+", "_", old_username).strip("_").lower()
                            clean_new_u = re.sub(r"[^a-zA-Z0-9]+", "_", user.username).strip("_").lower()
                            
                            new_key = None
                            if old_key.startswith(clean_old_u + "_"):
                                new_key = clean_new_u + "_" + old_key[len(clean_old_u) + 1:]
                            elif "_" in old_key:
                                parts = old_key.split("_", 1)
                                new_key = f"{clean_new_u}_{parts[1]}"
                            else:
                                new_key = f"{clean_new_u}_{old_key}"

                            if new_key and new_key != old_key:
                                try:
                                    if storage.is_connected:
                                        data = storage.download_file(old_key)
                                        storage.upload_file(data, new_key, doc.content_type or "application/pdf")
                                        storage.delete_file(old_key)
                                    doc.object_name = new_key
                                    logger.info(f"Renamed MinIO doc on username change: {old_key} -> {new_key}")
                                except Exception as ren_err:
                                    logger.warning(f"Could not rename MinIO object {old_key}: {ren_err}")
                                    doc.object_name = new_key
        except Exception as e:
            logger.warning(f"Failed to update profile in DB: {e}")

    user_dict = user.to_dict()
    user_dict.pop("hashed_password", None)
    user_dict.pop("sessions", None)

    return {
        "success": True,
        "message": "Profile updated successfully",
        "user": user_dict
    }


@router.post("/auth/reset-password")
async def reset_password(body: dict):
    """Public password reset endpoint."""
    state = get_state()
    auth_svc = state.get("auth")
    db = state.get("database")
    if not auth_svc:
        raise HTTPException(status_code=500, detail="Authentication service unavailable.")

    identifier = (body.get("identifier") or body.get("username") or body.get("email") or "").strip()
    new_password = (body.get("new_password") or body.get("password") or "").strip()

    if not identifier:
        raise HTTPException(status_code=400, detail="Username or email is required.")
    if not new_password:
        raise HTTPException(status_code=400, detail="New password is required.")

    # Validate password requirements
    is_valid_p, p_err = auth_svc.validate_password(new_password)
    if not is_valid_p:
        raise HTTPException(status_code=400, detail=p_err)

    store = getattr(auth_svc, "user_store", None) or getattr(auth_svc, "_store", None)
    if not store:
        raise HTTPException(status_code=500, detail="User store unavailable.")

    # Lookup user by username or email
    user = store.get_user_by_name(identifier)
    if not user:
        user = store.get_user_by_email(identifier.lower())
    if not user:
        # Check database directly if not in memory
        if db:
            try:
                with db.session_scope() as session:
                    db_u = session.query(User).filter(
                        (User.username == identifier) | (User.email == identifier.lower())
                    ).first()
                    if db_u:
                        user = store.get_user_by_id(db_u.user_id)
            except Exception as e:
                logger.warning(f"Error querying user for reset: {e}")

    if not user:
        raise HTTPException(status_code=404, detail="No account found with that username or email.")

    # Generate new hash
    salt = secrets.token_hex(16)
    new_hash = hashlib.sha256(f"{salt}{new_password}".encode()).hexdigest() + "$" + salt

    # Update in persistent store
    user.hashed_password = new_hash
    store._save()

    # Update in DB
    if db:
        try:
            with db.session_scope() as session:
                db_u = session.query(User).filter_by(user_id=user.user_id).first()
                if db_u:
                    db_u.hashed_password = new_hash
        except Exception as e:
            logger.warning(f"Failed to update password in DB: {e}")

    logger.info(f"Password reset successfully for user: {user.username} ({user.user_id})")
    return {
        "success": True,
        "message": "Password has been reset successfully. You can now sign in with your new password."
    }

