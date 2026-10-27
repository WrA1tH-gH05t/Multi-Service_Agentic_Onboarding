"""
test_agent_bugs.py - Regression Test Suite for Document Collection & Validation Agents (Bugs A1–A8).

Module Purpose & Role in the Project:
------------------------------------
This regression test suite validates bug fixes and safeguards invariants across
`CollectionAgent` and `ValidationAgent`. It uses synthetic test fixtures (avoiding real PII)
to confirm that previously identified architectural and logic bugs cannot re-emerge.

Regression Bug Coverage:
  - A1: `get_status_message()` immutability: Verifies that polling status or asking user questions
        does not mutate or pop requirements from `session.document_requirements`.
  - A2: Required slot enforcement: Asserts that uploading 1 of 2 mandatory documents yields
        status `'continue'` and never prematurely marks the application as `'complete'`.
  - A3: Upload failure thresholding: Asserts that the first upload failure returns `'retry'`;
        subsequent failures for the same reason trigger `'escalate_to_validation'`.
  - A4: Human review escalation: Confirms that medium-severity issues result in `'needs_review'`
        rather than catastrophic `'fail'`, keeping the human-in-the-loop workflow reachable.
  - A5: Expiry date parsing: Confirms unparseable date strings fail closed (return `None` for review),
        future dates pass, past dates fail, and month-year strings are valid through end-of-month.
  - A6: Set-based tolerant name matching: Asserts order-invariant, punctuation-insensitive,
        and diacritic/accent-folded matching (`José García` matches `jose garcia`).
  - A7: Missing shared cross-check fields: Unverifiable pairs (e.g. passport has DOB but national ID
        lacks DOB) report `'needs_review'` rather than silently passing.
  - A8: Multi-tenant session integrity: Enforces UUID generation for session IDs, collision-free
        fast instantiation, timezone-aware UTC timestamps, and strict `user_id` ownership checks.

Interconnections with Other Components:
---------------------------------------
- `agents.collection_agent`: Tests `CollectionAgent` and `ApplicationSession` state transitions.
- `agents.validation_agent`: Tests `ValidationAgent`, `ValidationReport`, and `ValidationIssue`.
- Backend Workflow: Mirrors the core business constraints enforced in `app.api.routes.documents`
  and the LangGraph agent supervisor nodes.
"""
import sys
import os
# Add project root to path so `agents` module is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
import hashlib
from agents.collection_agent import CollectionAgent, ApplicationSession
from agents.validation_agent import ValidationAgent, ValidationReport


# =====================================================================
# A1: get_status_message() must NOT mutate document_requirements
# =====================================================================

class TestA1_NoMutationOnGetStatusMessage:
    """
    Test suite verifying that querying session status does not mutate requirements.
    
    Interconnections:
    - Tests `ApplicationSession.get_status_message()` in `agents.collection_agent`.
    """

    def test_popitem_bug_fixed(self):
        """A1: get_status_message() used to call popitem() which deleted a requirement."""
        agent = CollectionAgent()
        session_id = agent.create_session(
            user_id="test_user_a1",
            service_id="national_id",
            service_name="Basic Registration",
            required_documents=["national_id", "passport"]
        )
        session = agent.get_session(session_id)

        # Before: should have exactly 2 requirements
        assert session.get_required_count() == 2

        # Calling get_status_message() should NOT remove any requirement
        msg1 = session.get_status_message()
        assert session.get_required_count() == 2

        msg2 = session.get_status_message()
        assert session.get_required_count() == 2

        # Multiple calls should not change anything
        for _ in range(10):
            session.get_status_message()
        assert session.get_required_count() == 2, "Requirements mutated by get_status_message()"

    def test_status_message_mentions_first_requirement(self):
        """The message should still be meaningful."""
        session = ApplicationSession("sess_test", "user", "service")
        session.add_document_requirement("passport", mandatory=True)
        session.add_document_requirement("national_id", mandatory=True)

        msg = session.get_status_message()
        assert "passport" in msg or "national_id" in msg
        assert "Please upload" in msg


