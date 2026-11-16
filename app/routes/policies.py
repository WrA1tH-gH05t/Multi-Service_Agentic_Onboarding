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

TERMS_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf")
PRIVACY_PDF_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "Docintake_Privacy_Policy_v1.0_DRAFT.pdf")


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
                return {"success": True, "data": [d.to_dict() for d in docs]}
        except Exception as e:
            pass
    return {
        "success": True,
        "data": [
            {
                "policy_id": "terms_and_conditions",
                "title": "Docintake Terms & Conditions and Service Policy",
                "version": "1.0",
                "status": "DRAFT — PENDING LEGAL APPROVAL",
                "pdf_filename": "Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf"
            },
            {
                "policy_id": "privacy_policy",
                "title": "Docintake Privacy Policy and Data Protection Framework",
                "version": "1.0",
                "status": "DRAFT — PENDING LEGAL APPROVAL",
                "pdf_filename": "Docintake_Privacy_Policy_v1.0_DRAFT.pdf"
            }
        ]
    }


@router.get("/policies/terms/download")
@router.get("/policies/terms/pdf")
async def download_terms_pdf():
    """Serve the official Terms & Conditions PDF document for view/download."""
    if os.path.exists(TERMS_PDF_PATH):
        return FileResponse(
            path=TERMS_PDF_PATH,
            filename="Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf",
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf"'}
        )
    raise HTTPException(status_code=404, detail="Terms & Conditions PDF not found")


@router.get("/policies/privacy/download")
@router.get("/policies/privacy/pdf")
async def download_privacy_pdf():
    """Serve the official Privacy Policy PDF document for view/download."""
    if os.path.exists(PRIVACY_PDF_PATH):
        return FileResponse(
            path=PRIVACY_PDF_PATH,
            filename="Docintake_Privacy_Policy_v1.0_DRAFT.pdf",
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="Docintake_Privacy_Policy_v1.0_DRAFT.pdf"'}
        )
    raise HTTPException(status_code=404, detail="Privacy Policy PDF not found")


@router.get("/policies/terms", response_class=HTMLResponse)
async def view_terms_html():
    """Render the official in-app Terms & Conditions and Service Policy HTML view."""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Docintake - Terms & Conditions and Service Policy (v1.0 DRAFT)</title>
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
    <div class="badge">DRAFT — PENDING UAE LEGAL APPROVAL</div>
  </div>

  <a href="/api/v1/policies/terms/download" class="btn-download">📄 Download Official PDF (v1.0 DRAFT)</a>

  <table class="meta-table">
    <tr><th>Company Name</th><td>Docintake</td><th>Jurisdiction</th><td>United Arab Emirates</td></tr>
    <tr><th>Registered Address</th><td>N/A</td><th>Document Status</th><td>DRAFT — PENDING LEGAL APPROVAL</td></tr>
    <tr><th>Policy Version</th><td>1.0</td><th>Effective Date</th><td>Pending Approval</td></tr>
    <tr><th>Customer Support</th><td>[SUPPORT EMAIL PLACEHOLDER]</td><th>Privacy Contact</th><td>[PRIVACY CONTACT PLACEHOLDER]</td></tr>
  </table>

  <div class="note">
    <strong>LEGAL NOTICE:</strong> This policy document is a formal technical draft prepared for the Docintake onboarding system. Prior to public promulgation or enforceability, this policy requires formal review and sign-off by qualified legal counsel licensed within the United Arab Emirates.
  </div>

  <h2>1. Introduction and Acceptance</h2>
  <p>Welcome to Docintake. By accessing, browsing, registering an account, or submitting documents through Docintake, you agree to be bound by these Terms & Conditions. If you do not agree, you must immediately discontinue use of the platform.</p>

  <h2>2. Company Identification</h2>
  <p>Docintake operates this platform within the United Arab Emirates. The company's registered address is N/A. Inquiries may be addressed to [SUPPORT EMAIL PLACEHOLDER].</p>

  <h2>3. Platform Purpose & Limitations</h2>
  <p>Docintake provides conversational guidance, structured document intake, optical and vision extraction, and completeness validation. Docintake does not conduct independent external government identity verification or database reconciliation unless an authorized integration exists. Automated extraction and validation completeness do not constitute government approval.</p>

  <h2>4. Active Services Catalogue</h2>
  <p><strong>1. Basic Registration:</strong> Requires one valid National ID card. (1-2 business days).<br>
  <strong>2. Premium / Cross Border:</strong> Requires BOTH a valid National ID card AND a valid Passport. Both documents must arrive before the application is complete. (3-5 business days).<br>
  <strong>3. Mobility / Rental:</strong> Requires an official Driving Licence. Uses dedicated licence extraction. (Same day).</p>

  <h2>5. Coming Soon Services</h2>
  <p>Services marked 'Coming Soon' in the directory (bank account, insurance, loans, utility, tenancy, etc.) are demonstrations and cannot accept live submissions.</p>

  <h2>6. Account Creation & Mandatory Terms Acceptance</h2>
  <p>Applicants must register an account and actively accept these Terms & Conditions via an unchecked checkbox. Credentials must remain confidential.</p>

  <h2>7. AI-Powered Extraction Disclaimer</h2>
  <p>Extraction results are generated via on-premise vision models. NO EXTRACTION RESULT IS GUARANTEED TO BE ERROR-FREE. Applicants must review and confirm extracted values.</p>

  <h2>8. Human Review Escalation</h2>
  <p>Applications with unreadable zones or confidence flags are escalated to authorized human reviewers.</p>

  <h2>9. Data Protection & On-Premise Storage</h2>
  <p>Customer documents remain strictly within on-premise MinIO storage and PostgreSQL. Documents are never transmitted to public third-party AI APIs.</p>

  <h2>10. Strict Developer Document Access Restrictions</h2>
  <p>Application developers are strictly prohibited from viewing or accessing customer document contents.</p>

  <h2>11. Governing Law & UAE Legal Review</h2>
  <p>Governed by the laws of the United Arab Emirates, subject to UAE legal counsel review.</p>
