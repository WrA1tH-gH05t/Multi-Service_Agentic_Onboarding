"""
MinIO Bucket Reorganization Utility for DocIntake Platform Task 1.

Reorganizes cluttered, nested, or legacy file uploads into the clean, standardized:
    <name>_<idnumber>_<date>.<ext>
format visible in the MinIO Console.
"""

import sys
import os
import logging

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.storage import StorageService
from services.database import DatabaseService, Document

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reorganize_minio")


def main():
    print("=" * 65)
    print("  DocIntake Platform Task 1 — MinIO Clean Bucket Reorganizer")
    print("  Target Format: <name>_<idnumber>_<date>.<ext>")
    print("=" * 65)

    storage = StorageService()
    if not storage.is_connected and not storage.connect():
        print(f"[ERROR] Could not connect to MinIO at {storage.endpoint}")
        return 1

    print(f"[OK] Connected to MinIO bucket '{storage.bucket_name}' at {storage.endpoint}")

    db = DatabaseService()
    try:
        db.connect()
    except Exception as e:
        logger.warning(f"Database offline or unavailable: {e}. Will reorganize MinIO without DB updates.")
        db = None

    result = storage.reorganize_clustered_objects()
    migrated = result.get("migrated", [])
    skipped = result.get("skipped", [])
    errors = result.get("errors", [])

    # If DB is connected, update document rows pointing to the old keys
    if db and migrated:
        with db.session_scope() as session:
            for item in migrated:
                old_key = item["old_key"]
                new_key = item["new_key"]
                docs = session.query(Document).filter_by(object_name=old_key).all()
                for doc in docs:
                    doc.object_name = new_key
                if docs:
                    logger.info(f"Updated {len(docs)} DB record(s) from {old_key} -> {new_key}")

    print("\n--- Summary ---")
    print(f"Migrated / Cleaned: {len(migrated)} objects")
    print(f"Already Formatted:  {len(skipped)} objects")
    print(f"Errors:             {len(errors)} objects")

    if migrated:
        print("\nCleaned Files:")
        for item in migrated:
            print(f"  {item['old_key']}  -->  {item['new_key']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
