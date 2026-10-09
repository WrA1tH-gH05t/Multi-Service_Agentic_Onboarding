"""Service catalogue routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

@router.get("/services")
async def get_services():
    """Get available services — aligned with frontend /services endpoint."""
    state = get_state()
    catalog = state["catalog"]
    available = catalog.get_available_services()
    services = []
    for s in available:
        services.append({
            "id": s.service_id,
            "name": s.name,
            "description": s.description,
            "documents_required": s.required_documents,
            "status": s.status.value,
            "processing_time": s.processing_time
        })
    return {"data": {"services": services}}