# =====================================================================
# A2: One of two required documents must never yield complete
# =====================================================================

class TestA2_RequiredSlotsCount:
    """Submitting only one of two mandatory docs must NOT mark complete."""

    def test_one_of_two_never_complete(self):
        """A2: With 2 required documents, submitting one must give 'continue', not 'complete'."""
        agent = CollectionAgent()
        session_id = agent.create_session(
            user_id="test_user_a2",
            service_id="premium_crossborder",
            service_name="Premium/Cross-Border",
            required_documents=["national_id", "passport"]
        )

        # Submit the first document
        result = agent.submit_document(
            session_id=session_id,
            doc_type="national_id",
            file_id="file_001",
            extraction_ok=True,
            extraction_fields={"name": "Test User", "document_number": "123456"},
            extraction_confidence=0.9
        )

        # Must NOT be complete
        assert result["action"] != "complete", (
            "BUG A2: One of two documents yielded 'complete' — should be 'continue'"
        )
        assert result["action"] == "continue", (
            f"Expected 'continue' but got '{result['action']}'"
        )

        # Session must still be collecting
        session = agent.get_session(session_id)
        assert session.status in ("collecting", "incomplete")

    def test_both_required_docs_yields_complete(self):
        """When both are submitted, it should be ready for validation."""
        agent = CollectionAgent()
        session_id = agent.create_session(
            user_id="test_user_a2",
            service_id="premium_crossborder",
            service_name="Premium/Cross-Border",
            required_documents=["national_id", "passport"]
        )

        agent.submit_document(
            session_id=session_id,
            doc_type="national_id",
            file_id="file_001",
            extraction_ok=True,
            extraction_fields={"name": "Test User", "document_number": "123456"},
            extraction_confidence=0.9
        )

        # Submit second
        result = agent.submit_document(
            session_id=session_id,
            doc_type="passport",
            file_id="file_002",
            extraction_ok=True,
            extraction_fields={"name": "Test User", "document_number": "AB12345"},
            extraction_confidence=0.9
        )

        # Should transition to validation
        assert result["action"] in ("complete", "needs_review"), (
            f"Expected 'complete' or 'needs_review' but got '{result['action']}'"
        )


# =====================================================================
# A3: First failed upload must NOT immediately escalate
# =====================================================================

class TestA3_UploadFailureCounting:
    """First failure gives retry, second failure with same reason escalates."""

    def test_first_failure_gives_retry(self):
        """A3: First failed upload should return 'retry', not 'escalate_to_validation'."""
        agent = CollectionAgent()
        session_id = agent.create_session(
            user_id="test_user_a3",
            service_id="national_id",
            service_name="Basic Registration",
            required_documents=["national_id"]
        )

        # First failure — should be retry
        result = agent.submit_document(
            session_id=session_id,
            doc_type="national_id",
            file_id="file_fail_001",
            extraction_ok=False
        )

        assert result["action"] == "retry", (
            f"BUG A3: First failure gave '{result['action']}' instead of 'retry'"
        )

        # Verify only 1 failure recorded (not 2)
        session = agent.get_session(session_id)
        req = session.document_requirements["national_id"]
        assert req.upload_failures == 1, (
            f"BUG A3: upload_failures = {req.upload_failures}, expected 1"
        )

    def test_second_failure_same_reason_escalates(self):
        """Second failure with the same reason should escalate."""
        agent = CollectionAgent()
        session_id = agent.create_session(
            user_id="test_user_a3",
            service_id="national_id",
            service_name="Basic Registration",
            required_documents=["national_id"]
        )

        # First failure
        r1 = agent.submit_document(
            session_id=session_id,
            doc_type="national_id",
            file_id="file_fail_001",
            extraction_ok=False
        )
        assert r1["action"] == "retry"

        # Second failure
        r2 = agent.submit_document(
            session_id=session_id,
            doc_type="national_id",
            file_id="file_fail_002",
            extraction_ok=False
        )
        assert r2["action"] == "escalate_to_validation", (
            f"BUG A3: Second failure gave '{r2['action']}' instead of 'escalate_to_validation'"
        )


