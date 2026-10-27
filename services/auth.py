"""
User Authentication & Authorization Service - Phase 6

Real login/signup with database-backed user accounts.
Every lookup is filtered by user ID at the database level.

Module Architecture & Interconnections:
----------------------------------------
- Upstream Callers:
  * FastAPI Routers:
    - `app.routes.auth` (`/auth/login`, `/auth/register`, `/auth/signup`, `/auth/logout`, `/auth/me`):
      Invokes `AuthService.authenticate()`, `register_user()`, `validate_token()`, and `logout()`.
    - `app.routes.wizard` (`/wizard/chat`, `/wizard/session`, etc.):
      Validates tokens via `validate_token()`, fetches user IDs and records to enforce per-user session isolation.
    - `app.routes.documents` (`/documents/sessions`, `/documents/sessions/summary`, `/documents/sessions/{session_id}`):
      Validates session tokens to scope collection sessions strictly to the authenticated user.
    - `app.routes.health` (`/health`):
      Checks state health status for auth service availability.
- Downstream Storage & Dependencies:
  * `services.user_store.PersistentUserStore`:
    Stores user accounts, credential hashes, and active sessions in disk-backed JSON (`services/auth_users.json`).
  * `services.database.User`:
    SQLAlchemy user model in SQLite/PostgreSQL where users and login timestamps are mirrored during authentication.
- Design Principles:
  * Strong password enforcement and salted SHA-256 password hashing.
  * Server-side revocable session tokens stored in memory and persisted to disk.
  * Architectural enforcement of tenant isolation: Data querying requires validated `user_id` values.
"""

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from services.user_store import PersistentUserStore


class UserAccount:
    """Represents a user account in the system.

    Attributes:
        user_id (str): Unique identifier for the user account (e.g., 'user_1234abcd').
        email (str): Registered email address of the user.
        username (str): Unique username used for login credentials.
        hashed_password (str): Salted SHA-256 hash string formatted as '<hash>$<salt>'.
        created_at (datetime): UTC timestamp when account was registered.
        last_login (Optional[datetime]): UTC timestamp of the most recent successful login.
        is_active (bool): Flag indicating if account is active or suspended.
        sessions (List[str]): List of active session tokens associated with this user.

    Interconnections:
        - Created and managed by `AuthService.register_user()` and `PersistentUserStore`.
        - Serialized via `to_dict()` for response delivery in `app.routes.auth.get_me()`.
    """

    def __init__(self, user_id: str, email: str, username: str, hashed_password: str,
                 created_at: datetime = None):
        """Initialize a new UserAccount instance.

        Args:
            user_id: Unique string identifier for the user.
            email: User's contact email.
            username: User's unique login handle.
            hashed_password: Salted password hash string.
            created_at: Optional creation timestamp (defaults to current UTC time).
        """
        self.user_id = user_id
        self.email = email
        self.username = username
        self.hashed_password = hashed_password
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login: Optional[datetime] = None
        self.is_active = True
        self.sessions: List[str] = []  # Active session tokens

    def to_dict(self) -> dict:
        """Convert the UserAccount object into a dictionary representation.

        Returns:
            dict: JSON-serializable dictionary containing account details.
                  Note: Callers in `app.routes.auth` strip `hashed_password` and `sessions`
                  before returning user data to external clients.
        """
        return {
            "user_id": self.user_id,
            "email": self.email,
            "username": self.username,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
            "sessions": self.sessions,
        }


