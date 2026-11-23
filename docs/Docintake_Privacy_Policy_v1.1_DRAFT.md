# Docintake — Privacy Policy

**Document Status: DRAFT — PENDING LEGAL APPROVAL**  
**Version:** v1.1  
**Effective Date:** Pending Legal Approval  
**Jurisdiction:** United Arab Emirates (subject to final legal verification)  
**Company:** Docintake  
**Registered Address:** N/A  

---

> **IMPORTANT NOTICE:** This document is a DRAFT and has not been reviewed or approved by qualified UAE legal counsel. It is not legally binding until formally approved. All statutory references are included for drafting purposes and must be verified by a qualified legal professional before this document is published or relied upon.

---

## 1. Introduction

Docintake ("Docintake", "we", "our", or "us") provides a digital document intake, collection, extraction, and routing platform ("Platform") operating under the laws of the United Arab Emirates. We are committed to protecting the privacy, confidentiality, and security of all personal data entrusted to us by our users and the children whose dependent profiles are managed on the Platform.

This Privacy Policy explains how Docintake collects, processes, uses, stores, retains, and protects personal data, including the personal data of adult users and children. It also outlines the statutory rights of data subjects and legal guardians under applicable UAE data protection laws.

This Privacy Policy applies to all individuals accessing or using the Platform, including account holders acting on their own behalf and legal guardians acting on behalf of child dependent profiles. This document should be read alongside the Docintake Terms and Conditions (v1.1 DRAFT).

---

## 2. Controller and Contact Information

**2.1 Data Controller Identity:**  
Docintake acts as the Data Controller in respect of user account information, profile administration, and platform operations. Where documents and applications are routed to designated authorized government-body reviewers, Docintake operates as an intake and routing processor, with each receiving government authority acting as an independent controller under its statutory mandate.

- **Company Name:** Docintake
- **Registered Address:** N/A
- **Jurisdiction:** United Arab Emirates (subject to final legal verification)
- **Policy Version:** v1.1
- **Document Status:** DRAFT — PENDING LEGAL APPROVAL
- **Effective Date:** Pending Legal Approval
- **Customer Support Contact:** [PLACEHOLDER]
- **Privacy & Data Protection Contact:** [PLACEHOLDER]

**2.2 Statutory Framework:**  
This Policy is drafted pursuant to the requirements of:
- UAE Federal Decree-Law No. 45 of 2021 on the Protection of Personal Data ("PDPL"); and
- UAE Federal Decree-Law No. 26 of 2025, specifically Article 7 governing parental consent and the processing of personal data relating to children.

---

## 3. Information We Collect

Docintake collects personal data strictly necessary to fulfill the services offered through the Platform. We collect data in the following categories:

### 3.1 Account Information
When an adult user registers an account on the Platform:
- Full legal name
- Contact telephone number and email address
- Login credentials (salted and hashed passwords)
- Account creation timestamp and status
- Acceptance records of general Terms & Conditions and Privacy Policy

### 3.2 Application and Document Data
When an application is initiated and identity documents are submitted:
- Submitted document image binaries (e.g., National ID cards, Passports, Driving Licences) in supported formats (JPEG, PNG, PDF)
- Cryptographic hash (SHA-256) of each submitted file to prevent duplicate processing
- Extracted structured fields, including document numbers, names, dates of birth, issue and expiry dates, document classes, and machine-readable zone (MRZ) characters
- Document verification logs and cross-document validation outcomes
- Application status, submission history, and workflow logs

### 3.3 Technical and Operational Data
To maintain operational integrity, platform performance, and security:
- Device and browser technical identifiers (user agent strings, protocol versions)
- Internet Protocol (IP) addresses recorded for security and consent verification audit purposes
- Operational timestamps for upload, processing, review, and routing events
- Non-sensitive system diagnostic and performance metrics

---

## 4. Children's Personal Data and Dependent Profiles

Docintake recognizes that children require enhanced protection with respect to their personal data. The Platform provides functionality allowing adult legal guardians to create and manage Child Dependent Profiles ("Child Profiles") strictly within the Guardian's registered account.

### 4.1 Nature of Child Profiles
A Child Profile is not an independent user account. A Child Profile:
- Does **NOT** have independent login credentials
- Does **NOT** collect or store a child's email address
- Does **NOT** collect or store a child's password
- Cannot access the Platform independently
- Is managed solely and exclusively by the verified adult Guardian

### 4.2 Information Collected for Child Profiles
Docintake collects only the minimum personal data necessary to establish a dependent profile and submit eligible applications:
- Child's full legal name (as printed on official identification)
- Child's date of birth (used to compute age classifications)
- Nature of the legal relationship to the Guardian (e.g., parent, legal guardian, authorized caregiver)
- Necessary nationality information
- Identity documents uploaded by the Guardian on behalf of the child (e.g., National ID card, Passport)
- Structured data extracted from uploaded documents
- Application status and routing records
- Guardian verification records and audit evidence
- Consent records, including timestamps, consent text hashes, and IP addresses

