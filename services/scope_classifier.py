"""DocIntake Project-Scope Classifier Service (v4.2 Intent-Based Architecture)."""

import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

# Standard rejection response for out-of-scope queries
OUT_OF_SCOPE_RESPONSE = (
    "I'm the DocIntake AI assistant, and I'm here to help with our onboarding services, "
    "document requirements, applications, and related platform support. I can't assist with "
    "unrelated topics, but I'd be happy to help with anything concerning DocIntake."
)

class ScopeClassifier:
    """Classifies user queries against the approved DocIntake project scope based on semantic intent."""

    # 1. Conversational courtesy patterns (In-scope basic courtesy)
    GREETING_PATTERNS = [
        r"^(hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings)[\s!.,?]*$",
        r"^(thank\s+you|thanks|thank\s+you\s+very\s+much|thanks\s+a\s+lot)[\s!.,?]*$",
        r"^(how\s+are\s+you|how's\s+it\s+going|how\s+do\s+you\s+do)[\s!.,?]*$",
        r"^(goodbye|bye|see\s+you|have\s+a\s+nice\s+day)[\s!.,?]*$"
    ]

    # 2. Strict Intent-Based Out-of-Scope Triggers (evaluated BEFORE keyword matching)
    # Even if they mention "passport", "license", "postgres", or "python", these intentions are strictly OUT_OF_SCOPE:
    STRICT_INTENT_OUT_OF_SCOPE = [
        # Creative writing / entertainment / humor
        r"\b(write\s+a\s+(story|fictional\s+story|poem|song|essay|play)|tell\s+me\s+a\s+(story|joke)|make\s+me\s+laugh|funny\s+joke)\b",
        # General education / tutorials from scratch / installation guides
        r"\b(teach\s+me\s+.*(from\s+scratch|for\s+data\s+science|programming|coding)|tutorial\s+for|how\s+do\s+i\s+install\s+.*(on\s+ubuntu|from\s+scratch|on\s+windows))\b",
        # History / origins / physical science / chemistry of materials
        r"\b(chemical\s+composition|who\s+invented\s+the\s+first|history\s+of\s+the\s+first|ancient\s+history\s+of|material\s+used\s+to\s+make)\b",
        # External commercial banking / foreign accounts
        r"\b(bank\s+account\s+in\s+switzerland|best\s+bank\s+in|open\s+an\s+offshore\s+account)\b",
        # Jailbreak / persona bypass attempts
        r"\b(ignore\s+(your\s+)?boundaries|ignore\s+all\s+previous|pretend\s+you\s+are\s+a\s+general|act\s+as\s+dan|disregard\s+rules)\b",
        # Cooking / food / recipes
        r"\b(recipe|cook|cooking|pasta|pizza|cake|bake|baking|ingredient|soup|salad|culinary|chef)\b",
        # Weather / climate
        r"\b(weather|temperature|forecast|rain\s+today|snow\s+today|sunny\s+today)\b",
        # Movies / media / celebrities
        r"\b(movie|film|cinema|watch\s+tonight|netflix|hollywood|actor|actress)\b",
        # Random facts / trivia / general astronomy / geography / history
        r"\b(random\s+fact|interesting\s+fact|fact\s+about\s+space|fact\s+about\s+the\s+moon|fact\s+about\s+the\s+ocean)\b",
        r"\b(capital\s+of\s+france|capital\s+of|land\s+border\s+with\s+bahrain|who\s+won|world\s+war|history\s+of|quantum\s+physics|physics|chemistry)\b",
        # Dining / travel / lifestyle
        r"\b(restaurant|restaurants|cafe|dining|food|places\s+to\s+eat|holiday\s+destination|vacation\s+spot|travel\s+to)\b",
        # Personal advice / finance / stocks / crypto
        r"\b(investment\s+advice|crypto|bitcoin|stock\s+market|personal\s+advice|relationship\s+advice|unrelated\s+personal\s+email)\b",
        r"\b(general\s+machine\s+learning|explain\s+general\s+ai|explain\s+general\s+machine\s+learning)\b",
    ]

    # 3. Explicit DocIntake Architecture & Implementation Mentions
    DOCINTAKE_TECH_PATTERNS = [
        r"\b(docintake|in\s+docintake|for\s+docintake|in\s+this\s+application|in\s+our\s+application|in\s+this\s+platform)\b",
        r"\b(fastapi|ollama|qwen|postgresql|postgres|clamav|minio|pymupdf|laplacian|blur\s+variance)\b",
        r"\b(document\s+extraction|extract\s+fields|field\s+extraction|how\s+does\s+the\s+system\s+validate)\b",
        r"\b(process\s+uploaded\s+pdfs|uploaded\s+pdf|pdf\s+processing|magic\s+bytes)\b",
        r"\b(what\s+database\s+does\s+docintake\s+use|database\s+accounts\s+in\s+our\s+application)\b",
        r"\b(what\s+is\s+python\s+used\s+for\s+in\s+docintake|python\s+used\s+in\s+docintake)\b"
    ]

    # 4. Ambiguous / Needs Clarification patterns
    AMBIGUOUS_PATTERNS = [
        r"^(i\s+want\s+to\s+apply\s+for\s+something|i\s+want\s+to\s+apply|help\s+me\s+apply)[\s!.,?]*$",
        r"^(can\s+you\s+help\s+me\s+with\s+my\s+documents|help\s+with\s+my\s+documents|i\s+have\s+documents)[\s!.,?]*$",
        r"^(can\s+you\s+help\s+me\s+with\s+my\s+account|help\s+with\s+my\s+account|my\s+account)[\s!.,?]*$",
        r"^(i\s+need\s+help)[\s!.,?]*$",
    ]

    # 5. Core In-Scope Service and Document Domains
    IN_SCOPE_CORE_PATTERNS = [
        r"\b(basic\s+registration|premium|cross[\s\-]border|mobility|rental)\b",
        r"\b(emirates\s+id|national\s+id|passport|driving\s+licen[sc]e|proof\s+of\s+address)\b",
        r"\b(upload|uploaded|uploading|submit|submitting|submission)\b",
        r"\b(application\s+status|track\s+application|check\s+my\s+application|my\s+application)\b",
        r"\b(human\s+review|validation\s+rules|validation\s+results|unsuccessful|extraction)\b",
        r"\b(login|sign\s+in|sign\s+up|register|authentication|account\s+functionality)\b",
        r"\b(expired\s+passport|expired\s+id|unreadable\s+licen[sc]e|missing\s+document)\b",
        r"\b(what\s+services\s+does\s+docintake\s+offer|what\s+services\s+are\s+available)\b",
        r"\b(renew\s+my\s+passport|passport\s+renewal)\b"
    ]

    @classmethod
    def classify(cls, query: str) -> Tuple[str, str, Optional[str]]:
        """Classify user query into:"""
        q = query.lower().strip()

        # Step 1: Check basic conversational courtesy
        for pat in cls.GREETING_PATTERNS:
            if re.search(pat, q):
                return ("IN_SCOPE", "Conversational courtesy", None)

        # Step 2: Check for mixed intents (DocIntake specific query combined with an out-of-scope query)
        has_docintake_explicit = any(re.search(pat, q) for pat in [
            r"\b(in\s+docintake|for\s+docintake|docintake|basic\s+registration|premium|mobility)\b"
        ])
        has_strict_out_of_scope = any(re.search(pat, q) for pat in cls.STRICT_INTENT_OUT_OF_SCOPE)

        if has_docintake_explicit and has_strict_out_of_scope:
            return ("IN_SCOPE", "Mixed intent - DocIntake question present", "MIXED_INTENT")

        # Step 3: Enforce strict out-of-scope intents (takes precedence over generic document keywords)
        for pat in cls.STRICT_INTENT_OUT_OF_SCOPE:
            if re.search(pat, q):
                return ("OUT_OF_SCOPE", f"Matched out-of-scope intent: {pat}", OUT_OF_SCOPE_RESPONSE)

        # Step 4: Check for ambiguous queries requiring clarification
        for pat in cls.AMBIGUOUS_PATTERNS:
            if re.search(pat, q):
                return ("NEEDS_CLARIFICATION", "Ambiguous query requiring clarification", None)

        # Step 5: Check explicit DocIntake architecture questions
        for pat in cls.DOCINTAKE_TECH_PATTERNS:
            if re.search(pat, q):
                return ("IN_SCOPE", "DocIntake technical architecture query", None)

        # Step 6: Check core service and document domain queries
        for pat in cls.IN_SCOPE_CORE_PATTERNS:
            if re.search(pat, q):
                return ("IN_SCOPE", "DocIntake service or document query", None)

        # Step 7: General question catch-all (questions with no DocIntake context)
        general_indicators = [
            r"\b(who\s+is|what\s+is\s+the\s+capital|where\s+is|how\s+many\s+planets|tell\s+me\s+about\s+the\s+universe)\b",
            r"\b(how\s+to\s+play|rules\s+of\s+chess|football|soccer|basketball|nba)\b",
            r"\b(translate\s+this|write\s+a\s+poem|write\s+a\s+song|sing\s+a\s+song)\b",
            r"\b(unrelated|different\s+topic|discuss\s+something\s+unrelated)\b"
        ]
        for pat in general_indicators:
            if re.search(pat, q):
                return ("OUT_OF_SCOPE", "Unrelated general question", OUT_OF_SCOPE_RESPONSE)

        # Default: Allow in-scope processing with system prompt grounding
        return ("IN_SCOPE", "General conversational or service inquiry", None)
