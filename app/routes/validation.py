"""Validation and FAQ routes."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.schemas import ValidationRequest, FAQRequest, FAQResponse, ChatResponse

from services.policy_service import get_grounding_context

router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    from app.main import app_state
    return app_state

# In-memory application store for validation
_application_store: dict = {}

# --- Validation ---
@router.post("/validate")
async def validate_application(req: ValidationRequest):
    """Validate an application using the ValidationAgent (Phase 2).
    
    Validates document count, mandatory fields, expiry dates, 
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
    """Query the FAQ system using service catalog + policy grounding.
    
    Policy: Every answer must come from actual service definition documents,
    never invented. The policy service provides grounded context for LLM answers.
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
