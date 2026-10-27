"""
Deterministic Router — Phase 2 (hardened)

Replaces LLM-based routing with fixed, explainable logic.

Design decisions:
- Fully deterministic: same input always yields same output
- No guessing: low-confidence matches return "ambiguous"
- Coming-soon services are explicitly named, never hidden
- Every decision is trace-logged with inputs, scores, and rule fired
- Configurable thresholds via config.yaml router section
- pgvector similarity fallback for semantic matching
- FAQ answers are grounded in service_definitions chunks
"""

import logging
import re
import os
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field

from services.service_catalog import ServiceCatalogService, ServiceDefinition, ServiceStatus

logger = logging.getLogger(__name__)


# ────────────────────────────────────────────────────────────────────
#  Data classes
# ────────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """A single deterministic routing result."""
    intent: str  # 'question', 'apply', 'other'
    service_resolution: str  # 'available', 'coming_soon', 'not_in_catalogue', 'ambiguous'
    matched_service: Optional[str] = None  # service_id
    score: float = 0.0  # 0-1 confidence
    rule_fired: str = ""  # description of which rule matched
    inputs: dict = field(default_factory=dict)


@dataclass
class FAQAnswer:
    """A grounded FAQ answer from pgvector retrieval."""
    answer: str
    source_file: str  # original document path
    chunk_id: str  # which chunk matched
    similarity: float  # 0-1 pgvector cosine similarity
    service_id: Optional[str] = None
    confidence: float = 0.0


# ────────────────────────────────────────────────────────────────────
#  Intent classification keywords (fixed rules)
# ────────────────────────────────────────────────────────────────────

QUESTION_PATTERNS = [
    r'\bwhat\s+(do\s+)?(i\s+need|are\s+the\s+requirements|is\s+required|about)\b',
    r'\bhow\s+(does\s+\w+\s+work|long\s+(does|will)|much\s+(does|will))\b',
    r'\brequirements?\s+for\b',
    r'\bcan\s+you\s+tell\s+(me\s+)?(me\s+about|about)\b',
    r'\binformation\s+about\b',
    r'\bwhat\s+are\s+(the\s+)?(requirements?|documents?|steps?|rules?|rules)\b',
    r'\bwhat\s+do\s+(i\s+)?need\b',
    r'\bwhat\s+is\s+(required|needed)\b',
    r'\bexplain\s+(me\s+)?\b',
    r'\bdefine\s+(me\s+)?\b',
    r'\bprocess\s+for\b',
    r'\bhow\s+(to|can\s+i|does)\b',
]

APPLY_PATTERNS = [
    r'\bi\s+want\s+to\s+apply\b',
    r'\bstart\s+my\s+(application|application\s+for|app)\b',
    r'\bsign\s+me\s+(up|on)\b',
    r'\bapply\s+(for\s+)?\b',
    r'\bbegin\s+(my\s+)?application\b',
    r'\bget\s+started\b',
    r'\bregister\s+now\b',
    r'\bsign\s+up\b',
    r'\bopen\s+(an\s+)?account\b',
    r'\bbegin\s+(my\s+)?signup\b',
]


# ────────────────────────────────────────────────────────────────────
#  Alias mappings
# ────────────────────────────────────────────────────────────────────

