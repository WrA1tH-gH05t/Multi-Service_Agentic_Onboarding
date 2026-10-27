# Document 4: Validation Agent Business Rules & Decision Justifications

**Project:** Moro Hub Multi-Service Document Intake & Verification System  
**Version:** 2.1 (Multi-Layered Security, Integrity & Cross-Validation)  
**Author:** AI Engineering & Architecture Team  
**Scope:** Business Rule Engine, Execution Gates, Inclusion & Exclusion Justifications

---

## Executive Summary

The **Validation Agent** acts as the automated gatekeeper of the Moro Hub document intake system. Its mission is to protect backend systems, prevent onboarding fraud, maintain legal compliance, and guarantee high data quality **before** any application reaches permanent storage or operational back-offices.

To avoid bloated validation logic that introduces false positives and frustrates legitimate users, the rules are organized into a **Strict Four-Tier Execution Ladder**:

```
[Tier 0: Structural Gate] ➔ [Tier 1: Malware & Safety] ➔ [Tier 2: Optical Quality] ➔ [Tier 3: Semantic Consistency]
```

---

## 1. The Active Business Rules Inventory

### Tier 0: File Structure & Container Integrity
1. **Rule 0.1: True MIME & Magic Byte Validation**
   * *Implementation:* Verified using `file_validation.py` content sniffing (inspecting `%PDF-` byte headers) rather than trusting client-supplied file extensions or MIME headers.
   * *Enforcement:* Instant HTTP 422 rejection. Non-PDF files uploaded as identity documents are refused.
2. **Rule 0.2: File Size Upper Bound (≤ 10 MB)**
   * *Implementation:* Stream length check terminates read operations exceeding 10,485,760 bytes.
   * *Enforcement:* HTTP 413 Payload Too Large.
3. **Rule 0.3: Document Page Count Enclosure (1 to 6 Pages)**
   * *Implementation:* PyMuPDF counts internal page trees.
   * *Enforcement:* Rejects files with > 6 pages.

### Tier 1: Active Content & Antivirus Safety Gates
4. **Rule 1.1: Zero-Tolerance Real-Time ClamAV Stream Scan**
   * *Implementation:* Real-time streaming over TCP socket (`127.0.0.1:3310`) via `zINSTREAM`.
   * *Enforcement:* Immediate rejection if virus signatures (EICAR, trojans, ransomware) are discovered. File bytes are discarded from memory.
5. **Rule 1.2: Active PDF Exploit & Embedded Object Ban**
   * *Implementation:* Deep structural scan of PDF dictionary objects for `/JavaScript`, `/JS`, `/Launch`, `/EmbeddedFiles`, and `/SubmitForm` hooks.
   * *Enforcement:* HTTP 422 rejection. Government onboarding documents must be static scans; active executable structures are treated as threat vectors.

### Tier 2: Physical Quality & Optical Readability Gates
6. **Rule 2.1: Laplacian Variance Blur Thresholding ($\sigma^2 \ge 100.0$)**
   * *Implementation:* Convolves rendered page images with OpenCV Laplacian kernel $\Delta = \frac{\partial^2}{\partial x^2} + \frac{\partial^2}{\partial y^2}$ and computes variance.
   * *Enforcement:* Rejection if variance falls below 100.0. Asks user for a flatter, higher-contrast, well-lit image.
7. **Rule 2.2: Two-Strike Human Escalation Policy**
   * *Implementation:* State manager tracks repeated failures per document slot (`failures[doc_type:reason]`).
   * *Enforcement:* If quality or blur checks fail twice consecutively, the system stops rejecting and routes the file to human review to prevent infinite re-upload loops.

### Tier 3: Semantic Integrity & Identity Cross-Validation
8. **Rule 3.1: Content-Hash Deduplication (SHA-256)**
   * *Implementation:* SHA-256 hash computed over file binary and cross-checked against existing user uploads.
   * *Enforcement:* If identical file is uploaded to the same slot, returns cached idempotent success. If uploaded to a *different* slot (e.g., uploading the same file as both National ID and Driving License), triggers duplicate conflict rejection.
