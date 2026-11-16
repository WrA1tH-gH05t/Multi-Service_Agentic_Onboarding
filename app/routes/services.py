"""Service catalogue routes."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Retrieve the singleton application state dictionary from the main module."""
    from app.main import app_state
    return app_state

@router.get("/services")
async def get_services():
    """Get all services (available + coming soon) aligned with frontend /services endpoint."""
    state = get_state()
    catalog = state["catalog"]
    all_services = catalog.get_all_services()
    services = []
    for s in all_services:
        services.append({
            "id": s.service_id,
            "name": s.name,
            "description": s.description,
            "documents_required": s.required_documents,
            "status": s.status.value,
            "processing_time": s.processing_time or ("Coming Soon" if s.status.value == "coming_soon" else "Standard")
        })
    return {"data": {"services": services}}
