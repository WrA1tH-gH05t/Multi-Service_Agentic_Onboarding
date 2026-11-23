import sqlite3

def run_migration():
    con = sqlite3.connect("data/app.db")
    cols = [c[1] for c in con.execute("PRAGMA table_info(applications)").fetchall()]
    if "child_profile_id" not in cols:
        con.execute("ALTER TABLE applications ADD COLUMN child_profile_id VARCHAR(36)")
        print("Added child_profile_id")
    if "applicant_type" not in cols:
        con.execute("ALTER TABLE applications ADD COLUMN applicant_type VARCHAR(50) DEFAULT 'adult'")
        print("Added applicant_type")
    con.commit()
    cols_after = [c[1] for c in con.execute("PRAGMA table_info(applications)").fetchall()]
    print("applications columns:", cols_after)
    con.close()

if __name__ == "__main__":
    run_migration()
