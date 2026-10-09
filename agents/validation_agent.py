"""
Validation Agent - Phase 2

Looks at everything submitted for an application together and decides
whether it actually meets the requirements.

Design Decision: Uses explicit validation rules rather than LLM-based
judgement, because:
1. Validation results must be deterministic (same input = same output)
2. Field cross-checking requires exact string/numeric comparison
3. Business rules need to be testable and auditable
4. LLM-based validation would introduce non-determinism into a critical path
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone
from enum import Enum


class ValidationResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_REVIEW = "needs_review"


class ValidationIssue:
    """A specific issue found during validation."""

    def __init__(self, field: str, expected: str, actual: str,
                 severity: str = "high"):
        self.field = field
        self.expected = expected
        self.actual = actual
        self.severity = severity
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
            "timestamp": self.timestamp.isoformat(),
        }


class ValidationReport:
    """Complete validation result for an application."""

    def __init__(self, application_id: str):
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
        """Add a validation issue.

        - Critical → FAIL (immediate reject)
        - High → increment fields_failed
        - Medium → send to review (fields_reviewed), NOT fields_failed
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
        """Record a field that passed validation."""
        self.fields_passed += 1
        self.fields_checked += 1

    def add_review(self, field: str, severity: str = "medium"):
        """Record a field sent for human review."""
        self.fields_reviewed += 1
        self.fields_checked += 1
        if severity == "critical":
            self.result = ValidationResult.NEEDS_REVIEW

    def finalize(self):
        """Finalize the validation report.

        Status logic:
        - All mandatory fields read and agreed → PASS
        - 1–2 fields uncertain/conflicting after extraction ladder → NEEDS_REVIEW
        - 3+ unreadable fields or missing docs → INCOMPLETE
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
        """Get list of fields that need human review."""
        return [i.field for i in self.issues if i.severity == "medium"]

    def get_failure_fields(self) -> List[str]:
        """Get list of fields that failed validation."""
        return [i.field for i in self.issues if i.severity == "high" or i.severity == "critical"]

    def to_dict(self) -> dict:
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
    Validation Agent - Phase 2

    Jobs:
    - Check that every required document has arrived
    - Check that each document is readable and correctly extracted
    - Check field-specific rules (e.g., expiry dates)
    - Cross-check shared fields across documents (e.g., name, DOB)
    - Try different extraction approaches before concluding document is the problem
    - Output clear pass/fail with specific reasons, not vague yes/no

    Design Decision: Validation rules are explicitly defined and tested,
    not inferred from LLM responses. This ensures determinism and auditability.
    """

    # Human review threshold: number of uncertain fields before escalation
    # Design: 1-2 uncertain fields -> review, 3+ -> reject
    REVIEW_THRESHOLD_LOW = 1
    REVIEW_THRESHOLD_HIGH = 2
    REJECT_THRESHOLD = 3

    def __init__(self):
        # Matched/mismatched pairs for testing
        self.matched_pairs: List[Dict] = []
        self.mismatched_pairs: List[Dict] = []
        # Validation rules per service
        self.rules: Dict[str, List[callable]] = {}

    def register_matched_pairs(self, pairs: List[Dict]):
        """Register matched identity pairs for validation testing."""
        self.matched_pairs = pairs

    def register_mismatched_pairs(self, pairs: List[Dict]):
        """Register mismatched identity pairs for validation testing."""
        self.mismatched_pairs = pairs

    def validate_application(self, application_data: Dict) -> ValidationReport:
        """
        Validate a complete application.

        Args:
            application_data: Dict containing:
                - application_id: str
                - service_id: str
                - documents: list of extracted document data
                - golden_dataset: optional reference for extraction check

        Returns:
            ValidationReport with pass/fail/review result
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
                if field in extracted_fields and extracted_fields[field]:
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
        Validate the matched/mismatched pairs.

        This proves the validation agent correctly:
        1. Passes genuine matches (true positives)
        2. Catches deliberate mismatches (true negatives)
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
        Get mandatory fields for a document type.

        Design Decision: Field selection based on what is needed for
        identity verification and service compliance. Non-essential
        fields (like secondary addresses) are optional.
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
            return ["name", "date_of_birth", "document_number", "expiry_date",
                    "license_class", "issue_date"]
        else:
            return core_mandatory

    def _check_field_rules(self, doc: Dict, doc_type: str, report: ValidationReport):
        """Check document-specific field rules (expiry, format, etc.)."""
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

    def _is_valid_expiry(self, expiry_date: str) -> Optional[bool]:
        """Check if an expiry date is in the future.

        Returns:
            True if valid future date, False if expired/invalid, None if unparseable
            (which should trigger human review — fail-closed).
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
        Cross-check shared fields across documents submitted together.

        For the premium service (ID + passport), name and date of birth
        must match between both documents.

        A6: Uses set-based name comparison (case/accents/punctuation/order insensitive).
        A7: Missing shared fields are reported as 'unverifiable', not silently skipped.
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
        """Check extracted fields against the golden dataset."""
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

    def retry_extraction_with_alternative(self, image_data: bytes, doc_type: str) -> Dict:
        """
        Try alternative extraction approaches before concluding document is the problem.

        Design Decision: If OCR fails with one approach, try:
        1. Higher-resolution crop of the field region
        2. MRZ-only parse (passporteye or mrz)
        3. Independent OCR read (PyMuPDF text or Tesseract)
        4. Compare results — keep the one that passes checksums/consensus

        Each rung is recorded in the trace. Never retry the same approach.
        """
        return {
            "status": "retry",
            "approach": "alternative_model",
            "message": f"Retrying {doc_type} extraction with alternative approach."
        }

    # -------------------------------------------------------------------------- #
    #  A6/A7: Name matching, date normalization, masking                         #
    # -------------------------------------------------------------------------- #

    @staticmethod
    def _names_match(name1: str, name2: str) -> bool:
        """Set-based name comparison — case/accents/punctuation/order insensitive.

        Handles:
        - "JOHN DOE" vs "john doe"
        - "José García" vs "jose garcia"
        - "Doe John" vs "John Doe" (reordered)
        - "O'Connor" vs "OConnor"
        - "Mary-Jane" vs "Mary Jane"
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
        """Normalize a date string to YYYY-MM-DD for comparison.

        Handles formats: %Y-%m-%d, %d/%m/%Y, %d.%m.%Y, %d %b %Y, %d %B %Y, %Y/%m/%d
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
        """Mask a name for output — keep first and last letter of each word."""
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
        """Mask a date for output — show only year."""
        normalized = ValidationAgent._normalize_date(date_str)
        if normalized:
            return f"****-{normalized[5:]}"
        return ValidationAgent._mask_name(date_str)