9. **Rule 3.2: Applicant Name Cross-Match Verification**
   * *Implementation:* Normalized token-level fuzzy match comparing the applicant name provided during wizard initialization against the name extracted from the document:
     $$\text{MatchScore} = \text{TokenSetRatio}(\text{ApplicantName}, \text{ExtractedName}) \ge 85\%$$
   * *Enforcement:* Hard rejection on passport or driving license mismatch to prevent identity fraud or accidental upload of family member credentials.
10. **Rule 3.3: Mandatory Field Completeness Check**
    * *Implementation:* Enforces that all schema fields declared in `_MANDATORY[doc_kind]` are populated with non-whitespace values.
11. **Rule 3.4: Adversarial Prompt Injection Neutralization**
    * *Implementation:* All extracted string fields pass through heuristic regex scanners detecting LLM jailbreak sequences (`"ignore all instructions"`, `"system prompt"`, `"sudo"`).
    * *Enforcement:* Sanitizes malicious values to `[REDACTED_INJECTION_ATTEMPT]` while preserving benign metadata.

---

## 2. Business Justification: Why These Rules?

| Rule Category | Business & Regulatory Rationale |
|---|---|
| **Magic Bytes + ClamAV + No JS** | **Cybersecurity & Infrastructure Hardening:** Enterprise systems processing citizen uploads are frequent targets for PDF-embedded zero-day exploits. Sandboxing files via memory-only streaming before MinIO commits neutralizes malware risks before storage. |
| **Laplacian Blur Threshold** | **Operational Cost Optimization:** Passing unreadable images to human reviewers increases back-office overhead and delays processing. Automated blur detection prompts the customer to re-photograph the card immediately while they are active in the onboarding session. |
| **Applicant Name Cross-Matching** | **KYC / AML Fraud Prevention:** Mandated by regulatory frameworks (Central Bank / Telecommunications authorities). Guarantees that the session applicant is the legal owner of the submitted credential. |
| **Two-Strike Escalation** | **Customer Experience SLA Protection:** Edge-case documents (e.g., weathered or worn driving licenses) will never pass automated blur thresholds. Cutting off re-uploads after two attempts prevents customer frustration while maintaining a clear audit trail for manual review. |

---

## 3. Deliberate Exclusions: Why Were Other Rules Omitted?

To prevent unnecessary false rejections and customer drop-off, the following checks were evaluated and **deliberately excluded** from automated rejections:

### 1. Automated Rejection on Expired Credentials
* **Why Excluded:** While expiration dates are extracted and highlighted on the review dashboard, expired credentials are **not** automatically rejected at the intake gate.
* **Justification:** Multiple enterprise services support grace periods (e.g., UAE vehicle registration renewal allows license renewal within 30 days of expiry). In other scenarios, an expired driving license serves as valid secondary proof of identity when accompanied by an active Emirates ID. Rejecting the upload automatically prevents legitimate customers from completing onboarding; the decision is properly left to human review.

### 2. Country-of-Origin & Nationality Blacklists
* **Why Excluded:** The validation agent does not filter or reject based on issuing country or nationality.
* **Justification:** Service-level residency or nationality restrictions are commercial policy decisions, not document intake rules. The extraction engine supports multi-country documents (MIDV standards). Policy restrictions are applied downstream in core business systems.

### 3. Strict Cryptographic Signature Validation of Digital PDFs
* **Why Excluded:** Verifying Adobe CDS (Certified Document Services) or UAE Pass cryptographic digital signatures was omitted from the intake boundary.
* **Justification:** Over 85% of mobile onboarding users submit photographed physical plastic cards converted to PDF or direct smartphone camera captures. Enforcing cryptographic PKI signatures would reject almost all standard camera uploads. Optical authenticity checks are used instead.
