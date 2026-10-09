"""Chat message route — the main conversational AI endpoint."""

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
    from app.main import app_state
    return app_state

@router.post("/chat/message")
async def chat(req: ChatMessage):
    """Send a chat message and get a reply.
    
    Phase 3: Persists all chat messages, enforces auth gate for application intent.
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
            "1. If a user asks about applying, signing up, or registering, be encouraging and offer to help them start. "
            "If they have NOT named a service, say something like: \"Sure! I'd be happy to help you get started. Which service are you interested in?\" "
            "If they HAVE named a service (it appears in the context above), never ask which service; say something like: "
            "\"Great choice! {service.name} is a great option. Would you like me to help you start your application?\" "
            "IMPORTANT: Never jump straight to asking for documents. Always ask the user if they want to apply FIRST, even if they seem interested. "
            "Don't be robotic.\n"
            "2. If a user asks a greeting (hi, hello, hey), greet them warmly. "
            "Example: \"Hi there! How can I help you today?\" or \"Good to see you! What can I do for you?\"\n"
            "3. Use the service info above to answer questions. Don't make up details.\n"
            "4. If a service isn't available, say so casually: \"That one isn't ready yet, but check back soon!\"\n"
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
