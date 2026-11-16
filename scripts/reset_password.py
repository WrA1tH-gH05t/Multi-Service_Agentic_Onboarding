"""Utility script: list users and reset a password by user ID or email."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras

DB_DSN = os.getenv("DATABASE_URL", "postgresql://intake:intake@localhost:5432/doc_intake")

try:
    import bcrypt
    BCRYPT_OK = True
except ImportError:
    BCRYPT_OK = False

def hash_password(password: str) -> str:
    if BCRYPT_OK:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    import hashlib
    salt = os.getenv("PASSWORD_SALT", "app_salt_v2")
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

conn = psycopg2.connect(DB_DSN, cursor_factory=psycopg2.extras.RealDictCursor)
cur = conn.cursor()

# List all users
cur.execute("SELECT id, email, full_name FROM users ORDER BY id")
rows = cur.fetchall()
print("\nAll users:")
for r in rows:
    print(f"  id={r['id']}  email={r['email']}  name={r['full_name']}")

# Reset password for arvinf256 (match by email containing arvinf or full_name)
TARGET_EMAIL = None
for r in rows:
    if "arvinf" in r["email"].lower() or "arvinf256" in r["email"].lower() or "arvin" in r["full_name"].lower():
        TARGET_EMAIL = r["email"]
        TARGET_ID = r["id"]
        print(f"\nFound user: id={r['id']} email={r['email']} name={r['full_name']}")
        break

if not TARGET_EMAIL:
    print("\nUser arvinf256 not found by name/email. Resetting by ID=1 as fallback.")
    cur.execute("SELECT id, email, full_name FROM users LIMIT 1")
    r = cur.fetchone()
    if r:
        TARGET_EMAIL = r["email"]
        TARGET_ID = r["id"]
        print(f"Fallback user: id={r['id']} email={r['email']}")

NEW_PASSWORD = "Classifiedteam1$"
new_hash = hash_password(NEW_PASSWORD)

cur.execute(
    "UPDATE users SET password_hash = %s WHERE id = %s",
    (new_hash, TARGET_ID)
)
conn.commit()
print(f"\nPassword reset for user id={TARGET_ID} ({TARGET_EMAIL})")
print(f"New password: {NEW_PASSWORD}")
print(f"Hash method: {'bcrypt' if BCRYPT_OK else 'sha256'}")

cur.close()
conn.close()
