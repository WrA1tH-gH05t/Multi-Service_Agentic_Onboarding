"""
DocIntake Text Classification Engine & Transparent Trace Explainer.
Exposes the multi-stage classification pipeline with evidence, feature extraction, and routing logic.
"""

import time
import re
from typing import Dict, Any, List

from services.security import detect_prompt_injection, INJECTION_PATTERNS
from services.scope_classifier import ScopeClassifier, OUT_OF_SCOPE_RESPONSE
from services.service_catalog import ServiceCatalogue, ServiceStatus
from services.deterministic_router import DeterministicRouter, RoutingDecision


def classify_text_live(text_input: str) -> Dict[str, Any]:
    """
    Executes the full text classification pipeline across all actual backend components
    and returns an interpretable trace explaining EXACTLY why the decision was made.
    """
    start_time = time.time()
    trace_steps = []
    
    # ── Stage 1: Reception & Preprocessing ──
    t0 = time.time()
    clean_text = text_input.strip()
    normalized_text = clean_text.lower().replace("\u2019", "'").replace("\u2018", "'")
    words = re.findall(r"\b\w+\b", normalized_text)
    
    trace_steps.append({
        "stage": "Input Reception & Text Preprocessing",
        "component": "TextNormalizer",
        "status": "PASSED",
        "duration_ms": round((time.time() - t0) * 1000, 2),
        "details": f"Processed {len(clean_text)} characters, {len(words)} tokens. Normalized typography.",
        "intermediate_data": {
            "token_count": len(words),
            "normalized_sample": normalized_text[:120] + ("..." if len(normalized_text) > 120 else "")
        }
    })
    
    # ── Stage 2: Security & Adversarial Guardrails ──
    t0 = time.time()
    is_injection, injection_reason = detect_prompt_injection(text_input)
    sec_duration = round((time.time() - t0) * 1000, 2)
    
    if is_injection:
        trace_steps.append({
            "stage": "Security Guardrail Evaluation",
            "component": "SecurityService.detect_prompt_injection",
            "status": "BLOCKED",
            "duration_ms": sec_duration,
            "details": f"Prompt injection violation: {injection_reason}",
            "evidence": [f"Triggered pattern: {injection_reason}"]
        })
        return {
            "text": text_input,
            "category": "BLOCKED_SECURITY_VIOLATION",
            "status": "REJECTED",
            "confidence": 1.0,
            "responsible_component": "SecurityService",
            "decision_summary": "Query contains instructions attempting to override system constraints or leak data.",
            "trace_steps": trace_steps,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "evidence_list": [injection_reason]
        }
        
    trace_steps.append({
        "stage": "Security Guardrail Evaluation",
        "component": "SecurityService.detect_prompt_injection",
        "status": "PASSED",
        "duration_ms": sec_duration,
        "details": f"Evaluated against {len(INJECTION_PATTERNS)} adversarial instruction patterns. No violations."
    })

    # ── Stage 3: Scope Classification ──
    t0 = time.time()
    scope_category, scope_reason, scope_special = ScopeClassifier.classify(text_input)
    scope_duration = round((time.time() - t0) * 1000, 2)
    
    if scope_category == "OUT_OF_SCOPE":
        trace_steps.append({
            "stage": "Domain & Scope Classifier",
            "component": "ScopeClassifier (Strict Intent Pattern Matcher)",
            "status": "OUT_OF_SCOPE",
            "duration_ms": scope_duration,
            "details": f"Query classified outside DocIntake onboarding boundaries. Reason: {scope_reason}",
            "evidence": [scope_reason]
        })
        return {
            "text": text_input,
            "category": "OUT_OF_SCOPE",
            "status": "REJECTED",
            "confidence": 0.98,
            "responsible_component": "ScopeClassifier",
            "decision_summary": f"Query rejected as out-of-scope: {scope_reason}. Standard refusal triggered.",
            "trace_steps": trace_steps,
            "duration_ms": round((time.time() - start_time) * 1000, 2),
            "evidence_list": [scope_reason, "Matches strict out-of-scope intent rule"]
        }
        
    trace_steps.append({
        "stage": "Domain & Scope Classifier",
        "component": "ScopeClassifier",
        "status": "IN_SCOPE",
        "duration_ms": scope_duration,
        "details": f"Query validated as in-scope ({scope_category}). Category trigger: {scope_reason or 'Domain valid'}."
    })

    # ── Stage 4: Deterministic Router & Intent Matching ──
    t0 = time.time()
    catalog = ServiceCatalogue()
    status, matched_service = catalog.match_service(text_input)
    
    # Feature extraction: identify application, inquiry, and conversational signals
    apply_signals = [
        "apply", "register", "sign up", "start application", "begin", "create account",
        "i want to apply", "how do i apply", "new application", "enroll", "submission", "upload"
    ]
    faq_signals = [
        "what", "how", "where", "why", "who", "cost", "fee", "price", "duration",
        "requirements", "documents needed", "time", "policy", "terms", "rules",
        "know more", "services", "tell me", "help me", "can you", "information", "about"
    ]
    greeting_signals = [
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"
    ]
    
    found_apply_signals = [kw for kw in apply_signals if re.search(r'\b' + re.escape(kw) + r'\b', normalized_text)]
    found_faq_signals = [kw for kw in faq_signals if re.search(r'\b' + re.escape(kw) + r'\b', normalized_text)]
    found_greeting_signals = [kw for kw in greeting_signals if re.search(r'\b' + re.escape(kw) + r'\b', normalized_text)]
    
    # Extract salient keywords from text (non-stopwords)
    stopwords = {"i", "a", "an", "the", "and", "or", "to", "in", "on", "at", "by", "for", "with", "about", "would", "like", "of", "your", "my", "is", "am", "are"}
    extracted_keywords = [w for w in words if w not in stopwords and len(w) > 2]

    router_duration = round((time.time() - t0) * 1000, 2)
    
    # Resolve predicted category & policy-grounded routing
    predicted_category = "GENERAL_INQUIRY"
    confidence = 0.70
    routing_destination = "Conversational FAQ Generator"
    policy_response = None
    
    # Check for requests to apply for a driving license or other non-existent services
    wants_driving_license_issuance = bool(re.search(r'\b(apply\s+for|get|obtain|issue|renew)\s+(a\s+)?(driving\s+licen[sc]e|driver\'?s?\s+licen[sc]e)\b', normalized_text))
    
    if scope_category == "GREETING":
        predicted_category = "CONVERSATIONAL_GREETING"
        confidence = 0.99
        routing_destination = "Greeting Dispatcher"
        policy_response = "Hello! I am the DocIntake AI Assistant. I can help guide you through our onboarding services, document requirements, and verification processes. How may I assist you today?"
    elif wants_driving_license_issuance:
        predicted_category = "UNSUPPORTED_SERVICE: DRIVING_LICENSE_ISSUANCE"
        confidence = 0.96
        routing_destination = "Catalog Handoff & Service Recommender"
        policy_response = (
            "I don't recognise driving licence issuance as an available service. DocIntake is an identity verification "
            "and onboarding platform, not a licensing authority. We currently support **Basic Registration**, "
            "**Premium / Cross Border**, and **Mobility / Rental** (which requires an existing driving licence). "
            "Would you like to know more about any of our available services?"
        )
    elif matched_service and status == ServiceStatus.COMING_SOON:
        predicted_category = f"COMING_SOON_SERVICE: {matched_service.service_id.upper()}"
        confidence = 0.98
        routing_destination = "Coming Soon Service Notifier"
        docs_str = ", ".join(matched_service.required_documents) if matched_service.required_documents else "required documents"
        policy_response = (
            f"**{matched_service.name}** is a coming soon service and is not yet available for processing. "
            f"When launched, it will require {docs_str}. "
            f"Currently active services: **Basic Registration**, **Premium / Cross Border**, and **Mobility / Rental**. "
            f"Please check back when {matched_service.name} becomes available."
        )
    elif found_apply_signals and matched_service and status == ServiceStatus.AVAILABLE:
        predicted_category = f"SERVICE_APPLICATION: {matched_service.service_id.upper()}"
        confidence = 0.95
        routing_destination = f"Application Wizard ({matched_service.name})"
        policy_response = (
            f"Great! Let's get started with **{matched_service.name}**. "
            f"This service requires {', '.join(matched_service.required_documents)}. "
            f"Processing time is {matched_service.processing_time}. "
            f"Please proceed to upload your {matched_service.required_documents[0].replace('_', ' ').title()}."
        )
    elif matched_service and status == ServiceStatus.AVAILABLE:
        predicted_category = f"SERVICE_INQUIRY: {matched_service.service_id.upper()}"
        confidence = 0.90
        routing_destination = f"Service Catalog Matcher ({matched_service.name})"
        policy_response = (
            f"**{matched_service.name}** is currently **Available**.\n\n"
            f"{matched_service.description}\n\n"
            f"• **Required documents:** {', '.join(matched_service.required_documents)}\n"
            f"• **Processing time:** {matched_service.processing_time}\n\n"
            f"Would you like to start an application for this service?"
        )
    elif found_apply_signals:
        predicted_category = "GENERIC_APPLICATION_INTENT"
        confidence = 0.85
        routing_destination = "Service Selection Prompter"
        policy_response = (
            "I'd be glad to help you apply! Which service would you like to apply for? "
            "We currently offer:\n"
            "1. **Basic Registration** (requires National ID)\n"
            "2. **Premium / Cross Border** (requires National ID + Passport)\n"
            "3. **Mobility / Rental** (requires Driving Licence)"
        )
    elif found_faq_signals or "services" in normalized_text:
        predicted_category = "GENERAL_SERVICE_INQUIRY"
        confidence = 0.88
        routing_destination = "Service Overview & Conversational Engine"
        
    trace_steps.append({
        "stage": "Deterministic Intent & Service Classifier",
        "component": "DeterministicRouter & ServiceCatalogue",
        "status": "CLASSIFIED",
        "duration_ms": router_duration,
        "details": f"Matched Service: '{matched_service.name if matched_service else 'None'}', Target: '{predicted_category}'",
        "intermediate_data": {
            "matched_service_id": matched_service.service_id if matched_service else None,
            "matched_service_status": status.value if status else None,
            "detected_apply_keywords": found_apply_signals,
            "detected_faq_keywords": found_faq_signals,
            "detected_greeting_keywords": found_greeting_signals,
            "salient_keywords": extracted_keywords,
            "target_destination": routing_destination
        }
    })

    total_time = round((time.time() - start_time) * 1000, 2)
    
    evidence = []
    if found_greeting_signals:
        evidence.append(f"Greeting / Courtesy Tokens: {', '.join(found_greeting_signals)}")
    if found_faq_signals:
        evidence.append(f"Inquiry Feature Patterns: {', '.join(found_faq_signals)}")
    if found_apply_signals:
        evidence.append(f"Application Intent Tokens: {', '.join(found_apply_signals)}")
    if matched_service:
        evidence.append(f"Matched Catalog Service: '{matched_service.name}' (Status: {status.value})")
        evidence.append(f"Required Documents: {', '.join(matched_service.required_documents)}")
    if extracted_keywords:
        evidence.append(f"Salient Vocabulary Features: {', '.join(extracted_keywords[:6])}")

    # Optionally query the local Qwen2.5-VL model to obtain the actual AI conversational response
    model_response = None
    try:
        import yaml, asyncio
        from services.generation import GenerationService
        with open("config.yaml", "r") as f:
            cfg = yaml.safe_load(f)
        gs = GenerationService(cfg.get("ollama", {}))
        sys_prompt = (
            "You are DocIntake AI Assistant. Help the user with onboarding, document verification (Passport, "
            "Emirates ID, Driving Licence), and service applications. Provide a clear, professional, direct answer."
        )
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        model_response = loop.run_until_complete(gs.generate_response(text_input, system=sys_prompt))
    except Exception as e:
        model_response = f"(Model response unavailable: {e})"
    if scope_category == "GREETING":
        evidence.append("Matched Conversational Greeting Regex Pattern")

    # Set final model/policy response:
    # If the system's deterministic policy dictates a specific answer (coming soon, unsupported, catalog handoff),
    # use that to guarantee strict compliance with platform rules; otherwise fall back to LLM conversational reply.
    final_output_response = policy_response or model_response

    return {
        "text": text_input,
        "category": predicted_category,
        "status": "CLASSIFIED",
        "confidence": confidence,
        "responsible_component": "DeterministicRouter & ScopeClassifier",
        "decision_summary": f"Classified as '{predicted_category}' with {confidence:.0%} confidence. Routed to '{routing_destination}'.",
        "routing_destination": routing_destination,
        "model_output": final_output_response,
        "trace_steps": trace_steps,
        "duration_ms": total_time,
        "evidence_list": evidence,
        "matched_service": matched_service.name if matched_service else None
    }
