# Multi-Service Agentic Onboarding System — Policies, Procedures & Compliance

## Document Control
- **Version:** 1.0
- **Date:** 2024-01-01
- **Author:** System Design Team
- **Status:** Final

---

## 1. Executive Summary

This document defines the complete set of policies, procedures, and compliance requirements for the Multi-Service Agentic Onboarding System. It maps directly to the grading criteria specified in the project problem statement and ensures every requirement is traceable, testable, and defensible.

---

## 2. System Principles

### 2.1 Core Design Principles

1. **Correctness over speed:** A slow correct answer is acceptable. A fast wrong answer is not.
2. **No hallucination:** Every system answer must come from actual service definition documents, never invented information.
3. **User data isolation:** One customer's data must never leak into another customer's session, even under heavy concurrent use.
4. **Graceful degradation:** When something goes wrong, the system should fail safely — never silently corrupt data or accept incorrect information.
5. **Traceability:** Every action in the system must be logged and auditable after the fact.

### 2.2 Out-of-Scope Boundaries

The following are explicitly NOT covered by this system:
- Checking extracted document data against any outside system, database, or live system
- Building the workflow that later reconciles extracted data with external systems
- Real-world document authenticity verification (e.g., checking if a passport is fake)

The system's job ends once it has extracted the right information and stored it correctly. Correctness is measured against the golden dataset, not against any live system.

---

## 3. Service Catalogue Policy

### 3.1 Service Classification

All services fall into one of three categories:

| Category | Definition | System Behaviour |
|----------|-----------|------------------|
| **Available** | Service is live and can process applications | Agent accepts applications and guides users |
| **Coming Soon** | Service exists in catalogue but is not ready | Agent clearly states it is not available yet |
| **Unknown** | Service is not in catalogue at all | Agent states it is not recognised |

### 3.2 Routing Policy

1. **Wrong service is a critical failure.** The system must never send a user to the wrong service.
2. **FAQ vs. Application intent must be detected accurately.** Pushing someone into uploading documents when they were only asking is wrong. Stalling someone who is clearly ready to apply is equally wrong.
3. **The three-way distinction (available vs. coming soon vs. unknown) must never be confused.**

### 3.3 Service Definitions

For each of the three primary services, a service definition document exists covering:
- What the service requires
- How the process works
- How long it takes
- Any special rules or constraints

These documents are the **source of truth** for FAQ answers. Every answer the system gives about a service must come from what is actually written in these documents.

---

## 4. Document Handling Policy

### 4.1 Document Acceptance

The system must:
- Accept file uploads only after verifying their **actual content type** by looking at file content (magic bytes), not file extension or name
- Reject files that are renamed, corrupted, or contain broken content before they reach the extraction pipeline
- Prevent duplicate uploads — uploading the same document twice must not create duplicate records
- Handle partial/interrupted uploads safely — no broken, half-saved files may remain on disk
- Prevent cross-service document contamination — if a customer switches services mid-conversation, previously uploaded documents must not attach to the wrong service

### 4.2 Document Types and Capture Conditions

The system handles the following document types from the MIDV-500 dataset:
- **National ID Cards** — for Basic Registration
- **Passports** — for Premium/Cross Border
- **Driving Licences** — for Mobility/Rental

Capture conditions represented in the dataset:
- Table (top-down, flat surface)
- Handheld (angled, perspective distortion)
- Cluttered background
- Partial occlusion / out of frame
- Glare and shadow

### 4.3 Field Extraction Policy

1. **Field sets are document-type-specific.** Driving licence extraction logic must not be reused for ID cards without verifying the extraction still fits.
2. **Mandatory vs. optional fields are explicitly defined** (see Field Selection Note).
3. **Extraction accuracy is measured against the golden dataset** — every extracted value must match exactly. A wrong value is a failure regardless of system confidence.
4. **Results are reported separately by document type and capture condition** — a clean photo and a partly hidden one must not be judged identically.
5. **Low confidence results must be surfaced to the user** — the system must ask for a better photo instead of silently saving a guess as fact.

---

## 5. Collection Agent Policy

### 5.1 Responsibilities

The Collection Agent is responsible for:
1. Working out what documents are required for the chosen service
2. Tracking what has been submitted against what is still missing
3. Asking for the right thing next
4. Reasoning about acceptable alternatives when a requested document is unavailable
5. Handling user questions or intent changes mid-submission without losing track of collected documents

### 5.2 Error Handling Behaviour