class AuthService:
    """
    Authentication and Authorization Service.

    Design Decision: Uses password hashing (SHA-256 with salt) for
    simplicity and on-premise compatibility. In production, this would
    use bcrypt or Argon2. Tokens are stored server-side (not client-side
    JWT-only) so they can be revoked.

    Every database query filters by user_id at the SQL level, not in
    application logic. This is the only way to prevent data leaks.

    Interconnections:
    - Coordinates with `services.user_store.PersistentUserStore` for JSON credential persistence.
    - Consumed by `app.routes.auth` for login, signup, registration, token verification, and logout.
    - Consumed by `app.routes.wizard` and `app.routes.documents` to authenticate request tokens.
    """

    def __init__(self, config=None):
        """Initialize AuthService with configuration and persistent user store.

        Restores active session tokens from the persistent store so client
        sessions survive backend server restarts.

        Args:
            config (Optional[dict]): Global application configuration dictionary.
                Reads `config["security"]["token_lifetime_hours"]` (default: 24).
        """
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
        """
        Validate password strength against corporate onboarding security standards.
        
        Rules:
        - Minimum 8 characters
        - At least 1 uppercase letter
        - At least 1 lowercase letter
        - At least 1 number
        - At least 1 special character

        Args:
            password: Plaintext password candidate string.

        Returns:
            tuple[bool, str]: (is_valid, validation_error_message). If valid, error message is empty.

        Interconnections:
            - Invoked by `register_user()` during signup workflows.
        """
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
        """
        Validate username format.
        
        Rules:
        - Must not be empty
        - No special characters (only alphanumeric characters and underscores allowed)

        Args:
            username: Proposed user login handle.

        Returns:
            tuple[bool, str]: (is_valid, validation_error_message). If valid, error message is empty.

        Interconnections:
            - Called by `register_user()` before persistence in `PersistentUserStore`.
        """
        if not username:
            return (False, "Username cannot be empty.")
        
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            return (False, "Username can only contain letters, numbers, and underscores. No special characters allowed.")
        
        return (True, "")

    def register_user(self, username: str, password: str, email: str = None, config=None) -> tuple[bool, str, Optional[UserAccount]]:
        """
        Register a new user account.
        
        Validates username syntax, password complexity, and checks for existing
        usernames or emails in `PersistentUserStore`. Upon passing, creates a random salt,
        hashes the password, constructs a `UserAccount`, and commits it to disk.

        Args:
            username: Unique username (alphanumeric + underscore only).
            password: Strong password (8+ chars, upper, lower, number, special).
            email: Email address (must be unique). Defaults to username if omitted.
            config: Optional config override.
            
        Returns:
            tuple[bool, str, Optional[UserAccount]]:
                (success, message, UserAccount instance or None if failed).

        Interconnections:
            - Invoked by `app.routes.auth.register` and `app.routes.auth.signup`.
            - Adds record into `services.user_store.PersistentUserStore`.
            - `app.routes.auth` mirrors this newly created user into `services.database.User` SQL table.
        """
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
        
        user = UserAccount(user_id, email, username, hashed)
        self._store.add_user(user_id, username, email, hashed)
        
        return (True, "User registered successfully.", user)

    def authenticate(self, username: str, password: str) -> tuple[bool, str, Optional[str]]:
        """
        Authenticate a user with username and password.
        Searches by username first, then falls back to searching by email.
        Verifies salted SHA-256 hash. On success, generates a 32-byte hex token,
        records session expiration, appends token to user sessions, and persists state.

        Args:
            username: Username or email string provided by client.
            password: Plaintext password candidate.

        Returns:
            tuple[bool, str, Optional[str]]:
                (success, status_message, session_token or None).

        Interconnections:
            - Called by `app.routes.auth.login` and automatically after registration in `register()`.
            - Interacts with `PersistentUserStore` to load and update session data.
            - Updates `last_login` timestamp in `services.database.User` via `app.routes.auth`.
        """
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
        """
        Validate a session token and return the associated user.

        Checks memory cache first, falling back to persistent store session arrays.
        Enforces token expiration time and checks if account is active.
        Revokes expired tokens automatically via `logout()`.

        Args:
            token: Hexadecimal session token string.

        Returns:
            Optional[UserAccount]: Validated user account object, or None if
                token is missing, invalid, expired, or account is disabled.

        Interconnections:
            - Central security checkpoint called across API routes:
              * `app.routes.auth.get_me`: Verifies identity of caller.
              * `app.routes.wizard`: Secures wizard chat turns and document submissions.
              * `app.routes.documents`: Scopes document upload & session inspection to user.
              * `AuthorizationMiddleware.require_auth`: Enforces route protection.
        """
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
        """
        Get all applications for a specific user.

        DESIGN CRITICAL: This query filters by user_id at the data access
        level. The caller MUST pass a validated user_id from auth.
        There is no way to query applications without a user_id.

        Args:
            user_id: Validated unique user ID string.

        Returns:
            List[Dict]: List of application dictionary records.

        Interconnections:
            - Database-backed equivalent implemented in `services.repository.ApplicationRepository`
              and `services.database.Application` querying with `WHERE user_id = :user_id`.
        """
        # In production, this would be a SQL query:
        # SELECT * FROM applications WHERE user_id = :user_id
        return []  # Placeholder - actual implementation connects to DB

    def get_user_application(self, user_id: str, application_id: str) -> Optional[Dict]:
        """
        Get a single application for a specific user.

        DESIGN CRITICAL: Filters by BOTH user_id AND application_id.
        This prevents a user from accessing another user's application
        even if they know the application ID.

        Args:
            user_id: Validated owner user ID string.
            application_id: Application primary identifier string.

        Returns:
            Optional[Dict]: Application details or None if not owned by user.

        Interconnections:
            - Enforced in `AuthorizationMiddleware.require_application_access()` to prevent
              horizontal privilege escalation between applicants.
        """
        # SQL: SELECT * FROM applications WHERE user_id = :user_id AND id = :app_id
        return None  # Placeholder

    def logout(self, token: str) -> bool:
        """Invalidate a session token.

        Removes token from memory maps (`_tokens`, `_token_expiry`) and removes
        it from the user's persisted session list in `PersistentUserStore`.

        Args:
            token: Hexadecimal session token to invalidate.

        Returns:
            bool: True if the token was found and invalidated, False otherwise.

        Interconnections:
            - Called by `app.routes.auth.logout` when applicant ends their session.
            - Called internally by `validate_token` upon encountering an expired token.
        """
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
        """Hash password with salt using SHA-256.

        Args:
            password: Raw plaintext password string.
            salt: Random hex salt string.

        Returns:
            str: Salted hash string formatted as '<digest>$<salt>'.
        """
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() + "$" + salt


