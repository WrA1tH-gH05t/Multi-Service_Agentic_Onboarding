"""Security and Prompt Injection Defense Service."""

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
    """Scan text for prompt injection, jailbreak attempts, or unauthorized access instructions."""
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
    """Sanitize document extracted fields to neutralize indirect prompt injection payloads."""
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
    """Normalize a name into lowercase alphanumeric tokens, stripping accents and punctuation."""
    import unicodedata
    if not name or not isinstance(name, str):
        return []
    name = unicodedata.normalize('NFKD', name)
    name = ''.join(c for c in name if not unicodedata.combining(c))
    name = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in name)
    return [token for token in name.lower().split() if token]


def validate_applicant_name_match(applicant_name: str, doc_name: str, doc_type: str) -> Tuple[bool, str]:
    """Validate user applicant name against document name according to business policy:"""
    user_tokens = _normalize_name_tokens(applicant_name)
    doc_tokens = _normalize_name_tokens(doc_name)

    if not user_tokens:
        return False, "Applicant name cannot be empty."
    if not doc_tokens:
        return False, "Document name is missing or unreadable."

    d_type = (doc_type or "").lower()
    is_passport = "passport" in d_type

    if is_passport:
        # Full name matching:
        # 1. Exact token set equality regardless of order (e.g. "SATISH KUMAR ARVIND KAUSHIK" vs "ARVIND KAUSHIK SATISH KUMAR")
        if set(user_tokens) == set(doc_tokens):
            return True, "Passport full name matched successfully."
        # 2. Check concatenated form (e.g. O'Connor vs OConnor)
        if "".join(user_tokens) == "".join(doc_tokens):
            return True, "Passport full name matched successfully."
        # 3. Subset matching: only if substantial (e.g. user entered full name and doc contains it with father/patronymic name)
        # However, if only first name or partial name is present, passport requires full name
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


# ──────────────────────────────────────────────────────────────────────
# Role-Based Access Control and Document Content Protection
# ──────────────────────────────────────────────────────────────────────

# Strict roles:
# - applicant: Can view and download ONLY their own documents
# - government_reviewer: Can view documents for applications routed to their assigned agency
# - compliance_reviewer: Can view documents if assigned and authorized
# - platform_admin: Can manage users, settings, and non-sensitive infrastructure (NO direct customer document content bypass)
# - developer: Strictly restricted to logs, code, metrics, synthetic data (CANNOT view real customer documents)

