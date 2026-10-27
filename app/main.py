"""
Main application entry point for the Multi-Service Agentic Onboarding system.

Module Purpose & Role in the Project:
-------------------------------------
This module serves as the primary FastAPI application factory and bootstrap orchestrator.
It is responsible for:
1. Initializing and configuring application state (`app_state`), including all core services:
   - OCRService: Vision & document text recognition.
   - GenerationService: LLM-based reasoning and field extraction (Ollama / Qwen2.5-VL 7B).
   - FileValidator: Content and structure validation for uploaded files.
   - StorageService: Object storage client connecting to MinIO with background reconnection.
   - AuthService: User credential authentication, password hashing, and session tokens.
   - ServiceCatalogService: Directory of onboarding services, requirements, and policy answers.
   - GoldenDatasetService: In-memory repository of benchmarked ground-truth identity documents.
   - PolicyService: Grounding engine for compliance policies and rules.
   - DatabaseService & Repository: SQLAlchemy persistence, session scopes, and thread-safe DB transactions.
   - CollectionAgent & ValidationAgent: Multi-agent orchestrators managing intake and cross-document validation.
   - WizardStateManager: In-memory session manager tracking user progress through multi-step onboarding.
2. Managing the application lifecycle via an async lifespan context manager (`lifespan`).
3. Configuring middleware, including CORS handling and an upload storage pre-check middleware
   (`require_storage_for_uploads`) that returns HTTP 503 if MinIO storage is unreachable.
4. Mounting modular sub-routers under `/api/v1` via `app.routes.router`.
5. Serving operator health checks (`/health`) and static single-page application assets for the frontend UI.

Interconnections with Other Files:
-----------------------------------
- `config.yaml`: Read at module load time to retrieve database, storage, LLM, and upload settings.
- `app/routes/__init__.py`: Imports root `api_router`, which bundles sub-routers for auth, applications,
  chat, collection, documents, golden dataset, health, services, validation, and wizard.
- `services/*`: Instantiates all core system services during startup and binds them to `app_state`.
- `agents/*`: Instantiates `CollectionAgent` and `ValidationAgent` bound with database repository.
- `app/static/`: Mounts static files and serves `index.html` to web browser clients.

Changes in this version:
-------------------------
- Each service starts independently. One failing service no longer stops the services after it
  (before, a MinIO or database error left the agents and repository as None).
- StorageService never raises on startup. A background watchdog keeps retrying MinIO, so starting
  the API before Docker finished no longer leaves uploads broken until the next restart.
- Upload endpoints return HTTP 503 with a friendly `detail` when storage is down, instead of
  running into a 500 crash. There is no silent fallback to the local filesystem.
- /health reports which components are up. `ready` is computed from storage, database and model.
- Shutdown no longer crashes when a service never started.
"""

import os
import json
import yaml
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from services.ocr import OCRService
from services.generation import GenerationService
from services.validation import FileValidator
from services.storage import StorageService, StorageUnavailable
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
# (routes -> services -> auth -> get_state -> app_state would be circular)
from app.routes import router as api_router

logger = logging.getLogger(__name__)

# Load configuration
config_path = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
with open(config_path, "r") as f:
    config = yaml.safe_load(f)

# Application state dictionary storing singleton references to services and agents
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
    "generation_status": "unknown",
    "startup_errors": {},
    "storage_task": None,
    "ready": False,
}

STORAGE_DOWN_MESSAGE = "File storage is temporarily unavailable. Please try again in a moment."


def _safe_init(name: str, factory):
    """
    Safely initialize a single service or dependency with error containment.

    Detailed Behavior:
    - Invokes the `factory` callable to create the service instance.
    - If successful, assigns the instance into `app_state[name]` and returns it.
    - If an exception occurs, logs the error, records the failure reason in
      `app_state["startup_errors"][name]`, sets `app_state[name] = None`, and allows
      subsequent service initialization to proceed without terminating startup.

    Parameters:
        name (str): Key identifying the service in `app_state`.
        factory (callable): Zero-argument factory function returning the initialized service.

    Returns:
        Any: The initialized service object, or None if initialization failed.

    Interconnections:
        - Invoked during `lifespan` startup for each service in `services/*` and `agents/*`.
    """
    try:
        obj = factory()
        app_state[name] = obj
        return obj
    except Exception as e:
        logger.exception(f"Service '{name}' failed to start")
        app_state["startup_errors"][name] = f"{type(e).__name__}: {str(e)[:200]}"
        app_state[name] = None
        return None