</div>
</body>
</html>
""")


@router.get("/policies/privacy", response_class=HTMLResponse)
async def view_privacy_html():
    """Render the official in-app Privacy Policy HTML view."""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Docintake - Privacy Policy and Data Protection Framework (v1.0 DRAFT)</title>
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
    <div style="font-size: 1.1rem; color: #93c5fd;">Privacy Policy and Data Protection Framework</div>
    <div style="font-size: 0.85rem; color: #d1d5db; margin-top: 4px;">Multi-Service Agentic Onboarding Platform Policy</div>
    <div class="badge">DRAFT — PENDING UAE LEGAL APPROVAL</div>
  </div>

  <a href="/api/v1/policies/privacy/download" class="btn-download">📄 Download Official PDF (v1.0 DRAFT)</a>

  <table class="meta-table">
    <tr><th>Company Name</th><td>Docintake</td><th>Jurisdiction</th><td>United Arab Emirates</td></tr>
    <tr><th>Registered Address</th><td>N/A</td><th>Document Status</th><td>DRAFT — PENDING LEGAL APPROVAL</td></tr>
    <tr><th>Policy Version</th><td>1.0</td><th>Effective Date</th><td>Pending Approval</td></tr>
    <tr><th>Customer Support</th><td>[SUPPORT EMAIL PLACEHOLDER]</td><th>Privacy Contact</th><td>[PRIVACY CONTACT PLACEHOLDER]</td></tr>
  </table>

  <div class="note">
    <strong>STATUTORY NOTICE:</strong> This policy reflects Docintake's technical architecture (on-premise storage, developer document exclusion, application-specific consent). Applicability of UAE Federal Decree-Law No. 45 of 2021 (PDPL) and public-sector exclusions must be reviewed by qualified UAE legal counsel.
  </div>

  <h2>1. Information Collected</h2>
  <p>Docintake collects only necessary data: account details, submitted document binaries (National ID, Passport, Driving Licence), extracted identity fields, application status records, consent audit trails, and document access logs.</p>

  <h2>2. Purpose of Processing</h2>
  <p>Data is processed strictly for account management, service onboarding, document intake, field extraction, validation, authorized government-agency inspection, and security audit.</p>

  <h2>3. On-Premise Storage Architecture</h2>
  <p>All document binaries remain strictly within on-premise MinIO storage. Structured information is stored in PostgreSQL. Document binaries are NEVER transmitted to third-party public cloud AI providers.</p>

  <h2>4. Authorized Government-Agency Review Access</h2>
  <p>Applications requiring agency review (e.g. Mobility / Rental routed to designated mobility reviewers such as RTA if confirmed; Basic Registration to identity reviewers; Premium to cross-border reviewers) are accessible ONLY to authorized reviewers of that specific agency. Cross-agency access is strictly prohibited. Every document view is recorded in an immutable audit trail.</p>

  <h2>5. Developer Document Access Restrictions</h2>
  <p>Platform developers are strictly restricted from viewing or downloading customer document contents. Developers only access source code, non-sensitive logs, metrics, and synthetic test suites. No developer bypass exists.</p>

  <h2>6. Data Retention & Consent Staging</h2>
  <p>Uploaded documents reside in a temporary staging area before consent. Upon explicit consent, documents are persisted. If consent is declined, temporary document binaries and sensitive extractions are purged immediately. Final retention periods remain configurable and subject to legal counsel approval.</p>

  <h2>7. Consent & Withdrawal Rights</h2>
  <p>Each application requires independent Document Review Consent. Applicants may decline consent (closing the application and purging staged files) or withdraw consent, halting future processing in accordance with UAE legal standards.</p>

  <h2>8. Privacy Requests</h2>
  <p>For data protection requests, contact: <strong>[PRIVACY CONTACT PLACEHOLDER]</strong>.</p>
</div>
</body>
</html>
""")
