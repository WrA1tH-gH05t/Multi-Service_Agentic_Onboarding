"""
Persistent user storage - survives server restarts.
Stores users as JSON in auth_users.json.

Module Architecture & Interconnections:
----------------------------------------
- Upstream Callers:
  * `services.auth.AuthService`:
    Directly instantiates and queries `PersistentUserStore` for authenticating logins,
    registering accounts, checking username/email uniqueness, and persisting session tokens.
  * `app.routes.wizard`:
    References `auth._store.get_user_by_id(user_id)` to resolve user metadata (username, email)
    when synchronizing application state and auditing submissions.
- Storage & Data Flow:
  * Manages reading and writing to `services/auth_users.json`.
  * Provides in-memory indexed dictionaries (`_user_by_name`, `_user_by_email`, `_user_by_id`)
    for O(1) lookups by username, email, or user ID.
  * Pairs with SQLAlchemy's `User` model in `services.database` as a redundant/local file-based store.
"""
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_users.json")


class PersistentUserStore:
    """Manages persistent JSON-file storage of user credentials and active sessions.

    Maintains dual in-memory hash maps for fast lookup by username, email, and user ID.
    Synchronizes updates immediately to disk (`auth_users.json`).

    Attributes:
        filepath (str): Absolute file path to the JSON storage file.
        _users (Dict[str, UserAccountDict]): Primary mapping of user_id -> UserAccountDict.
        _user_by_name (Dict[str, str]): Fast lookup index of username -> user_id.
        _user_by_email (Dict[str, str]): Fast lookup index of email -> user_id.
        _user_by_id (Dict[str, UserAccountDict]): Reference mapping of user_id -> UserAccountDict.

    Interconnections:
        - Instantiated by `services.auth.AuthService.__init__()`.
        - Accessed by `app.routes.wizard` during onboarding session validation.
    """

    def __init__(self, filepath=None):
        """Initialize PersistentUserStore with file path and load stored accounts.

        Args:
            filepath (Optional[str]): Custom path to JSON file; defaults to `services/auth_users.json`.
        """
        self.filepath = filepath or USERS_FILE
        self._users = {}
        self._user_by_name = {}      # username -> user_id
        self._user_by_email = {}     # email -> user_id
        self._user_by_id = {}        # user_id -> UserAccountDict
        self._load()
    
    def _load(self):
        """Load users from disk and populate in-memory lookup indexes.

        Converts ISO format datetime strings back into Python `datetime` objects.
        Resets storage gracefully to empty dicts if the file is missing or corrupt.
        """
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r") as f:
                    data = json.load(f)
                    for uid, ud in data.items():
                        # Convert string datetimes back to datetime objects
                        if isinstance(ud.get("created_at"), str):
                            ud["created_at"] = datetime.fromisoformat(ud["created_at"])
                        if isinstance(ud.get("last_login"), str):
                            ud["last_login"] = datetime.fromisoformat(ud["last_login"])
                        self._users[uid] = UserAccountDict(**ud)
                        self._user_by_id[uid] = self._users[uid]
                    # Build lookup indexes
                    for uid, ud in data.items():
                        uname = ud.get("username", ud.get("email", ""))
                        email = ud.get("email", "")
                        if uname:
                            self._user_by_name[uname] = uid
                        if email:
                            self._user_by_email[email] = uid
            except Exception:
                self._users = {}
                self._user_by_name = {}
                self._user_by_email = {}
                self._user_by_id = {}
    
    def _save(self):
        """Save all active user accounts and sessions to disk in JSON format.

        Serializes each `UserAccountDict` instance via `.to_dict()` with 2-space indentation.
        """
        data = {uid: ua.to_dict() for uid, ua in self._users.items()}
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
    
    def add_user(self, user_id: str, username: str, email: str, hashed_password: str, created_at=None):
        """Add a new user with username and email and write changes immediately to disk.

        Args:
            user_id: Unique generated user ID string.
            username: User login name.
            email: User's contact email.
            hashed_password: Salted SHA-256 hash.
            created_at (Optional[datetime]): Account creation timestamp.

        Interconnections:
            - Called by `services.auth.AuthService.register_user()`.
        """
        self._users[user_id] = UserAccountDict(
            user_id, email, hashed_password, created_at, username=username
        )
        self._user_by_name[username] = user_id
        self._user_by_email[email] = user_id
        self._user_by_id[user_id] = self._users[user_id]
        self._save()
    
    def get_user_by_name(self, username: str) -> Optional["UserAccountDict"]:
        """Get user account by username.

        Args:
            username: Target username string.

        Returns:
            Optional[UserAccountDict]: Matching user or None if not found.

        Interconnections:
            - Called by `services.auth.AuthService.authenticate()`.
        """
        user_id = self._user_by_name.get(username)
        return self._users.get(user_id) if user_id else None
    
    def get_user_by_email(self, email: str) -> Optional["UserAccountDict"]:
        """Get user account by email address.

        Args:
            email: Target email string.

        Returns:
            Optional[UserAccountDict]: Matching user or None if not found.

        Interconnections:
            - Called as a fallback during authentication when username lookup yields no match.
        """
        user_id = self._user_by_email.get(email)
        return self._users.get(user_id) if user_id else None
    
    def get_user_by_id(self, user_id: str) -> Optional["UserAccountDict"]:
        """Get user account by unique user ID.

        Args:
            user_id: Primary user ID string.

        Returns:
            Optional[UserAccountDict]: Matching user or None if not found.

        Interconnections:
            - Called by `services.auth.AuthService.validate_token()` and `logout()`.
            - Called by `app.routes.wizard` to resolve applicant details for human review / audits.
        """
        return self._user_by_id.get(user_id)
    
    def username_exists(self, username: str) -> bool:
        """Check if username is already taken.

        Args:
            username: Candidate username string.

        Returns:
            bool: True if already registered, False otherwise.

        Interconnections:
            - Called by `services.auth.AuthService.register_user()` during pre-registration checks.
        """
        return username in self._user_by_name
    
    def email_exists(self, email: str) -> bool:
        """Check if email is already registered.

        Args:
            email: Candidate email string.

        Returns:
            bool: True if already registered, False otherwise.

        Interconnections:
            - Called by `services.auth.AuthService.register_user()` to prevent duplicate accounts.
        """
        return email in self._user_by_email
    
    def user_exists(self, identifier: str) -> bool:
        """Check if either username or email is already taken.

        Args:
            identifier: Candidate username or email string.

        Returns:
            bool: True if existing account matches username or email, False otherwise.
        """
        return identifier in self._user_by_name or identifier in self._user_by_email
    
    def get_all_users(self) -> Dict[str, "UserAccountDict"]:
        """Retrieve all registered users dictionary.

        Returns:
            Dict[str, UserAccountDict]: Mapping of all user IDs to their user records.
        """
        return self._users