| Error Type | System Response |
|------------|----------------|
| Wrong document type entirely | Tell the customer exactly what is needed, not just try again |
| Right type but unclear image | Ask for a clearer photo and specify what would make it clearer |
| Same problem happens twice | Stop asking and hand the case to the Validation Agent as an exception |

### 5.3 Completion Criteria

An application is not marked complete until:
- All required documents have arrived
- Every required document has been successfully extracted
- The extraction results are valid (not expired fields, correct mandatory fields present)

---

## 6. Validation Agent Policy

### 6.1 Responsibilities

The Validation Agent's job is to look at everything submitted for an application together and decide whether it actually meets the requirements:
- That every required document has arrived
- That each one is readable and correctly extracted
- That field-specific rules are met (e.g., document has not expired)

### 6.2 Validation Checks

The validation agent runs the following checks:

1. **Document count check** — The correct number of documents must be present. If one document is missing for a service requiring two, the application is not marked complete. This is a simple count check, not agentic reasoning.

2. **Cross-document field matching** — For services requiring multiple documents (Premium/Cross Border), the system checks that shared fields (name, date of birth, document number) agree across all submitted documents.

3. **Field-specific validation** — Expired documents are rejected. Mandatory fields must be present and valid.

4. **Extraction approach diversity** — If extraction on a document produces a nonsensical result, retrying the exact same extraction on the exact same image will not help. The agent tries a different extraction approach before deciding the document itself is the problem.

### 6.3 Matched and Mismatched Pair Testing

The validation agent must be tested against a labeled dataset of:
- **~40 true match pairs** — proving the agent correctly approves genuine pairs
- **10+ labeled mismatch pairs** — proving the agent correctly catches deliberate field disagreements (different name, different DOB, etc.)

The output of each validation must be a clear **pass** or **fail**, with specific reasons for any failure and exactly what is missing or wrong — not a vague single yes/no.

---

## 7. Human-in-the-Loop (HITL) Policy

### 7.1 Escalation Threshold

The system follows this escalation logic:

| Scenario | Action |
|----------|--------|
| All fields correct | Auto-accept |
| Some fields wrong (8/10) | Escalate to human review |
| All fields wrong or missing | Auto-reject |
| Extraction confidence genuinely low | Escalate to human review |

### 7.2 Human Review Record Format

Human review records must include:
- Exactly which fields are in question (not just a flag on the whole record)
- The extracted value for each disputed field
- The golden dataset value for comparison
- The system's confidence score for each disputed field
- Any contextual notes from the validation agent

This record must be structured so that a future system could use it directly.

### 7.3 Worst Case Monitoring

The system tracks **auto-accepted records with undetected errors** separately from all other metrics. This is the worst-case scenario — a record accepted without any error detection — and must be counted and reported on its own, never blended into a single accuracy number.

---

## 8. Security and Governance Policy

### 8.1 Secrets Management

- No passwords, API keys, or connection details are written directly in code or committed to version control
- All secrets are stored in `.env` files (gitignored) or managed through environment variables
- Secret files are listed in `.gitignore`

### 8.2 Prompt Injection Resistance

- The system must not treat text inside documents that looks like instructions (e.g., "ignore all previous instructions") as real instructions
- The same applies to anything typed by the user that tries to override the system's behaviour or reach another user's data
- Guardrails (LLM Guard, Guardrails AI, NeMo Guardrails) should be used to scan and constrain LLM input/output

### 8.3 Prompt Injection Test Case

A documented test case must demonstrate at least one real instance where the system catches a prompt injection attempt. This test case is documented alongside other validation checks.

---

## 9. Authorization and Data Isolation Policy

### 9.1 Authentication Requirements

- The system must have real login and signup (not simulated)
- Each user's account, applications, and application statuses are stored in the backend database
- Every conversation is tied to the logged-in user's account ID

### 9.2 Authorization Enforcement

- Every database lookup must be filtered by user account ID **at the database level**, not just checked in conversation logic
- Someone who is not logged in gets no access to any application data
- One logged-in user must never be able to reach another user's data, no matter how the question is phrased

### 9.3 Concurrency Testing

At least one real, tested case must be shown of authorization working correctly with two users applying to the system at the same time.

---

## 10. Observability and Continuous Improvement Policy

### 10.1 Traceability

Every stage of every application must be traceable after the fact:
- Routing decision
- FAQ answer and its source
- Upload events
- Extraction results and confidence scores
- Human review escalation
- Final storage outcome

### 10.2 Failure Logging