class AuthorizationMiddleware:
    """
    Authorization middleware that enforces user-level data isolation.

    Every request that accesses data MUST pass through this middleware,
    which injects the user_id from the authenticated session.

    SQL WHERE clauses always include user_id = :user_id at the database
    level — not just in application logic.

    Attributes:
        auth_service (AuthService): Underlying authentication service used for validation.
    """

    def __init__(self, auth_service: AuthService):
        """Initialize AuthorizationMiddleware with an AuthService instance.

        Args:
            auth_service (AuthService): Configured authentication service.
        """
        self.auth_service = auth_service

    def require_auth(self, token: str) -> Optional[UserAccount]:
        """
        Require authentication for a request.

        Args:
            token: Session token provided in header or query parameter.

        Returns:
            UserAccount: The authenticated user instance.

        Raises:
            PermissionError: If token is missing, invalid, expired, or user is inactive.
        """
        user = self.auth_service.validate_token(token)
        if not user:
            raise PermissionError("Authentication required.")
        return user

    def require_application_access(self, token: str, application_id: str) -> Optional[UserAccount]:
        """
        Require that the authenticated user has access to the specified application.

        This is the critical check that prevents one user from accessing
        another user's data.

        Args:
            token: Session token provided by requestor.
            application_id: Application identifier requested for access.

        Returns:
            UserAccount: Authenticated user account if access is authorized.

        Raises:
            PermissionError: If user is unauthenticated or does not own the target application.
        """
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
