"""Policy routes — Terms & Conditions, Privacy Policy, in-app HTML views and PDF downloads."""

import os
import hashlib
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, FileResponse

router = APIRouter()

def get_state():
    from app.main import app_state
    return app_state

TERMS_V11_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Terms_and_Conditions_v1.1_DRAFT.pdf")
TERMS_V10_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf")
PRIVACY_V11_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Privacy_Policy_v1.1_DRAFT.pdf")
PRIVACY_V10_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Privacy_Policy_v1.0_DRAFT.pdf")

TERMS_PDF_PATH = TERMS_V11_PDF_PATH if os.path.exists(TERMS_V11_PDF_PATH) else TERMS_V10_PDF_PATH
PRIVACY_PDF_PATH = PRIVACY_V11_PDF_PATH if os.path.exists(PRIVACY_V11_PDF_PATH) else PRIVACY_V10_PDF_PATH


@router.get("/policies")
async def list_policies():
    """List available legal policy documents and metadata."""
    state = get_state()
    db = state.get("database")
    if db:
        try:
            with db.session_scope() as session:
                from services.database import PolicyDocument
                docs = session.query(PolicyDocument).all()
                if docs:
                    return {"success": True, "data": [d.to_dict() for d in docs]}
        except Exception as e:
            pass
    return {
        "success": True,
        "data": [
            {
                "policy_id": "terms_and_conditions",
                "title": "Docintake Terms & Conditions and Service Policy",
                "version": "1.1",
                "status": "DRAFT — PENDING LEGAL APPROVAL",
                "pdf_filename": "Docintake_Terms_and_Conditions_v1.1_DRAFT.pdf"
            },
            {
                "policy_id": "privacy_policy",
                "title": "Docintake Privacy Policy and Data Protection Framework",
                "version": "1.1",
                "status": "DRAFT — PENDING LEGAL APPROVAL",
                "pdf_filename": "Docintake_Privacy_Policy_v1.1_DRAFT.pdf"
            }
        ]
    }


@router.get("/policies/terms/download")
@router.get("/policies/terms/pdf")
async def download_terms_pdf():
    """Serve the official Terms & Conditions PDF document for view/download."""
    target_path = TERMS_V11_PDF_PATH if os.path.exists(TERMS_V11_PDF_PATH) else TERMS_V10_PDF_PATH
    display_filename = "DocIntake_Terms_and_Conditions_v1.1_DRAFT.pdf"
    if os.path.exists(target_path):
        return FileResponse(
            path=target_path,
            filename=display_filename,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{display_filename}"'}
        )
    raise HTTPException(status_code=404, detail="Terms & Conditions PDF not found")


@router.get("/policies/privacy/download")
@router.get("/policies/privacy/pdf")
async def download_privacy_pdf():
    """Serve the official Privacy Policy PDF document for view/download."""
    target_path = PRIVACY_V11_PDF_PATH if os.path.exists(PRIVACY_V11_PDF_PATH) else PRIVACY_V10_PDF_PATH
    display_filename = "DocIntake_Privacy_Policy_v1.1_DRAFT.pdf"
    if os.path.exists(target_path):
        return FileResponse(
            path=target_path,
            filename=display_filename,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{display_filename}"'}
        )
    raise HTTPException(status_code=404, detail="Privacy Policy PDF not found")


