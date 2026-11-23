"""DocIntake Project-Scope Classifier Service (v4.3 Intent-Based Architecture)."""

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


def is_out_of_scope_reply(reply: str) -> bool:
    """Inspect generated assistant text to guarantee no out-of-scope guidance (e.g. workout plans, recipes) leaks out."""
    if not reply:
        return False
    lower = reply.lower()

    # Workout / gym / fitness plan patterns
    workout_indicators = [
        r"\b(day\s+\d+:\s*(lower|upper|chest|back|legs|rest|push|pull|cardio|full\s+body))",
        r"\b(\d+\s*sets\s+of\s+\d+\s*reps|sets\s+of\s+\d+\s*reps|\d+\s*reps\s+each)\b",
        r"\b(squats?|deadlifts?|bench\s+press|glute\s+bridges|bicep\s+curls?|tricep\s+dips?|dumbbell\s+rows?|leg\s+press|leg\s+curls?|hip\s+thrusts?|bulgarian\s+split\s+squats?)\b",
        r"\b(warm\s+up\s+before\s+each\s+workout|fitness\s+professional|weightlifting|split\s+routine|gym\s+routine)\b",
    ]
    workout_matches = sum(1 for pat in workout_indicators if re.search(pat, lower))
    if workout_matches >= 2:
        return True

    # Recipe / cooking indicators
    recipe_indicators = [
        r"\b(ingredients?:|preheat\s+(the\s+)?oven|tablespoons?|teaspoons?|bake\s+for\s+\d+\s*min)\b"
    ]
    for pat in recipe_indicators:
        if re.search(pat, lower):
            return True

    # Standalone programming / script generation unrelated to DocIntake
    if "```python" in reply or "```javascript" in reply or "```cpp" in reply:
        if not any(k in lower for k in ["docintake", "fastapi", "minio", "pymupdf", "clamav", "postgres", "scoped_hash"]):
            return True

    return False