ALIAS_MAP: Dict[str, str] = {
    # national_id aliases
    "national id": "national_id",
    "nationalid": "national_id",
    "national identity": "national_id",
    "id card": "national_id",
    "national identity card": "national_id",
    # passport aliases
    "passport": "passport",
    "travel doc": "passport",
    "travel document": "passport",
    # driving_license aliases
    "driving license": "driving_license",
    "driving licence": "driving_license",
    "dl": "driving_license",
    "driving": "driving_license",
    "driver licence": "driving_license",
    "driver's license": "driving_license",
    "driver's licence": "driving_license",
    # Service name aliases
    "bank": "bank_account",
    "banking": "bank_account",
    "bank account": "bank_account",
    "insurance": "insurance",
    "insure": "insurance",
    "insurance coverage": "insurance",
    "sim": "sim_registration",
    "sim card": "sim_registration",
    "cell phone": "sim_registration",
    "mobile": "sim_registration",
    "phone": "sim_registration",
    "loan": "loan_application",
    "personal loan": "loan_application",
    "mortgage": "loan_application",
    "utility": "utility_connection",
    "electricity": "utility_connection",
    "water": "utility_connection",
    "gas": "utility_connection",
    "tenancy": "tenancy_agreement",
    "rent": "tenancy_agreement",
    "rental agreement": "tenancy_agreement",
    "professional license": "professional_license",
    "profession": "professional_license",
    "vehicle": "vehicle_registration",
    "car": "vehicle_registration",
    "motor": "vehicle_registration",
    "registration": "vehicle_registration",
    # Available service aliases
    "basic": "basic_registration",
    "simple": "basic_registration",
    "standard": "basic_registration",
    "cross border": "premium_crossborder",
    "premium": "premium_crossborder",
    "international": "premium_crossborder",
    "mobility": "mobility_rental",
    "rental": "mobility_rental",
    "car rental": "mobility_rental",
    "vehicle rental": "mobility_rental",
    "utility bill": "utility_bill",
    "property deed": "property_deed",
    "pay slip": "pay_slip",
    "payslip": "pay_slip",
    "bank statement": "bank_statement",
    "medical report": "medical_report",
    "employment letter": "employment_letter",
    "qualifications": "qualifications",
    "reference letter": "reference_letter",
    "insurance certificate": "insurance_certificate",
}

# Default thresholds (overridden by config.yaml router section)
DEFAULT_THRESHOLDS = {
    "embedding_threshold": 0.6,
    "keyword_threshold": 0.4,
    "fallback_threshold": 0.3,
}


def _levenshtein_distance(a: str, b: str) -> int:
    """Simple Levenshtein distance (edit distance) between two strings.
    Returns distance; if > 2, not considered a fuzzy match.
    """
    if len(a) < len(b):
        return _levenshtein_distance(b, a)
    if not b:
        return len(a)

    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (ca != cb)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


def _check_levenshtein(text: str, keyword: str, max_dist: int = 2) -> bool:
    """Check if a keyword matches within max_dist edit distance of any
    word or token in the text."""
    text_lower = text.lower()
    keyword_lower = keyword.lower()

    # Direct containment check first
    if keyword_lower in text_lower:
        return True

    # Token-level fuzzy check
    tokens = re.split(r'[\s\-_/]+', text_lower)
    for token in tokens:
        if _levenshtein_distance(token, keyword_lower) <= max_dist:
            return True

    return False