### 4.3 Age Classifications and Safeguards
The Platform enforces age-band-specific protections calculated automatically from the child's verified date of birth:

1. **Under 13 Years of Age:**
   - In accordance with Federal Decree-Law No. 26 of 2025, Article 7, processing of personal data for any child under 13 requires **explicit, documented, and verifiable parental or guardian consent**.
   - No application or document processing for an under-13 child profile can proceed without recorded explicit consent from the Guardian.
   - Enhanced safeguards apply to isolate and restrict access to under-13 data.

2. **Ages 13 to 17 (Inclusive):**
   - Personal data processing is safeguarded with strict access controls and purpose limitation.
   - Guardian consent remains required for dependent profile creation and document submission.

3. **Age 18 and Above (Age-18 Transition):**
   - Upon attaining eighteen (18) Gregorian years per Federal Decree-Law No. 25 of 2025, Article 84, the individual is no longer classified as a minor.
   - The dependent profile is suspended from automated child processing, and the adult individual is invited to establish an independent account.

### 4.4 Straightforward and Continuously Accessible Withdrawal Mechanism
The Guardian may withdraw consent for child profile processing at any time. The withdrawal mechanism:
- Is continuously accessible via the Platform interface
- Can be initiated with minimal operational friction
- Halts ongoing and future processing immediately upon submission
- Initiates the purge of unsubmitted staged files and unnecessary extracted data

---

## 5. Purposes of Processing (Child Profiles)

Personal data relating to Child Profiles is processed exclusively for the following defined purposes:

1. **Dependent Profile Management:** Establishing and administering the child's record within the Guardian's verified account.
2. **Eligible Application Submission:** Enabling the Guardian to prepare and submit applications for available public services that permit child applicants.
3. **Document Collection:** Ingesting and securely storing mandatory identity documents uploaded by the Guardian.
4. **AI-Assisted Field Extraction:** Extracting structured fields using local, on-premise vision-language models (Qwen2.5-VL 7B running on private infrastructure).
5. **Document Validation:** Verifying image legibility, document validity (ensuring non-expiry), and consistency across submitted documents.
6. **Human-Review Processing:** Escalating unreadable or conflicting documents to authorized internal human reviewers under strict confidentiality rules.
7. **Government-Agency Routing:** Transmitting verified application bundles to designated authorized government-body reviewers upon receipt of explicit, application-specific consent.
8. **Security and Statutory Audit:** Maintaining immutable audit logs of access, consent grants, consent withdrawals, and system operations to satisfy UAE regulatory compliance requirements.

---

## 6. Lawful Basis for Processing

Docintake processes personal data strictly in compliance with lawful grounds recognized under UAE law:

**6.1 General Processing (Adult Accounts):**  
Processing of adult user data is conducted pursuant to Article 4 of UAE Federal Decree-Law No. 45 of 2021 (PDPL), based upon:
- Performance of contract (providing Platform onboarding and intake services requested by the User);
- Compliance with legal and regulatory obligations; and
- Explicit consent where required.

**6.2 Child Personal Data (Dependent Profiles):**  
In accordance with Article 7 of UAE Federal Decree-Law No. 26 of 2025, the primary lawful basis for processing personal data belonging to children (particularly those under 13 years of age) is **explicit, documented, and verifiable consent** provided by the child's parent or authorized legal guardian.

---

## 7. Government Agency Access

Docintake operates as an onboarding intake and routing mechanism. Where applications are routed to external government bodies for statutory determination:

**7.1 Access Parameters:**
- Review access is strictly **service-specific, agency-specific, and application-specific**. A reviewer from one agency has no technical capability to view applications submitted to a different agency.
- Access requires affirmative, valid **Application-Specific Document Review Consent** (Consent Event C) executed by the Guardian prior to routing.
- All access by designated authorized government-body reviewers is authenticated, monitored, and permanently recorded in an immutable audit log.

**7.2 No Official Agency Endorsement:**  
Docintake does not claim or imply any official government partnership, exclusive government contract, statutory delegation, or regulatory certification unless independently verified and officially gazetted. Government reviewers access the Platform solely via designated secure review portals pursuant to specific service workflows.

---

## 8. Developer Document Access Restrictions

To maintain strict data confidentiality and fulfill statutory requirements under the PDPL:

**8.1 Separation of Duties:**  
Docintake enforces architectural and administrative separation between platform developers and sensitive customer records. Software engineers and developers **cannot view, download, or inspect real customer or child document binaries**.

**8.2 Permitted Developer Scope:**  
Developer access is strictly restricted to:
- Source code and application build scripts;
- Synthetically generated or anonymized test documents;
- Non-sensitive operational error logs stripped of personal identifiers;
- General system health metrics and hardware utilization statistics.

**8.3 Break-Glass Arrangements:**  
Any extraordinary technical access required for disaster recovery or critical system restoration requires multi-party authorization, is restricted to designated security personnel, and is recorded in immutable break-glass audit logs subject to independent compliance review.

