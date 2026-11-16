"""Persistent user storage - survives server restarts."""
import json
import os
import re
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_users.json")


class PersistentUserStore:
    """Manages persistent JSON-file storage of user credentials and active sessions."""

    def __init__(self, filepath=None):
        """Initialize PersistentUserStore with file path and load stored accounts."""
        self.filepath = filepath or USERS_FILE
        self._users = {}
        self._user_by_name = {}      # username -> user_id
        self._user_by_email = {}     # email -> user_id
        self._user_by_id = {}        # user_id -> UserAccountDict
        self._load()
    
    def _load(self):
        """Load users from disk and populate in-memory lookup indexes."""
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
        """Save all active user accounts and sessions to disk in JSON format."""
        data = {uid: ua.to_dict() for uid, ua in self._users.items()}
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)
    
    def add_user(self, user_id: str, username: str, email: str, hashed_password: str, created_at=None, full_name=None, birthday=None, gender=None):
        """Add a new user with username and email and write changes immediately to disk."""
        self._users[user_id] = UserAccountDict(
            user_id, email, hashed_password, created_at, username=username, full_name=full_name, birthday=birthday, gender=gender
        )
        self._user_by_name[username] = user_id
        self._user_by_email[email] = user_id
        self._user_by_id[user_id] = self._users[user_id]
        self._save()
    
    def get_user_by_name(self, username: str) -> Optional["UserAccountDict"]:
        """Get user account by username."""
        user_id = self._user_by_name.get(username)
        return self._users.get(user_id) if user_id else None
    
    def get_user_by_email(self, email: str) -> Optional["UserAccountDict"]:
        """Get user account by email address."""
        user_id = self._user_by_email.get(email)
        return self._users.get(user_id) if user_id else None
    
    def get_user_by_id(self, user_id: str) -> Optional["UserAccountDict"]:
        """Get user account by unique user ID."""
        return self._user_by_id.get(user_id)
    
    def username_exists(self, username: str) -> bool:
        """Check if username is already taken."""
        return username in self._user_by_name
    
    def email_exists(self, email: str) -> bool:
        """Check if email is already registered."""
        return email in self._user_by_email
    
    def user_exists(self, identifier: str) -> bool:
        """Check if either username or email is already taken."""
        return identifier in self._user_by_name or identifier in self._user_by_email
    
    def get_all_users(self) -> Dict[str, "UserAccountDict"]:
        """Retrieve all registered users dictionary."""
        return self._users


class UserAccountDict:
    """Lightweight data class representing a persisted user record."""

    def __init__(self, user_id, email, hashed_password, created_at=None, username=None, last_login=None, is_active=True, sessions=None, full_name=None, birthday=None, gender=None, **kwargs):
        """Initialize UserAccountDict instance."""
        self.user_id = user_id
        self.email = email
        self.hashed_password = hashed_password
        self.username = username or email
        self.created_at = created_at or datetime.now(timezone.utc)
        self.last_login = last_login
        self.is_active = is_active
        self.sessions = sessions or []
        self.full_name = full_name or kwargs.get("name") or self.username
        self.birthday = birthday
        self.gender = gender
    
    def to_dict(self) -> dict:
        """Serialize user account data into JSON-compatible dictionary."""
        return {
            "user_id": self.user_id,
            "email": self.email,
            "username": self.username,
            "hashed_password": self.hashed_password,
            "created_at": self.created_at.isoformat(),
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "is_active": self.is_active,
            "sessions": self.sessions,
            "full_name": self.full_name,
            "birthday": self.birthday,
            "gender": self.gender,
        }
