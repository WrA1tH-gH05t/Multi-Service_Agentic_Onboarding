"""
Golden dataset routes — benchmark reference data for document extraction evaluation.

Role in Project:
    Exposes the MIDV-500 golden dataset (ground-truth field values for identity documents)
    as a queryable REST API. The golden dataset is used for two purposes:
    1. **Offline benchmarking**: Comparing extraction outputs to known-good values to
       measure ExtractionLadder accuracy on passport, national ID, and driving licence samples.
    2. **Online validation grounding**: The `/validate` endpoint allows the ValidationAgent
       to check extracted fields against reference entries during application processing.

Cross-File Interconnections:
    - `services.golden_dataset.GoldenDatasetService` — the backing service loaded at startup
      in `app.main`. All endpoints delegate data retrieval and comparison to this service.
    - `agents.validation_agent.ValidationAgent` — calls `GoldenDatasetService.validate_extraction`
      when a `golden_dataset` entry is supplied in the application data.
    - `app.routes.validation.validate_application` — optionally passes a golden dataset entry
      to the ValidationAgent via `entry_id`.
    - `app.schemas.GoldenDatasetValidationRequest` / `GoldenDatasetSearchRequest` — Pydantic
      models for request body validation.
    - `app.main.app_state` — the `golden_dataset` service instance is fetched from here.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import GoldenDatasetValidationRequest, GoldenDatasetSearchRequest

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state. Lazy import avoids circular dependencies."""
    from app.main import app_state
    return app_state

@router.get("/golden-dataset/summary")
async def get_golden_dataset_summary():
    """Return aggregate statistics about the loaded golden dataset.

    Delegates to `GoldenDatasetService.get_summary()` which counts entries by document
    type, capture condition, and country of origin.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.get_summary`

    Returns:
        `{"data": <summary_dict>}` or `{"error": "not initialized"}` in degraded mode.
    """
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
    """List golden dataset entries with optional filtering.

    Supports three exclusive filter dimensions: document type, capture condition
    (e.g. 'original', 'screen'), or country code. Returns the first `limit` matches.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.get_entries_by_type`
        - `services.golden_dataset.GoldenDatasetService.get_entries_by_condition`
        - `services.golden_dataset.GoldenDatasetService.get_entries_by_country`

    Args:
        doc_type: Filter to a specific document class (e.g. 'passport', 'national_id').
        condition: Filter to a capture condition.
        country: ISO country code filter.
        limit: Maximum number of results.

    Returns:
        `{"data": {"entries": [...], "total": N}}`
    """
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
    """Fetch a single golden dataset entry by its unique ID.

    Used by the ValidationAgent and benchmark scripts to look up a specific reference
    record when validating extracted fields against known-good values.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.get_entry_by_id`

    Args:
        entry_id: Unique identifier of the golden entry.

    Returns:
        `{"data": <entry_dict>}` or HTTP 404 if not found.
    """
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
    """Validate extracted document fields against a golden dataset reference entry.

    Compares extracted field values to the ground-truth values stored in the golden entry
    and returns a per-field match report with an overall accuracy score.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.validate_extraction`
        - `app.schemas.GoldenDatasetValidationRequest` — request model (entry_id, fields dict).

    Args:
        req: Request body containing `entry_id` and a `fields` dict of extracted values.

    Returns:
        `{"data": <validation_result_dict>}` with per-field pass/fail and overall accuracy.
    """
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
    """Full-text keyword search across golden dataset entry fields and metadata.

    Used by the admin/benchmark UI to locate reference entries for specific document types,
    countries, or field values without knowing the exact entry_id.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.search`

    Args:
        query: Free-text search string.
        limit: Maximum number of results to return.

    Returns:
        `{"data": {"results": [...], "query": str}}`
    """
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
    """Return all unique field names that appear across all golden dataset entries.

    Used by the benchmark tool and admin UI to display available fields for filtering
    and to verify that the ExtractionLadder extracts the expected field names.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.get_all_field_names`

    Returns:
        `{"data": {"field_names": [str, ...]}}`
    """
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
    """Return example values for a specific field from across the golden dataset.

    Useful for understanding value formats, date formats, and how fields are spelled
    across different document types (e.g. how 'date_of_birth' looks on different IDs).

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.get_field_examples`

    Args:
        field_name: The field to look up examples for (e.g. 'surname', 'date_of_birth').

    Returns:
        `{"data": {"field": str, "examples": [str, ...]}}`
    """
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
    """Compare two golden dataset entries field-by-field.

    Useful for identifying differences between similar document captures (e.g. original
    vs. screen-captured versions) and understanding how field values vary.

    Interconnections:
        - `services.golden_dataset.GoldenDatasetService.compare_entries`

    Args:
        entry1_id: ID of the first golden entry.
        entry2_id: ID of the second golden entry.

    Returns:
        `{"data": <comparison_dict>}` or HTTP 404 if one or both entries are not found.
    """
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