class ScopeClassifier:
    """Classifies user queries against the approved DocIntake project scope based on semantic intent."""

    # 1. Conversational courtesy and assistant identity patterns (In-scope)
    GREETING_PATTERNS = [
        r"^(hi|hello|hey|good\s+morning|good\s+afternoon|good\s+evening|greetings)(\s+(lynx|docintake|bot|assistant))?[\s!.,?]*$",
        r"^(thank\s+you|thanks|thank\s+you\s+very\s+much|thanks\s+a\s+lot)[\s!.,?]*$",
        r"^(how\s+are\s+you|how's\s+it\s+going|how\s+do\s+you\s+do)[\s!.,?]*$",
        r"^(goodbye|bye|see\s+you|have\s+a\s+nice\s+day)[\s!.,?]*$",
        r"^(who\s+are\s+you|what\s+is\s+your\s+name|what\s+are\s+you|what\s+can\s+you\s+do|what\s+do\s+you\s+do|tell\s+me\s+about\s+yourself)[\s!.,?]*$",
        r"\b(who\s+are\s+you|what\s+can\s+you\s+help\s+with|what\s+is\s+docintake)\b",
    ]

    # 2. Strict Intent-Based Out-of-Scope Triggers (evaluated BEFORE keyword matching)
    STRICT_INTENT_OUT_OF_SCOPE = [
        # Gym, Fitness, Exercise & Workout Plans
        r"\b(gym|workout|fitness|exercise|exercises|bodybuilding|calisthenics|pushups?|pullups?|squats?|deadlifts?|bench\s+press|cardio|running\s+plan|marathon|weight\s+training|hypertrophy|biceps?|triceps?|abs\s+workout|muscle\s+gain|gym\s+routine|workout\s+routine|gym\s+plan|workout\s+plan|split\s+routine|leg\s+day|chest\s+day)\b",
        # Diet, Nutrition, Healthcare & Medical Advice
        r"\b(diet|diet\s+plan|meal\s+plan|keto|calories|calorie\s+deficit|weight\s+loss|lose\s+weight|gain\s+weight|protein\s+intake|vitamins?|nutrition|headache|diagnos(e|is)|symptoms?|medicine|medication|pill|doctor|pharmacy|disease|infection|pain\s+relief|treatment\s+for|medical\s+advice)\b",
        # Creative writing / entertainment / humor / music
        r"\b(write\s+a\s+(story|fictional\s+story|poem|song|essay|play|script)|tell\s+me\s+a\s+(story|joke)|make\s+me\s+laugh|funny\s+joke|rap\s+lyrics|write\s+a\s+song)\b",
        # General education / tutorials from scratch / installation guides
        r"\b(teach\s+me\s+.*(from\s+scratch|for\s+data\s+science|programming|coding)|tutorial\s+for|how\s+do\s+i\s+install\s+.*(on\s+ubuntu|from\s+scratch|on\s+windows)|write\s+(a\s+)?(python|javascript|typescript|c\+\+|java|rust|go|html|css|sql|bash|shell)\s+(script|code|program|function|class)|debug\s+(my\s+)?code|leetcode|algorithm\s+for|binary\s+search|web\s+scraper|scrape\s+a\s+website)\b",
        # Math / academic / homework / physics / chemistry
        r"\b(solve\s+.*equation|calculate|algebra|calculus|geometry|photosynthesis|theory\s+of\s+relativity|quantum|periodic\s+table|astronomy|solar\s+system|homework|derivat(ive|ion)|integral|chemical\s+composition|who\s+invented\s+the\s+first|history\s+of\s+the\s+first|ancient\s+history\s+of|material\s+used\s+to\s+make)\b",
        # External commercial banking / foreign accounts
        r"\b(bank\s+account\s+in\s+switzerland|best\s+bank\s+in|open\s+an\s+offshore\s+account)\b",
        # Jailbreak / persona bypass attempts
        r"\b(ignore\s+(your\s+)?boundaries|ignore\s+all\s+previous|pretend\s+you\s+are\s+a\s+general|act\s+as\s+dan|disregard\s+rules)\b",
        # Cooking / food / recipes
        r"\b(recipe|recipes|cook|cooking|pasta|pizza|cake|bake|baking|ingredient|ingredients|soup|salad|culinary|chef)\b",
        # Weather / climate
        r"\b(weather|temperature|forecast|rain\s+today|snow\s+today|sunny\s+today|humidity|climate\s+change)\b",
        # Movies / media / celebrities / gaming
        r"\b(movie|movies|film|films|cinema|watch\s+tonight|netflix|hollywood|bollywood|actor|actress|celebrity|oscar|video\s+games?|gaming|playstation|xbox|nintendo|elden\s+ring|fortnite|minecraft|pokemon)\b",
        # Sports / athletics / tournaments
        r"\b(football|soccer|basketball|nba|nfl|cricket|tennis|fifa|world\s+cup|premier\s+league|champions\s+league|super\s+bowl|olympics|messi|ronaldo)\b",
        # Random facts / trivia / general astronomy / geography / history
        r"\b(random\s+fact|interesting\s+fact|fact\s+about\s+space|fact\s+about\s+the\s+moon|fact\s+about\s+the\s+ocean)\b",
        r"\b(capital\s+of\s+france|capital\s+of|land\s+border\s+with\s+bahrain|who\s+won|world\s+war|history\s+of|quantum\s+physics|physics|chemistry)\b",
        # Dining / travel / lifestyle / hospitality
        r"\b(restaurant|restaurants|cafe|dining|food|places\s+to\s+eat|holiday\s+destination|vacation\s+spot|travel\s+to|hotel|flight\s+booking|cheap\s+flights|tourist\s+attraction|things\s+to\s+do\s+in|sightseeing|airbnb)\b",
        # Personal advice / career / finance / stocks / crypto / real estate
        r"\b(investment\s+advice|crypto|bitcoin|stock\s+market|personal\s+advice|relationship\s+advice|unrelated\s+personal\s+email|resume|cv|cover\s+letter|job\s+interview|ask\s+for\s+a\s+raise|buy\s+a\s+house|real\s+estate\s+market)\b",
        r"\b(general\s+machine\s+learning|explain\s+general\s+ai|explain\s+general\s+machine\s+learning)\b",
    ]

    # 3. Explicit DocIntake Architecture & Implementation Mentions
    DOCINTAKE_TECH_PATTERNS = [
        r"\b(docintake|in\s+docintake|for\s+docintake|in\s+this\s+application|in\s+our\s+application|in\s+this\s+platform)\b",
        r"\b(fastapi|ollama|qwen|postgresql|postgres|pgvector|clamav|minio|pymupdf|laplacian|blur\s+variance|docling|magic\s+bytes)\b",
        r"\b(document\s+extraction|extract\s+fields|field\s+extraction|how\s+does\s+the\s+system\s+validate)\b",
        r"\b(process\s+uploaded\s+pdfs|uploaded\s+pdf|pdf\s+processing)\b",
        r"\b(what\s+database\s+does\s+docintake\s+use|database\s+accounts\s+in\s+our\s+application)\b",
        r"\b(what\s+is\s+python\s+used\s+for\s+in\s+docintake|python\s+used\s+in\s+docintake)\b",
        r"\b(scoped\s+hash|tamper|encryption|audit\s+log|security\s+audit)\b",
    ]

    # 4. Ambiguous / Needs Clarification patterns
    AMBIGUOUS_PATTERNS = [
        r"^(i\s+want\s+to\s+apply\s+for\s+something|i\s+want\s+to\s+apply|help\s+me\s+apply|how\s+do\s+i\s+apply)[\s!.,?]*$",
        r"^(can\s+you\s+help\s+me\s+with\s+my\s+documents|help\s+with\s+my\s+documents|i\s+have\s+documents)[\s!.,?]*$",
        r"^(can\s+you\s+help\s+me\s+with\s+my\s+account|help\s+with\s+my\s+account|my\s+account)[\s!.,?]*$",
        r"^(i\s+need\s+help|can\s+you\s+help\s+me|help\s+me|how\s+does\s+this\s+work|i'm\s+new\s+here|where\s+do\s+i\s+start)[\s!.,?]*$",
    ]

    # 5. Core In-Scope Service, Document, and Platform Domains
    IN_SCOPE_CORE_PATTERNS = [
        # Available and catalog services
        r"\b(basic\s+registration|premium|cross[\s\-]border|mobility|rental|bank\s+account|insurance|sim\s+registration|loan\s+application|utility\s+connection|tenancy\s+agreement|professional\s+licen[sc]e|vehicle\s+registration|health\s+insurance)\b",
        # Document types
        r"\b(emirates\s+id|national\s+id|passport|driving\s+licen[sc]e|proof\s+of\s+address|utility\s+bill|pay\s+slip|bank\s+statement|tenancy\s+contract)\b",
        # Uploading and submission
        r"\b(upload|uploaded|uploading|submit|submitting|submission|document\s+requirement|file\s+format|file\s+size|pdf|jpeg|png)\b",
        # Application tracking and workflow
        r"\b(application\s+status|track\s+application|check\s+my\s+application|my\s+application|application\s+id|reference\s+number)\b",
        # Verification and validation
        r"\b(human\s+review|validation\s+rules|validation\s+results|unsuccessful|extraction|mrz|blur|blurred|unreadable|expiry|expired)\b",
        # Account and authentication
        r"\b(login|sign\s+in|sign\s+up|register|authentication|account\s+functionality|reset\s+password|logout)\b",
        # Policies and compliance
        r"\b(privacy\s+policy|terms\s+and\s+conditions|terms\s+of\s+service|consent|data\s+retention|gdpr|legal\s+policy)\b",
        # Child Dependent Profiles and Guardian Management
        r"\b(child|children|dependent|dependents|guardian|guardians|minor|minors|parent|parents|caregiver|child\s+profile|dependent\s+profile|article\s+7|parental\s+consent)\b",
        # Catalog questions
        r"\b(what\s+services\s+(do\s+you|does\s+docintake)\s+offer|what\s+services\s+are\s+available|available\s+services|list\s+services|service\s+catalog)\b",
        r"\b(renew\s+my\s+passport|passport\s+renewal)\b",
        # General onboarding terms
        r"\b(onboard|onboarding|applicant|application|verify|verification|validate|validation|document|documents)\b",
    ]

    # Anchors that indicate legitimate DocIntake domain grounding
    IN_SCOPE_ANCHORS = [
        r"\b(docintake|service|services|document|documents|doc|docs|id|passport|licen[sc]e|apply|application|onboard|onboarding|verify|verification|validate|validation|upload|uploaded|file|files|status|track|tracking|account|login|register|registration|terms|privacy|policy|child|children|dependent|guardian|minor|profile)\b"
    ]

    @classmethod
    def classify(cls, query: str) -> Tuple[str, str, Optional[str]]:
        """Classify user query into:
        - ('IN_SCOPE', reason, None or 'MIXED_INTENT')
        - ('OUT_OF_SCOPE', reason, OUT_OF_SCOPE_RESPONSE)
        - ('NEEDS_CLARIFICATION', reason, None)
        """
        q = query.lower().strip()

        # Step 1: Check basic conversational courtesy and bot identity
        for pat in cls.GREETING_PATTERNS:
            if re.search(pat, q):
                return ("IN_SCOPE", "Conversational courtesy / identity", None)

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

        # Step 6: Check core service, document, and platform domain queries
        for pat in cls.IN_SCOPE_CORE_PATTERNS:
            if re.search(pat, q):
                return ("IN_SCOPE", "DocIntake service or document query", None)

        # Step 7: Anchored domain validation (Zero-Trust fallback: Queries with NO DocIntake connection are OUT_OF_SCOPE)
        has_anchor = any(re.search(pat, q) for pat in cls.IN_SCOPE_ANCHORS)
        if not has_anchor:
            return ("OUT_OF_SCOPE", "Query has no connection to DocIntake project scope", OUT_OF_SCOPE_RESPONSE)

        # Step 8: Default: Allow in-scope processing with system prompt grounding
        return ("IN_SCOPE", "General conversational or service inquiry", None)
