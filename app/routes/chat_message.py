"""
Chat message route — the main conversational AI endpoint for the Moro Hub onboarding system.

Role in Project:
    This is the central HTTP endpoint that receives every user chat message and routes it
    through the full conversational AI pipeline. It is the "nerve centre" connecting:
    the security layer, the intent classifier, the LLM generation service, the wizard state
    machine, and the database audit log.

Conversation Pipeline (in order):
    1. **Auth resolution**: Bearer token → user_id (or anonymous).
    2. **Chat persistence**: User message saved to `chat_messages` PostgreSQL table.
    3. **Service routing**: `ServiceCatalogService.match_service` classifies the query intent.
    4. **Prompt injection guard**: `security.detect_prompt_injection` blocks jailbreak attempts.
    5. **Service keyword fallback**: Secondary keyword matching if catalog routing misses a service name.
    6. **Intent classification**: Determines if the user wants to apply, ask an FAQ, or browse.
    7. **Auth gate**: If apply intent is detected, checks authentication. If unauthenticated,
       prompts login instead of opening an application.
    8. **Context building**: Assembles service details + policy grounding for the LLM.
    9. **LLM generation**: `GenerationService.generate_response` produces Lynx's reply.
    10. **Response persistence**: Assistant reply saved to `chat_messages` table.
    11. **Audit logging**: Event written to `audit_events` for traceability.

Cross-File Interconnections:
    - `services.security.detect_prompt_injection` — step 4: jailbreak/injection guard.
    - `services.service_catalog.ServiceCatalogService.match_service` — step 3: intent + routing.
    - `services.service_catalog.ServiceCatalogService.answer_faq` — FAQ context for LLM.
    - `services.policy_service.get_grounding_context` — step 8: anti-hallucination grounding.
    - `services.generation.GenerationService.generate_response` — step 9: LLM call.
    - `services.auth.AuthService.validate_token` — step 1, 7: token validation.
    - `services.database.DatabaseService.get_or_create_chat_session` — step 2: session mgmt.
    - `services.database.DatabaseService.save_chat_message` — steps 2, 10: persistence.
    - `services.database.DatabaseService.log_event` — step 11: audit trail.
    - `app.schemas.ChatMessage`, `ChatResponse` — Pydantic request/response models.
    - `app.main.app_state` — all service instances fetched from the shared state dict.

Phase 3: Persists all chat messages, enforces auth gate for application intent.
"""

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
    """Receive a user chat message and return Lynx's AI-generated reply.

    This is the primary endpoint for the conversational UI in `app.py`. Every message typed
    by the user in the chat panel is sent here, and the returned `ChatResponse` provides the
    assistant reply, intent classification, and metadata for rendering.

    Security guardrail (step 4 of the pipeline):
        Prompt injection attempts are detected by `security.detect_prompt_injection` before
        any LLM call is made. Blocked messages get a canned refusal reply and are logged to
        the audit trail under `intent='blocked_injection'`.

    Application intent + auth gate (step 7):
        If the user's message expresses intent to apply for a service AND they are not
        authenticated, the bot responds with a login prompt rather than initiating an
        application flow. This prevents anonymous sessions from creating dangling applications.

    Args:
        req: `ChatMessage` Pydantic model with:
            - `query` (str): The user's message.
            - `token` (str, optional): Bearer token for auth-aware responses.
            - `context` (str, optional): Additional context passed by the frontend.

    Returns:
        `ChatResponse` with:
            - `response` (str): The assistant's reply text.
            - `sources` (list): Policy/service sources cited.
            - `confidence` (float): Routing confidence score.
            - `intent` (str): Classified intent (e.g. 'apply', 'faq', 'browse', 'blocked_injection').
            - `matched_service` (str|None): service_id if a service was matched.

    Phase 3: Persists all chat messages to DB, enforces auth gate for application intent.
    """
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
                sources=[],
                confidence=1.0,
                intent="blocked_injection",
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
        system_prompt = (
            "You are Lynx, a helpful and friendly onboarding assistant for a document onboarding system. "
            "Be natural, conversational, and concise. Answer like a person would in a chat — "
            "not like a policy document. Use complete sentences but keep it brief.\n\n"
            "Available services:\n"
            "- Basic Registration (basic_registration): Simple identity registration. "
                        "Required documents: National ID, proof of address. "
                        "Processing time: 2-3 business days.\n"
                        "- Premium Cross-Border (premium_crossborder): International services for cross-border applications. "
                        "Required documents: National ID, Passport, proof of address. "
                        "Processing time: 5-7 business days.\n"
                        "- Mobility Rental (mobility_rental): Vehicle and rental services. "
                        "Required documents: driving_license, proof of address. "
            "Processing time: 1-2 business days. Coming soon.\n\n"
            "KEY RULES:\n"
            "1. If a user asks about applying, signing up, or registering, be encouraging and offer to help them start ONLY if the service is available. "
            "If the service is coming soon or unavailable, state clearly that it is not open for applications yet and do NOT offer or ask to start an application. "
            "If they have NOT named a service, say something like: \"Sure! I'd be happy to help you get started. Which service are you interested in?\" "
            "If they HAVE named an available service (it appears in the context above), never ask which service; say something like: "
            "\"Great choice! {service.name} is a great option. Would you like me to help you start your application?\" "
            "IMPORTANT: Never jump straight to asking for documents. Always ask the user if they want to apply FIRST, even if they seem interested. "
            "Don't be robotic.\n"
            "2. If a user asks a greeting (hi, hello, hey), greet them warmly. "
            "Example: \"Hi there! How can I help you today?\" or \"Good to see you! What can I do for you?\"\n"
            "3. Use the service info above to answer questions. Don't make up details.\n"
            "4. If a service isn't available or is coming soon, say so clearly and casually: \"That service isn't available yet, but check back soon!\" Do NOT ask if they would like to start or apply for it.\n"
            "5. If you don't know the answer, say so: \"I don't have info on that right now, but our team can help.\"\n"
            "6. Never say 'I don't have information about that in my current service catalog' — that's too formal.\n"
            "7. Keep responses under 3-4 sentences for natural flow."
        )

        # Generate response using vision model (text mode — no image needed)
        reply = None
        if state["generation"]:
            try:
                reply = await state["generation"].generate_response(
                    req.query,
                    context=context if context else "",
                    system=system_prompt
                )
            except Exception as e:
                logger.error(f"Generation failed: {e}")
                traceback.print_exc()

        if not reply:
            # Fallback to catalog FAQ
            if service:
                if status.value == "coming_soon":
                    reply = f"{service.name} is currently coming soon. We don't have details yet, but please check back later."
                else:
                    faq_answer, _ = catalog.answer_faq(req.query)
                    reply = faq_answer
            else:
                faq_answer, _ = catalog.answer_faq(req.query)
                reply = faq_answer

        # Determine intent
        intent = None
        matched_service = None

        if service:
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

        # Calculate confidence
        confidence = 0.0
        if service and status.value == "available":
            confidence = 0.85
        elif service and status.value == "coming_soon":
            confidence = 0.7
        else:
            confidence = 0.4

        # Build sources list
        sources = []
        if policy_context:
            sources.append({"type": "policy", "document": "ROUTING_POLICIES.md"})
            sources.append({"type": "policy", "document": "FAQ_ANSWER_POLICIES.md"})

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
                    confidence=confidence,
                )
            except Exception as e:
                logger.warning(f"Failed to persist assistant message: {e}")

        # Phase 3: Auth gate for application intent
        if intent == "apply" and not user_id:
            return ChatResponse(
                response="To apply for a service, please sign in or sign up first. You can continue asking general questions without signing in.",
                sources=sources,
                confidence=confidence,
                intent=intent,
                matched_service=matched_service
            )

        return ChatResponse(
            response=reply,
            sources=sources,
            confidence=confidence,
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
    """Return the authenticated user's full chat history.

    Only messages belonging to the authenticated user's chat session(s) are
    returned — it is impossible for one user to read another user's messages
    because the session is looked up via the user_id bound to their token.
    """
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
    """Return the status of the authenticated user's onboarding application(s).

    Ownership is enforced: each DB query is scoped to user_id so no cross-user
    data can leak. Unauthenticated requests are rejected with 401.
    """
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
