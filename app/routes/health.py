"""Health check endpoint — system readiness and per-component status reporting."""

import logging
from typing import Optional
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state. Lazy import avoids circular dependencies."""
    from app.main import app_state
    return app_state

@router.get("/health")
async def health():
    """Return system health status for all major components."""
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


@router.get("/health/ready")
async def readiness():
    """Kubernetes / Docker readiness probe checking live MinIO and relational database responsiveness."""
    state = get_state()
    storage_ready = False
    storage_details = {}

    if state.get("storage") and hasattr(state["storage"], "readiness_probe"):
        try:
            storage_ready, storage_details = state["storage"].readiness_probe()
        except Exception as e:
            storage_details = {"ready": False, "reason": str(e)}
    else:
        storage_ready = bool(state.get("storage") and state["storage"].is_connected)
        storage_details = {"ready": storage_ready}

    is_ready = bool(state.get("ready") and storage_ready)
    status_code = 200 if is_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "ready": is_ready,
            "overall_status": "healthy" if state.get("ready") else "degraded",
            "storage": storage_details,
        },
    )


@router.get("/metrics/storage")
async def storage_metrics():
    """Telemetry and operation metrics for the MinIO object storage subsystem."""
    state = get_state()
    storage = state.get("storage")
    if storage and hasattr(storage, "get_telemetry"):
        return JSONResponse(content=storage.get_telemetry())
    return JSONResponse(
        status_code=503,
        content={"error": "storage service uninitialized or telemetry collector unavailable"},
    )
