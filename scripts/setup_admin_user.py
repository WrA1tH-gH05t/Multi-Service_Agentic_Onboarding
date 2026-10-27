"""
setup_admin_user.py - Bootstrap and Reset Script for Admin Account in auth_users.json.

Module Purpose & Role in the Project:
------------------------------------
This administrative provisioning utility resets the legacy authentication file (`auth_users.json`)
and establishes a single known administrative user (`arvinf256`). It wipes out any stale, test,
or orphaned user accounts in the JSON file.

Generated Account Credentials:
- Username: `arvinf256`
- Default Password: Read from ADMIN_PASSWORD environment variable (default: prompt or changeme)
- Email: `arvinf256@example.com`

Interconnections with Other Components:
---------------------------------------
- `auth_users.json`: Writes directly to this file, replacing its contents with the single admin record.
- `services.user_store.PersistentUserStore`: Reads `auth_users.json` when the legacy store is active.
- `scripts.migrate_users`: Can migrate this generated admin account into the PostgreSQL `users` table.
- Streamlit UI (`app.py`) & FastAPI Login (`app.api.routes.auth`): Allows immediate developer login
  with the seeded admin credentials.

Usage:
    python scripts/setup_admin_user.py
"""
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
    """
    Hash a plaintext password with a random hexadecimal salt using SHA-256.

    Interconnections:
    - Produces salted hash formatted as `<hex_digest>$<salt>` matching the format
      expected by `PersistentUserStore` password verification.

    Args:
        password (str): Plaintext password to hash.
        salt (str): Cryptographically random hexadecimal salt.

    Returns:
        str: Salted hash string in `<digest>$<salt>` format.
    """
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() + "$" + salt

def main() -> None:
    """
    Generate admin user profile, hash credentials, and overwrite auth_users.json.

    Interconnections:
    - Generates 16 bytes of secure random salt via `os.urandom(16).hex()`.
    - Creates user payload with active status and UTC timestamp.
    - Atomically overwrites `auth_users.json`.
    """
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
