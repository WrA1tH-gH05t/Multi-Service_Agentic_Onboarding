# Docintake Legal & Consent Framework — Deployment & Operations Guide

## Overview
This release integrates the comprehensive Legal-Policy, Privacy Policy, Government Review Access, and Application-Specific Consent Framework into the Docintake Multi-Service Agentic Onboarding Platform.

---

## 1. Pre-Modification Backup Verification
Before any files were updated, an automated snapshot was created and verified:
- **Location:** `backups/pre_legal_consent_20261116_102335/`
- **Total Files Verified:** 97 files with SHA-256 integrity checksums.
- **Manifest:** `backups/pre_legal_consent_20261116_102335/backup_manifest.txt`
- **Database Snapshot:** Included `data/app.db`.

---

## 2. Generated Policy Documents & Assets
The formal legal drafts have been compiled with professional formatting, headers, footers, and statutory callouts:

1. **Terms & Conditions and Service Policy:**
   - PDF Asset: `docs/Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf`
   - Static Asset: `app/static/policies/Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf`
   - In-App HTML Endpoint: `/api/v1/policies/terms`
   - Direct Download Endpoint: `/api/v1/policies/terms/download`

2. **Privacy Policy and Data Protection Framework:**
   - PDF Asset: `docs/Docintake_Privacy_Policy_v1.0_DRAFT.pdf`
   - Static Asset: `app/static/policies/Docintake_Privacy_Policy_v1.0_DRAFT.pdf`
   - In-App HTML Endpoint: `/api/v1/policies/privacy`
   - Direct Download Endpoint: `/api/v1/policies/privacy/download`

---

## 3. Database Schema Changes & Migration
Database models and tables have been extended with complete support for PostgreSQL and SQLite:
- `policy_documents`: Legal policy metadata, versioning (`1.0`), and content hashes.
- `user_terms_acceptances`: Records mandatory Terms acceptance at registration.
- `government_agencies`: Agency routing mappings (`identity_authority`, `crossborder_authority`, `mobility_rta`).
- `user_roles`: RBAC roles (`applicant`, `government_reviewer`, `developer`, `platform_admin`, `compliance_reviewer`) with agency scoping.
- `application_consents`: Application-specific consent records (`agreed`, `declined`, `withdrawn`) with document scope and timestamps.
- `document_access_audits`: Immutable audit trail for every document inspection action.

**Alembic Migration Script:**  
`alembic/versions/d4e5f6a7b8c9_legal_policy_and_review_access.py`

To apply migration to a PostgreSQL instance:
```bash
alembic upgrade head
```

---

## 4. Key Security & Functional Workflows

### Mandatory Registration Terms Acceptance
- Registration (`/api/v1/auth/signup` and `/api/v1/auth/register`) enforces `accept_terms: true`.
- Requests without explicit acceptance are rejected with `HTTP 400 Bad Request`.
- Acceptance is recorded in `user_terms_acceptances` with UTC timestamp and content hash.

### Strict Developer Access Restrictions
- Accounts with role `developer` are strictly forbidden from viewing, downloading, or generating presigned URLs for customer documents (`/documents/{id}/view`, `/documents/{id}/download`, `/documents/{id}/presigned-url`).
- Developer document view attempts are blocked with `HTTP 403 Forbidden` and logged in `document_access_audits`.
- Developers have access only to metrics, non-sensitive logs, and synthetic test suites.

### Application-Specific Document Review Consent
- Title: `DOCUMENT REVIEW CONSENT`
- Checkbox is unchecked by default.
- **Agree & Continue:** Commits documents to storage, sets status to `under_agency_review`, logs consent audit event, and routes application to the designated agency queue.
- **Decline:** Sets status to `rejected_consent_declined`, purges staged document binaries from MinIO, blanks sensitive extracted fields, logs decline audit event. Reopening is blocked.
- **Withdrawal:** Applicants can withdraw consent via `/applications/{id}/withdraw-consent`, halting processing and closing the application while retaining immutable history.

### Government Agency Compartmentalization
- Reviewers authenticate independently and access only applications routed to their assigned agency (`/api/v1/agency/applications`).
- Reviewers attempting to inspect documents from an unassigned agency receive `HTTP 403 Forbidden`.

---

## 5. Verification & Running Tests
Execute the end-to-end legal and consent test suite:
```bash
python -m pytest tests/test_legal_consent_e2e.py -v
```

All 5 core end-to-end security test cases pass:
- `test_01_legal_policies_and_downloads` (PASSED)
- `test_02_account_registration_terms_acceptance_mandatory` (PASSED)
- `test_03_developer_access_restrictions` (PASSED)
- `test_04_application_consent_workflow_three_services` (PASSED)
- `test_05_government_reviewer_compartmentalization` (PASSED)