class DocumentAccessControl:
    """Enforces strict role-based access control and developer restrictions on document content."""

    DEVELOPER_RESTRICTED_ACTIONS = {"view", "download", "presigned_url", "extract_raw"}

    @staticmethod
    def get_user_role(db, user_id: str) -> Tuple[str, Optional[str]]:
        """Retrieve user's primary role and assigned agency_id from database or default to applicant."""
        if not db or not user_id:
            return "applicant", None
        try:
            with db.session_scope() as session:
                from services.database import UserRole
                role_record = session.query(UserRole).filter_by(user_id=user_id).first()
                if role_record:
                    return role_record.role_name, role_record.agency_id
        except Exception as e:
            logger.warning(f"Error checking user role for {user_id}: {e}")
        return "applicant", None

    @classmethod
    def authorize_document_access(
        cls,
        db,
        user_id: str,
        document_id: str,
        action: str = "view",
        ip_address: Optional[str] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Verify whether a user is authorized to view or download a specific document.
        
        Returns:
            (authorized: bool, reason: str, doc_data: Optional[Dict])
        """
        import uuid
        from services.database import Document, Application, ApplicationConsent, DocumentAccessAudit

        role_name, assigned_agency = cls.get_user_role(db, user_id)

        # 1. STRICT DEVELOPER ACCESS EXCLUSION
        if role_name == "developer":
            logger.warning(f"SECURITY ALERT: Developer {user_id} attempted to access document {document_id}")
            cls._log_access_attempt(
                db, document_id=document_id, application_id=None, user_id=user_id,
                user_role=role_name, agency_id=assigned_agency, action=action,
                access_granted=False, denial_reason="developer_access_forbidden", ip_address=ip_address
            )
            return False, "Access denied: Platform developers are strictly restricted from accessing customer document contents.", None

        # Fetch document from DB
        with db.session_scope() as session:
            doc = session.query(Document).filter_by(document_id=document_id).first()
            if not doc:
                return False, "Document not found.", None
            
            doc_dict = doc.to_dict()
            app_id = doc.application_id
            owner_id = doc.user_id

            # Check if document belongs to an application for a child profile owned by this parent
            is_child_owner = False
            if app_id:
                app_record = session.query(Application).filter_by(application_id=app_id).first()
                if app_record and app_record.child_profile_id:
                    from services.database import ChildProfile
                    cp = session.query(ChildProfile).filter_by(
                        profile_id=app_record.child_profile_id,
                        parent_user_id=user_id
                    ).first()
                    if cp:
                        is_child_owner = True

            # 2. APPLICANT ROLE: Can access their own documents or their dependent child's documents
            if role_name in ("applicant", "parent", "guardian"):
                if owner_id == user_id or is_child_owner:
                    cls._log_access_attempt(
                        db, document_id=document_id, application_id=app_id, user_id=user_id,
                        user_role=role_name, agency_id=None, action=action,
                        access_granted=True, denial_reason=None, ip_address=ip_address
                    )
                    return True, "Authorized as document owner or legal guardian.", doc_dict
                else:
                    cls._log_access_attempt(
                        db, document_id=document_id, application_id=app_id, user_id=user_id,
                        user_role=role_name, agency_id=None, action=action,
                        access_granted=False, denial_reason="unauthorized_applicant_not_owner", ip_address=ip_address
                    )
                    return False, "Access denied: You do not own this document.", None

            # 3. GOVERNMENT REVIEWER: Check application routing, consent, and assigned agency
            if role_name == "government_reviewer":
                if not app_id:
                    cls._log_access_attempt(
                        db, document_id=document_id, application_id=None, user_id=user_id,
                        user_role=role_name, agency_id=assigned_agency, action=action,
                        access_granted=False, denial_reason="unassigned_application", ip_address=ip_address
                    )
                    return False, "Access denied: Document is not linked to an application.", None

                app = session.query(Application).filter_by(application_id=app_id).first()
                if not app:
                    return False, "Application not found.", None

                # Check valid consent (either adult ApplicationConsent or ChildApplicationReviewConsent)
                consent = session.query(ApplicationConsent).filter_by(application_id=app_id, status="agreed").first()
                child_consent = None
                if not consent:
                    from services.database import ChildApplicationReviewConsent
                    child_consent = session.query(ChildApplicationReviewConsent).filter(
                        ChildApplicationReviewConsent.application_id == app_id,
                        ChildApplicationReviewConsent.consent_status == "accepted"
                    ).first()

                if not consent and not child_consent:
                    cls._log_access_attempt(
                        db, document_id=document_id, application_id=app_id, user_id=user_id,
                        user_role=role_name, agency_id=assigned_agency, action=action,
                        access_granted=False, denial_reason="no_active_consent", ip_address=ip_address
                    )
                    return False, "Access denied: Applicant or legal guardian has not provided active document review consent.", None

                # Check Agency Scoping: Reviewer agency must match application designated agency
                target_agency = consent.designated_agency if consent else child_consent.receiving_agency_id
                if assigned_agency and target_agency and assigned_agency != target_agency:
                    cls._log_access_attempt(
                        db, document_id=document_id, application_id=app_id, user_id=user_id,
                        user_role=role_name, agency_id=assigned_agency, action=action,
                        access_granted=False, denial_reason="cross_agency_forbidden", ip_address=ip_address
                    )
                    return False, f"Access denied: This application is designated for '{target_agency}', not your agency '{assigned_agency}'.", None

                cls._log_access_attempt(
                    db, document_id=document_id, application_id=app_id, user_id=user_id,
                    user_role=role_name, agency_id=assigned_agency, action=action,
                    access_granted=True, denial_reason=None, ip_address=ip_address
                )
                return True, "Authorized government agency reviewer.", doc_dict

            # 4. COMPLIANCE REVIEWER: Audit inspection permitted with logging
            if role_name == "compliance_reviewer":
                cls._log_access_attempt(
                    db, document_id=document_id, application_id=app_id, user_id=user_id,
                    user_role=role_name, agency_id=assigned_agency, action=action,
                    access_granted=True, denial_reason=None, ip_address=ip_address
                )
                return True, "Authorized compliance audit inspection.", doc_dict

            # 5. PLATFORM ADMIN: Infrastructure only — no direct document content access
            if role_name == "platform_admin":
                cls._log_access_attempt(
                    db, document_id=document_id, application_id=app_id, user_id=user_id,
                    user_role=role_name, agency_id=None, action=action,
                    access_granted=False, denial_reason="admin_content_access_forbidden", ip_address=ip_address
                )
                return False, "Access denied: Platform administrators manage infrastructure and cannot view customer document binaries.", None

        return False, "Access denied: Unrecognized role or permissions.", None

    @staticmethod
    def _log_access_attempt(db, document_id, application_id, user_id, user_role, agency_id, action, access_granted, denial_reason, ip_address):
        """Append an immutable document access audit record."""
        import uuid
        try:
            with db.session_scope() as session:
                from services.database import DocumentAccessAudit
                audit = DocumentAccessAudit(
                    audit_id=f"acc_{uuid.uuid4().hex[:12]}",
                    document_id=document_id,
                    application_id=application_id,
                    user_id=user_id,
                    user_role=user_role,
                    agency_id=agency_id,
                    action=action,
                    access_granted=access_granted,
                    denial_reason=denial_reason,
                    ip_address=ip_address,
                )
                session.add(audit)
        except Exception as e:
            logger.error(f"Failed to record DocumentAccessAudit: {e}")