class UserAccountDict:
    """Lightweight data class representing a persisted user record.

    Attributes:
        user_id (str): Unique user identifier.
        email (str): Registered email address.
        hashed_password (str): Salted password hash string.
        username (str): Login username (defaults to email if not provided).
        created_at (datetime): Account creation timestamp (UTC).
        last_login (Optional[datetime]): Timestamp of last successful authentication.
        is_active (bool): Whether the account is active or disabled.
        sessions (List[str]): List of active session tokens belonging to the user.

    Interconnections:
        - Returned by `PersistentUserStore` to `services.auth.AuthService`.
        - Compatible with `UserAccount` attributes expected by callers.
    """

    def __init__(self, user_id, email, hashed_password, created_at=None, username=None, last_login=None, is_active=True, sessions=None):
        """Initialize UserAccountDict instance.

        Args:
            user_id: Unique user identifier.
            email: User email.
            hashed_password: Salted password hash.
            created_at (Optional[datetime]): Account creation time.
            username (Optional[str]): User handle.
            last_login (Optional[datetime]): Timestamp of last login.
            is_active (bool): Account enabled state.
            sessions (Optional[List[str]]): List of active session tokens.
        """
        self.user_id = user_id
        self.email = email
        self.hashed_password = hashed_password
        self.username = username or email
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
        self.is_active = is_active
        self.sessions = sessions or []
    
    def to_dict(self) -> dict:
        """Serialize user account data into JSON-compatible dictionary.

        Returns:
            dict: Dictionary with stringified ISO timestamps and session array.
        """
        return {
            "user_id": self.user_id,
            "email": self.email,
            "username": self.username,
            "hashed_password": self.hashed_password,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
            "sessions": self.sessions,
        }