def _database_ok() -> bool:
    """
    Check whether the configured relational database service is connected and operational.

    Detailed Behavior:
    - Retrieves the database service from `app_state["database"]`.
    - If uninitialized or None, returns False.
    - Calls `db.check_connection()` and inspects the resulting status string.
    - Returns True only if the connection is active and does not indicate error or disconnection.

    Returns:
        bool: True if database connection is healthy, False otherwise.

    Interconnections:
        - Calls `DatabaseService.check_connection()` in `services.database`.
        - Used by `refresh_ready()` and operator `/health` endpoint.
    """
    db = app_state.get("database")
    if db is None:
        return False
    try:
        status = str(db.check_connection()).strip().lower()
        return not status.startswith(("unavailable", "error", "unhealthy", "disconnected", "failed", "none"))
    except Exception:
        return False


def refresh_ready() -> bool:
    """
    Compute and update the overall system readiness flag in `app_state["ready"]`.

    Detailed Behavior:
    - Evaluates the combined health of four critical pillars:
      1. Vision AI generation model (`generation_status == "healthy"`).
      2. Object storage (`storage.is_connected` is True).
      3. Relational database (`_database_ok()` is True).
      4. Core orchestration agents (`repository`, `collection_agent`, `validation_agent` are present).
    - Sets `app_state["ready"]` to True only when all components are active.

    Returns:
        bool: The updated readiness status of the application.

    Interconnections:
        - Checked by document upload and wizard processing endpoints in `app/routes/documents.py`
          and `app/routes/wizard.py` to prevent processing under degraded infrastructure.
    """
    storage = app_state.get("storage")
    app_state["ready"] = bool(
        app_state.get("generation_status") == "healthy"
        and storage is not None and storage.is_connected
        and _database_ok()
        and app_state.get("repository") is not None
        and app_state.get("collection_agent") is not None
        and app_state.get("validation_agent") is not None
    )
    return app_state["ready"]


