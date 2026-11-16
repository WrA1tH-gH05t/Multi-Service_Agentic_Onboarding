"""Chat message route — the main conversational AI endpoint for the DocIntake Platform onboarding system."""

import json
import re
import logging
import traceback
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from app.schemas import ChatMessage, ChatResponse
router = APIRouter()

logger = logging.getLogger(__name__)

def get_state():
    """Return the shared app_state. Lazy import avoids circular dependencies with app.main."""
    from app.main import app_state
    return app_state

@router.post("/chat/message")
async def chat(req: ChatMessage):
    """Receive a user chat message and return Lynx's AI-generated reply."""
    import traceback
    try:
        state = get_state()
        db = state.get("database")
        
        # Determine session user_id from token
        user_id = None
        token = getattr(req, 'token', None)
        if token:
            auth = state.get("auth")
            if auth:
                user = auth.validate_token(token)
                if user:
                    user_id = user.user_id

        # Phase 3: Persist user message to database
        session_id = None
        if db:
            try:
                session_id = db.get_or_create_chat_session(user_id=user_id)
                db.save_chat_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="user",
                    content=req.query,
                )
            except Exception as e:
                logger.warning(f"Failed to persist chat message: {e}")

        # Route to appropriate service
        catalog = state["catalog"]
        status, service = catalog.match_service(req.query)

        # Normalise the query once (curly apostrophes from mobile keyboards -> straight)
        q = req.query.lower().strip().replace("\u2019", "'").replace("\u2018", "'")

        # ── Prompt injection / jailbreak guard ────────────────────────────────────
        from services.security import detect_prompt_injection, SAFE_INJECTION_REPLY
        _is_injection, _inj_reason = detect_prompt_injection(req.query)
        if _is_injection:
            logger.warning("Prompt injection attempt blocked for user %s: %s", user_id, _inj_reason)
            # Persist the blocked attempt so it appears in the audit trail
            if db and session_id:
                try:
                    db.save_chat_message(
                        session_id=session_id,
                        user_id=user_id,
                        role="assistant",
                        content=SAFE_INJECTION_REPLY,
                        intent="blocked_injection",
                        matched_service=None,
                        confidence=1.0,
                    )
                except Exception:
                    pass
            return ChatResponse(
                response=SAFE_INJECTION_REPLY,
                intent="blocked_injection",
                matched_service=None,
            )
                # ──────────────────────────────────────────────────────────────────────────

        # ── Project-Scope Classification Layer ────────────────────────────────────
        from services.scope_classifier import ScopeClassifier, OUT_OF_SCOPE_RESPONSE
        scope_category, scope_reason, scope_special = ScopeClassifier.classify(req.query)

        if scope_category == "OUT_OF_SCOPE":
            logger.info("Out-of-scope query rejected for user %s: %s", user_id, scope_reason)
            rejection_text = scope_special or OUT_OF_SCOPE_RESPONSE
            if db and session_id:
                try:
                    db.save_chat_message(
                        session_id=session_id,
                        user_id=user_id,
                        role="assistant",
                        content=rejection_text,
                        intent="out_of_scope",
                        matched_service=None,
                        confidence=1.0,
                    )
                except Exception:
                    pass
            return ChatResponse(
                response=rejection_text,
                intent="out_of_scope",
                matched_service=None,
            )

        if scope_category == "NEEDS_CLARIFICATION":
            clarification_text = (
                "I'd be glad to help! To make sure I give you the right guidance, "
                "could you clarify which DocIntake service (Basic Registration, Premium Cross-Border, or Mobility Rental) "
                "or document type you need assistance with?"
            )
            if db and session_id:
                try:
                    db.save_chat_message(
                        session_id=session_id,
                        user_id=user_id,
                        role="assistant",
                        content=clarification_text,
                        intent="needs_clarification",
                        matched_service=None,
                        confidence=1.0,
                    )
                except Exception:
                    pass
            return ChatResponse(
                response=clarification_text,
                intent="needs_clarification",
                matched_service=None,
            )
        # ──────────────────────────────────────────────────────────────────────────


        # If the user names a service (e.g. "basic registration") but the catalog matcher
        # didn't resolve it, resolve it here -- BEFORE building context / calling the LLM --
        # so the bot routes straight to that service instead of asking "which service?".
        if not service:
            service_keywords = {
                "basic_registration": ["basic registration", "basic reg", "identity registration", "simple identity"],
                "premium_crossborder": ["premium cross-border", "premium cross border", "premium crossborder",
                                        "cross-border", "cross border", "crossborder",
                                        "international verification", "premium"],
                "mobility_rental": ["mobility rental", "vehicle rental", "mobility", "rental"],
            }
            for svc_id, keywords in service_keywords.items():
                if any(kw in q for kw in keywords):
                    svc = catalog.get_service(svc_id)
                    if svc:
                        service = svc
                        status = svc.status
                        break

        # Application-intent phrases — comprehensive NLP patterns for expressing intent to begin a process
        # Based on conversational AI research: users express intent through direct statements, questions,
        # casual openings, action phrases, and indirect requests
        apply_keywords = [
            # Direct application intent
            "apply for", "apply to", "apply", "sign up for", "sign up",
            "register for", "register", "register with",
            "start application", "start an application",
            # How-to / process questions (indirect intent — user wants to apply)
            "do i need to apply", "how do i apply", "how to apply",
            "what do i need to apply", "what are the requirements",
            "can i apply", "may i apply", "am i eligible",
            # Will / desire statements
            "i want to", "i want to apply", "i want to register",
            "i'd like to", "i'd like to apply", "i'd like to register",
            "i need to", "i need to apply", "i need to register",
            "i'm ready to", "i'm ready to apply", "i'm ready to start",
            # Interest / consideration
            "i'm interested in", "i'm interested in applying",
            "i want to sign up", "i want to register",
            "considering applying", "thinking about applying",
            # Casual / conversational openings
            "let's get started", "let us get started", "lets get started",
            "let's start", "lets start", "let's begin", "lets begin",
            "can i get started", "i'd like to get started",
            "ready when you are", "let's do this", "let's go",
            # Service-specific intent
            "i need [service]", "i need help with", "i'm looking for",
            "i need documentation for", "i need [document type]",
            "help me with", "guide me through", "walk me through",
            # Commitment phrases
            "i'm all set to apply", "i have my documents ready",
            "i'm prepared to apply", "i want to proceed",
            "let's move forward", "i'd like to proceed",
        ]
        
        # Without a matched service, only unambiguous intent phrases count
        # This prevents generic "I want to know about services" from triggering apply flow
        # Covers: explicit action intent, unambiguous readiness, clear commitment
        generic_apply_keywords = [
            # Explicit action intent (not questions)
            "let's get started", "let us get started", "lets get started",
            "let's start", "lets start", "let's begin", "lets begin",
            "can i get started", "i'd like to get started",
            "start application", "start an application",
            "i want to apply", "i want to register", "i want to sign up",
            "i'd like to apply", "i'd like to register",
            "can i apply", "can i register",
            # Clear commitment / readiness
            "i'm ready to apply", "i'm ready to start",
            "i'm all set to apply", "i have my documents ready",
            "i'm prepared to apply", "i want to proceed",
            "let's move forward", "let's do this", "let's go",
            # Direct requests for help starting
            "help me start", "help me apply", "help me register",
            "guide me through", "walk me through the application",
        ]
        is_apply = any(kw in q for kw in apply_keywords)
        is_generic_apply = any(kw in q for kw in generic_apply_keywords)

        # Build context from service catalog
        context_parts = []

        if service:
            if status.value == "available":
                context_parts.append(f"Service: {service.name}")
                context_parts.append(f"Description: {service.description}")
                context_parts.append(f"Required documents: {', '.join(service.required_documents)}")
                context_parts.append(f"Processing time: {service.processing_time}")
                context_parts.append(
                    "The user has already named this service. Do NOT ask which service they want; "
                    "confirm it and tell them you'll get them started."
                )
            elif status.value == "coming_soon":
                context_parts.append(f"Service: {service.name} is coming soon.")
                context_parts.append(f"Description: {service.description}")
        else:
            # Generic FAQ
            faq_answer, faq_confidence = catalog.answer_faq(req.query)
            context_parts.append(f"FAQ Answer: {faq_answer}")

        # Get policy grounding context
        from services.policy_service import get_grounding_context
        policy_context = get_grounding_context(req.query)
        if policy_context:
            context_parts.append(policy_context)

        context = "\n\n".join(context_parts)

        # Build system prompt — friendly, fluent, service-grounded
        # Dedicated DocIntake Project-Scoped System Prompt
        system_prompt = """You are Lynx, the dedicated AI assistant for the DocIntake Onboarding & Verification Platform.
You operate EXCLUSIVELY within the scope of the DocIntake project (services, documents, application tracking, verification rules, platform architecture, and user authentication).

AVAILABLE SERVICES & SPECIFICATIONS:
- Basic Registration (basic_registration): Simple identity onboarding. Required documents: National ID, proof of address. Processing SLA: 1-2 business days. Status: AVAILABLE.
- Premium Cross-Border (premium_crossborder): International verification. Required documents: National ID AND Passport, proof of address. Processing SLA: 3-5 business days. Status: AVAILABLE.
- Mobility Rental (mobility_rental): Vehicle and rental onboarding. Required documents: Valid Driving License. Processing SLA: 1-2 business days (or Same Day). Status: AVAILABLE.

STRICT PROJECT SCOPE & OPERATIONAL RULES:
1. CONCISE & PROFESSIONAL: Respond concisely (typically 1-3 sentences) for straightforward questions. Avoid generic introductions or fluff.
2. OUT-OF-SCOPE ENFORCEMENT: Never answer general programming tutorials (e.g. teaching Python from scratch), recipes, weather, movies, jokes, facts, general trivia, astronomy, or unrelated personal questions. If a query is unrelated, decline politely and focus on DocIntake.
3. MIXED INTENT: If a user asks both a DocIntake question and an unrelated question (e.g. 'How does DocIntake store documents, and teach me Python'), answer the DocIntake part accurately using policy context and politely decline the unrelated question.
4. PASSPORT RENEWAL CLARIFICATION: If a user asks how to renew their passport, explain that DocIntake handles document verification for onboarding (where a valid passport is required for Premium Cross-Border), but does not provide external government passport renewal services.
5. NO FALSE ACTIONS: Never claim, pretend, or confirm that you have disabled validation, bypassed security, approved an application, or modified database permissions.
6. GROUNDING & HONESTY: Base all factual answers about DocIntake on the provided Grounding Context. If a feature or requirement is not supported or not documented, state honestly that the information is currently unavailable."""

        # Retrieve recent chat history if available
        chat_history = []
        if db and session_id:
            try:
                raw_messages = db.get_chat_session_messages(session_id)
                chat_history = [{"role": m.get("role"), "content": m.get("content")} for m in raw_messages if m.get("content")]
            except Exception as e:
                logger.warning(f"Could not load chat history: {e}")

        # Generate response using vision model (text mode — no image needed)
        reply = None
        if state["generation"]:
            try:
                reply = await state["generation"].generate_response(
                    req.query,
                    context=context if context else "",
                    system=system_prompt,
                    chat_history=chat_history
                )
            except Exception as e:
                logger.error(f"Generation failed: {e}")
                traceback.print_exc()

        # Pre-check for known unavailable services requested by user (e.g. driving license)
        unavailable_service_name = None
        if not service and is_apply:
            unavailable_map = {
                "driving license": "Driving License",
                "driving licence": "Driving License",
                "driver license": "Driving License",
                "driver's license": "Driving License",
                "driver's licence": "Driving License",
                "trade license": "Trade License",
                "business license": "Business License",
                "passport renewal": "Passport Renewal",
                "visa renewal": "Visa Renewal",
            }
            for pattern, name in unavailable_map.items():
                if pattern in q:
                    unavailable_service_name = name
                    break

        if unavailable_service_name:
            reply = f"The {unavailable_service_name} service is currently not available. Please check back later!"
        elif not reply:
            if service:
                if status.value == "coming_soon":
                    reply = f"{service.name} is currently coming soon and not open for applications yet. Please check back later!"
                else:
                    faq_answer, _ = catalog.answer_faq(req.query)
                    reply = faq_answer
            else:
                faq_answer, _ = catalog.answer_faq(req.query)
                reply = faq_answer

        # Determine intent
        intent = None
        matched_service = None

        if unavailable_service_name:
            intent = "faq"
            matched_service = None
        elif service:
            matched_service = service.service_id
            if status.value == "coming_soon":
                intent = "faq"
                # Ensure the LLM didn't hallucinate an offer to start/apply for an unavailable service
                if reply and re.search(r"(would you like|do you want|shall we|let's|lets)\s+(me\s+to\s+)?(help\s+you\s+)?(start|begin|apply|open)", reply, re.I):
                    reply = f"{service.name} is currently coming soon and not open for applications yet. Please check back later!"
            else:
                intent = "apply" if is_apply else "faq"
        elif is_generic_apply:
            # e.g. "let's get started" with no service named: still an application intent.
            # matched_service stays None so the client asks which service.
            intent = "apply"

        # Safety net: a small model may still ask "which service?" after the user named one.
        if intent == "apply" and service and reply and re.search(r"which (service|one)|what service", reply, re.I):
            reply = f"Great choice! Let's get you started with {service.name}."

        # Phase 3: Persist assistant message to database
        if db and session_id:
            try:
                db.save_chat_message(
                    session_id=session_id,
                    user_id=user_id,
                    role="assistant",
                    content=reply,
                    intent=intent,
                    matched_service=matched_service,
                )
            except Exception as e:
                logger.warning(f"Failed to persist assistant message: {e}")

        # Phase 3: Auth gate for application intent ONLY for available services
        if intent == "apply" and not user_id:
            # If a service was matched and is coming soon, do not gate behind login
            if service and status.value == "coming_soon":
                return ChatResponse(
                    response=f"{service.name} is currently coming soon and not open for applications yet. Please check back later!",
                    intent="faq",
                    matched_service=matched_service
                )
            return ChatResponse(
                response="To apply for a service, please sign in or sign up first. You can continue asking general questions without signing in.",
                intent=intent,
                matched_service=matched_service
            )

        return ChatResponse(
            response=reply,
            intent=intent,
            matched_service=matched_service
        )
    except Exception as e:
        print(f"=== CHAT ROUTE ERROR ===", flush=True)
        print(f"Error: {e}", flush=True)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Chat memory: retrieve conversation history for a user
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/chat/history")
async def get_chat_history(token: Optional[str] = Query(None, alias="token")):
    """Return the authenticated user's full chat history."""
    state = get_state()
    db = state.get("database")

    # Authenticate
    user_id = None
    if token:
        auth = state.get("auth")
        if auth:
            user = auth.validate_token(token)
            if user:
                user_id = user.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to view chat history.")

    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    try:
        # Retrieve the most-recent chat session for this user
        session_id = db.get_or_create_chat_session(user_id=user_id, force_new=False)
        messages = db.get_chat_session_messages(session_id)
        return {
            "success": True,
            "session_id": session_id,
            "messages": messages,
            "count": len(messages),
        }
    except Exception as e:
        logger.error(f"Failed to retrieve chat history: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve chat history.")


