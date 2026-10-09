"""Health check endpoint."""

import logging
from typing import Optional
from fastapi import APIRouter

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

@router.get("/health")
async def health():
    """System health check."""
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
