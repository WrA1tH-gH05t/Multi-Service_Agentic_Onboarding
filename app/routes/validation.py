"""
Validation and FAQ routes — document validation API and grounded FAQ answering.

Role in Project:
    Provides two distinct but related capabilities:

    1. **Application Validation (`/validate`)**: Accepts a completed application's document
       data and runs the full ValidationAgent pipeline — checking mandatory fields, expiry
       dates, cross-document name/DOB consistency, and optional golden dataset comparisons.

    2. **FAQ Answering (`/faq`)**: Answers user questions about Moro Hub services using a
       two-tier strategy:
       a. Fast path: The ServiceCatalogService's built-in FAQ matcher returns a high-confidence
          direct answer if one exists.
       b. LLM path: If confidence is below threshold, the PolicyService provides grounded
          context from policy markdown documents, and the GenerationService (Qwen LLM) answers
          using only that context — never hallucinating service details.

Cross-File Interconnections:
    - `agents.validation_agent.ValidationAgent.validate_application` — the core validation
      engine invoked by the `/validate` endpoint.
    - `services.service_catalog.ServiceCatalogService.answer_faq` — first-pass FAQ lookup
      against deterministic service definitions.
    - `services.policy_service.get_grounding_context` — retrieves relevant policy sections to
      ground LLM FAQ answers, preventing hallucination.
    - `services.generation.GenerationService.generate_response` — LLM fallback for FAQ answers
      not covered by the service catalog.
    - `services.golden_dataset.GoldenDatasetService.get_entry_by_id` — optional golden entry
      data passed to the ValidationAgent for benchmark validation.
    - `app.schemas.ValidationRequest`, `FAQRequest`, `FAQResponse` — Pydantic schemas.
    - `app.main.app_state` — all service instances fetched from global state.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.schemas import ValidationRequest, FAQRequest, FAQResponse, ChatResponse

from services.policy_service import get_grounding_context

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state. Lazy import prevents circular dependencies."""
    from app.main import app_state
    return app_state

# In-memory application store for validation
_application_store: dict = {}

# --- Validation ---
@router.post("/validate")
async def validate_application(req: ValidationRequest):
    """Validate a completed application's documents using the ValidationAgent.

    Assembles application data from the request (or falls back to `_application_store`)
    and delegates to `ValidationAgent.validate_application` for a multi-stage check:
        - Document count and completeness (mandatory documents present).
        - Mandatory field extraction (e.g. name, date_of_birth, document_number).
        - Expiry date validation (documents must not be expired).
        - Cross-document consistency (name + DOB must match across all submitted docs).
        - Optional golden dataset comparison (if `entry_id` is provided).

    Interconnections:
        - `agents.validation_agent.ValidationAgent.validate_application`
        - `services.golden_dataset.GoldenDatasetService.get_entry_by_id` — if entry_id provided.
        - `app.schemas.ValidationRequest` — request Pydantic model.

    Args:
        req: Pydantic model with application_id, optional documents list, and optional entry_id.

    Returns:
        `{"success": True, "data": <validation_report_dict>, "message": "Validation passed/failed"}`
        HTTP 503 if ValidationAgent is not available.
        HTTP 404 if application_id is not found and no inline documents provided.

    Phase 2: Validates document count, mandatory fields, expiry dates,
    cross-document field matching (name/DOB), and golden dataset.
    """
    state = get_state()
    
    validation_agent = state.get("validation_agent")
    if not validation_agent:
        raise HTTPException(status_code=503, detail="Validation agent not available")
    
    # Look up application data
    app = None
    if req.application_id in _application_store:
        app = _application_store[req.application_id]
    elif req.application_id.startswith("pair_") or req.application_id.startswith("mismatch_"):
        # Test pairs pass through directly
        app = {"service_id": "premium_crossborder"}
    elif req.documents:
        # Standalone validation: documents provided inline, no pre-registered app needed
        app = {"service_id": "premium_crossborder"}
    else:
        raise HTTPException(status_code=404, detail=f"Application not found: {req.application_id}")
    
    # Build application data for validation
    from agents.validation_agent import ValidationReport
    app_data = {
        "application_id": req.application_id,
        "service_id": app.get("service_id", ""),
        "required_documents": app.get("required_documents", []),
        "documents": [],
        "golden_dataset": None,
    }
    
    # Add document data from req.documents or _application_store
    if hasattr(req, "documents") and req.documents:
        app_data["documents"] = req.documents
    elif "documents" in app:
        app_data["documents"] = app["documents"]
    
    # Add golden dataset if available
    if state.get("golden_dataset") and req.entry_id:
        entry = state["golden_dataset"].get_entry_by_id(req.entry_id)
        if entry:
            app_data["golden_dataset"] = {entry.document_type: entry.golden_fields}
    
    # Run validation
    report = validation_agent.validate_application(app_data)
    report_dict = report.to_dict()
    
    return {
        "success": True,
        "data": report_dict,
        "message": f"Validation {'passed' if report.result.value == 'pass' else 'failed'}",
    }

# --- FAQ ---
@router.post("/faq")
async def query_faq(req: FAQRequest):
    """Answer a user's question about Moro Hub services using grounded, policy-anchored responses.

    Resolution order:
        1. `ServiceCatalogService.answer_faq(question)` — deterministic lookup in the service
           catalog's FAQ database. Returns immediately if confidence > 0.8.
        2. `PolicyService.get_grounding_context(question)` — retrieves relevant sections from
           the policy markdown documents to prevent the LLM from hallucinating answers.
        3. `GenerationService.generate_response` — Qwen LLM generates an answer using ONLY
           the provided policy context. Explicitly instructed not to invent service details.

    The `sources` list in the response tells the UI where the answer came from (policy doc name),
    enabling transparent attribution.

    Interconnections:
        - `services.service_catalog.ServiceCatalogService.answer_faq`
        - `services.policy_service.get_grounding_context`
        - `services.generation.GenerationService.generate_response`
        - `app.schemas.FAQRequest`, `FAQResponse`

    Args:
        req: Pydantic model with `question` (str) and optional `context` (str).

    Returns:
        `FAQResponse` with answer, sources list, and confidence score.

    Policy: Every answer must come from actual service definition documents, never invented.
    """
    state = get_state()
    catalog = state["catalog"]
    
    # Get policy grounding context for this question
    policy_context = get_grounding_context(req.question)
    
    answer, confidence = catalog.answer_faq(req.question)

    if confidence > 0.8:
        # Build response with policy sources
        sources = []
        if policy_context:
            sources.append({"type": "policy", "document": "FAQ_ANSWER_POLICIES.md"})
        return FAQResponse(
            answer=answer,
            sources=sources,
            confidence=confidence
        )

    # Fallback to LLM if no catalog match — ground it with policies
    if state["generation"]:
        try:
            system_msg = (
                "You are a helpful onboarding assistant. You must answer questions about "
                "services using ONLY the policy context provided below. NEVER invent or guess information. "
                "If the policy context doesn't contain the answer, say: "
                "'I don't have information about that in my current service catalog.' "
                "Be concise and helpful. Never make up service details."
            )
            reply = await state["generation"].generate_response(
                req.question,
                context=req.context + "\n\n" + policy_context if policy_context else req.context or "",
                system=system_msg
            )
            sources = []
            if policy_context:
                sources.append({"type": "policy", "document": "FAQ_ANSWER_POLICIES.md"})
            return FAQResponse(
                answer=reply,
                sources=sources,
                confidence=0.7
            )
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")

    return FAQResponse(
        answer="I don't have an answer for that. Please contact support.",
        sources=[],
        confidence=0.0
    )
