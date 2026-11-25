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
async def chat(req: ChatMessage, token: Optional[str] = Query(None, alias="token")):
    """Receive a user chat message and return Lynx's AI-generated reply."""
    import traceback
    try:
        steps_taken = []
        state = get_state()
        db = state.get("database")
        
        # Determine session user_id from token (check body token or query token)
        user_id = None
        auth_token = getattr(req, 'token', None) or token
        if auth_token:
            auth = state.get("auth")
            if auth:
                user = auth.validate_token(auth_token)
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
            steps_taken.append({
                "step": "Security & Guardrails",
                "status": "failed",
                "details": f"Blocked prompt injection attempt: {_inj_reason}"
            })
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
                execution_steps=steps_taken
            )
        else:
            steps_taken.append({
                "step": "Security & Guardrails",
                "status": "passed",
                "details": "Passed security and anti-injection pattern validation"
            })
                # ──────────────────────────────────────────────────────────────────────────

        # ── Project-Scope Classification Layer ────────────────────────────────────
        from services.scope_classifier import ScopeClassifier, OUT_OF_SCOPE_RESPONSE
        scope_category, scope_reason, scope_special = ScopeClassifier.classify(req.query)
        steps_taken.append({
            "step": "Scope Classifier",
            "status": "passed" if scope_category != "OUT_OF_SCOPE" else "rejected",
            "details": f"Category: {scope_category} ({scope_reason or 'DocIntake domain valid'})"
        })

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
                execution_steps=steps_taken
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
                execution_steps=steps_taken
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

        # ── "Ok / got it / thanks" after the bot gave service info ───────────────
        # Detect when the user sends a short acknowledgement (ok, sure, got it, etc.)
        # right after the bot described a service (tracked in recent chat history).
        # In that case, ask them whether they have any issues or want to start an
        # application, and surface the service so the frontend can offer the wizard.
        OK_PHRASES = {
            "ok", "okay", "ok.", "okay.", "ok!", "okay!", "sure", "sure.", "alright",
            "alright.", "got it", "got it.", "i see", "i see.", "understood",
            "noted", "great", "thanks", "thank you", "cool", "nice", "good",
        }
        is_ok_ack = q.strip().rstrip("!.,") in OK_PHRASES or q.strip() in OK_PHRASES

        if is_ok_ack and not service and not is_apply:
            # Look at the last few assistant messages to see if a service was mentioned
            if db and session_id:
                try:
                    recent = db.get_chat_session_messages(session_id)
                    # Walk backwards through assistant turns only
                    for m in reversed(recent[:-1]):  # exclude the message just persisted
                        if m.get("role") != "assistant":
                            continue
                        content_lower = (m.get("content") or "").lower()
                        for svc_id, svc_keywords in {
                            "basic_registration": ["basic registration", "basic reg", "identity registration"],
                            "premium_crossborder": ["premium cross-border", "premium cross border", "crossborder", "premium crossborder"],
                            "mobility_rental": ["mobility rental", "vehicle rental", "mobility rental"],
                        }.items():
                            if any(kw in content_lower for kw in svc_keywords):
                                svc = catalog.get_service(svc_id)
                                if svc:
                                    service = svc
                                    status = svc.status
                                break
                        if service:
                            break
                except Exception as e:
                    logger.warning(f"Could not inspect recent chat history for ok-ack: {e}")

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

        # Build dynamic time-of-day greeting context
        user_time_greeting = req.time_greeting or "Good day"
        greeting_instruction = (
            f"USER TIME OF DAY CONTEXT: The user's current local time corresponds to '{user_time_greeting}'. "
            f"If the user is saying hello, hi, hey, or greeting you, warmly greet them using '{user_time_greeting}! I\\'m Lynx, your DocIntake assistant.' "
            f"Keep conversational responses natural, neat, and direct without robotic disclaimers or repetitive lists."
        )

        # Build system prompt — friendly, fluent, service-grounded
        # Dedicated DocIntake Project-Scoped System Prompt
        system_prompt = f"""You are Lynx, the dedicated AI assistant for the DocIntake Onboarding & Verification Platform.
You operate EXCLUSIVELY within the scope of the DocIntake project (services, documents, application tracking, verification rules, platform architecture, user authentication, and child dependent profiles).

CONVERSATIONAL BEHAVIOR & TONE:
- {greeting_instruction}
- NATURAL & COHERENT: Speak naturally and conversationally. Do not repeat the exact same service list or robotic disclaimer on every turn if the user is simply acknowledging or greeting you.
- HELPFUL & DIRECT: Answer what the user asked cleanly and concisely (1-3 sentences for simple questions). When asked "what can you do" or "why are you here", explain your capabilities (document intake, onboarding service applications, automatic data validation, and parent-managed child dependent profiles) in a fluid, engaging manner.
- DO NOT loop or regurgitate fixed menu lists unless the user specifically asks for service options or requirements.

AVAILABLE SERVICES & SPECIFICATIONS:
- Basic Registration (basic_registration): Simple identity onboarding. Required documents: National ID, proof of address. Processing SLA: 1-2 business days. Status: AVAILABLE. (Available to eligible adults and child dependent profiles).
- Premium Cross-Border (premium_crossborder): International verification. Required documents: National ID AND Passport, proof of address. Processing SLA: 3-5 business days. Status: AVAILABLE. (Available to eligible adults and child dependent profiles).
- Mobility Rental (mobility_rental): Vehicle and rental onboarding. Required documents: Valid Driving License. Processing SLA: 1-2 business days (or Same Day). Status: AVAILABLE for eligible adult applicants. STRICTLY NOT AVAILABLE to dependent child profiles under 18 due to minimum driving-licence age requirements.

PARENT / GUARDIAN ACCOUNTS & CHILD DEPENDENT PROFILES:
- Adult accounts: Account holders must be at least 18 Gregorian years old under UAE Civil Transactions Law (Federal Decree-Law No. 25 of 2025, Article 84).
- Dependent profiles: Children do NOT have independent login accounts, emails, or passwords. Adult parents and legally authorized guardians manage child profiles through their own authenticated Docintake accounts. One parent can manage multiple child profiles.
- Child profile creation: Collects child full legal name, date of birth, relationship to guardian, and nationality. Requires explicit confirmation of parental/caregiver authority.
- Child data protection (UAE Federal Decree-Law No. 26 of 2025, Article 7): Children under 13 require explicit, documented, and verifiable parental/caregiver consent before any personal data is collected or persisted. A continuously accessible and straightforward withdrawal mechanism is provided.
- Application-specific review consent: Each application submitted on behalf of a child requires explicit document review consent before designated government-body reviewers can inspect submitted documents. If consent is declined, documents are not routed to reviewers and temporary staging is purged.
- Strict developer access restrictions: Platform developers are strictly prohibited from viewing, downloading, or inspecting real customer or child document binaries.
- On-premise infrastructure: MinIO (binaries), PostgreSQL (records), and Ollama/Qwen2.5-VL 7B (local inference). Zero external public cloud AI transmission.

STRICT PROJECT SCOPE & OPERATIONAL RULES:
1. ABSOLUTE DOMAIN BOUNDARY: You MUST NOT answer questions outside the DocIntake project scope. Under NO circumstances should you provide gym plans, workout routines, fitness advice, medical diagnoses, cooking recipes, programming help, creative writing, or general trivia.
2. OUT-OF-SCOPE ENFORCEMENT: If a user asks ANY question unrelated to DocIntake, decline politely and state: "I'm the DocIntake AI assistant, and I'm here to help with our onboarding services, document requirements, applications, and related platform support. I can't assist with unrelated topics, but I'd be happy to help with anything concerning DocIntake."
3. CONCISE & PROFESSIONAL: Respond concisely (typically 1-3 sentences) for straightforward questions. Avoid generic introductions or fluff.
4. MIXED INTENT: If a user asks both a DocIntake question and an unrelated question, answer the DocIntake part accurately using policy context and politely decline the unrelated question.
5. PASSPORT RENEWAL CLARIFICATION: If a user asks how to renew their passport, explain that DocIntake handles document verification for onboarding (where a valid passport is required for Premium Cross-Border), but does not provide external government passport renewal services.
6. NO FALSE ACTIONS: Never claim, pretend, or confirm that you have disabled validation, bypassed security, approved an application, or modified database permissions. Never create a child profile without explicit user confirmation.
7. GROUNDING & HONESTY: Base all factual answers about DocIntake on the provided Grounding Context. If a feature or requirement is not supported or not documented, state honestly that the information is currently unavailable."""

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

        # If the user just acknowledged service info with "ok/sure/got it", ask
        # them whether they have any issues or would like to start an application.
        if is_ok_ack and service and service.status.value == "available":
            reply = (
                f"Great! Do you have any questions or issues about {service.name}, "
                "or would you like to go ahead and start an application for it?"
            )

        # Determine intent
        intent = None
        matched_service = None
        action = None
        data = None

        # ── Child Profile & Guardian Inquiries / Actions ─────────────────────────
        child_create_patterns = [
            r"\b(create|add|make|set up|open|register)\s+(a\s+)?(child|dependent|minor|son|daughter|kid)\s*(profile|account)?\b",
            r"\baccount\s+for\s+(my\s+)?(child|son|daughter|kid)\b",
            r"\bprofile\s+for\s+(my\s+)?(child|son|daughter|kid)\b",
            r"\b(add|register)\s+(my\s+)?(child|son|daughter|kid)\b",
            r"\bi want to (create|add|register)\s+(a\s+)?(child|profile for my)\b",
        ]
        is_child_create = any(re.search(pat, q, re.I) for pat in child_create_patterns)
        
        child_eligibility_patterns = [
            r"\b(can|eligible|eligibility|is it possible)\b.*\b(child|son|daughter|dependent|minor)\b",
            r"\b(child|son|daughter|dependent|minor)\b.*\b(eligible|eligibility|can use|apply for|mobility|rental|car)\b",
            r"\bmobility\b.*\b(child|son|daughter|minor|under 18)\b",
            r"\brental\b.*\b(child|son|daughter|minor|under 18)\b",
        ]
        is_child_eligibility = any(re.search(pat, q, re.I) for pat in child_eligibility_patterns)

        child_consent_patterns = [
            r"\b(child|minor|under 13|dependent)\b.*\b(consent|privacy|withdraw|article 7|parental consent)\b",
            r"\b(consent|withdraw)\b.*\b(child|minor|dependent|son|daughter)\b",
        ]
        is_child_consent = any(re.search(pat, q, re.I) for pat in child_consent_patterns)

        # ── Check if user is asking to apply for a child profile ──────────────────
        matched_child = None
        if user_id and db:
            try:
                from services.database import ChildProfile
                with db.session_scope() as sess:
                    # If the frontend passed child_profile_id explicitly (child was already selected),
                    # look up that specific child profile first so context is preserved across turns.
                    frontend_child_id = getattr(req, 'child_profile_id', None)
                    if frontend_child_id:
                        cp = sess.query(ChildProfile).filter_by(
                            profile_id=frontend_child_id,
                            parent_user_id=user_id,
                            profile_status="active"
                        ).first()
                        if cp:
                            matched_child = cp.to_dict()

                    # Fallback: match child by name mention in the message
                    if not matched_child:
                        cps = sess.query(ChildProfile).filter_by(parent_user_id=user_id, profile_status="active").all()
                        for cp in cps:
                            cname = cp.full_name.lower().strip()
                            first_name = cname.split()[0] if cname else ""
                            if cname in q or (first_name and len(first_name) >= 3 and first_name in q):
                                matched_child = cp.to_dict()
                                break
            except Exception as e:
                logger.warning(f"Error checking child profiles in chat: {e}")

        # Check if the query is asking to apply for a child or dependent
        # Also treat it as a child apply if the frontend explicitly passed a child_profile_id
        # (meaning the user is in child-context mode and asking about a service)
        frontend_child_id = getattr(req, 'child_profile_id', None)
        is_child_apply = bool(
            matched_child or
            (frontend_child_id and service) or  # Child context + service request = child apply
            re.search(r"\b(apply|application|register)\b.*\b(child|son|daughter|kid|dependent|minor)\b", q, re.I) or
            re.search(r"\b(for|on behalf of)\s+(my\s+)?(child|son|daughter|kid|dependent|minor)\b", q, re.I)
        )

        if is_child_apply and matched_child:
            action = "start_child_application"
            data = {"child_profile_id": matched_child["profile_id"], "full_name": matched_child["full_name"]}
            if service:
                matched_service = service.service_id
                reply = f"Starting an application for {matched_child['full_name']} for {service.name}."
            else:
                reply = f"Starting an application for {matched_child['full_name']}. Which service would you like to apply for? (Note: Mobility / Rental is unavailable for dependent profiles under 18)."
            intent = "apply"
        elif is_child_create:
            if not user_id:
                reply = (
                    "Docintake allows parents and legally authorized guardians aged 18 or older to manage child dependent profiles through their own account. "
                    "Please sign in or register to create and manage child profiles."
                )
                intent = "auth_required"
                action = "open_login"
            else:
                reply = (
                    "Docintake allows parents and legally authorized guardians aged 18 or older to manage child dependent profiles through their own account. "
                    "Children do not need separate login accounts or passwords. Would you like to create a child profile now?"
                )
                intent = "child_profile_create"
                action = "open_child_modal"
        elif is_child_eligibility:
            reply = (
                "For child dependent profiles: Basic Registration and Premium / Cross Border are available subject to standard document requirements and guardian consent. "
                "Mobility / Rental is NOT AVAILABLE for dependent profiles under 18 because applicants must meet the minimum driving-licence age requirements. "
                "(Mobility / Rental remains fully active and available for eligible adult applicants)."
            )
            intent = "faq"
        elif is_child_consent:
            reply = (
                "Under UAE Federal Decree-Law No. 26 of 2025 (Child Digital Safety, Article 7), explicit parental consent is required before collecting or processing personal information for children under 13. "
                "Docintake provides a continuously accessible withdrawal mechanism. In addition, every application submitted for a child requires separate application-specific document review consent before government reviewers may inspect submitted files."
            )
            intent = "faq"
        elif unavailable_service_name:
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
                # An ok-ack after service info should also count as apply intent
                intent = "apply" if (is_apply or is_ok_ack) else "faq"
        elif is_generic_apply:
            # e.g. "let's get started" with no service named: still an application intent.
            # matched_service stays None so the client asks which service.
            intent = "apply"

        # Safety net: a small model may still ask "which service?" after the user named one.
        if intent == "apply" and service and reply and re.search(r"which (service|one)|what service", reply, re.I):
            reply = f"Great choice! Let's get you started with {service.name}."

        # Output safety net: Ensure the model did not generate an out-of-scope response (e.g. gym/workout routine, recipe, etc.)
        from services.scope_classifier import is_out_of_scope_reply
        if reply and is_out_of_scope_reply(reply):
            logger.warning("LLM generated an out-of-scope reply; overridden by scope safety net.")
            reply = OUT_OF_SCOPE_RESPONSE
            intent = "out_of_scope"
            matched_service = None

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
        steps_taken.append({
            "step": "Intent & Service Routing",
            "status": "passed",
            "details": f"Intent: {intent}, Service: {matched_service or 'None'} (status: {status.value if service else 'N/A'})"
        })
        steps_taken.append({
            "step": "Response Generation",
            "status": "passed",
            "details": f"Generated response ({len(reply) if reply else 0} chars)"
        })

        if intent == "apply" and not user_id:
            # If a service was matched and is coming soon, do not gate behind login
            if service and status.value == "coming_soon":
                return ChatResponse(
                    response=f"{service.name} is currently coming soon and not open for applications yet. Please check back later!",
                    intent="faq",
                    matched_service=matched_service,
                    execution_steps=steps_taken
                )
            return ChatResponse(
                response="To apply for a service, please sign in or sign up first. You can continue asking general questions without signing in.",
                intent=intent,
                matched_service=matched_service,
                execution_steps=steps_taken
            )

        return ChatResponse(
            response=reply,
            intent=intent,
            matched_service=matched_service,
            action=action,
            data=data,
            execution_steps=steps_taken
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
    """Return the authenticated user's active (non-reset) chat session messages."""
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
        # Only return messages from the current active session.
        # get_or_create_chat_session(force_new=False) returns the existing active session
        # or creates a new empty one — never crossing into another user's session.
        session_id = db.get_active_chat_session(user_id=user_id)
        if not session_id:
            return {"success": True, "session_id": None, "messages": [], "count": 0}
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
# Chat reset: start a fresh session (server-side) for the authenticated user
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/chat/reset")
async def reset_chat_session(token: Optional[str] = Query(None, alias="token")):
    """Mark the current chat session as reset and create a new active session."""
    state = get_state()
    db = state.get("database")

    user_id = None
    if token:
        auth = state.get("auth")
        if auth:
            user = auth.validate_token(token)
            if user:
                user_id = user.user_id

    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required.")

    if not db:
        raise HTTPException(status_code=503, detail="Database unavailable.")

    try:
        new_session_id = db.reset_chat_session(user_id=user_id)
        return {"success": True, "new_session_id": new_session_id}
    except Exception as e:
        logger.error(f"Failed to reset chat session: {e}")
        raise HTTPException(status_code=500, detail="Could not reset chat session.")


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