@router.get("/policies/terms", response_class=HTMLResponse)
async def view_terms_html():
    """Render the official in-app Terms & Conditions and Service Policy HTML view (v1.1 DRAFT)."""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Docintake - Terms & Conditions and Service Policy (v1.1 DRAFT)</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1f2937; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f9fafb; }
  .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
  .header-box { background: #18202f; color: #ffffff; padding: 24px; border-radius: 6px; margin-bottom: 24px; }
  .badge { display: inline-block; background: #fef3c7; color: #92400e; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; margin-top: 8px; }
  .meta-table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 0.9rem; }
  .meta-table th, .meta-table td { border: 1px solid #e5e7eb; padding: 8px 12px; }
  .meta-table th { background: #f3f4f6; text-align: left; width: 25%; font-weight: 600; }
  h2 { color: #1e3a8a; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; margin-top: 28px; font-size: 1.25rem; }
  .note { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 16px 0; font-size: 0.9rem; color: #b45309; }
  .btn-download { display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 500; font-size: 0.9rem; margin-bottom: 20px; }
  .btn-download:hover { background: #1d4ed8; }
</style>
</head>
<body>
<div class="card">
  <div class="header-box">
    <h1 style="margin:0 0 8px 0; font-size: 1.8rem;">DOCINTAKE</h1>
    <div style="font-size: 1.1rem; color: #93c5fd;">Terms & Conditions and Service Policy</div>
    <div style="font-size: 0.85rem; color: #d1d5db; margin-top: 4px;">Multi-Service Agentic Onboarding Platform Policy</div>
    <div class="badge">DRAFT — PENDING UAE LEGAL APPROVAL • v1.1</div>
  </div>

  <a href="/api/v1/policies/terms/download" class="btn-download">📄 Download Official PDF (v1.1 DRAFT)</a>

  <table class="meta-table">
    <tr><th>Company Name</th><td>Docintake</td><th>Jurisdiction</th><td>United Arab Emirates</td></tr>
    <tr><th>Registered Address</th><td>N/A</td><th>Document Status</th><td>DRAFT — PENDING LEGAL APPROVAL</td></tr>
    <tr><th>Policy Version</th><td>1.1</td><th>Effective Date</th><td>Pending Legal Approval</td></tr>
    <tr><th>Customer Support</th><td>[SUPPORT EMAIL PLACEHOLDER]</td><th>Privacy Contact</th><td>[PRIVACY CONTACT PLACEHOLDER]</td></tr>
  </table>

  <div class="note">
    <strong>LEGAL NOTICE:</strong> This policy document is a formal technical draft prepared for the Docintake onboarding system. Prior to public promulgation or enforceability, this policy requires formal review and sign-off by qualified legal counsel licensed within the United Arab Emirates.
  </div>

  <h2>1. Scope, Applicability & Parent/Guardian Accounts</h2>
  <p>These Terms govern Docintake ("Platform", "we", "us", or "our"), an agentic document intake and verification platform operating within the United Arab Emirates. These Terms govern primary adult accounts, parent/guardian management of child dependent profiles, application processing, document handling, and review by designated government review authorities.</p>

  <h2>2. Legal Capacity and Guardian Eligibility (Article 84)</h2>
  <p>Under Article 84 of UAE Federal Decree-Law No. 25 of 2025 (Civil Transactions Law), full legal majority is attained at 18 Gregorian years. To register an account or create a child dependent profile, you represent and warrant that you are at least 18 Gregorian years old, possess full civil legal capacity, and are the parent or legally authorized caregiver/guardian of any minor child whose profile you manage.</p>

  <h2>3. Child Dependent Profiles & Profile Creation</h2>
  <p>Child Dependent Profiles are dependent identity records linked exclusively to the parent or guardian's primary account. Minors do not hold independent login accounts, passwords, or autonomous sessions. Guardians may create child profiles via the Accounts Section or via the AI Assistant, providing the child's full legal name, date of birth, relationship, and nationality.</p>

  <h2>4. Child-Data Protection and Article 7 Consent</h2>
  <p>In compliance with Article 7 of UAE Federal Decree-Law No. 26 of 2025 (Child Digital Safety), processing personal data of children under 13 requires explicit, verifiable parental consent. Consent may be revoked at any time via the Child Profiles management area, whereupon data processing for that child immediately ceases.</p>

  <h2>5. Active Services Catalogue, SLAs & Demonstrator Services</h2>
  <p>Docintake operates three (3) active services: <strong>Basic Registration</strong> (National ID, 1–2 business days), <strong>Premium / Cross Border</strong> (National ID + Passport, 3–5 business days), and <strong>Mobility / Rental</strong> (Driving Licence, Same-day/2–4 hours; restricted to adults 18+). Stated processing times represent operational estimates. Additional services marked "Coming Soon" (Bank Account, Insurance, SIM, Loan, Utility, Tenancy, Professional Licence, Vehicle Registration) are demonstrator listings that cannot accept live submissions.</p>

  <h2>6. Document Ingestion, Expiration & Automatic Purge Policy</h2>
  <p>Accepted document formats include PDF, PNG, JPEG, and TIFF. All files undergo strict MIME magic byte validation, ClamAV antivirus scanning, and active-content PDF structural inspection. All submitted documents must be valid and unexpired; expired documents will fail automated validation, alert the user, and trigger automatic deletion of expired binaries and records from storage and the database.</p>

  <h2>7. AI-Assisted Extraction & Automated Validation</h2>
  <p>Document field extraction is performed locally using on-premise vision models (Qwen2.5-VL via Ollama) without external cloud APIs. Algorithmic extraction does not guarantee error-free results; users must review and confirm extracted data in-app. Deterministic validation checks mandatory field presence, checksums, date consistency, and cross-document identity consistency (ID vs Passport).</p>

  <h2>8. Human Review Procedures</h2>
  <p>Applications encountering edge-case discrepancies, unreadable zones, or confidence scores requiring clarification are routed to an authorized Human Review queue under role-based access control and supervisory audit logging.</p>

  <h2>9. Application-Specific Document Review Consent</h2>
  <p>Prior to routing any application to designated UAE government reviewing authorities, separate, application-specific consent must be provided. If declined or withdrawn, the application is halted and staged document binaries are purged in accordance with data minimization.</p>

  <h2>10. Government Review & Developer Access Restrictions</h2>
  <p>Submitted applications are transferred exclusively to authorized UAE government review bodies on a service-specific, agency-specific, and application-specific basis. Docintake software engineers and platform developers are subject to a strict Zero Routine Access Policy, preventing inspection of unmasked customer or child dependent documents.</p>

  <h2>11. Prohibited Platform Activities</h2>
  <p>Users may not upload fraudulent or altered documents, attempt prompt injection, jailbreaking, or adversarial subversion against the AI model, bypass security checks, or upload synthetic/manipulated PDFs.</p>

  <h2>12. Limitation of Scope, Liability & UAE Governing Law</h2>
  <p>Docintake operates as an intake and routing gateway; a status of "Complete" indicates document ingestion completeness only and does not constitute government regulatory certification or approval. These Terms are governed exclusively by UAE federal law, subject to final review and sign-off by qualified UAE legal counsel.</p>
</div>
</body>
</html>
""")


@router.get("/policies/privacy", response_class=HTMLResponse)
async def view_privacy_html():
    """Render the official in-app Privacy Policy HTML view (v1.1 DRAFT)."""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Docintake - Privacy Policy & Data Protection Framework (v1.1 DRAFT)</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1f2937; max-width: 900px; margin: 40px auto; padding: 0 20px; background: #f9fafb; }
  .card { background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 32px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
  .header-box { background: #18202f; color: #ffffff; padding: 24px; border-radius: 6px; margin-bottom: 24px; }
  .badge { display: inline-block; background: #fef3c7; color: #92400e; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 0.8rem; margin-top: 8px; }
  .meta-table { width: 100%; border-collapse: collapse; margin-bottom: 24px; font-size: 0.9rem; }
  .meta-table th, .meta-table td { border: 1px solid #e5e7eb; padding: 8px 12px; }
  .meta-table th { background: #f3f4f6; text-align: left; width: 25%; font-weight: 600; }
  h2 { color: #1e3a8a; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; margin-top: 28px; font-size: 1.25rem; }
  .note { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px 16px; margin: 16px 0; font-size: 0.9rem; color: #b45309; }
  .btn-download { display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; padding: 10px 18px; border-radius: 6px; font-weight: 500; font-size: 0.9rem; margin-bottom: 20px; }
  .btn-download:hover { background: #1d4ed8; }
</style>
</head>
<body>
<div class="card">
  <div class="header-box">
    <h1 style="margin:0 0 8px 0; font-size: 1.8rem;">DOCINTAKE</h1>
    <div style="font-size: 1.1rem; color: #93c5fd;">Privacy Policy & Data Protection Framework</div>
    <div style="font-size: 0.85rem; color: #d1d5db; margin-top: 4px;">Parent/Guardian Accounts & Child Dependent Data Protection</div>
    <div class="badge">DRAFT — PENDING UAE LEGAL APPROVAL • v1.1</div>
  </div>

  <a href="/api/v1/policies/privacy/download" class="btn-download">📄 Download Official PDF (v1.1 DRAFT)</a>

  <table class="meta-table">
    <tr><th>Company Name</th><td>Docintake</td><th>Jurisdiction</th><td>United Arab Emirates</td></tr>
    <tr><th>Registered Address</th><td>N/A</td><th>Document Status</th><td>DRAFT — PENDING LEGAL APPROVAL</td></tr>
    <tr><th>Policy Version</th><td>1.1</td><th>Effective Date</th><td>Pending Legal Approval</td></tr>
    <tr><th>Customer Support</th><td>[SUPPORT EMAIL PLACEHOLDER]</td><th>Privacy Contact</th><td>[PRIVACY CONTACT PLACEHOLDER]</td></tr>
  </table>

  <div class="note">
    <strong>LEGAL NOTICE:</strong> This Privacy Policy is a technical draft prepared for the Docintake onboarding system. Prior to formal promulgation, this document requires formal sign-off by qualified legal counsel licensed within the United Arab Emirates.
  </div>

  <h2>1. Scope & Legal Authority</h2>
  <p>Docintake processes personal information under UAE Federal Decree-Law No. 45 of 2021 (Personal Data Protection Law), Federal Decree-Law No. 25 of 2025 (Civil Transactions Law, Article 84 on majority at 18 Gregorian years), and Federal Decree-Law No. 26 of 2025 (Child Digital Safety, Article 7 on verifiable parental consent).</p>

  <h2>2. Age Classification</h2>
  <p>Docintake classifies dependent data into three categories: (a) Children Under 13: requires mandatory Article 7 verifiable guardian consent; (b) Minors 13 to 17: guardian-managed onboarding with age-appropriate privacy safeguards; (c) Adults 18 and Above: independent account holders with full legal capacity.</p>

  <h2>3. On-Premises Storage & Technical Isolation</h2>
  <p>All document binaries reside in secure, self-hosted on-premises MinIO storage encrypted with AES-256. Structured records reside in PostgreSQL/SQLite. Zero document binaries or child personal data are transmitted to public third-party AI APIs.</p>

  <h2>4. Zero Developer Access & Government Review Access</h2>
  <p>Platform developers and technical operators are strictly blocked from accessing unmasked document binaries or child PII. Documents are routed exclusively to designated UAE government reviewing authorities based on explicit, application-specific review consent.</p>

  <h2>5. Guardian Rights and Consent Revocation</h2>
  <p>Guardians may withdraw consent at any time via the Child Profiles interface. Upon withdrawal, active processing ceases immediately and staged documents associated with drafts are deleted.</p>
</div>
</body>
</html>
""")