# =====================================================================
# A4: Medium-severity issues must lead to NEEDS_REVIEW, not FAIL
# =====================================================================

class TestA4_HumanReviewReachability:
    """One uncertain mandatory field → needs_human_review (not FAIL)."""

    def test_medium_issue_gives_needs_review(self):
        """A4: A single medium-severity issue should NOT result in FAIL."""
        report = ValidationReport("test_a4")

        # Add a single medium-severity issue (e.g., low confidence)
        from agents.validation_agent import ValidationIssue
        report.add_issue(ValidationIssue(
            field="passport.expiry_date",
            expected="Future date",
            actual="unparseable",
            severity="medium"
        ))
        report.finalize()

        assert report.result.value == "needs_review", (
            f"BUG A4: Medium issue gave '{report.result.value}' instead of 'needs_review'"
        )

    def test_all_fields_passed_gives_pass(self):
        """All fields passed → PASS."""
        report = ValidationReport("test_a4_pass")
        report.add_pass("passport.name")
        report.add_pass("passport.document_number")
        report.finalize()
        assert report.result.value == "pass"

    def test_critical_issue_gives_fail(self):
        """Critical issue → FAIL."""
        report = ValidationReport("test_a4_critical")
        from agents.validation_agent import ValidationIssue
        report.add_issue(ValidationIssue(
            field="passport.name",
            expected="present",
            actual="missing",
            severity="critical"
        ))
        report.finalize()
        assert report.result.value == "fail"


# =====================================================================
# A5: Unparseable expiry must fail-closed (go to review)
# =====================================================================

class TestA5_ExpiryValidation:
    """Unparseable expiry → None (review). Month-year → valid through last day. Expired → False."""

    def test_unparseable_expiry_returns_none(self):
        """A5: 'garbage' and other unparseable strings should return None."""
        agent = ValidationAgent()
        assert agent._is_valid_expiry("garbage") is None, "Unparseable expiry should return None"
        assert agent._is_valid_expiry("") is None
        assert agent._is_valid_expiry("xyz") is None

    def test_valid_future_date(self):
        """Future date → True."""
        agent = ValidationAgent()
        assert agent._is_valid_expiry("2030-01-15") is True
        assert agent._is_valid_expiry("15/01/2030") is True

    def test_expired_date(self):
        """Past date → False."""
        agent = ValidationAgent()
        assert agent._is_valid_expiry("2020-01-15") is False
        assert agent._is_valid_expiry("15/01/2020") is False

    def test_month_year_valid(self):
        """Month-year format valid through last day of that month."""
        agent = ValidationAgent()
        # December 2025 — if today is before Dec 31 2025, should be True
        # January 2020 — should be False
        assert agent._is_valid_expiry("01/2020") is False

    def test_month_year_current(self):
        """Month-year in the current month should be valid."""
        import datetime
        agent = ValidationAgent()
        now = datetime.date.today()
        month_year = f"{now.month:02d}/{now.year}"
        assert agent._is_valid_expiry(month_year) is True, (
            f"Month-year {month_year} should be valid for current month"
        )


# =====================================================================
# A6: Set-based name matching — reordered, accented, punctuated names
# =====================================================================

class TestA6_NameMatching:
    """Same person with reordered name and different date format passes cross-check."""

    def test_same_name_different_order(self):
        """A6: 'Doe John' should match 'John Doe'."""
        assert ValidationAgent._names_match("Doe John", "John Doe") is True

    def test_same_name_different_case(self):
        """Case insensitive."""
        assert ValidationAgent._names_match("JOHN DOE", "john doe") is True
        assert ValidationAgent._names_match("John Doe", "JOHN DOE") is True

    def test_accented_vs_plain(self):
        """José García should match jose garcia."""
        assert ValidationAgent._names_match("José García", "jose garcia") is True
        assert ValidationAgent._names_match("Müller", "Muller") is True

    def test_punctuation_insensitive(self):
        """O'Connor should match OConnor."""
        assert ValidationAgent._names_match("O'Connor", "OConnor") is True
        assert ValidationAgent._names_match("Mary-Jane", "Mary Jane") is True

    def test_different_names_do_not_match(self):
        assert ValidationAgent._names_match("John Doe", "Jane Doe") is False
        assert ValidationAgent._names_match("John Doe", "John Smith") is False