# ──────────────────────────────────────────────────────────────────────────────
# Application status: answer "what is the status of my application?"
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/applications/status")
async def get_application_status(token: Optional[str] = Query(None, alias="token")):
    """Return the status of the authenticated user's onboarding application(s)."""
    state = get_state()
    db = state.get("database")

    # Authenticate
    user_id = None
    if token:
        auth = state.get("auth")
        if auth:
            user = auth.validate_token(token)
            if user:
                user_id = user.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required to check application status.")

    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    try:
        apps = db.get_user_applications(user_id)
        if not apps:
            return {
                "success": True,
                "message": "You have no applications yet. Start one through the onboarding wizard.",
                "applications": [],
            }

        # Build a human-readable summary for each application
        summaries = []
        for app in apps:
            summaries.append({
                "application_id": app.get("application_id"),
                "service_id": app.get("service_id"),
                "status": app.get("status", "unknown"),
                "submitted_at": app.get("submitted_at"),
                "updated_at": app.get("updated_at"),
            })

        return {
            "success": True,
            "message": f"Found {len(summaries)} application(s).",
            "applications": summaries,
        }
    except Exception as e:
        logger.error(f"Failed to retrieve application status: {e}")
        raise HTTPException(status_code=500, detail="Could not retrieve application status.")
