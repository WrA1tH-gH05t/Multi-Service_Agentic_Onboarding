"""
Seed services, service_documents, and service_definitions into PostgreSQL.

Pulls ServiceDefinition objects from ServiceCatalogService and persists them
into the DB models: services, service_documents, service_definitions.

Usage:
    python -m scripts.seed_services
"""

import os
import sys
import logging
import yaml

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from services.database import DatabaseService, Service, ServiceDocument, ServiceDefinition as DBServiceDefinition
from services.service_catalog import ServiceCatalogService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def seed_services(db: DatabaseService, catalog: ServiceCatalogService) -> dict:
    """Seed all services from the catalogue into PostgreSQL.

    Returns:
        dict with keys: created, updated, skipped
    """
    all_services = catalog.get_all_services()
    session = db.get_session()
    created = 0
    updated = 0
    skipped = 0

    for svc_def in all_services:
        # Check if already exists
        db_svc = session.query(Service).filter_by(service_id=svc_def.service_id).first()

        if db_svc:
            # Update existing
            db_svc.name = svc_def.name
            db_svc.status = svc_def.status.value
            db_svc.description = svc_def.description
            db_svc.required_documents = svc_def.required_documents
            updated += 1
            logger.info(f"  Updated '{svc_def.name}' ({svc_def.service_id})")
        else:
            # Create new
            db_svc = Service(
                service_id=svc_def.service_id,
                name=svc_def.name,
                status=svc_def.status.value,
                description=svc_def.description,
                required_documents=svc_def.required_documents,
            )
            session.add(db_svc)
            created += 1
            logger.info(f"  Created '{svc_def.name}' ({svc_def.service_id})")

        # Seed service_documents for each required document
        for slot_idx, doc_type in enumerate(svc_def.required_documents):
            slot = f"doc_{slot_idx}"
            db_doc = session.query(ServiceDocument).filter_by(
                service_id=svc_def.service_id,
                slot=slot,
            ).first()

            if db_doc:
                db_doc.accepted_types = svc_def.allowed_alternatives.get(doc_type, [])
                db_doc.mandatory = True
            else:
                db_doc = ServiceDocument(
                    service_id=svc_def.service_id,
                    slot=slot,
                    accepted_types=svc_def.allowed_alternatives.get(doc_type, []),
                    mandatory=True,
                )
                session.add(db_doc)

        # Seed service_definitions (placeholder for RAG chunks)
        if svc_def.definition_doc_path and os.path.exists(svc_def.definition_doc_path):
            db_def = session.query(DBServiceDefinition).filter_by(
                service_id=svc_def.service_id,
                source_file=svc_def.definition_doc_path,
            ).first()
            if not db_def:
                db_def = DBServiceDefinition(
                    id=f"def_{svc_def.service_id}",
                    service_id=svc_def.service_id,
                    source_file=svc_def.definition_doc_path,
                    chunks=[],  # Will be populated when RAG pipeline runs
                    embeddings=[],
                )
                session.add(db_def)

        session.flush()

    session.commit()
    session.close()

    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Service Seeding: ServiceCatalogService → PostgreSQL")
    logger.info("=" * 60)

    with open(os.path.join(PROJECT_ROOT, "config.yaml"), "r") as f:
        config = yaml.safe_load(f)

    db = DatabaseService(config)
    db.connect()
    logger.info(f"Database connected: {db.check_connection()}")

    catalog = ServiceCatalogService()
    logger.info(f"Catalog loaded: {len(catalog.get_all_services())} services")

    result = seed_services(db, catalog)

    logger.info("=" * 60)
    logger.info(f"Seeding complete:")
    logger.info(f"  Created:  {result['created']}")
    logger.info(f"  Updated:  {result['updated']}")
    logger.info(f"  Skipped:  {result['skipped']}")
    logger.info("=" * 60)
