import sys, os, yaml
sys.path.insert(0, os.path.abspath('.'))

from services.database import DatabaseService, Base
from sqlalchemy import text

with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

db = DatabaseService(config)
db.connect()

with db.engine.connect() as conn:
    print('Connected to database successfully!')
    print('Engine URL:', db.engine.url)
    
    # 1. Update applications table
    conn.execute(text("ALTER TABLE applications ADD COLUMN IF NOT EXISTS child_profile_id VARCHAR(36);"))
    conn.execute(text("ALTER TABLE applications ADD COLUMN IF NOT EXISTS applicant_type VARCHAR(50) DEFAULT 'adult';"))
    conn.commit()
    print("Updated applications table columns.")

# 2. Create any missing tables (child_profiles, guardian_consents, etc.)
Base.metadata.create_all(db.engine)
print("Base.metadata.create_all completed.")

with db.engine.connect() as conn:
    if "postgresql" in str(db.engine.url):
        tables = [r[0] for r in conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")).fetchall()]
        print('PostgreSQL public tables:', sorted(tables))
        cols = [r[0] for r in conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='applications'")).fetchall()]
        print('Applications columns:', cols)
    else:
        tables = [r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
        print('SQLite tables:', sorted(tables))
