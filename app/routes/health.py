"""
Health check endpoint — system readiness and per-component status reporting.

Role in Project:
    Provides a single `/health` GET endpoint that returns the operational status of every
    major system component. The frontend (`app.py` Streamlit sidebar) polls this endpoint
    periodically to display a live status panel, and DevOps/Docker health checks use it to
    decide whether the container is ready to serve traffic.

Cross-File Interconnections:
    - `services.generation.GenerationService.check_connection` — pings the Qwen vision
      model (Ollama) to see if the LLM backend is responding.
    - `services.storage.StorageService.check_connection` — verifies MinIO connectivity.
    - `services.database.DatabaseService.check_connection` — verifies PostgreSQL connectivity.
    - `app.main.app_state["ready"]` — the `ready` boolean is set by the startup lifespan
      in `app.main` and reflects whether storage, database, and generation are all healthy.
      It is used to return `"status": "healthy"` vs `"status": "degraded"`.

Response Shape:
    {
        "status": "healthy" | "degraded",
        "services": {
            "generation": str,     # "healthy" | "unavailable" | <error>
            "storage": str,
            "ocr": "healthy" | "unavailable",
            "auth": "healthy" | "unavailable",
            "catalog": "healthy" | "unavailable",
            "golden_dataset": "healthy" | "unavailable",
            "database": str,
        }
    }
"""

import logging
from typing import Optional
from fastapi import APIRouter

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state. Lazy import avoids circular dependencies."""
    from app.main import app_state
    return app_state

@router.get("/health")
async def health():
    """Return system health status for all major components.

    Probes each component individually so a single failure does not hide the status of
    other healthy components. Non-responsive components return "unavailable" rather than
    raising an exception, enabling graceful degraded-mode operation.

    Checks performed:
        - GenerationService.check_connection() — async ping to Ollama/Qwen LLM.
        - StorageService.check_connection() — sync ping to MinIO.
        - DatabaseService.check_connection() — sync ping to PostgreSQL.
        - Presence check for OCR, auth, catalog, golden_dataset services.

    Returns:
        JSONResponse with overall status and per-service status dict.
    """
    state = get_state()

    generation_status = "unknown"
    if state["generation"]:
        try:
            generation_status = await state["generation"].check_connection()
        except Exception:
            generation_status = "unavailable"

    storage_status = "unavailable"
    if state["storage"]:
        try:
            storage_status = state["storage"].check_connection()
        except Exception:
            storage_status = "unavailable"

    db_status = "unavailable"
    if state["database"]:
        try:
            db_status = state["database"].check_connection()
        except Exception:
            db_status = "unavailable"

    from fastapi.responses import JSONResponse
    return JSONResponse(content={
        "status": "healthy" if state["ready"] else "degraded",
        "services": {
            "generation": generation_status,
            "storage": storage_status,
            "ocr": "healthy" if state["ocr"] else "unavailable",
            "auth": "healthy" if state["auth"] else "unavailable",
            "catalog": "healthy" if state["catalog"] else "unavailable",
            "golden_dataset": "healthy" if state["golden_dataset"] else "unavailable",
            "database": db_status,
        }
    })