# =====================================================================
# A7: Missing shared fields reported as unverifiable, not silently skipped
# =====================================================================

class TestA7_MissingFieldsCrossCheck:
    """A pair where one document lacks DOB reports 'unverifiable'."""

    def test_missing_field_gives_review(self):
        """Missing shared field → review item, not a silent pass."""
        agent = ValidationAgent()
        report = ValidationReport("test_a7")

        documents = [
            {
                "doc_type": "national_id",
                "extracted_fields": {
                    "name": "John Doe",
                    # date_of_birth missing from ID card
                }
            },
            {
                "doc_type": "passport",
                "extracted_fields": {
                    "name": "John Doe",
                    "date_of_birth": "1990-01-15",
                }
            }
        ]

        agent._check_cross_document_fields(documents, report)

        # Should have review items for the missing DOB
        assert report.fields_reviewed > 0, (
            "BUG A7: Missing shared field should produce a review item"
        )

    def test_both_have_field_match(self):
        """Both docs have matching DOB → pass."""
        report = ValidationReport("test_a7_match")
        agent = ValidationAgent()

        documents = [
            {"doc_type": "national_id", "extracted_fields": {"name": "John Doe", "date_of_birth": "15/01/1990"}},
            {"doc_type": "passport", "extracted_fields": {"name": "John Doe", "date_of_birth": "1990-01-15"}},
        ]

        agent._check_cross_document_fields(documents, report)

        # Should pass name and DOB cross-checks
        assert report.fields_passed > 0, "Matching fields should pass cross-check"


# =====================================================================
# A8: Session ID uniqueness + user_id ownership filtering
# =====================================================================

class TestA8_SessionOwnership:
    """Sessions use UUIDs, have user_id, and getters filter by user."""

    def test_session_ids_are_uuids(self):
        """A8: Session IDs should be UUIDs, not guessable timestamps."""
        agent = CollectionAgent()

        sid1 = agent.create_session("user1", "svc1")
        sid2 = agent.create_session("user2", "svc2")

        # Must be UUIDs (8-4-4-4-12 format)
        import uuid as pyuuid
        assert pyuuid.UUID(sid1)  # Raises if not a valid UUID
        assert pyuuid.UUID(sid2)

        # Must be unique
        assert sid1 != sid2

    def test_session_ids_do_not_collide_in_same_second(self):
        """Two sessions created in the same second must not collide."""
        agent = CollectionAgent()

        sid1 = agent.create_session("user1", "svc1")
        sid2 = agent.create_session("user1", "svc1")
        sid3 = agent.create_session("user1", "svc1")

        assert sid1 != sid2 != sid3, (
            "BUG A8: Sessions created in quick succession have colliding IDs"
        )

    def test_get_session_ownership_filter(self):
        """A8: get_session(session_id, user_id) must reject if user_id doesn't match."""
        agent = CollectionAgent()

        sid = agent.create_session("user_alpha", "svc1")

        # Same user can access
        session = agent.get_session(sid, user_id="user_alpha")
        assert session is not None, "Owner should be able to access their session"

        # Different user cannot
        session = agent.get_session(sid, user_id="user_beta")
        assert session is None, (
            "BUG A8: User should NOT be able to access another user's session"
        )

    def test_datetime_aware(self):
        """A8: All datetime fields should be timezone-aware."""
        from datetime import timezone

        agent = CollectionAgent()
        sid = agent.create_session("user_test", "svc1")
        session = agent.get_session(sid)

        assert session.created_at.tzinfo is not None, "created_at must be timezone-aware"
        assert session.last_updated.tzinfo is not None, "last_updated must be timezone-aware"
