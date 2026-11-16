import hashlib
import json
import secrets
import psycopg2

salt = secrets.token_hex(16)
password = "Classifiedteam1$"
hashed = hashlib.sha256(f"{salt}{password}".encode()).hexdigest() + "$" + salt

# 1. Update services/auth_users.json
users_path = "services/auth_users.json"
with open(users_path, "r", encoding="utf-8") as f:
    data = json.load(f)

found = False
for uid, uinfo in data.items():
    if uinfo.get("username") == "arvinf256":
        uinfo["hashed_password"] = hashed
        found = True
        print(f"Updated auth_users.json for {uid} (arvinf256)")
        break

if found:
    with open(users_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
else:
    print("Warning: arvinf256 not found in auth_users.json")

# 2. Update PostgreSQL users table
conn = psycopg2.connect("postgresql://intake:intake_secret_2026@localhost:5432/doc_intake")
cur = conn.cursor()
cur.execute(
    "UPDATE users SET hashed_password = %s WHERE username = %s",
    (hashed, "arvinf256")
)
conn.commit()
print(f"Updated PostgreSQL users table, rows affected: {cur.rowcount}")
cur.close()
conn.close()

print(f"Password for arvinf256 successfully reset to: {password}")
print(f"New hash: {hashed}")