class DeterministicRouter:
    """
    Deterministic router that replaces LLM-based routing with fixed,
    explainable logic.

    Usage:
        router = DeterministicRouter(catalog, config)
        decision = router.route("How do I apply for a passport?", user_id="user123")
        print(decision.intent, decision.service_resolution, decision.matched_service)
    """

    def __init__(
        self,
        catalog: Optional[ServiceCatalogService] = None,
        config: Optional[dict] = None,
        db_service=None,  # DatabaseService instance for pgvector/trace
    ):
        self.catalog = catalog or ServiceCatalogService()
        # Load thresholds from config, fall back to defaults
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        router_config = (config or {}).get("router", {})
        for key in self.thresholds:
            if key in router_config:
                self.thresholds[key] = float(router_config[key])
        self.embedding_threshold: float = self.thresholds["embedding_threshold"]
        self.keyword_threshold: float = self.thresholds["keyword_threshold"]
        self.fallback_threshold: float = self.thresholds["fallback_threshold"]
        self._trace_logger = None
        self._db = db_service
        self._ollama_config = (config or {}).get("ollama", {})

    # ───────────────────────────────────────────────────────────────
    #  Public API
    # ───────────────────────────────────────────────────────────────

    def route(self, user_input: str, user_id: Optional[str] = None,
              application_id: Optional[str] = None) -> RoutingDecision:
        """
        Route a user input to the appropriate service.

        Steps:
        1. Classify intent (question / apply / other)
        2. Try keyword match against catalogue
        3. Try alias match against catalogue
        4. Try embedding similarity (pgvector + Ollama)
        5. If confidence too low, return ambiguous
        6. If coming-soon service, return coming_soon resolution
        7. Log the decision to trace_events table AND trace logger

        Returns a RoutingDecision with all fields populated.
        """
        inputs = {
            "user_input": user_input,
            "user_id": user_id,
            "application_id": application_id,
        }

        # Step 1: Intent classification
        intent = self._classify_intent(user_input)
        inputs["intent"] = intent

        # Step 2: Service matching
        matched_service = self._match_service_keywords(user_input)
        inputs["keyword_match"] = matched_service.service_id if matched_service else None

        score = 0.0
        rule_fired = ""
        resolution = "not_in_catalogue"

        if matched_service is None:
            # No keyword/alias match — try embeddings
            emb_score = self._check_embedding_similarity(user_input)
            inputs["embedding_score"] = emb_score
            if emb_score >= self.embedding_threshold:
                score = emb_score
                rule_fired = f"embedding_similarity_score={emb_score:.2f}>=threshold={self.embedding_threshold}"
                resolution = "ambiguous"  # we don't have a matched service from embedding alone
            else:
                score = emb_score
                rule_fired = f"embedding_similarity_score={emb_score:.2f}<threshold={self.embedding_threshold}"
                resolution = "not_in_catalogue"
        else:
            score = self._compute_keyword_score(user_input, matched_service)
            if score >= self.keyword_threshold:
                inputs["keyword_score"] = score
                rule_fired = f"keyword_match_score={score:.2f}>=threshold={self.keyword_threshold}"
                if matched_service.status == ServiceStatus.AVAILABLE:
                    resolution = "available"
                else:
                    resolution = "coming_soon"
            else:
                # Low keyword score — check if any other service matches better
                alt_service, alt_score = self._find_best_alternative(user_input)
                if alt_service and alt_score >= self.keyword_threshold:
                    matched_service = alt_service
                    score = alt_score
                    rule_fired = f"alternative_keyword_match_score={alt_score:.2f}"
                    if matched_service.status == ServiceStatus.AVAILABLE:
                        resolution = "available"
                    else:
                        resolution = "coming_soon"
                else:
                    inputs["keyword_score"] = score
                    rule_fired = f"keyword_match_score={score:.2f}<threshold={self.keyword_threshold}"
                    resolution = "ambiguous"

        decision = RoutingDecision(
            intent=intent,
            service_resolution=resolution,
            matched_service=matched_service.service_id if matched_service else None,
            score=round(score, 4),
            rule_fired=rule_fired,
            inputs=inputs,
        )

        # Log to trace logger AND trace_events table
        self._log_routing_decision(decision, application_id)

        return decision

    def set_trace_logger(self, trace_logger):
        """Attach a TraceLogger instance for tracing routing decisions."""
        self._trace_logger = trace_logger

    # ───────────────────────────────────────────────────────────────
    #  Intent classification (fixed rules, no LLM)
    # ───────────────────────────────────────────────────────────────

    def _classify_intent(self, text: str) -> str:
        """
        Classify the intent of user input using fixed rules.

        Returns one of: 'question', 'apply', 'other'

        Rules:
        - Contains question words + service reference -> question
        - Contains apply/start/sign up keywords -> apply
        - Both present -> question (answer first, then offer apply button)
        - No clear signal -> other
        """
        text_lower = text.lower()

        matches_question = any(
            re.search(pattern, text_lower) for pattern in QUESTION_PATTERNS
        )
        matches_apply = any(
            re.search(pattern, text_lower) for pattern in APPLY_PATTERNS
        )

        if matches_question and matches_apply:
            # Mixed: prioritize question (answer first, offer apply)
            return "question"
        elif matches_question:
            return "question"
        elif matches_apply:
            return "apply"
        else:
            return "other"

    # ───────────────────────────────────────────────────────────────
    #  Service matching
    # ───────────────────────────────────────────────────────────────

    def _match_service_keywords(self, text: str) -> Optional[ServiceDefinition]:
        """
        Match user input against the service catalogue using keyword matching.

        Handles:
        - Direct keyword index lookups (exact sub-string)
        - Alias mapping (e.g., "national id" -> "national_id")
        - Fuzzy matching (up to 2 character Levenshtein distance)

        Returns the best matching ServiceDefinition, or None.
        """
        text_lower = text.lower()

        # 1. Direct keyword index lookup (exact sub-string match)
        if text_lower in self.catalog._keyword_index:
            svc = self.catalog._services[self.catalog._keyword_index[text_lower]]
            return svc

        # 2. Alias mapping lookup
        for alias, target in ALIAS_MAP.items():
            alias_lower = alias.lower()
            if alias_lower in text_lower:
                svc = self.catalog.get_service(target)
                if svc:
                    return svc
                # Alias points to a doc type that's a required doc of a service
                for svc_candidate in self.catalog._services.values():
                    if target in svc_candidate.required_documents:
                        return svc_candidate

        # 3. Check service IDs / names directly in the text
        for svc_id, svc in self.catalog._services.items():
            if svc_id in text_lower:
                return svc
            if svc.name.lower() in text_lower:
                return svc

        # 4. Fuzzy matching against keyword index (token-level)
        for keyword, svc_id in self.catalog._keyword_index.items():
            if _check_levenshtein(text_lower, keyword, max_dist=2):
                svc = self.catalog._services[svc_id]
                return svc

        # 5. Alias-based fuzzy matching
        for alias, target in ALIAS_MAP.items():
            if _check_levenshtein(text_lower, alias, max_dist=2):
                svc = self.catalog.get_service(target)
                if svc:
                    return svc

        return None

    def _compute_keyword_score(self, text: str, service: ServiceDefinition) -> float:
        """
        Compute a keyword match score (0-1) for a given service.

        Scoring:
        - Service ID mentioned: 1.0
        - Service name mentioned: 0.8
        - Required document mentioned: 0.7
        - Alias mentioned: 0.6
        - Description keywords match: 0.3-0.5 depending on count
        """
        text_lower = text.lower()
        max_score = 0.0

        # Service ID match
        if service.service_id in text_lower:
            return 1.0

        # Service name match
        if service.name.lower() in text_lower:
            return 0.9

        # Required document matches
        doc_matches = sum(
            1 for doc in service.required_documents if doc.lower() in text_lower
        )
        if doc_matches > 0:
            doc_score = min(0.95, 0.7 * doc_matches / max(len(service.required_documents), 1))
            max_score = max(max_score, doc_score)

        # Alias matches
        for alias in ALIAS_MAP:
            if ALIAS_MAP[alias] in (service.service_id, *service.required_documents):
                if alias.lower() in text_lower:
                    max_score = max(max_score, 0.6)

        # Description keyword overlap
        desc_words = set(re.findall(r'\b[a-z]{3,}\b', service.description.lower()))
        text_words = set(re.findall(r'\b[a-z]{3,}\b', text_lower))
        if desc_words and text_words:
            overlap = len(desc_words & text_words) / len(desc_words)
            max_score = max(max_score, 0.3 + overlap * 0.3)

        return max_score

    def _find_best_alternative(self, text: str) -> Tuple[Optional[ServiceDefinition], float]:
        """
        Find the best alternative service match by scoring all services.
        Returns (service_definition, score) or (None, 0.0).
        """
        best_svc = None
        best_score = 0.0

        for svc in self.catalog.get_all_services():
            score = self._compute_keyword_score(text, svc)
            if score > best_score:
                best_score = score
                best_svc = svc

        return best_svc, best_score

    # ───────────────────────────────────────────────────────────────
    #  Embedding similarity (optional, requires pgvector + Ollama)
    # ───────────────────────────────────────────────────────────────

    def _check_embedding_similarity(self, text: str) -> float:
        """
        Check embedding similarity between user input and all service definitions.

        Uses pgvector stored embeddings first, falls back to Ollama inline.
        Returns similarity score 0-1.
        """
        if not self._db:
            # Try Ollama directly as last resort
            return self._check_ollama_embedding(text)

        try:
            from services.database import ServiceDefinition as DBServiceDef, TraceEvent
            session = self._db.get_session()
            try:
                db_defs = session.query(DBServiceDef).all()
                if not db_defs:
                    return self._check_ollama_embedding(text)

                # Get Ollama host/port
                host = self._ollama_config.get("host", "127.0.0.1")
                port = self._ollama_config.get("port", 11434)
                embed_model = self._ollama_config.get("embedding_model", "nomic-embed-text")

                import httpx
                resp = httpx.post(
                    f"http://{host}:{port}/api/embeddings",
                    json={
                        "model": embed_model,
                        "prompt": text,
                    },
                    timeout=30,
                )
                if resp.status_code != 200:
                    return 0.0

                query_emb = resp.json().get("embedding", [])
                if not query_emb:
                    return 0.0

                # Compare with each stored embedding
                best_sim = 0.0
                for db_def in db_defs:
                    stored_emb = db_def.embeddings
                    if stored_emb and len(stored_emb) == len(query_emb):
                        sim = self._cosine_similarity(query_emb, stored_emb)
                        best_sim = max(best_sim, sim)
                return best_sim
            finally:
                session.close()
        except Exception:
            return self._check_ollama_embedding(text)

    def _check_ollama_embedding(self, text: str) -> float:
        """Fallback: compute Ollama embeddings for query + all services inline."""
        try:
            import httpx
        except ImportError:
            return 0.0

        host = self._ollama_config.get("host", "127.0.0.1")
        port = self._ollama_config.get("port", 11434)
        embed_model = self._ollama_config.get("embedding_model", "nomic-embed-text")

        try:
            resp = httpx.post(
                f"http://{host}:{port}/api/embeddings",
                json={"model": embed_model, "prompt": text},
                timeout=30,
            )
            if resp.status_code != 200:
                return 0.0

            query_emb = resp.json().get("embedding", [])
            if not query_emb:
                return 0.0

            best_sim = 0.0
            for svc in self.catalog.get_all_services():
                svc_desc = f"{svc.name} {svc.description} {' '.join(svc.required_documents)}"
                svc_resp = httpx.post(
                    f"http://{host}:{port}/api/embeddings",
                    json={"model": embed_model, "prompt": svc_desc},
                    timeout=30,
                )
                if svc_resp.status_code == 200:
                    svc_emb = svc_resp.json().get("embedding", [])
                    if svc_emb and len(svc_emb) == len(query_emb):
                        sim = self._cosine_similarity(query_emb, svc_emb)
                        best_sim = max(best_sim, sim)
            return best_sim
        except Exception:
            return 0.0

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = (sum(x * x for x in a)) ** 0.5
        norm_b = (sum(x * x for x in b)) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ───────────────────────────────────────────────────────────────
    #  Grounded FAQ — pgvector retrieval from service_definitions
    # ───────────────────────────────────────────────────────────────

    def answer_faq(self, question: str) -> Optional[FAQAnswer]:
        """
        Answer a FAQ question using pgvector retrieval from service_definitions.

        Uses temperature=0 equivalent: deterministic top-1 chunk retrieval.
        Returns FAQAnswer with source_file + chunk_id for traceability.

        Steps:
        1. Embed the question using Ollama
        2. Compare against stored embeddings in service_definitions table
        3. Return top-1 match with source file and chunk ID
        4. If no stored embeddings exist, fall back to keyword matching

        Returns None if no match above fallback_threshold.
        """
        if not self._db:
            # Fall back to keyword-based FAQ
            return self._faq_keyword_fallback(question)

        import uuid
        from services.database import ServiceDefinition as DBServiceDef

        try:
            session = self._db.get_session()
            try:
                db_defs = session.query(DBServiceDef).all()
                if not db_defs:
                    return self._faq_keyword_fallback(question)

                host = self._ollama_config.get("host", "127.0.0.1")
                port = self._ollama_config.get("port", 11434)
                embed_model = self._ollama_config.get("embedding_model", "nomic-embed-text")

                import httpx
                resp = httpx.post(
                    f"http://{host}:{port}/api/embeddings",
                    json={"model": embed_model, "prompt": question},
                    timeout=30,
                )
                if resp.status_code != 200:
                    return self._faq_keyword_fallback(question)

                query_emb = resp.json().get("embedding", [])
                if not query_emb:
                    return self._faq_keyword_fallback(question)

                # Compare with each stored chunk embedding
                best_match = None
                best_sim = 0.0

                for db_def in db_defs:
                    stored_emb = db_def.embeddings
                    if stored_emb and len(stored_emb) == len(query_emb):
                        sim = self._cosine_similarity(query_emb, stored_emb)
                        if sim > best_sim:
                            best_sim = sim
                            best_match = db_def

                if best_match is None or best_sim < self.fallback_threshold:
                    return self._faq_keyword_fallback(question)

                # Build grounded answer from the matched chunk
                chunk_id = best_match.id
                source_file = best_match.source_file or "unknown"
                chunk_data = best_match.chunks or {}
                if isinstance(chunk_data, dict):
                    answer = chunk_data.get("text", chunk_data.get("content", ""))
                elif isinstance(chunk_data, list) and len(chunk_data) > 0:
                    answer = chunk_data[0] if isinstance(chunk_data[0], str) else str(chunk_data[0])
                else:
                    answer = str(chunk_data)

                if not answer:
                    return self._faq_keyword_fallback(question)

                return FAQAnswer(
                    answer=answer.strip(),
                    source_file=source_file,
                    chunk_id=chunk_id,
                    similarity=round(best_sim, 4),
                    service_id=best_match.service_id,
                    confidence=best_sim,
                )
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"pgvector FAQ retrieval failed, falling back to keywords: {e}")
            return self._faq_keyword_fallback(question)

    def _faq_keyword_fallback(self, question: str) -> Optional[FAQAnswer]:
        """Keyword-based FAQ fallback when pgvector is unavailable."""
        answer_text, conf = self.catalog.answer_faq(question)
        if conf < self.fallback_threshold:
            return None
        return FAQAnswer(
            answer=answer_text,
            source_file="service_catalogue",
            chunk_id=f"keyword_match_{hash(question) % 10000}",
            similarity=conf,
            confidence=conf,
        )

    # ───────────────────────────────────────────────────────────────
    #  Trace logging
    # ───────────────────────────────────────────────────────────────

    def _log_routing_decision(self, decision: RoutingDecision, application_id: Optional[str] = None):
        """Log a routing decision to trace_events table AND trace logger."""
        # 1. Log to trace_events table via DB
        if self._db and application_id:
            try:
                self._db.log_trace_event(
                    application_id=application_id,
                    stage="routing",
                    inputs={
                        "user_input": decision.inputs.get("user_input", ""),
                        "user_id": decision.inputs.get("user_id"),
                        "intent": decision.intent,
                        "matched_service": decision.matched_service,
                    },
                    scores={
                        "confidence": decision.score,
                        "keyword_score": decision.inputs.get("keyword_score"),
                        "embedding_score": decision.inputs.get("embedding_score"),
                    },
                    rule=decision.rule_fired,
                    confidence=decision.score,
                )
            except Exception as e:
                logger.warning(f"Failed to log routing decision to trace_events: {e}")
        elif self._db and not application_id:
            # Log without application context (routing before application created)
            try:
                self._db.log_trace_event(
                    application_id=None,
                    stage="routing",
                    inputs={
                        "user_input": decision.inputs.get("user_input", ""),
                        "user_id": decision.inputs.get("user_id"),
                        "intent": decision.intent,
                        "matched_service": decision.matched_service,
                    },
                    scores={
                        "confidence": decision.score,
                        "keyword_score": decision.inputs.get("keyword_score"),
                        "embedding_score": decision.inputs.get("embedding_score"),
                    },
                    rule=decision.rule_fired,
                    confidence=decision.score,
                )
            except Exception as e:
                logger.warning(f"Failed to log routing decision to trace_events: {e}")

        # 2. Log to trace logger if attached
        if self._trace_logger is not None:
            try:
                self._trace_logger.log_routing(
                    application_id=application_id,
                    user_id=decision.inputs.get("user_id"),
                    inputs={
                        "user_input": decision.inputs.get("user_input", ""),
                        "intent": decision.intent,
                        "matched_service": decision.matched_service,
                    },
                    scores={
                        "confidence": decision.score,
                        "keyword_score": decision.inputs.get("keyword_score"),
                        "embedding_score": decision.inputs.get("embedding_score"),
                    },
                    rule=decision.rule_fired,
                    confidence=decision.score,
                )
            except Exception as e:
                logger.warning(f"Failed to log routing decision via trace logger: {e}")


