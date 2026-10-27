"""
migrate_users.py - Migration Pipeline from Legacy JSON User Store to PostgreSQL.

Module Purpose & Role in the Project:
------------------------------------
This data migration script reads existing user credentials and profile records
from the legacy JSON storage file (`auth_users.json` via `PersistentUserStore`)
and imports them into the relational PostgreSQL `users` table via SQLAlchemy ORM.

Key Functionality:
  1. Conflict avoidance: Queries PostgreSQL before inserting each user; skips any account
     whose username or email already exists.
  2. Preserves password security hashes: Directly carries over existing bcrypt hashes
     without requiring users to reset passwords.
  3. Transaction isolation: Runs per-user insert/commit cycles with automatic rollback
     upon exception, logging failure details into an errors collection.

Interconnections with Other Components:
---------------------------------------
- `auth_users.json`: Flat-file user database accessed via `services.user_store.PersistentUserStore`.
- `services.database.DatabaseService`: Manages SQL session lifecycle and connection pool.
- `services.database.User`: The SQLAlchemy model representing rows in PostgreSQL `users`.
- `services.auth.AuthService`: Central authentication engine that now verifies credentials
  against the migrated database records.
- Backend Routes (`app.api.routes.auth`): Enables users migrated by this script to log in
  seamlessly through the API and Streamlit UI.

Usage:
    python -m scripts.migrate_users
"""

import os
import sys
import logging
import uuid
import yaml

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from services.database import Base, DatabaseService, User
from services.user_store import PersistentUserStore
from services.auth import AuthService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def migrate_users(db: DatabaseService, auth: AuthService) -> dict:
    """
    Migrate all users from the legacy auth_users.json store to PostgreSQL.

    Interconnections:
    - Reads legacy user dictionary from `PersistentUserStore.get_all_users()`.
    - Queries PostgreSQL `users` table to detect conflicts on `username` or `email`.
    - Inserts new `User` ORM entities and commits individual database transactions.
    - Called By: Root execution entry point in `scripts/migrate_users.py`.

    Args:
        db (DatabaseService): Connected database service instance.
        auth (AuthService): Initialized authentication service instance.

    Returns:
        dict: Summary metrics containing counts for `migrated`, `skipped`, and a list of `errors`.
    """
    # Load legacy users
    store = PersistentUserStore()
    legacy_users = store.get_all_users()

    migrated = 0
    skipped = 0
    errors = []

    for user_id, legacy_user in legacy_users.items():
        session = db.get_session()
        try:
            db_user = session.query(User).filter(
                (User.username == legacy_user.username) |
                (User.email == legacy_user.email)
            ).first()

            if db_user:
                logger.info(f"  Skipping '{legacy_user.username}' (already in DB)")
                skipped += 1
                continue

            # Create new user in DB
            new_user = User(
                user_id=legacy_user.user_id,
                username=legacy_user.username,
                email=legacy_user.email,
                hashed_password=legacy_user.hashed_password,
                created_at=legacy_user.created_at,
                is_active=legacy_user.is_active,
            )
            session.add(new_user)
            session.commit()
            logger.info(f"  Migrated '{legacy_user.username}' ({legacy_user.email})")
            migrated += 1

        except Exception as e:
            session.rollback()
            errors.append(f"Failed to migrate '{legacy_user.username}': {e}")
            logger.error(f"  Error: {e}")
        finally:
            session.close()

    return {"migrated": migrated, "skipped": skipped, "errors": errors}


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("User Migration: auth_users.json → PostgreSQL")
    logger.info("=" * 60)

    # Load config
    config_path = os.path.join(PROJECT_ROOT, "config.yaml")
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)

    # Initialize services
    db = DatabaseService(config)
    db.connect()
    logger.info(f"Database connected: {db.check_connection()}")

    auth = AuthService(config)
    logger.info("AuthService initialized")

    # Run migration
    result = migrate_users(db, auth)

    logger.info("=" * 60)
    logger.info(f"Migration complete:")
    logger.info(f"  Migrated: {result['migrated']}")
    logger.info(f"  Skipped:  {result['skipped']}")
    logger.info(f"  Errors:   {len(result['errors'])}")
    if result["errors"]:
        for err in result["errors"]:
            logger.error(f"    - {err}")
    logger.info("=" * 60)

    # If all OK, optionally update auth service to use DB instead of JSON
    if result["migrated"] > 0 and not result["errors"]:
        logger.info("Tip: Consider updating auth_users.json or removing it to avoid future conflicts.")