async def _storage_watchdog():
    """
    Background worker loop that continuously monitors and recovers object storage connectivity.

    Detailed Behavior:
    - Periodically checks if the MinIO storage backend is connected.
    - If already connected, verifies health every 30 seconds via `storage.check_connection()`.
    - If disconnected (e.g., MinIO Docker container started slowly or restarted), attempts
      reconnection with an exponential backoff delay (doubling up to 60 seconds).
    - Re-evaluates overall system readiness via `refresh_ready()` upon each status change.

    Lifecycle:
    - Spawned as an `asyncio.Task` during application startup in `lifespan`.
    - Cancelled cleanly upon application shutdown.

    Interconnections:
        - Interacts with `StorageService` in `services.storage`.
        - Prevents API startup failures caused by delayed storage initialization in Docker/K8s.
    """
    delay = 5
    while True:
        storage = app_state.get("storage")
        if storage is None:
            return
        try:
            if storage.is_connected:
                await asyncio.sleep(30)
                status = await asyncio.to_thread(storage.check_connection)
                if status != "healthy":
                    logger.warning(f"MinIO health check: {status}")
            else:
                if await asyncio.to_thread(storage.connect):
                    delay = 5
                else:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 60)
            refresh_ready()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Storage watchdog error")
            await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI application lifespan context manager governing startup and graceful shutdown.

    Detailed Behavior:
    Startup Phase:
    - Initializes services sequentially using `_safe_init`:
      * OCR, Vision generation, Upload file validator, MinIO storage, Auth, Service catalog.
      * PolicyService: Loads markdown compliance and business rules.
      * GoldenDatasetService: Loads benchmark ground-truth identity entries.
      * DatabaseService: Establishes database connection, creates tables, and syncs initial users
        from `services/auth_users.json` if necessary.
      * Repository: Instantiates repository pattern layer and seeds default validation rules into DB.
      * CollectionAgent & ValidationAgent: Wires multi-agent state machines with DB repository.
      * WizardStateManager: Initializes in-memory wizard session store.
    - Launches background tasks:
      * Asynchronous health probe checking Ollama vision model availability.
      * Background `_storage_watchdog` task for MinIO connection resilience.
    - Yields control to handle incoming HTTP requests.

    Shutdown Phase:
    - Cancels background storage watchdog and generation probe tasks.
    - Closes HTTP sessions and resources held by `GenerationService`.
    - Completes graceful termination.

    Parameters:
        app (FastAPI): The root FastAPI application instance.

    Interconnections:
        - Sets up all dependencies consumed by route modules under `app/routes/`.
    """
    logger.info("Starting services...")

    _safe_init("ocr", lambda: OCRService(config.get("ocr", {})))
    _safe_init("generation", lambda: GenerationService(config.get("ollama", {})))
    _safe_init("validator", lambda: FileValidator(config.get("upload", {}).get("max_file_size_mb", 200) * 1024 * 1024))
    _safe_init("storage", lambda: StorageService(config.get("storage", {})))
    _safe_init("auth", lambda: AuthService(config))
    _safe_init("catalog", lambda: ServiceCatalogService())

    def _policy():
        svc = PolicyService()
        logger.info(f"Policy service loaded {len(svc.list_available_policies())} policies")
        return svc
    _safe_init("policy_service", _policy)

    def _golden():
        golden_path = config.get("golden_dataset", {}).get("dataset_path", "data/golden_dataset.json")
        if not os.path.exists(golden_path):
            logger.warning(f"Golden dataset file not found at {golden_path}")
            return None
        svc = GoldenDatasetService()
        svc.load(golden_path)
        logger.info(f"Golden dataset loaded: {len(svc.entries)} entries")
        return svc
    _safe_init("golden_dataset", _golden)

    def _database():
        db = DatabaseService(config)
        db.connect()
        logger.info(f"Database connected: {db.check_connection()}")
        try:
            users_file = os.path.join(os.path.dirname(__file__), "..", "services", "auth_users.json")
            if os.path.exists(users_file):
                with open(users_file, "r") as f:
                    u_data = json.load(f)
                with db.session_scope() as session:
                    from services.database import User
                    for uid, ud in u_data.items():
                        if not session.query(User).filter_by(user_id=uid).first():
                            session.add(User(
                                user_id=uid,
                                username=ud.get("username", uid),
                                email=ud.get("email"),
                                hashed_password=ud.get("hashed_password", "disabled"),
                            ))
                logger.info(f"Synchronized {len(u_data)} users to database.")
        except Exception as e:
            logger.warning(f"Could not sync users to database: {e}")
        return db
    _safe_init("database", _database)

    if app_state["database"] is not None:
        def _repository():
            repo = Repository(app_state["database"])
            repo.load_default_validation_rules()
            logger.info("Repository ready; validation rules loaded from config.yaml into DB")
            return repo
        _safe_init("repository", _repository)

    if app_state["repository"] is not None:
        _safe_init("collection_agent", lambda: CollectionAgent(repository=app_state["repository"]))
    else:
        logger.error("Collection agent not started: repository unavailable")

    def _validation_agent():
        agent = ValidationAgent()
        pairs_path = "data/identity_pairs.json"
        if os.path.exists(pairs_path):
            with open(pairs_path, "r") as f:
                pairs = json.load(f)
            agent.register_matched_pairs(pairs.get("matched_pairs", []))
            agent.register_mismatched_pairs(pairs.get("mismatched_pairs", []))
        return agent
    _safe_init("validation_agent", _validation_agent)

    _safe_init("wizard_manager", lambda: WizardStateManager())

    storage = app_state["storage"]
    if storage is not None and not storage.is_connected:
        logger.warning("MinIO is not reachable yet. The API will start; uploads return 503 until it connects.")
    if app_state["startup_errors"]:
        logger.error(f"Startup errors: {app_state['startup_errors']}")

    async def check_services():
        """Asynchronously probe the vision generation model status."""
        try:
            status = await app_state["generation"].check_connection()
            app_state["generation_status"] = status
            logger.info(f"Health: generation={status}")
        except Exception as e:
            app_state["generation_status"] = "unavailable"
            logger.error(f"Health check failed: {e}")
        refresh_ready()

    health_task = asyncio.create_task(check_services()) if app_state["generation"] is not None else None
    if storage is not None:
        app_state["storage_task"] = asyncio.create_task(_storage_watchdog())

    yield

    logger.info("Shutting down services...")
    for task in (app_state.get("storage_task"), health_task):
        if task is not None:
            task.cancel()
    if app_state.get("generation") is not None:
        await asyncio.gather(app_state["generation"].close(), return_exceptions=True)
    logger.info("Shutdown complete")


# Primary FastAPI application instance
app = FastAPI(
    title="Multi-Service Agentic Onboarding",
    description="On-premise document intake and onboarding system with vision AI",
    version="3.0.0",
    lifespan=lifespan,
)


# Registered BEFORE CORS middleware so that 503 responses still carry proper CORS headers
@app.middleware("http")
async def require_storage_for_uploads(request: Request, call_next):
    """
    Pre-flight middleware intercepting document uploads to ensure storage availability.

    Detailed Behavior:
    - Filters incoming requests for `POST` calls containing `/upload` under `/api/v1/`.
    - If storage is uninitialized or disconnected, calls `storage.require()` in a thread
      to trigger an immediate connection attempt.
    - If storage remains unavailable, short-circuits the pipeline with an HTTP 503 Service
      Unavailable JSONResponse including a `Retry-After: 5` header and friendly error message.
    - Otherwise, allows the request to pass cleanly to the downstream route handler.

    Parameters:
        request (Request): The incoming FastAPI HTTP request.
        call_next (callable): Downstream middleware/endpoint handler.

    Returns:
        Response: The HTTP response generated by the downstream handler or HTTP 503 JSONResponse.

    Interconnections:
        - Prevents document routes in `app/routes/documents.py` and `app/routes/wizard.py`
          from attempting file operations when MinIO is down.
    """
    path = request.url.path
    if request.method == "POST" and path.startswith("/api/v1/") and "/upload" in path:
        storage = app_state.get("storage")
        available = False
        if storage is not None:
            try:
                await asyncio.to_thread(storage.require)   # retries the connection, rate limited
                available = True
            except StorageUnavailable:
                available = False
        if not available:
            return JSONResponse(
                status_code=503,
                content={"success": False, "detail": STORAGE_DOWN_MESSAGE, "reason_code": "storage_unavailable"},
                headers={"Retry-After": "5"},
            )
    return await call_next(request)


# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include all API sub-routers under /api/v1 prefix
app.include_router(api_router, prefix="/api/v1")


@app.get("/health", include_in_schema=False)
async def health():
    """
    Operator health check endpoint reporting component statuses and readiness.

    Detailed Behavior:
    - Recalculates `app_state["ready"]` via `refresh_ready()`.
    - Returns a sanitised JSON dictionary describing:
      * Overall readiness flag (`ready`).
      * Individual component availability (storage, database, model, repository, agents).
      * Sorted list of service names that encountered startup failures (without exposing credentials).

    Returns:
        dict: Diagnostic health dictionary for infrastructure orchestrators (Kubernetes / Docker).

    Interconnections:
        - Supplements the API router health endpoint at `/api/v1/health` (`app/routes/health.py`).
    """
    storage = app_state.get("storage")
    refresh_ready()
    return {
        "ready": app_state["ready"],
        "components": {
            "storage": bool(storage and storage.is_connected),
            "database": _database_ok(),
            "model": app_state.get("generation_status"),
            "repository": app_state.get("repository") is not None,
            "collection_agent": app_state.get("collection_agent") is not None,
            "validation_agent": app_state.get("validation_agent") is not None,
        },
        "failed_to_start": sorted(app_state["startup_errors"].keys()),
    }


# Serve React frontend. Resolve to project root (parent of app/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(PROJECT_ROOT, "app", "static")
os.makedirs(STATIC_DIR, exist_ok=True)
logger.info(f"Serving static files from: {STATIC_DIR}")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
async def serve_frontend():
    """
    Root route serving the single-page application (SPA) entrypoint.

    Detailed Behavior:
    - Returns `app/static/index.html` as a FileResponse to client browsers.

    Returns:
        FileResponse: The compiled frontend HTML entry document.
    """
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))