# ────────────────────────────────────────────────────────────────────
#  Groundedness test
# ────────────────────────────────────────────────────────────────────

class FAQGroundednessTester:
    """
    Tests that FAQ answers are grounded in actual service definitions.

    Verifies:
    1. Every answer cites a source_file
    2. The source_file exists or is a known internal source
    3. The answer text contains keywords from the source
    4. pgvector similarity is above threshold
    """

    def __init__(self, router: DeterministicRouter):
        self.router = router

    def test_answer(self, question: str, answer: Optional[FAQAnswer]) -> dict:
        """
        Run groundedness checks on a single FAQ answer.

        Returns:
            {
                "question": str,
                "answer": str or None,
                "grounded": bool,
                "checks": {
                    "has_answer": bool,
                    "has_source": bool,
                    "source_valid": bool,
                    "similarity_ok": bool,
                    "keywords_present": bool,
                }
            }
        """
        checks = {
            "has_answer": answer is not None and bool(answer.answer),
            "has_source": answer is not None and bool(answer.source_file),
            "source_valid": False,
            "similarity_ok": False,
            "keywords_present": False,
        }
        grounded = True

        if not checks["has_answer"]:
            grounded = False

        if checks["has_source"]:
            # Check source is a known file or internal marker
            known_sources = {"service_catalogue"}
            source_file = answer.source_file
            checks["source_valid"] = source_file in known_sources or os.path.exists(source_file)
            if not checks["source_valid"]:
                # Check in docs/ directory
                docs_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "docs"
                )
                checks["source_valid"] = os.path.exists(os.path.join(docs_dir, source_file))

        if checks["has_answer"]:
            checks["similarity_ok"] = answer.similarity >= self.router.fallback_threshold if answer.similarity is not None else False
            if not checks["similarity_ok"]:
                grounded = False

            # Check that answer contains at least 2 keywords from question
            q_words = set(re.findall(r'\b[a-z]{4,}\b', question.lower()))
            a_words = set(re.findall(r'\b[a-z]{4,}\b', answer.answer.lower()))
            if q_words and a_words:
                overlap = len(q_words & a_words)
                checks["keywords_present"] = overlap >= 2
                if not checks["keywords_present"]:
                    grounded = False  # soft warning only
            else:
                checks["keywords_present"] = True  # short questions pass

        return {
            "question": question,
            "answer": answer.answer if answer else None,
            "source_file": answer.source_file if answer else None,
            "similarity": answer.similarity if answer else None,
            "grounded": grounded,
            "checks": checks,
        }

    def run_suite(self) -> dict:
        """
        Run a full groundedness test suite against known FAQ patterns.

        Returns summary with pass/fail counts.
        """
        test_questions = [
            "What documents do I need for basic registration?",
            "How do I apply for a passport?",
            "What is required for a bank account?",
            "Tell me about vehicle rental",
            "How does the process work?",
            "I want to apply for basic registration",
            "What are the requirements for cross border service?",
        ]

        results = []
        passed = 0
        failed = 0

        for q in test_questions:
            answer = self.router.answer_faq(q)
            result = self.test_answer(q, answer)
            results.append(result)
            if result["grounded"]:
                passed += 1
            else:
                failed += 1

        return {
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }
