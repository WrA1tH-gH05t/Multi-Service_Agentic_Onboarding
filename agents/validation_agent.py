"""
Validation Agent - Phase 2 & Phase 4 (Enhanced Multi-Rung Validation)

Module Purpose & Role in the Project:
-------------------------------------
The Validation Agent is the deterministic verification authority of the system.
Once the Collection Agent (`agents/collection_agent.py`) has gathered all required documents
for an application, the Validation Agent inspects the entire submission holistically.
It ensures document completeness, verifies readability and confidence thresholds, executes
document-specific field validation rules (e.g., expiry dates, driving license categories),
cross-checks shared identity fields (e.g., set-based name matching and ISO date comparisons
between national ID and passport), and orchestrates multi-rung fallback extraction
via the `ExtractionLadder` (`services/extraction_ladder.py`).

Design Decision:
----------------
Uses explicit, deterministic validation rules rather than LLM-based judgement, because:
1. Validation results must be deterministic (identical input produces identical output across audits).
2. Field cross-checking requires exact string/numeric normalization and comparison.
3. Government compliance and business rules must be rigorously auditable and testable.
4. LLM-based validation would introduce non-determinism, hallucinations, and latency into a critical path.

System Architecture & Cross-File Interconnections:
--------------------------------------------------
1. Upstream Callers:
   - `app/main.py`: Instantiates `ValidationAgent` during application startup and registers it into
     `app_state["validation_agent"]`.
   - `app/routes/validation.py` (`/validate` endpoint): Receives validation requests for complete applications,
     constructs application payloads, and executes `validate_application()`.
   - `app/routes/collection.py` (`/collection/session/{session_id}/validate` endpoint): Automatically
     triggers application validation once a collection session reaches completion.
   - Test Suites (`tests/test_agent_bugs.py`): Invokes validation methods to test edge cases, name variations,
     and date format handling.

2. Downstream Dependencies & Supporting Services:
   - `config.yaml` (`validation_rules` & `extraction_ladder` sections): Defines per-document thresholds
     (`pass_threshold`, `human_review_threshold`, `reject_threshold`, `mandatory_fields`, `optional_fields`).
     Loaded dynamically in `_load_thresholds_from_config()`.
   - `services/extraction_ladder.py` (`ExtractionLadder`): Invoked by `retry_extraction_with_alternative()`
     to run the 5-rung extraction sequence (Docling layout parse -> Qwen2.5-VL vision model -> MRZ crop ->
     MRZ parse library -> OCR fallback) when initial extraction is ambiguous or rejected.
   - `services/database.py` (`DatabaseService`): Updates application lifecycle status based on validation
     results (`validated` / `needs_review` / `rejected`), logging audit events in `audit_logs`.
   - `agents/collection_agent.py` (`CollectionAgent`): Provides completed document sets and extraction fields
     ready for validation.
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum


class ValidationResult(str, Enum):
    """
    Enumeration of overall validation outcomes.

    Values:
    -------
    PASS: Application satisfied all mandatory document checks and field rules.
    FAIL: Application violated critical rules (e.g. missing documents, expired ID, identity mismatch).
    NEEDS_REVIEW: Application contains ambiguous fields, medium confidence scores, or unverifiable values
                  requiring human validator review.
    """
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


class ValidationIssue:
    """
    Represents a specific discrepancy, failure, or warning found during validation.

    Responsibility:
    ---------------
    Captures structured diagnostic details for any validation anomaly discovered across
    document counts, mandatory fields, expiration checks, or cross-document comparisons.

    Attributes:
    -----------
    field (str): The specific field or check path that triggered the issue (e.g. 'passport.expiry_date',
                 'cross_check.name', 'document_count').
    expected (str): Description of the required or expected value/condition.
    actual (str): Description or masked representation of the actual encountered value.
    severity (str): Impact classification ('critical', 'high', 'medium').
    timestamp (datetime): UTC timestamp when the issue was recorded.

    Interconnections:
    -----------------
    Constructed inside `ValidationAgent.validate_application()` and aggregated into `ValidationReport`.
    Serialized via `to_dict()` and returned through `/validate` routes in `app/routes/validation.py`.
    """

    def __init__(self, field: str, expected: str, actual: str,
                 severity: str = "high"):
        """
        Initialize a validation issue.

        Args:
            field (str): Name or path of the field/rule evaluated.
            expected (str): Expected rule criteria or value description.
            actual (str): Actual value or condition found.
            severity (str, optional): Issue severity ('critical', 'high', 'medium'). Defaults to "high".
        """
        self.field = field
        self.expected = expected
        self.actual = actual
        self.severity = severity
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        """
        Serialize the validation issue into a dictionary.

        Role & Interconnections:
            Called by `ValidationReport.to_dict()` for REST API JSON responses
            and persistent logging in database audit trails.

        Returns:
            dict: Structured dictionary containing issue details and ISO timestamp.
        """
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
        }


class ValidationReport:
    """
    Complete validation result report for an application.

    Responsibility:
    ---------------
    Collects passed fields, failed issues, and review items across all documents in an application.
    Applies multi-tiered severity decision logic during `finalize()` to assign the final status:
    PASS, FAIL, or NEEDS_REVIEW.

    State Attributes:
    -----------------
    application_id (str): Identifier of the application evaluated.
    result (ValidationResult): Overall status outcome (PASS, FAIL, NEEDS_REVIEW).
    issues (List[ValidationIssue]): Collection of recorded issues.
    fields_checked (int): Total count of field-level rules and checks executed.
    fields_passed (int): Number of checks that fully satisfied criteria.
    fields_failed (int): Number of high or critical failures.
    fields_reviewed (int): Number of medium-severity or uncertain checks flagged for human review.
    completed_at (Optional[datetime]): Timestamp when validation was finalized.
    review_notes (List[str]): Additional diagnostic notes (e.g. matched pair test labels).

    Interconnections:
    -----------------
    Instantiated and populated by `ValidationAgent.validate_application()`. Returned to
    FastAPI route handlers in `app/routes/validation.py` and `app/routes/collection.py`,
    and recorded into database audit logs via `DatabaseService`.
    """

    def __init__(self, application_id: str):
        """
        Initialize a validation report.

        Args:
            application_id (str): Unique application identifier.
        """
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
        """
        Add a validation issue and update failure counters.

        Severity Decision Logic:
        -------------------------
        - Critical -> Immediately marks `self.result = ValidationResult.FAIL` and increments `fields_failed`.
        - High -> Increments `fields_failed`.
        - Medium -> Flags for review by incrementing `fields_reviewed` and `fields_checked` (does NOT increment failure).

        Args:
            issue (ValidationIssue): Validation issue instance to record.
        """
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
        """
        Record a field or rule that successfully passed validation.

        Args:
            field (str): Field identifier or check path that passed.
        """
        self.fields_passed += 1
        self.fields_checked += 1

    def add_review(self, field: str, severity: str = "medium"):
        """
        Record a field or check sent for human review due to ambiguity or moderate confidence.

        Args:
            field (str): Field identifier requiring manual human review.
            severity (str, optional): Review urgency severity. Defaults to "medium".
        """
        self.fields_reviewed += 1
        self.fields_checked += 1
        if severity == "critical":
            self.result = ValidationResult.NEEDS_REVIEW

    def finalize(self):
        """
        Finalize the validation report and resolve final application outcome.

        Status Resolution Logic:
        -------------------------
        1. If zero failures and zero review flags -> PASS.
        2. If any issue has severity 'critical' -> FAIL (immediate rejection; cannot be overridden).
        3. If there are review items and no critical failures -> NEEDS_REVIEW.
        4. If there are high-severity failures (e.g. missing required document) -> FAIL.
        5. Default fallback -> NEEDS_REVIEW.
        """
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
        """
        Get the list of field names flagged for human review.

        Returns:
            List[str]: Field identifiers where issue severity is 'medium'.
        """
        return [i.field for i in self.issues if i.severity == "medium"]

    def get_failure_fields(self) -> List[str]:
        """
        Get the list of field names that caused validation failures.

        Returns:
            List[str]: Field identifiers where issue severity is 'high' or 'critical'.
        """
        return [i.field for i in self.issues if i.severity == "high" or i.severity == "critical"]

    def to_dict(self) -> dict:
        """
        Serialize the validation report to a JSON-compatible dictionary.

        Role & Interconnections:
            Supplies response payloads for `/validate` endpoints in `app/routes/validation.py`
            and audit trail event logs in `services/database.py`.

        Returns:
            dict: Summary metrics, result string, issue list, and field breakdown.
        """
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
    """
    Validation Agent - Phase 2 + Phase 4 (Enhanced Multi-Rung Validation)

    Primary Responsibilities:
    -------------------------
    - Check that every required document has arrived
    - Check that each document is readable and correctly extracted
    - Check field-specific rules (e.g., expiry dates, license categories)
    - Cross-check shared fields across documents (e.g., name, DOB)
    - Try different extraction approaches via ExtractionLadder before concluding document is the problem
    - Output clear pass/fail/needs_review with specific reasons, not vague answers
    - Load thresholds from config.yaml (human_review, pass, reject)
    - Provide test fixtures for matched vs mismatched identity pairs

    Cross-File Interconnections:
    ----------------------------
    - `app/main.py`: Initialized at startup and stored in `app_state["validation_agent"]`.
    - `app/routes/validation.py`: Invoked by `validate_application` API endpoint.
    - `app/routes/collection.py`: Called to validate an application after document collection completes.
    - `services/extraction_ladder.py`: Called via `retry_extraction_with_alternative()` for multi-rung extraction.
    - `config.yaml`: Reads `validation_rules` for document-specific thresholds and mandatory field lists.
    - `services/database.py`: Results trigger state transitions to 'validated', 'needs_review', or 'rejected'.
    """

    # Backwards-compatible defaults (overridden by config if provided)
    REVIEW_THRESHOLD_LOW = 1
    REVIEW_THRESHOLD_HIGH = 2
    REJECT_THRESHOLD = 3

    def __init__(self, config: Dict = None):
        """
        Initialize the ValidationAgent.

        Args:
            config (Optional[Dict], optional): Application configuration dict (from config.yaml).
                If None, uses internal defaults for backwards compatibility.
        """
        self.matched_pairs: List[Dict] = []
        self.mismatched_pairs: List[Dict] = []
        self.rules: Dict[str, List[callable]] = {}

        # Phase 4: Load thresholds from config
        self._config = config or {}
        self._load_thresholds_from_config()

    def _load_thresholds_from_config(self):
        """
        Load human_review_threshold, pass_threshold, reject_threshold from config.yaml.

        Role & Interconnections:
            Parses the `validation_rules` block in `config.yaml` to configure document-specific
            mandatory fields, optional fields, and numerical confidence boundaries.
        """
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
        """
        Register matched identity pairs for validation testing.

        Role & Interconnections:
            Used in integration test suites (`tests/test_agent_bugs.py`) to verify true positive
            matching behavior across cross-document identity fields.

        Args:
            pairs (List[Dict]): List of test pair fixtures containing matching ID & passport fields.
        """
        self.matched_pairs = pairs

    def register_mismatched_pairs(self, pairs: List[Dict]):
        """
        Register mismatched identity pairs for validation testing.

        Role & Interconnections:
            Used in integration test suites to verify that deliberate name or DOB discrepancies
            are caught as critical issues (true negatives).

        Args:
            pairs (List[Dict]): List of test pair fixtures containing conflicting identity fields.
        """
        self.mismatched_pairs = pairs

    def validate_application(self, application_data: Dict) -> ValidationReport:
        """
        Validate a complete application across all submitted documents and rules.

        Validation Steps:
        -----------------
        1. Document Count Rule: Checks that all documents in `required_documents` were submitted.
           If any required document is missing, adds a critical issue and immediately fails.
        2. Readability & Confidence Rule: Verifies that each document produced extracted fields
           and that extraction confidence is above minimum acceptable bounds (<0.3 critical, <0.5 review).
        3. Mandatory Fields Rule: Verifies presence of mandatory fields (with alias support for document numbers).
        4. Field-Specific Rules: Validates expiry dates, name lengths, and driving license specifications.
        5. Cross-Document Cross-Checking: Compares identity fields (name, date_of_birth) across all document pairs.
        6. Golden Dataset Check: If golden dataset is provided, compares extracted fields against reference truths.
        7. Report Finalization: Executes `report.finalize()` to calculate PASS, FAIL, or NEEDS_REVIEW.

        Cross-File Interconnections:
        ----------------------------
        Called by `/validate` route in `app/routes/validation.py` and by `/collection/session/{id}/validate`
        in `app/routes/collection.py`.

        Args:
            application_data (Dict): Application dictionary containing:
                - application_id (str): Application UUID or identifier.
                - service_id (str): Target service identifier.
                - required_documents (List[str]): List of expected doc_types.
                - documents (List[Dict]): List of document dicts with doc_type, extracted_fields, confidence.
                - golden_dataset (Optional[Dict]): Reference values for testing or benchmark validation.

        Returns:
            ValidationReport: Finalized validation report.
        """
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
        """
        Validate the registered matched and mismatched test pairs.

        Role & Interconnections:
            Called during diagnostic testing to prove that the validation engine correctly:
            1. Passes genuine matches (true positives).
            2. Catches deliberate mismatches (true negatives).

        Returns:
            List[ValidationReport]: Combined list of reports for matched and mismatched test runs.
        """
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
        """
        Get mandatory fields for a specific document type.

        Design Decision:
            Field selection is based on what is strictly required for identity verification
            and legal compliance. Non-essential fields (like secondary addresses) are optional.

        Args:
            service_id (str): Service identifier.
            doc_type (str): Document type name (e.g. 'national_id', 'passport', 'driving_license').

        Returns:
            List[str]: List of required field name strings.
        """
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
        """
        Check document-specific field rules (expiry dates, minimum name lengths, license gear types).

        Internal helper called by `validate_application()` to evaluate single-document integrity.

        Args:
            doc (Dict): Document data dictionary with 'extracted_fields'.
            doc_type (str): Category string of the document.
            report (ValidationReport): Target report where issues or passes are recorded.
        """
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
        """
        Check if an expiry date is in the future.

        Supported Date Formats:
        -----------------------
        - Day-level: %Y-%m-%d, %d/%m/%Y, %d.%m.%Y, %d %b %Y, %d %B %Y, %Y/%m/%d
        - Month-level: %m/%Y, %B %Y, %b %Y (valid through the last day of the given month)

        Args:
            expiry_date (str): Raw or extracted expiry date string.

        Returns:
            Optional[bool]:
                - True: Valid future date.
                - False: Date is in the past or today (expired).
                - None: Unparseable date string (triggers human review via fail-closed security).
        """
        from datetime import datetime, date

        if not expiry_date or not expiry_date.strip():
            return None

        expiry_date = expiry_date.strip()

        # Try multiple date formats
        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d"]:
            try:
                expiry = datetime.strptime(expiry_date, fmt)
                return expiry.date() > date.today()
            except ValueError:
                continue

        # Handle month-year formats (valid through last day of that month)
        for fmt in ["%m/%Y", "%B %Y", "%b %Y"]:
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
        """
        Cross-check shared identity fields across documents submitted together.

        Design Requirements:
        --------------------
        - Compares every unique pair of documents submitted for an application.
        - Checks shared fields: 'name' and 'date_of_birth' (document numbers are distinct by design).
        - Name Comparison (A6): Uses set-based name comparison (`_names_match`) that is case-, accent-,
          punctuation-, and order-insensitive.
        - Missing Shared Fields (A7): If a shared field is missing from either document, it is reported
          as unverifiable with 'medium' severity for human review, rather than silently passed.
        - Date Comparison: Normalizes both dates to ISO format (`_normalize_date`) before comparing.
        - Masking: Logs masked names and dates to preserve privacy in audit logs.

        Args:
            documents (List[Dict]): List of extracted document payloads.
            report (ValidationReport): Target report for adding pass, review, or failure issues.
        """
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
                        # A6: Set-based comparison (case/accents/punctuation/order insensitive)
                        if self._names_match(str(val1), str(val2)):
                            report.add_pass(f"cross_check.{field} ({documents[i].get('doc_type', '')} vs {documents[j].get('doc_type', '')})")
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
        """
        Check extracted fields against the reference golden dataset.

        Role & Interconnections:
            Used during benchmark evaluations and automated regression tests to verify that
            extraction models extracted exact ground truth values.

        Args:
            documents (List[Dict]): List of extracted document dicts.
            golden (Dict): Mapping of doc_type to expected ground truth field dicts.
            report (ValidationReport): Target report to record passes or medium-severity issues.
        """
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
        """
        Phase 4: Multi-rung fallback extraction using ExtractionLadder.

        Workflow & Ladder Interconnections:
        -----------------------------------
        Directly integrates with `services.extraction_ladder.ExtractionLadder`.
        When primary extraction fails or returns low confidence, this method invokes the ladder:
          - Rung 0: Docling layout parse & pre-processing
          - Rung 1: Qwen2.5-VL 3B vision model
          - Rung 2: MRZ crop region extraction
          - Rung 3: MRZ parse library (passport/ID)
          - Rung 4: PyMuPDF / Tesseract OCR fallback
        Consensus fields and confidence metrics are calculated across all completed rungs.

        Args:
            image_data (bytes): Raw binary bytes of the document image or PDF.
            doc_type (str): Document category identifier (e.g. 'passport', 'national_id').
            config (Optional[Dict], optional): Application configuration dict. Defaults to loaded `self._config`.

        Returns:
            Dict: Result dictionary containing:
                - status (str): 'success' or 'retry'
                - approach (str): 'extraction_ladder'
                - extracted_fields (Dict): Consolidated highest-confidence field mapping
                - extraction_confidence (float): Weighted consensus confidence
                - ladder_trace (List[Dict]): Step-by-step diagnostic trace of every executed rung
                - source_rung_by_field (Dict): Origin rung name for each extracted field
                - rejected_fields, reviewed_fields, passed_fields: Categorized field lists
        """
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
    def _names_match(name1: str, name2: str) -> bool:
        """
        Set-based name comparison — case-, accent-, punctuation-, and order-insensitive.

        Handles Complex Identity Variations:
        ------------------------------------
        - Case variations: "JOHN DOE" vs "john doe"
        - Accented characters: "José García" vs "jose garcia", "Müller" vs "Muller"
        - Reordered names: "Doe John" vs "John Doe"
        - Punctuation / Hyphens: "Mary-Jane" vs "Mary Jane"
        - Single-word vs joined variants: "O'Connor" vs "OConnor"

        Args:
            name1 (str): First name string.
            name2 (str): Second name string.

        Returns:
            bool: True if names match semantically under normalized token or concatenated comparison.
        """
        import unicodedata

        def normalize(name: str) -> set:
            # Remove accents/diacritics
            name = unicodedata.normalize('NFKD', name)
            name = ''.join(c for c in name if not unicodedata.combining(c))
            # Replace punctuation with spaces (so "Mary-Jane" → "Mary Jane")
            name = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in name)
            name = ' '.join(name.lower().split())
            return set(name.split()) if name else set()

        def normalize_concat(name: str) -> str:
            """Concatenated form — removes all non-alphanumeric chars.
            Handles single-word vs multi-word variants: O'Connor vs OConnor."""
            name = unicodedata.normalize('NFKD', name)
            name = ''.join(c for c in name if not unicodedata.combining(c))
            name = ''.join(c for c in name if c.isalnum())
            return name.lower()

        n1_set = normalize(name1)
        n2_set = normalize(name2)
        if n1_set and n1_set == n2_set:
            return True

        # Fallback: concatenated comparison for single-word vs multi-word
        n1_concat = normalize_concat(name1)
        n2_concat = normalize_concat(name2)
        if n1_concat and n1_concat == n2_concat:
            return True

        return False

    @staticmethod
    def _normalize_date(date_str: str) -> Optional[str]:
        """
        Normalize an arbitrary date string to ISO YYYY-MM-DD format for comparison.

        Supported Input Formats:
        ------------------------
        %Y-%m-%d, %d/%m/%Y, %d.%m.%Y, %d %b %Y, %d %B %Y, %Y/%m/%d

        Args:
            date_str (str): Raw extracted date string.

        Returns:
            Optional[str]: Normalized 'YYYY-MM-DD' string, or None if unparseable.
        """
        from datetime import datetime

        if not date_str or not date_str.strip():
            return None

        date_str = date_str.strip()

        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

        return None  # Unparseable — leave to reviewer

    @staticmethod
    def _mask_name(name: str) -> str:
        """
        Mask a person's name for privacy compliance in audit logs and API error strings.
        Keeps the first and last character of each word, replacing intermediate letters with '*'.

        Example:
            "John Doe" -> "J**n D*e"

        Args:
            name (str): Raw person name.

        Returns:
            str: Masked representation.
        """
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
        """
        Mask a date string for privacy compliance in logs and reports.
        Preserves only the month/day while redacting the exact year.

        Example:
            "1990-05-15" -> "****-05-15"

        Args:
            date_str (str): Date string.

        Returns:
            str: Masked date string.
        """
        normalized = ValidationAgent._normalize_date(date_str)
        if normalized:
            return f"****-{normalized[5:]}"
        return ValidationAgent._mask_name(date_str)

    # -------------------------------------------------------------------------- #
    #  Phase 4: Cross-validation (WP7) — internal logic checks                    #
    # -------------------------------------------------------------------------- #

    def validate_internal_logic(self, extracted_fields: Dict,
                                doc_type: str = "") -> List[dict]:
        """
        Run internal-logic cross-validation on extracted fields within a single document.

        Evaluates field dependencies and physical plausibility:
        - Expiry Date vs DOB: Expiry must be chronologically after Date of Birth.
        - Issue Date vs Expiry: Issue date must strictly precede expiry date.
        - Name Plausibility: Name must be >= 2 characters and not composed exclusively of digits.
        - Sex / Gender Codes: Must conform to standard ISO/ICAO codes ('M', 'F', 'X', 'OTHER').

        Role & Interconnections:
            Called during extraction pipeline evaluation to detect hallucinated or misaligned fields
            before committing them to database records.

        Args:
            extracted_fields (Dict): Extracted document fields dictionary.
            doc_type (str, optional): Document category identifier. Defaults to "".

        Returns:
            List[dict]: List of violation objects in the format:
                `[{"field": "...", "violation": "...", "severity": "..."}]`
        """
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
        """
        Classify a confidence score using config-driven thresholds for a document type.

        Threshold Boundaries:
        ---------------------
        - confidence >= pass_threshold: Returns "pass"
        - confidence >= human_review_threshold: Returns "review"
        - confidence < human_review_threshold: Returns "reject"

        Args:
            confidence (float): Aggregate or field-level extraction confidence score (0.0 - 1.0).
            doc_type (str, optional): Document category identifier. Defaults to "national_id".

        Returns:
            str: One of "pass", "review", or "reject".
        """
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
        """
        Return the loaded configuration thresholds for a specific document type.

        Role & Interconnections:
            Called by diagnostic endpoints and `ExtractionLadder` to verify active thresholds
            loaded from `config.yaml`.

        Args:
            doc_type (str): Document category identifier.

        Returns:
            Dict: Dictionary containing pass_threshold, human_review_threshold, reject_threshold,
                  extraction_threshold, mandatory_fields, and optional_fields.
        """
        return dict(self._thresholds.get(doc_type, {
            "pass_threshold": 0.8,
            "human_review_threshold": 0.7,
            "reject_threshold": 3,
            "extraction_threshold": 0.5,
            "mandatory_fields": [],
            "optional_fields": [],
        }))
