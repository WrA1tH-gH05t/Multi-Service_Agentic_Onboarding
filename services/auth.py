"""User Authentication & Authorization Service - Phase 6"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from services.user_store import PersistentUserStore


class UserAccount:
    """Represents a user account in the system."""

    def __init__(self, user_id: str, email: str, username: str, hashed_password: str,
                 created_at: datetime = None, full_name: str = None, birthday: str = None, gender: str = None):
        self.user_id = user_id
        self.email = email
        self.username = username
        self.hashed_password = hashed_password
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login: Optional[datetime] = None
        self.is_active = True
        self.sessions: List[str] = []  # Active session tokens
        self.full_name = full_name or username
        self.birthday = birthday
        self.gender = gender

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "username": self.username,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
            "sessions": self.sessions,
            "full_name": self.full_name,
            "birthday": self.birthday,
            "gender": self.gender,
        }


class AuthService:
    """Authentication and Authorization Service."""

    def __init__(self, config=None):
        """Initialize AuthService with configuration and persistent user store."""
        self._config = config or {}
        self._store = PersistentUserStore()
        self._tokens: Dict[str, str] = {}  # token -> user_id
        self._token_expiry: Dict[str, datetime] = {}  # token -> expiry
        # Restore active tokens from persistent store so sessions survive server restart
        for uid, user in self._store._users.items():
            for tok in getattr(user, "sessions", []):
                self._tokens[tok] = uid

    @staticmethod
    def validate_password(password: str) -> tuple[bool, str]:
        """Validate password strength against corporate onboarding security standards."""
        if len(password) < 8:
            return (False, "Password must be at least 8 characters long.")
        
        if not re.search(r'[A-Z]', password):
            return (False, "Password must contain at least one uppercase letter.")
        
        if not re.search(r'[a-z]', password):
            return (False, "Password must contain at least one lowercase letter.")
        
        if not re.search(r'[0-9]', password):
            return (False, "Password must contain at least one number.")
        
        if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\'\\:"|,.<>\/?`~]', password):
            return (False, "Password must contain at least one special character.")
        
        return (True, "")

    @staticmethod
    def validate_username(username: str) -> tuple[bool, str]:
        """Validate username format."""
        if not username:
            return (False, "Username cannot be empty.")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return (False, "Username can only contain letters, numbers, and underscores. No special characters allowed.")
        
        return (True, "")

    def register_user(self, username: str, password: str, email: str = None, config=None, full_name: str = None, birthday: str = None, gender: str = None) -> tuple[bool, str, Optional[UserAccount]]:
        """Register a new user account."""
        # Validate username format
        valid, msg = self.validate_username(username)
        if not valid:
            return (False, msg, None)
        
        # Validate password strength
        valid, msg = self.validate_password(password)
        if not valid:
            return (False, msg, None)
        
        # Check if username already exists
        if self._store.username_exists(username):
            return (False, "Username is already taken.", None)
        
        # Check if email already registered
        if email and self._store.email_exists(email):
            return (False, "This email is already registered with us.", None)
        
        # Create user
        user_id = f"user_{secrets.token_hex(8)}"
        salt = secrets.token_hex(16)
        hashed = self._hash_password(password, salt)
        
        # Default email to username if not provided
        if not email:
            email = username
        
        user = UserAccount(user_id, email, username, hashed, full_name=full_name or username, birthday=birthday, gender=gender)
        self._store.add_user(user_id, username, email, hashed, full_name=full_name or username, birthday=birthday, gender=gender)
        
        return (True, "User registered successfully.", user)

    def authenticate(self, username: str, password: str) -> tuple[bool, str, Optional[str]]:
        """Authenticate a user with username and password."""
        # Try by username first
        user = self._store.get_user_by_name(username)
        
        # Fallback: try by email
        if not user:
            user = self._store.get_user_by_email(username)
        
        if not user:
            return (False, "Invalid username or password.", None)

        if not user.is_active:
            return (False, "Account is disabled.", None)

        salt = user.hashed_password.split("$")[1] if "$" in user.hashed_password else ""
        if not salt:
            return (False, "Invalid username or password.", None)

        entered_hash = self._hash_password(password, salt)
        if entered_hash != user.hashed_password:
            return (False, "Invalid username or password.", None)

        # Create session token
        token = secrets.token_hex(32)
        self._tokens[token] = user.user_id
        # Token expiry: 24 hours default
        token_lifetime_hours = self._config.get("security", {}).get("token_lifetime_hours", 24)
        self._token_expiry[token] = datetime.now(timezone.utc) + timedelta(hours=token_lifetime_hours)
        user.last_login = datetime.now(timezone.utc)
        user.sessions.append(token)
        self._store._save()  # Persist login time

        return (True, "Authentication successful.", token)

    def validate_token(self, token: str) -> Optional[UserAccount]:
        """Validate a session token and return the associated user."""
        user_id = self._tokens.get(token)
        if not user_id:
            # Fallback: check if token exists in any user's persistent sessions
            for uid, user_obj in self._store._users.items():
                if token in getattr(user_obj, "sessions", []):
                    self._tokens[token] = uid
                    user_id = uid
                    break
        if not user_id:
            return None

        # Check expiration if tracked
        if token in self._token_expiry:
            if datetime.now(timezone.utc) > self._token_expiry[token]:
                self.logout(token)
                return None

        # Get user by ID from store
        user = self._store.get_user_by_id(user_id)
        
        if not user or not user.is_active:
            return None

        return user

    def get_user_applications(self, user_id: str) -> List[Dict]:
        """Get all applications for a specific user."""
        # In production, this would be a SQL query:
        # SELECT * FROM applications WHERE user_id = :user_id
        return []  # Placeholder - actual implementation connects to DB

    def get_user_application(self, user_id: str, application_id: str) -> Optional[Dict]:
        """Get a single application for a specific user."""
        # SQL: SELECT * FROM applications WHERE user_id = :user_id AND id = :app_id
        return None  # Placeholder

    def logout(self, token: str) -> bool:
        """Invalidate a session token."""
        user_id = self._tokens.get(token)
        if user_id:
            user = self._store.get_user_by_id(user_id)
            if user and token in user.sessions:
                user.sessions.remove(token)
                self._store._save()
            if token in self._tokens:
                del self._tokens[token]
            if token in self._token_expiry:
                del self._token_expiry[token]
            return True
        if token in self._tokens:
            del self._tokens[token]
        if token in self._token_expiry:
            del self._token_expiry[token]
        return False

    def _hash_password(self, password: str, salt: str) -> str:
        """Hash password with salt using SHA-256."""
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() + "$" + salt


class AuthorizationMiddleware:
    """Authorization middleware that enforces user-level data isolation."""

    def __init__(self, auth_service: AuthService):
        """Initialize AuthorizationMiddleware with an AuthService instance."""
        self.auth_service = auth_service

    def require_auth(self, token: str) -> Optional[UserAccount]:
        """Require authentication for a request."""
        user = self.auth_service.validate_token(token)
        if not user:
            raise PermissionError("Authentication required.")
        return user

    def require_application_access(self, token: str, application_id: str) -> Optional[UserAccount]:
        """Require that the authenticated user has access to the specified application."""
        user = self.require_auth(token)

        # Database-level check: SELECT * FROM applications
        # WHERE user_id = :user_id AND id = :app_id
        # If this returns zero rows, the user does not have access.
        app = self.auth_service.get_user_application(user.user_id, application_id)
        if not app:
            raise PermissionError(
                f"Application {application_id} not found or you do not have access to it."
            )

        return user