Failures and escalations must be logged and easy to inspect, not silently absorbed. The system must accumulate logs that make failure patterns visible:
- If a certain phrasing repeatedly causes the wrong service to be chosen, this should surface on its own
- The golden dataset and eval set should grow from real failures observed during development
- A later change that brings back a fixed problem must be catchable using the accumulated eval set

### 10.3 Trend Tracking

The following metrics should be tracked as trends across the project:
- Routing accuracy
- Extraction accuracy
- Human review rates

---

## 11. Performance and Trust Metrics Policy

### 11.1 Correctness Metrics

| Metric | Measurement Method |
|--------|-------------------|
| Routing accuracy | Correct service identification and correct question vs. apply detection, measured separately |
| FAQ groundedness | Answers checked and confirmed traceable to the actual service definition document |
| Extraction accuracy | Against golden dataset, reported by document type and capture condition |
| Human review correctness | How often escalation was the right call; separately, how often a record was wrongly auto-accepted with an error nobody caught |

### 11.2 Trust and Audit Metrics

| Metric | Measurement Method |
|--------|-------------------|
| Full application history | End-to-end trace from first question to final outcome |
| Authorization case | Kept on record, not just claimed once |
| Reproducibility | Same request, asked twice, produces same routing and outcome |
| Edge case handling | Behaviour on confusing requests, mixed requests, attempts to skip checklist steps |

### 11.3 Operational Metrics

| Metric | Measurement Method |
|--------|-------------------|
| Session isolation | Checked correctly under concurrent scenarios |
| Response time | Under concurrent load, at each stage |
| Upload/storage correctness | Free of duplicates when retried |

---

## 12. Design Decision Defence Policy

### 12.1 Required Justifications

The system design must be able to explain and justify:
1. Why each tool or framework was chosen and what role it plays
2. The routing approach and how it scales to the full catalogue without hardcoding for each service
3. The extraction approach and how it was checked against the golden dataset
4. The business rules chosen for the validation agent and why those rules and not others
5. The human review thresholds and why they were set at those levels
6. The Phase 5 reconciliation agent design and the reasoning behind its input, output, and escalation contract
7. Trade-offs considered and not taken, and why
8. How design choices address Phase 3 scenarios and the answer quality bar

---

## 13. Reconciliation Agent Design (Phase 5)

### 13.1 Purpose

The reconciliation agent would check extracted information against an authoritative outside source (government ID registry or internal customer database). This is a design exercise only — not built in this project.

### 13.2 Input Contract

The reconciliation agent would receive from the validation agent:
- Extracted fields from all documents submitted for the application
- The document type for each set of fields
- The service being applied for
- The confidence scores for each extracted field
- Any flags raised by the validation agent

### 13.3 Output Contract

The reconciliation agent would return:
- **Match** — All fields verified against the external source
- **Mismatch** — One or more fields do not match the external source, with specific fields identified
- **Unverifiable** — The external source could not be reached or returned insufficient data

Each result includes:
- Evidence behind the decision
- Explanation in plain language
- Recommendation on whether to escalate to human review

### 13.4 Failure Modes

| Failure Mode | Handling Strategy |
|-------------|-------------------|
| External source slow | Timeout after reasonable interval; flag as unverifiable |
| External source unavailable | Flag as unverifiable; offer user option to retry |
| Low confidence result from external source | Flag for human review; do not auto-accept |

---

## 14. Handoff Documentation Policy

### 14.1 README Requirements

The project repository must include a README that lists:
- The exact commands to bring the system up from a clean clone/download
- Steps must be commands actually used and verified — no paraphrased or "should work" instructions
- System must come up successfully on a machine other than the one it was built on (portability check)

### 14.2 Known Limitations

The system must document all known limitations clearly.

---

## Appendix A: Required Deliverables Checklist

| Deliverable | Reference | Status |
|-------------|-----------|--------|
| Working, containerized system | Section 5 bar | To be completed |
| MIDV document type selection note | Section 2 | ✓ Complete |
| Service definition documents (PDF) | Section 2 | To be completed |
| Golden dataset | Section 2 | In progress |
| Matched/mismatched document pairs | Section 2 | In progress |
| Field selection note | Section 2 | ✓ Complete |
| Eval results by stage/question type | Section 8 | To be completed |
| Authorization layer test case | Section 6 | To be completed |
| Phase 5 reconciliation agent design | Section 5 | In progress |
| Trust report | Section 8 | To be completed |
| Architecture and design decision writeup | Section 10 | To be completed |
| Handoff documentation | Section 11 | In progress |

---

*This policy document is living documentation and should be updated as the project progresses through each phase.*