---

## 9. On-Premise Storage Architecture

Docintake employs a private, on-premise infrastructure architecture to guarantee data sovereignty and eliminate unauthorized external disclosures:

- **Document Binaries:** Stored in private, locally deployed MinIO object storage within UAE-based physical infrastructure.
- **Structured Data:** Stored in a private, locally deployed PostgreSQL relational database with database-level tenant isolation.
- **AI Processing:** Field extraction is performed locally using the Qwen2.5-VL 7B vision-language model deployed via Ollama on local hardware.
- **Zero Public Cloud AI Transmission:** **No document images, text snippets, or personal data are ever transmitted to third-party public cloud AI providers, commercial LLM APIs, or external processing endpoints.**

---

## 10. Data Retention and Purging

**10.1 Configurable Retention Policy:**  
Personal data is retained only for the duration necessary to satisfy the specific purpose for which it was collected, subject to final legal retention schedules approved by UAE counsel.

**10.2 Child Data Limitation:**  
Children's personal data is retained for the minimum period legally required. Once an application reaches final status or is formally concluded, document binaries are scheduled for secure deletion in accordance with applicable retention schedules.

**10.3 Consent Decline & Staging Purge:**  
If a Guardian declines consent during profile creation or application submission, or if an onboarding session is abandoned, all staged temporary document binaries and uncommitted extracted data are automatically purged from system storage.

**10.4 Audit Metadata Preservation:**  
Where required or permitted by UAE law, non-sensitive audit metadata (such as timestamps of consent events, withdrawal logs, and transaction identifiers) is retained to provide verifiable legal evidence of regulatory compliance.

---

## 11. Data Security

Docintake implements robust technical and organizational security measures, including:
- AES-256 encryption at rest for stored document objects;
- TLS 1.3 encryption in transit for all communications;
- Cryptographic hashing (SHA-256) for document integrity verification and deduplication;
- Role-Based Access Control (RBAC) enforcing least-privilege principles;
- Automated session timeouts and rate limiting;
- Continuous vulnerability scanning and access monitoring.

---

## 12. Your Rights and Guardian Rights

Under UAE Federal Decree-Law No. 45 of 2021 (PDPL), adult users and legal guardians acting on behalf of children possess the following statutory rights:

- **Right of Access:** Obtain confirmation of whether personal data is being processed and receive a structured copy of that data.
- **Right to Rectification:** Request correction or completion of inaccurate or incomplete personal records.
- **Right to Erasure (Right to be Forgotten):** Request deletion of personal data where processing is no longer necessary or where consent has been lawfully withdrawn.
- **Right to Restriction of Processing:** Restrict further processing under specific statutory circumstances.
- **Right to Withdraw Consent:** Continuously accessible right to revoke previously granted consent without affecting the lawfulness of processing carried out prior to revocation.

To exercise any of these rights, contact our Data Protection representative at [PLACEHOLDER].

---

## 13. Children's Rights Under UAE Law

Docintake prioritizes the best interests of the child in all data processing operations:
- **Federal Decree-Law No. 26 of 2025:** Establishes specific statutory protections for children in digital environments, mandating verifiable parental authorization for children under 13 and prohibiting unfair commercial profiling or automated exploitation.
- **Federal Decree-Law No. 45 of 2021:** Ensures child data subjects are accorded the full scope of privacy protections, exercisable through their legally recognized parents or guardians.

---

## 14. Cookies and Technical Data

The Platform utilizes strictly necessary session cookies and security tokens required to authenticate users, protect sessions, and maintain state across multi-step document intake workflows. The Platform does not deploy third-party advertising cookies, cross-site trackers, or behavioral profiling scripts.

---

## 15. Contact Information

For inquiries, privacy concerns, or to exercise statutory data rights:
- **Data Protection Officer / Privacy Contact:** [PLACEHOLDER]
- **Customer Support:** [PLACEHOLDER]
- **Platform Provider:** Docintake
- **Address:** N/A, United Arab Emirates

---

## 16. Changes to This Privacy Policy

Docintake reserves the right to amend this Privacy Policy to reflect evolving regulatory requirements or platform enhancements. Material modifications will be communicated via prominent platform notifications. The version history and effective dates of all policy iterations are maintained for transparency.

---

## Document Information

| Field | Value |
|---|---|
| Document Title | Docintake Privacy Policy |
| Version | v1.1 |
| Status | DRAFT — PENDING LEGAL APPROVAL |
| Effective Date | Pending Legal Approval |
| Previous Version | v1.0 |
| Jurisdiction | United Arab Emirates (subject to final legal verification) |
| Company | Docintake |
| Registered Address | N/A |
| Customer Support | [PLACEHOLDER] |
| Privacy Contact | [PLACEHOLDER] |

---

*This document is a DRAFT. It has not been reviewed by qualified UAE legal counsel and is not legally binding until formally approved. All statutory references must be verified by a qualified legal professional.*
