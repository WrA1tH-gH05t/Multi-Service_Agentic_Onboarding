# Docintake Legal Review & Statutory Compliance Checklist (UAE Jurisdiction)

**Status:** DRAFT — PENDING FORMAL QUALIFIED UAE LEGAL COUNSEL REVIEW  
**Policy Version:** 1.0  
**Effective Date:** Pending Approval  
**Platform Owner:** Docintake  
**Jurisdiction:** United Arab Emirates (Federal, Emirate-level, and Sector-specific scopes)

---

## 1. Corporate Identity and Statutory Status Disclosures
- [ ] **Company Identification:** Verify the legal operating entity designation for Docintake under UAE corporate law (Mainland vs Free-Zone).
- [ ] **Registered Address:** Replace current placeholder `N/A` with the authorized registered office address upon formal licensing.
- [ ] **Contact Channels:** Replace `[SUPPORT EMAIL PLACEHOLDER]` and `[PRIVACY CONTACT PLACEHOLDER]` with monitored official channels.
- [ ] **Regulatory Representations:** Ensure no implied representation of official government status, agency ownership, or unverified government partnerships exists in public materials.

---

## 2. Applicability of UAE Federal Decree-Law No. 45 of 2021 (PDPL)
- [ ] **Scope and Government Exclusions (Article 2):**  
  Assess whether and to what extent participating government entities (such as Road and Transport Authorities, Identity Authorities) fall within public sector exceptions or separate governmental data frameworks under Article 2(2).
- [ ] **Controller vs Processor Boundaries (Articles 7 & 8):**  
  Confirm whether Docintake operates strictly as a Data Processor on behalf of the designated inspecting government bodies (who act as Controllers), or as an independent Data Controller for customer onboarding accounts.
- [ ] **Lawful Processing Grounds (Article 4):**  
  Review the dual grounds relied upon: explicit consent for sensitive document review vs contractual necessity for account onboarding administration.
- [ ] **Data Minimization and Purpose Limitation (Article 5):**  
  Validate that document intake is strictly limited to mandatory items (National ID for Basic Registration, National ID + Passport for Premium Cross-Border, Driving Licence for Mobility Rental) without extraneous document collection.
- [ ] **Consent and Revocation Standards (Article 6):**  
  Review the application-specific consent mechanism (`DOCUMENT REVIEW CONSENT`) and verify the statutory compliance of the consent withdrawal right. Confirm that withdrawal correctly halts optional future processing while preserving minimal audit trails for statutory dispute periods.

---

## 3. Government Review Access & Inter-Agency Compartmentalization
- [ ] **Agency Routing Validation:**  
  Confirm statutory and operational boundaries for each designated agency (Identity Authority, Cross-Border Inspection, RTA Mobility branch).
- [ ] **Inter-Agency Boundary Enforcement:**  
  Verify that role-based restrictions preventing reviewers of Agency A from accessing applications of Agency B are legally sufficient under UAE government data sharing protocols.
- [ ] **Audit Trail Integrity:**  
  Confirm that immutable recording of every document view (`document_access_audits` table) meets UAE evidentiary requirements under Federal Decree-Law No. 46 of 2021 on Electronic Transactions and Trust Services.

---

## 4. Developer Access Exclusion & On-Premise Infrastructure
- [ ] **Developer Customer Data Exclusion:**  
  Confirm enforceability of strict security policies preventing software developers and infrastructure engineers from viewing customer document binaries.
- [ ] **Data Localization:**  
  Validate private on-premise storage architecture (MinIO & PostgreSQL within UAE infrastructure) against national data residency standards and cloud computing regulatory frameworks.
- [ ] **Zero Public AI Leakage:**  
  Verify compliance of strictly local, on-premise AI extraction ladders without third-party public AI transmission.

---

## 5. Retention, Staging Cleanup, and Deletion Policy
- [ ] **Pre-Consent Staging Cleanup:**  
  Approve the automatic purging of document binaries upon consent decline or session expiration.
- [ ] **Post-Consent Retention Schedule:**  
  Establish statutory retention duration for accepted applications in consultation with participating government authorities and legal counsel.
