"""Validation Agent - Phase 2 & Phase 4 (Enhanced Multi-Rung Validation)"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum


class ValidationResult(str, Enum):
    """Enumeration of overall validation outcomes."""
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


class ValidationIssue:
    """Represents a specific discrepancy, failure, or warning found during validation."""

    def __init__(self, field: str, expected: str, actual: str,
                 severity: str = "high"):
        """Initialize a validation issue."""
        self.field = field
        self.expected = expected
        self.actual = actual
        self.severity = severity
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """Serialize the validation issue into a dictionary."""
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
        }


class ValidationReport:
    """Complete validation result report for an application."""

    def __init__(self, application_id: str):
        """Initialize a validation report."""
        self.application_id = application_id
        self.result: ValidationResult = ValidationResult.NEEDS_REVIEW
        self.issues: List[ValidationIssue] = []
        self.fields_checked: int = 0
        self.fields_passed: int = 0
        self.fields_failed: int = 0
        self.fields_reviewed: int = 0
        self.completed_at: Optional[datetime] = None
        self.review_notes: List[str] = []

    def add_issue(self, issue: ValidationIssue):
        """Add a validation issue and update failure counters."""
        self.issues.append(issue)
        if issue.severity in ("high", "critical"):
            self.fields_failed += 1
            if issue.severity == "critical":
                self.result = ValidationResult.FAIL
        else:
            # Medium severity → review, not failure
            self.fields_reviewed += 1
            self.fields_checked += 1

    def add_pass(self, field: str):
        """Record a field or rule that successfully passed validation."""
        self.fields_passed += 1
        self.fields_checked += 1

    def add_review(self, field: str, severity: str = "medium"):
        """Record a field or check sent for human review due to ambiguity or moderate confidence."""
        self.fields_reviewed += 1
        self.fields_checked += 1
        if severity == "critical":
            self.result = ValidationResult.NEEDS_REVIEW

    def finalize(self):
        """Finalize the validation report and resolve final application outcome."""
        self.completed_at = datetime.now(timezone.utc)

        # If no issues at all → PASS
        if self.fields_failed == 0 and self.fields_reviewed == 0:
            self.result = ValidationResult.PASS
        # Critical failures → FAIL (reject) — don't let review overwrite this
        elif any(i.severity == "critical" for i in self.issues):
            self.result = ValidationResult.FAIL
        # Medium severity issues → NEEDS_REVIEW
        elif self.fields_reviewed > 0:
            self.result = ValidationResult.NEEDS_REVIEW
        # High severity but not critical (e.g. missing doc) → FAIL
        elif self.fields_failed > 0:
            self.result = ValidationResult.FAIL
        else:
            self.result = ValidationResult.NEEDS_REVIEW

    def get_review_fields(self) -> List[str]:
        """Get the list of field names flagged for human review."""
        return [i.field for i in self.issues if i.severity == "medium"]

    def get_failure_fields(self) -> List[str]:
        """Get the list of field names that caused validation failures."""
        return [i.field for i in self.issues if i.severity == "high" or i.severity == "critical"]

    def to_dict(self) -> dict:
        """Serialize the validation report to a JSON-compatible dictionary."""
        return {
            "application_id": self.application_id,
            "result": self.result.value,
            "issues": [i.to_dict() for i in self.issues],
            "fields_checked": self.fields_checked,
            "fields_passed": self.fields_passed,
            "fields_failed": self.fields_failed,
            "fields_reviewed": self.fields_reviewed,
            "review_fields": self.get_review_fields(),
            "failure_fields": self.get_failure_fields(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class ValidationAgent:
    """Validation Agent - Phase 2 + Phase 4 (Enhanced Multi-Rung Validation)"""

    # Backwards-compatible defaults (overridden by config if provided)
    REVIEW_THRESHOLD_LOW = 1
    REVIEW_THRESHOLD_HIGH = 2
    REJECT_THRESHOLD = 3

    def __init__(self, config: Dict = None):
        """Initialize the ValidationAgent."""
        self.matched_pairs: List[Dict] = []
        self.mismatched_pairs: List[Dict] = []
        self.rules: Dict[str, List[callable]] = {}

        # Phase 4: Load thresholds from config
        self._config = config or {}
        self._load_thresholds_from_config()

    def _load_thresholds_from_config(self):
        """Load human_review_threshold, pass_threshold, reject_threshold from config.yaml."""
        doc_config = self._config.get("validation_rules", {}) or {}
        # Merge all doc-type thresholds into a single lookup
        self._thresholds: Dict[str, Dict] = {}
        for doc_type, cfg in doc_config.items():
            if not isinstance(cfg, dict):
                continue
            self._thresholds[doc_type] = {
                "human_review_threshold": cfg.get("human_review_threshold", 0.7),
                "pass_threshold": cfg.get("pass_threshold", cfg.get("extraction_threshold", 0.5)),
                "reject_threshold": cfg.get("reject_threshold", 3),
                "extraction_threshold": cfg.get("extraction_threshold", 0.5),
                "mandatory_fields": cfg.get("mandatory_fields", []),
                "optional_fields": cfg.get("optional_fields", []),
            }
        # Also load global extraction_ladder config
        self._ladder_config = self._config.get("extraction_ladder", {})

        # If any doc-specific reject threshold found, update class-level default
        for tc in self._thresholds.values():
            if tc["reject_threshold"] < self.REJECT_THRESHOLD:
                self.REJECT_THRESHOLD = tc["reject_threshold"]

    def register_matched_pairs(self, pairs: List[Dict]):
        """Register matched identity pairs for validation testing."""
        self.matched_pairs = pairs

    def register_mismatched_pairs(self, pairs: List[Dict]):
        """Register mismatched identity pairs for validation testing."""
        self.mismatched_pairs = pairs

    def validate_application(self, application_data: Dict) -> ValidationReport:
        """Validate a complete application across all submitted documents and rules."""
        report = ValidationReport(application_data["application_id"])

        documents = application_data.get("documents", [])
        service_id = application_data.get("service_id", "")

        # Rule 1: Check document count
        required_docs = application_data.get("required_documents", [])
        submitted_doc_types = [d.get("doc_type") for d in documents]

        for req_doc in required_docs:
            if req_doc not in submitted_doc_types:
                report.add_issue(ValidationIssue(
                    field="document_count",
                    expected=f"{req_doc} submitted",
                    actual=f"{req_doc} missing",
                    severity="critical"
                ))

        # If critical count failure, return immediately
        if report.result == ValidationResult.FAIL:
            report.finalize()
            return report

        # Rule 2: Check each document is readable and has extracted fields
        for doc in documents:
            doc_type = doc.get("doc_type", "unknown")
            extracted_fields = doc.get("extracted_fields", {})
            confidence = doc.get("extraction_confidence", 0.0)

            # Check if document has any extracted fields
            if not extracted_fields or len(extracted_fields) == 0:
                report.add_issue(ValidationIssue(
                    field=f"{doc_type}._all_fields",
                    expected="At least some fields extracted",
                    actual="No fields extracted",
                    severity="high"
                ))
                continue

            # Check confidence levels
            if confidence < 0.3:
                report.add_issue(ValidationIssue(
                    field=f"{doc_type}._confidence",
                    expected=f"Confidence >= 0.3",
                    actual=str(confidence),
                    severity="medium"
                ))
            elif confidence < 0.5:
                report.add_review(f"{doc_type}._confidence_low")

            # Rule 3: Check mandatory fields exist
            mandatory_fields = self._get_mandatory_fields(service_id, doc_type)
            for field in mandatory_fields:
                val = extracted_fields.get(field)
                # Allow standard aliases
                if not val and field == "document_number":
                    val = extracted_fields.get("license_no") or extracted_fields.get("license_number") or extracted_fields.get("national_id_number") or extracted_fields.get("passport_number")
                if not val and field == "license_no":
                    val = extracted_fields.get("document_number") or extracted_fields.get("license_number")

                if val:
                    report.add_pass(f"{doc_type}.{field}")
                else:
                    report.add_issue(ValidationIssue(
                        field=f"{doc_type}.{field}",
                        expected=f"Value present",
                        actual="Missing",
                        severity="high"
                    ))

            # Rule 4: Check field-specific rules (expiry, format, etc.)
            self._check_field_rules(doc, doc_type, report)

        # Rule 5: Cross-check shared fields across documents
        self._check_cross_document_fields(documents, report)

        # Rule 6: Check against golden dataset if provided
        golden = application_data.get("golden_dataset")
        if golden:
            self._check_against_golden(documents, golden, report)

        report.finalize()
        return report

    def validate_matched_pairs(self) -> List[ValidationReport]:
        """Validate the registered matched and mismatched test pairs."""
        results = []

        # Validate matched pairs (should all pass)
        for pair in self.matched_pairs:
            app_data = {
                "application_id": f"pair_{pair.get('id', 'unknown')}",
                "service_id": "premium_crossborder",
                "required_documents": ["national_id", "passport"],
                "documents": [
                    {
                        "doc_type": "national_id",
                        "extracted_fields": pair.get("id_fields", {}),
                        "extraction_confidence": pair.get("id_confidence", 0.9),
                    },
                    {
                        "doc_type": "passport",
                        "extracted_fields": pair.get("passport_fields", {}),
                        "extraction_confidence": pair.get("passport_confidence", 0.9),
                    },
                ],
            }
            report = self.validate_application(app_data)
            report.review_notes.append(f"Matched pair test: expected PASS, is match=True")
            results.append(report)

        # Validate mismatched pairs (should all fail or need review)
        for pair in self.mismatched_pairs:
            app_data = {
                "application_id": f"mismatch_{pair.get('id', 'unknown')}",
                "service_id": "premium_crossborder",
                "required_documents": ["national_id", "passport"],
                "documents": [
                    {
                        "doc_type": "national_id",
                        "extracted_fields": pair.get("id_fields", {}),
                        "extraction_confidence": pair.get("id_confidence", 0.9),
                    },
                    {
                        "doc_type": "passport",
                        "extracted_fields": pair.get("passport_fields", {}),
                        "extraction_confidence": pair.get("passport_confidence", 0.9),
                    },
                ],
            }
            report = self.validate_application(app_data)
            report.review_notes.append(f"Mismatched pair test: expected FAIL, is match=False")
            results.append(report)

        return results

    def _get_mandatory_fields(self, service_id: str, doc_type: str) -> List[str]:
        """Get mandatory fields for a specific document type."""
        # Core mandatory fields for ALL document types
        core_mandatory = ["name", "date_of_birth", "document_number", "expiry_date"]

        # Document-type specific mandatory fields
        if doc_type == "national_id":
            return ["name", "date_of_birth", "document_number", "expiry_date", "issuing_country"]
        elif doc_type == "passport":
            return ["name", "date_of_birth", "document_number", "expiry_date",
                    "issuing_country", "passport_type"]
        elif doc_type == "driving_license":
            return ["name", "date_of_birth", "document_number", "expiry_date", "issue_date"]
        else:
            return core_mandatory

    def _check_field_rules(self, doc: Dict, doc_type: str, report: ValidationReport):
        """Check document-specific field rules (expiry dates, minimum name lengths, license gear types)."""
        fields = doc.get("extracted_fields", {})

        # Check expiry date (document must not be expired)
        if "expiry_date" in fields and fields["expiry_date"]:
            expiry = fields["expiry_date"]
            result = self._is_valid_expiry(expiry)
            if result is False:
                report.add_issue(ValidationIssue(
                    field=f"{doc_type}.expiry_date",
                    expected="Future date",
                    actual=expiry,
                    severity="critical"
                ))
            elif result is None:
                report.add_review(
                    f"{doc_type}.expiry_date",
                    severity="medium"
                )

        # Check name format (must not be empty or invalid)
        if "name" in fields and fields["name"]:
            name = fields["name"]
            if len(name.strip()) < 2:
                report.add_issue(ValidationIssue(
                    field=f"{doc_type}.name",
                    expected="Valid name (2+ chars)",
                    actual=name,
                    severity="high"
                ))

        # Driving license specific validations: gear and glasses
        if doc_type == "driving_license":
            if "gear_type" in fields and fields["gear_type"]:
                gear = str(fields["gear_type"]).strip().lower()
                if "auto" in gear or "manual" in gear:
                    report.add_pass(f"{doc_type}.gear_type")
                else:
                    report.add_issue(ValidationIssue(
                        field=f"{doc_type}.gear_type",
                        expected="Automatic Gear or Manual Gear",
                        actual=fields["gear_type"],
                        severity="medium"
                    ))

            if "glasses_requirement" in fields and fields["glasses_requirement"]:
                report.add_pass(f"{doc_type}.glasses_requirement")

    def _is_valid_expiry(self, expiry_date: str) -> Optional[bool]:
        """Check if an expiry date is in the future."""
        from datetime import datetime, date

        if not expiry_date or not expiry_date.strip():
            return None

        expiry_date = expiry_date.strip()

        # Try multiple date formats
        for fmt in [
            "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y",
            "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%d-%b-%Y",
            "%d-%B-%Y", "%Y.%m.%d", "%d %b, %Y", "%b %d, %Y"
        ]:
            try:
                expiry = datetime.strptime(expiry_date, fmt)
                return expiry.date() > date.today()
            except ValueError:
                continue

        # Handle month-year formats (valid through last day of that month)
        for fmt in ["%m/%Y", "%B %Y", "%b %Y", "%m-%Y", "%Y-%m"]:
            try:
                dt = datetime.strptime(expiry_date, fmt)
                # Last day of the month
                import calendar
                last_day = date(dt.year, dt.month, calendar.monthrange(dt.year, dt.month)[1])
                return last_day >= date.today()
            except ValueError:
                continue

        # If no format matched → unparseable → return None (fail-closed)
        return None

    def _check_cross_document_fields(self, documents: List[Dict], report: ValidationReport):
        """Cross-check shared identity fields across documents submitted together."""
        if len(documents) < 2:
            return

        # Find shared fields (name and DOB must match; document numbers differ by design)
        shared_fields = ["name", "date_of_birth"]
        seen_pairs = set()

        # Compare every pair of documents
        for i in range(len(documents)):
            for j in range(i + 1, len(documents)):
                pair_key = (i, j)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                first_doc = documents[i].get("extracted_fields", {})
                second_doc = documents[j].get("extracted_fields", {})

                for field in shared_fields:
                    val1 = first_doc.get(field, None)
                    val2 = second_doc.get(field, None)

                    if val1 is None or val1 == "":
                        # A7: Field missing from first document → report as unverifiable
                        report.add_review(
                            f"cross_check.{field} ({documents[i].get('doc_type', 'unknown')})",
                            severity="medium"
                        )
                        continue
                    if val2 is None or val2 == "":
                        # A7: Field missing from second document → report as unverifiable
                        report.add_review(
                            f"cross_check.{field} ({documents[j].get('doc_type', 'unknown')})",
                            severity="medium"
                        )
                        continue

                    if field == "name":
                        # A6: Set-based & phonetic/token comparison (case/accents/punctuation/order insensitive)
                        is_match, is_partial = self._names_match_detailed(str(val1), str(val2))
                        if is_match:
                            report.add_pass(f"cross_check.{field} ({documents[i].get('doc_type', '')} vs {documents[j].get('doc_type', '')})")
                        elif is_partial:
                            # Substantial match / subset / patronymic variation -> Route to human review instead of immediate critical fail
                            report.add_review(
                                f"cross_check.{field} ({documents[i].get('doc_type', '')} vs {documents[j].get('doc_type', '')}): {self._mask_name(str(val1))} vs {self._mask_name(str(val2))}",
                                severity="medium"
                            )
                        else:
                            report.add_issue(ValidationIssue(
                                field=f"cross_check.{field}",
                                expected=self._mask_name(str(val1)),
                                actual=f"{self._mask_name(str(val1))} vs {self._mask_name(str(val2))}",
                                severity="critical"
                            ))
                    elif field == "date_of_birth":
                        # Normalize dates to ISO before comparing
                        date1 = self._normalize_date(str(val1))
                        date2 = self._normalize_date(str(val2))
                        if date1 and date2 and date1 == date2:
                            report.add_pass(f"cross_check.{field} ({documents[i].get('doc_type', '')} vs {documents[j].get('doc_type', '')})")
                        else:
                            report.add_issue(ValidationIssue(
                                field=f"cross_check.{field}",
                                expected=self._mask_date(str(val1)),
                                actual=f"{self._mask_date(str(val1))} vs {self._mask_date(str(val2))}",
                                severity="critical"
                            ))

    def _check_against_golden(self, documents: List[Dict],
                               golden: Dict, report: ValidationReport):
        """Check extracted fields against the reference golden dataset."""
        for doc in documents:
            doc_type = doc.get("doc_type", "")
            extracted = doc.get("extracted_fields", {})

            if doc_type in golden:
                golden_fields = golden[doc_type]
                for field, golden_value in golden_fields.items():
                    if field in extracted:
                        extracted_value = str(extracted[field]).strip().lower()
                        golden_value = str(golden_value).strip().lower()

                        if extracted_value == golden_value:
                            report.add_pass(f"golden.{doc_type}.{field}")
                        else:
                            # Medium severity: field extracted but wrong
                            report.add_issue(ValidationIssue(
                                field=f"golden.{doc_type}.{field}",
                                expected=golden_value,
                                actual=extracted_value,
                                severity="medium"
                            ))

    def retry_extraction_with_alternative(self, image_data: bytes, doc_type: str,
                                          config: Dict = None) -> Dict:
        """Phase 4: Multi-rung fallback extraction using ExtractionLadder."""
        from services.extraction_ladder import ExtractionLadder
        if config is None:
            config = self._config or {}
        try:
            ladder = ExtractionLadder(config=config, image_bytes=image_data)
            ladder_result = ladder.run(document_type=doc_type)
            return {
                "status": "success",
                "approach": "extraction_ladder",
                "extracted_fields": ladder_result.consensus,
                "extraction_confidence": ladder_result.consensus_confidence,
                "ladder_trace": [r.to_dict() for r in ladder_result.rungs],
                "source_rung_by_field": ladder_result.source_rung_by_field,
                "rejected_fields": ladder_result.rejected_fields,
                "reviewed_fields": ladder_result.reviewed_fields,
                "passed_fields": ladder_result.passed_fields,
            }
        except Exception as e:
            logger = __import__("logging").getLogger(__name__)
            logger.warning(f"Extraction ladder failed for {doc_type}: {e}")
            return {
                "status": "retry",
                "approach": "alternative_model",
                "message": f"Extraction ladder failed: {e}",
                "extracted_fields": {},
                "extraction_confidence": 0.0,
                "ladder_trace": [],
            }

    # -------------------------------------------------------------------------- #
    #  A6/A7: Name matching, date normalization, masking                         #
    # -------------------------------------------------------------------------- #

    @staticmethod
    def _names_match_detailed(name1: str, name2: str) -> Tuple[bool, bool]:
        """Set-based name comparison with detailed partial/subset variation analysis."""
        import unicodedata
        import re

        def normalize_tokens(name: str) -> List[str]:
            name = unicodedata.normalize('NFKD', name)
            name = ''.join(c for c in name if not unicodedata.combining(c))
            name = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in name)
            tokens = [t.lower() for t in name.split() if t.strip()]
            # Strip common honorifics / patronymic prefixes in GCC/international identity docs
            cleaned = []
            for t in tokens:
                if t in ("mr", "mrs", "ms", "dr", "al", "bin", "bint", "ibn"):
                    continue
                cleaned.append(t)
            return cleaned or tokens

        def normalize_concat(name: str) -> str:
            name = unicodedata.normalize('NFKD', name)
            name = ''.join(c for c in name if not unicodedata.combining(c))
            name = ''.join(c for c in name if c.isalnum())
            return name.lower()

        tok1 = normalize_tokens(name1)
        tok2 = normalize_tokens(name2)
        set1, set2 = set(tok1), set(tok2)

        if set1 and set1 == set2:
            return True, False

        # Concatenated equality (e.g. O'Connor vs OConnor)
        c1, c2 = normalize_concat(name1), normalize_concat(name2)
        if c1 and c1 == c2:
            return True, False

        # Name subset check: e.g. Passport contains [Given, Middle, Surname] while ID contains [Given, Surname]
        # or National ID repeats/includes patronymic names: if confidence and core name tokens match (given name + surname), treat as match
        if set1 and set2 and (set1.issubset(set2) or set2.issubset(set1)):
            # If both contain at least 2 common tokens (e.g. given name + surname), it is an identity match
            if len(set1.intersection(set2)) >= 2:
                return True, False
            return False, True

        # High token overlap check (>= 60% common tokens)
        intersection = set1.intersection(set2)
        if len(intersection) >= 2 and (len(intersection) / max(len(set1), len(set2)) >= 0.60):
            return True, False

        return False, False

    @staticmethod
    def _names_match(name1: str, name2: str) -> bool:
        """Set-based name comparison — case-, accent-, punctuation-, and order-insensitive."""
        match, _ = ValidationAgent._names_match_detailed(name1, name2)
        return match

    @staticmethod
    def _normalize_date(date_str: str) -> Optional[str]:
        """Normalize an arbitrary date string to ISO YYYY-MM-DD format for comparison."""
        from datetime import datetime

        if not date_str or not date_str.strip():
            return None

        date_str = date_str.strip()

        for fmt in [
            "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y",
            "%d %b %Y", "%d %B %Y", "%Y/%m/%d", "%d-%b-%Y",
            "%d-%B-%Y", "%Y.%m.%d", "%d %b, %Y", "%b %d, %Y"
        ]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None  # Unparseable — leave to reviewer

    @staticmethod
    def _mask_name(name: str) -> str:
        """Mask a person's name for privacy compliance in audit logs and API error strings."""
        words = name.split()
        masked = []
        for word in words:
            if len(word) <= 1:
                masked.append(word)
            else:
                masked.append(word[0] + '*' * (len(word) - 2) + word[-1])
        return ' '.join(masked)

    @staticmethod
    def _mask_date(date_str: str) -> str:
        """Mask a date string for privacy compliance in logs and reports."""
        normalized = ValidationAgent._normalize_date(date_str)
        if normalized:
            return f"****-{normalized[5:]}"
        return ValidationAgent._mask_name(date_str)

    # -------------------------------------------------------------------------- #
    #  Phase 4: Cross-validation (WP7) — internal logic checks                    #
    # -------------------------------------------------------------------------- #

    def validate_internal_logic(self, extracted_fields: Dict,
                                doc_type: str = "") -> List[dict]:
        """Run internal-logic cross-validation on extracted fields within a single document."""
        violations: List[dict] = []
        fields = {k.lower(): v for k, v in extracted_fields.items() if v}

        # Expiry > DOB
        dob = fields.get("date_of_birth")
        expiry = fields.get("expiry_date")
        if dob and expiry:
            dob_n = self._normalize_date(str(dob))
            exp_n = self._normalize_date(str(expiry))
            if dob_n and exp_n:
                if exp_n < dob_n:
                    violations.append({
                        "field": "expiry_date",
                        "violation": f"expiry ({expiry}) is before date_of_birth ({dob})",
                        "severity": "critical",
                    })

        # Issue date < expiry date
        issue = fields.get("issue_date")
        if issue and expiry:
            issue_n = self._normalize_date(str(issue))
            exp_n = self._normalize_date(str(expiry))
            if issue_n and exp_n:
                if issue_n >= exp_n:
                    violations.append({
                        "field": "issue_date",
                        "violation": f"issue_date ({issue}) is on or after expiry_date ({expiry})",
                        "severity": "high",
                    })

        # Name must be at least 2 chars and not all digits
        name = fields.get("name") or fields.get("given_name") or fields.get("surname")
        if name:
            name = str(name).strip()
            if not name.isdigit() and len(name) >= 2:
                pass  # OK
            elif name.isdigit():
                violations.append({
                    "field": "name",
                    "violation": f"name appears to be all digits: {name}",
                    "severity": "high",
                })

        # Sex field must be valid
        sex = fields.get("sex") or fields.get("gender")
        if sex:
            sex_upper = str(sex).strip().upper()
            if sex_upper not in ("M", "F", "X", "OTHER", ""):
                violations.append({
                    "field": "sex" if fields.get("sex") else "gender",
                    "violation": f"invalid sex/gender value: {sex}",
                    "severity": "medium",
                })

        return violations

    def classify_result_by_thresholds(self, confidence: float,
                                      doc_type: str = "national_id") -> str:
        """Classify a confidence score using config-driven thresholds for a document type."""
        thresholds = self._thresholds.get(doc_type, {
            "pass_threshold": 0.8,
            "human_review_threshold": 0.7,
        })
        pass_t = thresholds.get("pass_threshold", 0.8)
        review_t = thresholds.get("human_review_threshold", 0.7)

        if confidence >= pass_t:
            return "pass"
        elif confidence >= review_t:
            return "review"
        else:
            return "reject"

    def get_thresholds_for_doc_type(self, doc_type: str) -> Dict:
        """Return the loaded configuration thresholds for a specific document type."""
        return dict(self._thresholds.get(doc_type, {
            "pass_threshold": 0.8,
            "human_review_threshold": 0.7,
            "reject_threshold": 3,
            "extraction_threshold": 0.5,
            "mandatory_fields": [],
            "optional_fields": [],
        }))
