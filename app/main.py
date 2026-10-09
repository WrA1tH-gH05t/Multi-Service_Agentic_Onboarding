"""
Main application entry point.

Changes:
- Removed EmbeddingService (vision model handles embeddings internally)
- Removed SearchService (no more vector DB — vision model handles extraction directly)
- GenerationService now uses Qwen2.5-VL 3B vision model
- Added StorageService (MinIO object storage) to replace local filesystem uploads
"""

import sys
import os
import json
import yaml
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from services.ocr import OCRService
from services.generation import GenerationService
from services.validation import FileValidator
from services.storage import StorageService
from services.auth import AuthService
from services.service_catalog import ServiceCatalogService, ServiceStatus
from services.golden_dataset import GoldenDatasetService
from services.policy_service import PolicyService, get_policy_service, get_grounding_context
from agents.collection_agent import CollectionAgent
from agents.validation_agent import ValidationAgent
from services.database import DatabaseService
from services.repository import Repository
from services.wizard import WizardStateManager

# Import routers BEFORE app_state and app are defined to avoid circular imports
# (routes → services → auth → get_state → app_state would be circular)
from app.routes import router as api_router

logger = logging.getLogger(__name__)

# Load configuration
config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)

# Application state
app_state = {
    "ocr": None,
    "generation": None,
    "validator": None,
    "storage": None,
    "auth": None,
    "catalog": None,
    "golden_dataset": None,
    "policy_service": None,
    "collection_agent": None,
    "validation_agent": None,
    "database": None,
    "repository": None,
    "wizard_manager": None,
    "ready": False,
}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifecycle — startup and shutdown."""
    # Startup
    logger.info("Starting services...")

    try:
        app_state["ocr"] = OCRService(config.get("ocr", {}))
        app_state["generation"] = GenerationService(config.get("ollama", {}))
        app_state["validator"] = FileValidator(config.get("upload", {}).get("max_file_size_mb", 200) * 1024 * 1024)
        app_state["storage"] = StorageService(config.get("storage", {}))
        app_state["auth"] = AuthService(config)
        app_state["catalog"] = ServiceCatalogService()

        # Initialize policy service — loads all policy docs from docs/
        app_state["policy_service"] = PolicyService()
        available_policies = app_state["policy_service"].list_available_policies()
        logger.info(f"Policy service loaded {len(available_policies)} policies: {', '.join(available_policies)}")

        # Initialize golden dataset service
        golden_config = config.get("golden_dataset", {})
        golden_path = golden_config.get("dataset_path", "data/golden_dataset.json")
        if os.path.exists(golden_path):
            try:
                app_state["golden_dataset"] = GoldenDatasetService()
                app_state["golden_dataset"].load(golden_path)
                logger.info(f"Golden dataset loaded: {len(app_state['golden_dataset'].entries)} entries")
            except Exception as gd_err:
                logger.warning(f"Failed to load golden dataset: {gd_err}")
        else:
            logger.warning(f"Golden dataset file not found at {golden_path}")

        # Initialize database service (Phase 3)
        app_state["database"] = DatabaseService(config)
        app_state["database"].connect()
        logger.info(f"Database connected: {app_state['database'].check_connection()}")

        # Initialize repository layer (WP8: user-scoped data access)
        app_state["repository"] = Repository(app_state["database"])
        logger.info("Repository layer initialized")

        # Initialize collection agent (Phase 2) with repository for session persistence
        app_state["collection_agent"] = CollectionAgent(repository=app_state["repository"])
        logger.info("Collection agent initialized with repository persistence")

        # Initialize validation agent (Phase 2)
        app_state["validation_agent"] = ValidationAgent()
        logger.info("Validation agent initialized")

        # Initialize wizard manager (Phase 3 — Basic Registration)
        app_state["wizard_manager"] = WizardStateManager()
        logger.info("Wizard manager initialized")

        # Load identity pairs for validation testing
        pairs_path = "data/identity_pairs.json"
        if os.path.exists(pairs_path):
            try:
                with open(pairs_path, "r") as f:
                    pairs_data = json.load(f)
                matched = pairs_data.get("matched_pairs", [])
                mismatched = pairs_data.get("mismatched_pairs", [])
                app_state["validation_agent"].register_matched_pairs(matched)
                app_state["validation_agent"].register_mismatched_pairs(mismatched)
                logger.info(f"Identity pairs loaded: {len(matched)} matched, {len(mismatched)} mismatched")
            except Exception as pairs_err:
                logger.warning(f"Failed to load identity pairs: {pairs_err}")
        else:
            logger.warning(f"Identity pairs file not found at {pairs_path}")

        # Background health check
        async def check_services():
            try:
                status = await app_state["generation"].check_connection()
                logger.info(f"Health: generation={status}")
                app_state["ready"] = status in ("healthy", "model_not_found")
                if status == "model_not_found":
                    logger.warning("Vision model not loaded — please run: ollama pull qwen2.5vl:3b")
                elif status != "healthy":
                    logger.warning(f"System not fully ready: generation={status}")
            except Exception as e:
                logger.error(f"Health check failed: {e}")
                app_state["ready"] = False

        asyncio.create_task(check_services())
        logger.info("Health check task started; ready flag will be set once services are verified")

    except Exception as e:
        logger.error(f"Service startup failed: {e}")
        app_state["ready"] = False

    # If only MinIO was the problem, app_state["storage"] exists but is disconnected.
    # Still allow the app to serve (filesystem fallback) — just not ready for uploads.
    if not app_state["ready"] and app_state["storage"] is not None:
        if not app_state["storage"]._connected:
            logger.warning("MinIO unavailable but other services started OK — app will run with limited functionality.")
            app_state["ready"] = False  # uploads will fail, but list/auth/chat still work

    yield

    # Shutdown
    logger.info("Shutting down services...")
    await asyncio.gather(
        app_state["generation"].close(),
        return_exceptions=True
    )
    logger.info("Shutdown complete")

app = FastAPI(
    title="Multi-Service Agentic Onboarding",
    description="On-premise document intake and onboarding system with vision AI",
    version="3.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routes
from app.routes import router as api_router
app.include_router(api_router, prefix="/api/v1")

# Serve React frontend
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

# Resolve to project root (parent of app/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "app", "static")
os.makedirs(STATIC_DIR, exist_ok=True)
print(f"Serving static files from: {STATIC_DIR}")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", include_in_schema=False)
async def serve_frontend():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
