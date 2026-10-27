# Moro Hub Multi-Service Document Intake & Verification System
## Comprehensive Master Technical Documentation (v2.1)

---

### Executive Overview & Index of Technical Specifications

This documentation consolidates the complete architectural, algorithmic, operational, and policy documentation for the **Moro Hub Document Intake Platform**. The system provides end-to-end customer onboarding, dynamic catalog routing, multimodal Vision AI field extraction, ClamAV antivirus stream scanning, and robust session persistence.

The technical documentation is organized into five standalone modules:

1. [**Document 1: Tool & Framework Selection and Architectural Roles**](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/docs/01_TOOL_AND_FRAMEWORK_SELECTION.md)
   * Detailed rationale for FastAPI, React 18 (Zero-Build CDN), Ollama + Qwen2.5-VL Multimodal Vision AI, PyMuPDF (`pymupdf`), ClamAV TCP stream scanning, MinIO S3-compliant storage, and PostgreSQL/PersistentUserStore dual persistence.
2. [**Document 2: Dynamic Routing Approach & Full-Catalog Scalability**](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/docs/02_ROUTING_AND_CATALOG_SCALABILITY.md)
   * The declarative Service Catalog engine, dynamic requirement resolution, polymorphic document kind classification, and zero-hardcoding scaling to 15+ services.
3. [**Document 3: Vision Extraction Pipeline & Golden Dataset Verification**](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/docs/03_EXTRACTION_AND_GOLDEN_DATASET.md)
   * The 11-field driving license extraction specification (primary key `license_no`, reverse transmission type, spectacles/glasses restriction logo), canonicalization mapping, and benchmark verification against the Golden Dataset.
4. [**Document 4: Validation Agent Business Rules & Decision Justifications**](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/docs/04_VALIDATION_RULES_AND_RATIONALE.md)
   * The four-tier execution ladder (structural integrity, malware/anti-exploit, Laplacian blur variance $\ge 100$, applicant name fuzzy cross-matching, prompt injection defenses), plus rationale for deliberate exclusions.
5. [**Document 5: Human Review Confidence Thresholds & Automated Escalation Policy**](file:///c:/Users/arvin/Desktop/Work%20and%20Uni/Work/task%201/docs/05_HUMAN_REVIEW_THRESHOLDS.md)
   * Mathematical scoring formula, operational workflows for Tier 1 (<50% reject), Tier 2 (51%–79% human review), and Tier 3 ($\ge 80\%$ straight-through auto-approval).

---

### Summary of System Enhancements (v2.1)

* **Sign-Up & Authentication Overhaul:** Fixed black-screen crashes caused by unhandled validation arrays; integrated full Email, Username, and Password account creation; auto-authenticates upon registration and routes directly to the main interface.
* **Full 11-Field Driving License Extraction:** Expanded `DRIVING_LICENSE_SCHEMA` to extract `license_no` (primary key), `name`, `nationality`, `date_of_birth`, `issue_date`, `place_of_issue`, `expiry_date`, `licensing_authority`, `traffic_code_no`, `gear_type` (Automatic vs Manual), and `glasses_requirement` (vision condition logo detection).
* **Live Inspection & ClamAV Feedback:** Replaced generic "Checking" messages with step-by-step diagnostic feedback (malware scanning via ClamAV socket, PDF integrity check, field-by-field verification, and real confidence score calculation).
* **Calibrated Threshold Routing:** Strictly enforces `<50%` reject with guidance, `51%–79%` human review tagging, and `$\ge 80\%$` auto-approval.
* **100% Restart Persistence:** Fixed session token and application resets across server restarts by implementing startup session re-hydration in `services/auth.py` and direct database querying in `app/routes/applications.py`.
* **PyMuPDF Modernization:** Completely replaced deprecated `fitz` imports with `import pymupdf as fitz` across the entire codebase, eliminating startup warnings.
