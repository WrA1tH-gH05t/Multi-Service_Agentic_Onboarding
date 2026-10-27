"""
Service catalogue routes.

Module Purpose & Role in the Project:
-------------------------------------
This module exposes endpoints for browsing the service catalogue. It provides client applications
and onboarding wizards with metadata about available onboarding tiers, their required documentation,
descriptions, availability status ('available' vs 'coming_soon'), and expected SLA turnaround times.

Interconnections with Other Files:
-----------------------------------
- `services/service_catalog.py`: Reads service offerings from `ServiceCatalogService` stored in `app_state["catalog"]`.
- `app/schemas.py`: Aligned with `ServiceCatalogItem` and `ServiceCatalogResponse`.
- `app/routes/wizard.py` & `app/routes/applications.py`: Downstream wizards and application processors
  validate selected `service_id` keys against the items published by this catalog.
- Consumed by the frontend UI to display service selection cards and onboarding requirements.
"""

import logging
from typing import Optional
from fastapi import APIRouter, Depends

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """
    Retrieve the singleton application state dictionary from the main module.

    Returns:
        dict: The shared `app_state` dictionary from `app.main`.

    Interconnections:
        - Lazily accesses `app_state["catalog"]` to avoid circular imports.
    """
    from app.main import app_state
    return app_state

@router.get("/services")
async def get_services():
    """
    Get all services (available + coming soon) aligned with frontend /services endpoint.

    Detailed Behavior:
    - Queries `ServiceCatalogService.get_all_services()` to retrieve all configured service definitions.
    - Iterates over each service object and serializes standard frontend schema:
      * `id`: Service identifier key (e.g., 'basic_registration', 'premium_crossborder', 'mobility_rental').
      * `name`: Display name.
      * `description`: Overview description.
      * `documents_required`: List of required document types.
      * `status`: Service availability ('available' or 'coming_soon').
      * `processing_time`: Estimated SLA time (defaults to 'Coming Soon' or 'Standard').
    - Returns structured payload under `{"data": {"services": [...]}}`.

    Returns:
        dict: Wrapped dictionary of services ready for UI consumption.

    Interconnections:
        - Calls `services.service_catalog.ServiceCatalogService:get_all_services`.
        - Drives frontend service selection views and documentation requirements checklists.
    """
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
