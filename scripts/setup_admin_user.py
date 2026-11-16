"""setup_admin_user.py - Bootstrap and Reset Script for Admin Account in auth_users.json."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

# Resolve path to the project directory
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
auth_users_file = os.path.join(project_dir, "auth_users.json")

# If running from services/ directory, adjust
if not os.path.exists(auth_users_file):
    auth_users_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth_users.json")

def hash_password(password: str, salt: str) -> str:
    """Hash a plaintext password with a random hexadecimal salt using SHA-256."""
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() + "$" + salt

def main() -> None:
    """Generate admin user profile, hash credentials, and overwrite auth_users.json."""
    admin_password = os.getenv("ADMIN_PASSWORD", "Classifiedteam1$")
    salt = os.urandom(16).hex()
    hashed_password = hash_password(admin_password, salt)
    
    now = datetime.now(timezone.utc).isoformat()
    
    admin_user = {
        "user_id": "admin_arvinf256",
        "email": "arvinf256@example.com",
        "username": "arvinf256",
        "hashed_password": hashed_password,
        "created_at": now,
        "last_login": None,
        "is_active": True,
        "sessions": []
    }
    
    # Write only the admin user
    with open(auth_users_file, "w") as f:
        json.dump({
            "admin_arvinf256": admin_user
        }, f, indent=2)
    
    print(f"✅ Created user 'arvinf256'")
    print(f"✅ Deleted all other accounts")
    print(f"✅ Auth file updated: {auth_users_file}")

if __name__ == "__main__":
    main()
