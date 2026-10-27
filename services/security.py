"""
Security and Prompt Injection Defense Service.

Role in Project:
    Acts as the defensive perimeter for incoming text and extracted OCR/Vision data.
    Provides real-time regex detection of jailbreaks, prompt overrides, system leakage,
    and cross-tenant data tampering. Also performs applicant name matching between 
    identity documents and applicant claims according to business policy rules.

Cross-File Interconnections:
    - Called by `app.routes.chat_message.send_chat_message` to block direct prompt injection
      attacks before invoking LLM generation (`services.generation`).
    - Called by `services.extraction_ladder` / `app.routes.documents` to sanitize OCR-extracted
      document fields (`sanitize_extracted_document_fields`) and neutralize indirect prompt injections.
    - Called by `agents.validation_agent` to verify document ownership (`validate_applicant_name_match`)
      ensuring names on passports and IDs match the user's application account.

Protects against:
1. Prompt injection & jailbreak attempts in user chat messages.
2. Indirect prompt injections hidden inside scanned/extracted document text or fields.
3. Attempts to leak system instructions, access other users' data, or execute unauthorized operations.
"""

import re
import logging
from typing import Tuple, Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Patterns that indicate prompt injection, jailbreaking, or system override attempts
INJECTION_PATTERNS = [
    # Direct instruction overrides
    r"ignore\s+(all\s+)?(previous|prior|above|existing|system)\s+(instructions|prompts|rules|commands|constraints)",
    r"disregard\s+(all\s+)?(previous|prior|above|existing|system)\s+(instructions|prompts|rules|commands|constraints)",
    r"forget\s+(all\s+)?(previous|prior|above|existing|system)\s+(instructions|prompts|rules|commands|constraints)",
    r"(set|put)\s+(all\s+)?(previous|prior|above|existing|system)\s+(instructions|prompts|rules|commands|constraints)\s+(aside|away)",
    r"override\s+(all\s+)?(previous|prior|system|safety)\s+(instructions|prompts|rules|commands|constraints)",
    r"bypass\s+(all\s+)?(security|system|safety|rules|instructions|filters|guardrails)",
    
    # Role-play / Mode-switching exploits
    r"you\s+are\s+now\s+(in\s+)?(developer\s+mode|dan|jailbreak|unrestricted|god\s+mode|root|admin)",
    r"act\s+as\s+(an?\s+)?(unrestricted|jailbroken|evil|unfiltered|system\s+administrator|terminal|command\s+line)",
    r"pretend\s+(you\s+have\s+no\s+rules|you\s+are\s+not|you\s+can\s+do\s+anything|to\s+be\s+an?\s+unrestricted)",
    
    # System prompt / internal leak attempts
    r"(reveal|show|display|print|output|repeat|leak|dump)\s+(the\s+|your\s+)?(system\s+prompt|initial\s+prompt|secret|instructions|passwords?|api\s*keys?|developer\s+(message|prompt|instructions))",
    r"what\s+(is|are)\s+your\s+(initial|system|hidden|developer)\s+(instructions|prompts|rules)",
    r"(tell|share|quote)\s+(me\s+)?(your\s+)?(system\s+prompt|prompt\s+instructions|system\s+instructions|developer\s+prompt)",
    
    # Cross-user data / unauthorized access attempts
    r"(show|list|dump|get|display|access)\s+(all\s+)?(other\s+users?|other\s+applications?|another\s+user'?s?\s+data|database\s+records?|passwords?|api\s*keys?|internal\s+tables?)",
    r"(give\s+me|switch\s+to)\s+(another|other|different)\s+user'?s?\s+(account|data|session|application|profile)",
    
    # Markdown/XML injection markers
    r"<\s*(system|instruction|prompt)\s*>",
    r"\[\s*(system|instruction|prompt)\s*\]",
    r"```\s*(system|instruction|prompt)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]

SAFE_INJECTION_REPLY = (
    "I cannot process this request because it contains instructions that attempt to override "
    "system policies or access unauthorized data. Please continue with your onboarding application "
    "or ask questions regarding our onboarding services."
)


def detect_prompt_injection(text: str) -> Tuple[bool, Optional[str]]:
    """Scan text for prompt injection, jailbreak attempts, or unauthorized access instructions.
    
    Checks incoming user messages or raw document strings against compiled regex patterns
    representing known attack vectors (e.g., 'ignore previous instructions', 'DAN mode', system prompt leaks).

    Interconnections:
        - Invoked in `app.routes.chat_message.send_chat_message` before user prompt is fed to `services.generation`.
        - Invoked in `sanitize_extracted_document_fields` to screen OCR/Vision parsed text.

    Args:
        text: Input string from a chat message or extracted document value.

    Returns:
        (is_injection, matched_pattern_or_reason)
    """
    if not text or not isinstance(text, str):
        return False, None
    
    normalized = " ".join(text.split()).strip()
    
    for regex in _COMPILED_PATTERNS:
        match = regex.search(normalized)
        if match:
            matched_text = match.group(0)
            logger.warning("Prompt injection detected matching pattern '%s': '%s'", regex.pattern, matched_text)
            return True, f"Injection detected: '{matched_text}'"
            
    return False, None


def sanitize_extracted_document_fields(fields: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """Sanitize document extracted fields to neutralize indirect prompt injection payloads.
    
    If an extracted field contains an injection instruction (e.g. 'ignore previous instructions'),
    that field is flagged and replaced with a neutralized marker '[REDACTED_INJECTION_ATTEMPT]'.

    Interconnections:
        - Called by document processing pipelines (`services.extraction_ladder` and `app.routes.documents`)
          before extracted fields are committed to PostgreSQL or used in downstream LLM reasoning.
    
    Args:
        fields: Dictionary of extracted key-value pairs from documents.

    Returns:
        (sanitized_fields, list_of_flagged_fields)
    """
    if not fields or not isinstance(fields, dict):
        return fields or {}, []
    
    sanitized = {}
    flagged = []
    
    for k, v in fields.items():
        if isinstance(v, str):
            is_inj, pattern = detect_prompt_injection(v)
            if is_inj:
                flagged.append(f"{k} ({pattern})")
                sanitized[k] = "[REDACTED_INJECTION_ATTEMPT]"
                continue
        sanitized[k] = v
        
    return sanitized, flagged


def _normalize_name_tokens(name: str) -> list[str]:
    """Normalize a name into lowercase alphanumeric tokens, stripping accents and punctuation.

    Interconnections:
        - Helper function exclusively utilized by `validate_applicant_name_match()`.
    """
    import unicodedata
    if not name or not isinstance(name, str):
        return []
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in name)
    return [token for token in name.lower().split() if token]


def validate_applicant_name_match(applicant_name: str, doc_name: str, doc_type: str) -> Tuple[bool, str]:
    """Validate user applicant name against document name according to business policy:
    - passport: full name must match (all tokens match, order/accent/case insensitive).
    - national_id / driving_license: at least the first name must match.
    - other documents: at least the first name must match.

    Interconnections:
        - Invoked by `agents.validation_agent.ValidationAgent` during cross-document and
          identity consistency checks.
        - Enforces Moro Hub strict identity governance rules preventing impersonation or
          uploading someone else's ID documents for an application.

    Args:
        applicant_name: The applicant's declared name on the account/application.
        doc_name: The extracted name read from the document.
        doc_type: Document identifier (e.g. 'passport', 'national_id', 'emirates_id').

    Returns:
        (is_match, reason_message)
    """
    user_tokens = _normalize_name_tokens(applicant_name)
    doc_tokens = _normalize_name_tokens(doc_name)

    if not user_tokens:
        return False, "Applicant name cannot be empty."
    if not doc_tokens:
        return False, "Document name is missing or unreadable."

    d_type = (doc_type or "").lower()
    is_passport = "passport" in d_type

    if is_passport:
        # Full name must match: set of tokens must be identical or concatenated match
        if set(user_tokens) == set(doc_tokens):
            return True, "Passport full name matched successfully."
        # Also check concatenated form (e.g. O'Connor vs OConnor)
        if "".join(user_tokens) == "".join(doc_tokens):
            return True, "Passport full name matched successfully."
        return False, (
            f"Passport name mismatch: full name must match. "
            f"Provided: '{applicant_name}', Document: '{doc_name}'"
        )
    else:
        # National ID, driving license, etc.: at least the first name must match
        user_first = user_tokens[0]
        doc_first = doc_tokens[0]
        if user_first == doc_first:
            return True, f"{doc_type} first name matched successfully."
        # If first token doesn't match directly, check if user's first name appears anywhere in doc tokens
        # (e.g. if document lists Surname First or Middle names)
        if user_first in doc_tokens:
            return True, f"{doc_type} first name found in document names."
        return False, (
            f"{doc_type} name mismatch: at least the first name must match. "
            f"Provided first name: '{user_first}', Document names: '{doc_name}'"
        )
