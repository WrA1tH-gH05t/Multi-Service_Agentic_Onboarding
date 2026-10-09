"""Golden dataset routes."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import GoldenDatasetValidationRequest, GoldenDatasetSearchRequest

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

@router.get("/golden-dataset/summary")
async def get_golden_dataset_summary():
    """Get summary statistics of the golden dataset."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        summary = state["golden_dataset"].get_summary()
        return {"data": summary}
    except Exception as e:
        logger.error(f"Failed to get golden dataset summary: {e}")
        return {"error": str(e)}

@router.get("/golden-dataset/entries")
async def get_golden_dataset_entries(
    doc_type: Optional[str] = None,
    condition: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get golden dataset entries with optional filtering."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        gd = state["golden_dataset"]

        if doc_type:
            entries = gd.get_entries_by_type(doc_type)
        elif condition:
            entries = gd.get_entries_by_condition(condition)
        elif country:
            entries = gd.get_entries_by_country(country)
        else:
            entries = gd.entries

        result = []
        for entry in entries[:limit]:
            result.append({
                "id": entry.id,
                "document_type": entry.document_type,
                "capture_condition": entry.capture_condition,
                "source_note": entry.source_note,
                "golden_fields": entry.golden_fields,
                "validation_rules": entry.validation_rules,
            })

        return {"data": {"entries": result, "total": len(result)}}
    except Exception as e:
        logger.error(f"Failed to get golden dataset entries: {e}")
        return {"error": str(e)}

@router.get("/golden-dataset/entries/{entry_id}")
async def get_golden_dataset_entry(entry_id: str):
    """Get a specific golden dataset entry by ID."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        entry = state["golden_dataset"].get_entry_by_id(entry_id)
        if not entry:
            raise HTTPException(status_code=404, detail=f"Entry not found: {entry_id}")

        return {"data": {
            "id": entry.id,
            "document_type": entry.document_type,
            "capture_condition": entry.capture_condition,
            "source_note": entry.source_note,
            "golden_fields": entry.golden_fields,
            "validation_rules": entry.validation_rules,
        }}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get golden dataset entry: {e}")
        return {"error": str(e)}

@router.post("/golden-dataset/validate")
async def validate_extraction(req: GoldenDatasetValidationRequest):
    """Validate an extraction result against the golden dataset."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        result = state["golden_dataset"].validate_extraction(
            req.entry_id,
            req.fields
        )
        return {"data": result}
    except Exception as e:
        logger.error(f"Failed to validate extraction: {e}")
        return {"error": str(e)}

@router.get("/golden-dataset/search")
async def search_golden_dataset(query: str, limit: int = Query(default=10, ge=1, le=50)):
    """Search the golden dataset by keywords."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        results = state["golden_dataset"].search(query, limit=limit)
        return {"data": {"results": results, "query": query}}
    except Exception as e:
        logger.error(f"Failed to search golden dataset: {e}")
        return {"error": str(e)}

@router.get("/golden-dataset/field-names")
async def get_all_field_names():
    """Get all unique field names across the golden dataset."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        field_names = state["golden_dataset"].get_all_field_names()
        return {"data": {"field_names": field_names}}
    except Exception as e:
        logger.error(f"Failed to get field names: {e}")
        return {"error": str(e)}

@router.get("/golden-dataset/field-examples")
async def get_field_examples(field_name: str):
    """Get example values for a specific field."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        examples = state["golden_dataset"].get_field_examples(field_name)
        return {"data": {"field": field_name, "examples": examples}}
    except Exception as e:
        logger.error(f"Failed to get field examples: {e}")
        return {"error": str(e)}

@router.post("/golden-dataset/compare")
async def compare_golden_entries(entry1_id: str, entry2_id: str):
    """Compare two golden dataset entries."""
    state = get_state()
    if not state["golden_dataset"]:
        return {"error": "Golden dataset service not initialized"}

    try:
        comparison = state["golden_dataset"].compare_entries(entry1_id, entry2_id)
        if not comparison:
            raise HTTPException(status_code=404, detail="One or both entries not found")

        return {"data": comparison}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to compare golden entries: {e}")
        return {"error": str(e)}
