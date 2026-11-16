"""Script to generate professional legal drafts:
1. Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf
2. Docintake_Privacy_Policy_v1.0_DRAFT.pdf
"""

import os
import hashlib
from fpdf import FPDF
from fpdf.enums import XPos, YPos

def clean_ascii(text: str) -> str:
    """Normalize unicode characters to ASCII/Latin-1 compatible equivalents."""
    replacements = {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "•": "*",
        "…": "...",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text

class PolicyPDF(FPDF):
    def __init__(self, doc_title: str, doc_subtitle: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = clean_ascii(doc_title)
        self.doc_subtitle = clean_ascii(doc_subtitle)
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        if self.page_no() == 1:
            return  # Cover / title block handled separately on page 1
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, f"DOCINTAKE  |  {self.doc_title.upper()} (v1.0 DRAFT)", border=0, align="L")
        self.ln(4)
        self.set_draw_color(210, 210, 210)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(6)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.set_draw_color(210, 210, 210)
        self.set_line_width(0.3)
        self.line(10, self.get_y() - 2, 200, self.get_y() - 2)
        notice = "DRAFT - PENDING UAE LEGAL APPROVAL | Confidential & Proprietary to Docintake"
        self.cell(140, 10, notice, border=0, align="L")
        self.cell(50, 10, f"Page {self.page_no()}/{{nb}}", border=0, align="R")

    def render_title_block(self):
        self.set_fill_color(24, 32, 47) # Dark slate
        self.rect(10, 12, 190, 48, "F")
        
        self.set_xy(15, 16)
        self.set_font("Helvetica", "B", 18)
        self.set_text_color(255, 255, 255)
        self.cell(0, 9, "DOCINTAKE", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_x(15)
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(147, 197, 253) # Soft blue
        self.cell(0, 8, self.doc_title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_x(15)
        self.set_font("Helvetica", "", 9)
        self.set_text_color(209, 213, 219)
        self.cell(0, 6, self.doc_subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

        self.set_xy(10, 63)
        # Metadata Table
        self.set_font("Helvetica", "B", 8)
        self.set_text_color(70, 70, 70)
        self.set_fill_color(243, 244, 246)
        
        meta = [
            ("Company Name:", "Docintake", "Jurisdiction:", "United Arab Emirates"),
            ("Registered Address:", "N/A", "Status:", "DRAFT - PENDING LEGAL APPROVAL"),
            ("Policy Version:", "1.0", "Effective Date:", "Pending Approval"),
            ("Customer Support:", "[SUPPORT EMAIL PLACEHOLDER]", "Privacy Contact:", "[PRIVACY CONTACT PLACEHOLDER]")
        ]
        for row in meta:
            self.set_font("Helvetica", "B", 8)
            self.cell(32, 6, f" {row[0]}", border=1, fill=True)
            self.set_font("Helvetica", "", 8)
            self.cell(63, 6, f" {row[1]}", border=1)
            self.set_font("Helvetica", "B", 8)
            self.cell(32, 6, f" {row[2]}", border=1, fill=True)
            self.set_font("Helvetica", "", 8)
            self.cell(63, 6, f" {row[3]}", border=1)
            self.ln(6)
        self.ln(4)

    def section_heading(self, num_str: str, title: str):
        self.ln(3)
        self.set_fill_color(238, 242, 255) # very light indigo
        self.set_draw_color(199, 210, 254)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(30, 58, 138)
        self.cell(0, 7, f" {clean_ascii(num_str)}  {clean_ascii(title).upper()}", border=1, new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.ln(2)

    def subsection_heading(self, title: str):
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(55, 65, 81)
        self.cell(0, 6, clean_ascii(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.ln(1)

    def body_p(self, text: str):
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(31, 41, 55)
        self.multi_cell(0, 4.5, clean_ascii(text))
        self.ln(2)

    def legal_callout(self, text: str):
        self.set_fill_color(254, 243, 199) # soft amber
        self.set_draw_color(245, 158, 11)
        self.set_text_color(146, 64, 14)
        self.set_font("Helvetica", "B", 8)
        self.multi_cell(0, 4.5, f"LEGAL REVIEW NOTE: {clean_ascii(text)}", border=1, fill=True)
        self.ln(2)


def generate_terms_pdf(output_paths: list[str]):
    pdf = PolicyPDF("Terms & Conditions and Service Policy", "Multi-Service Agentic Onboarding Platform Policy")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.render_title_block()

    pdf.legal_callout("This document is a formal draft prepared for technical and procedural integration within the Docintake onboarding system. Prior to public promulgation or enforceability, this policy must undergo comprehensive review and formal sign-off by qualified legal counsel licensed within the United Arab Emirates.")

    # 1. Introduction and acceptance
    pdf.section_heading("1.", "Introduction and Acceptance")
    pdf.body_p("Welcome to Docintake. By accessing, browsing, registering for an account, or submitting any documents or information through the Docintake platform, you ('User', 'Applicant', or 'You') acknowledge that you have read, understood, and unconditionally agree to be bound by these Terms & Conditions and Service Policy ('Terms'). If you do not agree with any provision of these Terms, you must immediately cease accessing the platform and discontinue account registration.")

    # 2. Company Identification
    pdf.section_heading("2.", "Company Identification")
    pdf.body_p("The Docintake platform is operated by Docintake ('Company', 'We', 'Us', or 'Our'). The Company's registered address is currently designated as N/A. The platform is designed and intended for operation within the United Arab Emirates ('UAE'). Official support inquiries may be directed to our designated Customer Support at [SUPPORT EMAIL PLACEHOLDER].")

    # 3. Platform Purpose
    pdf.section_heading("3.", "Platform Purpose and Scope")
    pdf.body_p("Docintake is an enterprise agentic onboarding and document intake platform. The platform facilitates conversational service guidance, structured document upload, automated format validation, optical and vision-based structured information extraction, and completeness verification for service onboarding applications.")
    pdf.body_p("LIMITATION OF SCOPE: Docintake is an intake, collection, extraction, and routing gateway. Docintake does not conduct independent external government identity verification or database reconciliation unless an authorized integration is explicitly enabled. Automated extraction and completeness validation do not constitute government certification or final approval of any application.")

    # 4. Available Services
    pdf.section_heading("4.", "Active Services Catalogue")
    pdf.body_p("The following three (3) services are active and operational within the Docintake catalogue:")
    pdf.body_p("1. Basic Registration: Standard identity onboarding service requiring the submission of a valid National ID card. Intended processing turnaround: 1 to 2 business days.")
    pdf.body_p("2. Premium / Cross Border: Enhanced cross-border onboarding service requiring the submission of BOTH a valid National ID card AND a valid Passport. Both required documents must be uploaded and validated before the application is deemed complete. Intended processing turnaround: 3 to 5 business days.")
    pdf.body_p("3. Mobility / Rental: Specialised automotive rental and mobility onboarding service requiring the submission of an official Driving Licence. Driving licence extraction executes dedicated field parsing. Intended processing turnaround: Same-day processing.")

    # 5. Coming Soon Services
    pdf.section_heading("5.", "Services Marked Coming Soon")
    pdf.body_p("Additional services appearing within the platform directory (including Bank Account Onboarding, Commercial Insurance, SIM Card Registration, Loan Applications, Utility Connections, Tenancy Agreements, Professional Licences, and Vehicle Registration) are marked 'Coming Soon'. These services are for catalogue demonstration purposes only and cannot accept live document submissions.")

    # 6. Account Creation and User Responsibilities
    pdf.section_heading("6.", "Account Creation and User Responsibilities")
    pdf.body_p("To initiate applications and upload documents, you must create a registered user account. You agree to provide accurate, true, current, and complete personal credentials. You are strictly responsible for maintaining the confidentiality of your credentials. Registration requires mandatory, active acceptance of these Terms. Account sharing or submitting documentation on behalf of unauthorized third parties without lawful representation is strictly prohibited.")

    # 7. Document Submission Requirements
    pdf.section_heading("7.", "Document Submission Requirements")
    pdf.body_p("Applicants are required to submit legible, genuine, unaltered, and uncorrupted digital copies of original physical documents. Proof of Address or additional non-mandatory documentation is not required for the active services unless explicitly established in approved service definition updates.")

    # 8. Supported Document Formats and Security Filters
    pdf.section_heading("8.", "Supported Document Formats and Antivirus Filtering")
    pdf.body_p("Docintake accepts documents in PDF format, as well as approved raster formats (PNG, JPEG, TIFF). Uploaded files are subject to automated security scanning, content validation, and raster verification. Screenshots, vector-only synthetic PDFs, digitally manipulated images, and password-protected files may be rejected automatically.")

    # 9. AI-Powered Extraction Disclaimers
    pdf.section_heading("9.", "AI-Powered Information Extraction")
    pdf.body_p("Docintake utilizes on-premise vision-language processing models and extraction ladders to extract textual and identity fields from submitted files. NO DOCUMENT PROCESSING RESULT IS GUARANTEED TO BE ERROR-FREE. Automated optical and vision extraction is an algorithmic approximation. Applicants are provided an in-app verification step to review, confirm, or edit extracted values before final application submission.")

    # 10. Automated Validation
    pdf.section_heading("10.", "Automated Validation and Business Rules")
    pdf.body_p("The platform applies deterministic rules including mandatory field presence, checksum validation, date consistency (issue date prior to expiry), and applicant name matching. For Premium / Cross Border applications, cross-document comparison is conducted between corresponding fields of the National ID and Passport.")

    # 11. Document Expiration and Validity Policy
    pdf.section_heading("11.", "Document Expiration Policy")
    pdf.body_p("All submitted identity documents, passports, and driving licences must be valid and unexpired at the date of application submission. Documents displaying an expired validity period will fail automated validation checks and will be routed to human review or rejected.")

    # 12. Human-Review Escalation Procedures
    pdf.section_heading("12.", "Human-Review Procedures")
    pdf.body_p("Applications failing automated confidence thresholds, containing edge-case discrepancies, or presenting unreadable zones are placed into a Human Review queue. Human review is conducted solely by authorized personnel under strict supervisory logging.")

    # 13. Application Status and Completion
    pdf.section_heading("13.", "Application Status and Completion")
    pdf.body_p("An application status transitioning to 'complete' within Docintake indicates solely that all mandatory documents have been ingested and validated for completeness. COMPLETE SUBMISSION IS NOT AUTOMATICALLY EQUIVALENT TO REGULATORY APPROVAL OR LICENCE ISSUANCE.")

    # 14. Document Review Authorization
    pdf.section_heading("14.", "Application-Specific Document Review Authorization")
    pdf.body_p("Before an application is routed to the designated review authority, you must provide independent, explicit Document Review Consent. You retain the right to decline or withdraw consent in accordance with applicable UAE legal standards.")

    # 15. Data Protection and Storage Responsibilities
    pdf.section_heading("15.", "Data Protection and On-Premise Infrastructure")
    pdf.body_p("Docintake stores customer documents and data strictly within private on-premise infrastructure utilizing MinIO object storage and PostgreSQL relational databases. Customer document binaries are never transmitted to third-party public cloud AI providers or external APIs.")

    # 16. Prohibited Activities
    pdf.section_heading("16.", "Prohibited Activities")
    pdf.body_p("Users may not: (a) upload fraudulent, forged, or unlawfully obtained documents; (b) attempt prompt injection, jailbreaking, or algorithmic subversion; (c) bypass access control barriers; (d) probe, scan, or test the vulnerability of the system.")

    # 17. Platform Availability
    pdf.section_heading("17.", "Platform Availability")
    pdf.body_p("The platform is provided on an 'AS IS' and 'AS AVAILABLE' basis. While Docintake endeavors to ensure high availability, uninterrupted service is not warranted.")

    # 18. Processing Time Expectations
    pdf.section_heading("18.", "Processing Time Expectations")
    pdf.body_p("Stated processing times (e.g. 1-2 days for Basic Registration, 3-5 days for Premium, same-day for Mobility) represent operational estimates and do not constitute binding contractual guarantees.")

    # 19. Service Limitations
    pdf.section_heading("19.", "Service Limitations and Third-Party Dependencies")
    pdf.body_p("Docintake operates solely as an onboarding intake conduit and does not issue legal identity documents, visas, driving permits, or government authorizations.")

    # 20. User Support and Inquiries
    pdf.section_heading("20.", "User Support and Inquiries")
    pdf.body_p("Users experiencing technical difficulties or seeking assistance may contact [SUPPORT EMAIL PLACEHOLDER].")

    # 21. Policy Updates and Versioning
    pdf.section_heading("21.", "Policy Updates and Modifications")
    pdf.body_p("Docintake reserves the right to modify these Terms. Material modifications will be published with an updated version number. Continued use following notification constitutes acceptance of amended Terms.")

    # 22. Account Suspension and Termination
    pdf.section_heading("22.", "Account Suspension and Termination")
    pdf.body_p("Docintake reserves the unilateral right to suspend or terminate any user account found to be in violation of these Terms or attempting security breaches.")

    # 23. Liability Limitations
    pdf.section_heading("23.", "Limitation of Liability")
    pdf.body_p("To the fullest extent permitted under UAE law, Docintake and its officers, directors, and employees shall not be liable for any indirect, incidental, special, consequential, or punitive damages arising from the use or inability to use the platform.")
    pdf.legal_callout("Specific financial liability caps and disclaimer provisions must be reviewed against UAE Civil Code provisions governing contractual liability and damages.")

    # 24. Governing Law and Dispute Resolution
    pdf.section_heading("24.", "Governing Law and Dispute Resolution")
    pdf.body_p("These Terms shall be governed by and construed in accordance with the laws of the United Arab Emirates. Any dispute, controversy, or claim arising under or relating to these Terms shall be subject to the exclusive jurisdiction of the competent courts of the United Arab Emirates.")
    pdf.legal_callout("Subject to counsel review regarding specific choice of court (Emirate-level local courts, DIFC Courts, or ADGM Courts).")

    # 25. Contact Information
    pdf.section_heading("25.", "Contact Information")
    pdf.body_p("Company: Docintake\nRegistered Address: N/A\nSupport Email: [SUPPORT EMAIL PLACEHOLDER]\nPrivacy Contact: [PRIVACY CONTACT PLACEHOLDER]")

    # 26. Acceptance of Terms & Conditions
    pdf.section_heading("26.", "Formal Acceptance of Terms & Conditions")
    pdf.body_p("By checking the mandatory acceptance checkbox during account registration, you confirm that you have read, understood, and agreed to all 26 sections of these Terms & Conditions and Service Policy.")

    for path in output_paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pdf.output(path)
        print(f"Generated Terms PDF at: {path}")


def generate_privacy_pdf(output_paths: list[str]):
    pdf = PolicyPDF("Privacy Policy and Data Protection Framework", "Multi-Service Agentic Onboarding Platform Policy")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.render_title_block()

    pdf.legal_callout("This Privacy Policy reflects Docintake's technical architecture (on-premise storage, developer document exclusion, application-specific consent). Applicability of UAE Federal Decree-Law No. 45 of 2021 (PDPL) and public-sector exclusions must be reviewed by qualified UAE legal counsel.")

    # 1. Information Collected
    pdf.section_heading("1.", "Categories of Personal Information Collected")
    pdf.body_p("Docintake collects and processes only the personal data strictly required to execute its onboarding and intake functionalities:")
    pdf.body_p("- Account Credentials: Username, email address, cryptographic password hash, full name, date of birth, gender.")
    pdf.body_p("- Submitted Document Binaries: Scanned images and PDF files of National ID cards, Passports, and Driving Licences.")
    pdf.body_p("- Extracted Identity Fields: Full name, document numbers, nationality, date of birth, issue date, expiry date, licensing authority, and relevant metadata.")
    pdf.body_p("- Application Lifecycle Data: Service selected, submission status, automated validation outcomes, review decisions.")
    pdf.body_p("- Audit and Consent Logs: Registration Terms acceptance records, application-specific document review consents, consent decline and withdrawal records, and immutable reviewer access audit logs.")

    # 2. Purpose of Processing
    pdf.section_heading("2.", "Purpose and Legal Basis of Processing")
    pdf.body_p("Personal data is collected and processed for the following specified, explicit, and legitimate purposes:")
    pdf.body_p("1. Account management and authentication.")
    pdf.body_p("2. Service matching and onboarding guidance.")
    pdf.body_p("3. Document intake, raster validation, and format verification.")
    pdf.body_p("4. Vision-based information extraction and field matching.")
    pdf.body_p("5. Facilitating authorized government-agency inspection.")
    pdf.body_p("6. Operational traceability, fraud prevention, and platform security.")

    # 3. On-Premise Storage Architecture
    pdf.section_heading("3.", "On-Premise Infrastructure and Data Localization")
    pdf.body_p("All customer document binaries and structured database records remain strictly within Docintake's approved private on-premise infrastructure:")
    pdf.body_p("- Document Binaries: Securely stored in self-hosted MinIO object storage.")
    pdf.body_p("- Structured Metadata & Audits: Persisted in private PostgreSQL databases.")
    pdf.body_p("- Local AI Processing: Optical and vision extraction is executed strictly on local infrastructure models. Document contents are NEVER transmitted to external third-party public AI APIs or cloud storage services.")

    # 4. Authorized Government-Agency Access
    pdf.section_heading("4.", "Authorized Government-Agency Review Access")
    pdf.body_p("Docintake acts as an intake gateway. Following explicit Document Review Consent, applications are routed to the designated reviewing body:")
    pdf.body_p("- Mobility / Rental: Routed to designated authorized mobility reviewers (e.g. RTA reviewer queue, if approved).")
    pdf.body_p("- Basic Registration: Routed to designated identity/onboarding inspection queues.")
    pdf.body_p("- Premium / Cross Border: Routed to designated cross-border inspection reviewers.")
    pdf.body_p("Strict Access Boundaries: Access is compartmentalized by assigned agency. Reviewers from one agency are technically prevented from inspecting applications or documents belonging to another agency. Every document view and inspection action is recorded in an immutable audit trail.")

    # 5. Developer Access Restrictions
    pdf.section_heading("5.", "Strict Developer Access Restrictions")
    pdf.body_p("APPLICATION DEVELOPERS ARE STRICTLY FORBIDDEN FROM ACCESSING REAL CUSTOMER DOCUMENT CONTENTS. Docintake maintains strict role-based separation between platform developers, system administrators, compliance officers, and government reviewers:")
    pdf.body_p("- Developers have access only to source code, non-sensitive system health metrics, synthetic test records, and anonymized logs.")
    pdf.body_p("- The platform does NOT provide a developer bypass. Attempted access to customer document binaries or presigned URLs by a developer account is blocked with HTTP 403 Forbidden and logged as a security event.")

    # 6. Data Retention Policy
    pdf.section_heading("6.", "Data Retention and Disposal Policy")
    pdf.body_p("Docintake operates a configurable data retention framework:")
    pdf.body_p("- Temporary Staging: Uploaded files prior to consent reside in a temporary staging area. If consent is declined or abandoned, staged files are purged.")
    pdf.body_p("- Persistent Storage: Documents are committed to persistent storage only following explicit Document Review Consent.")
    pdf.body_p("- Retention Periods: Documents are retained for the duration required to complete onboarding, subject to applicable UAE statutory retention periods confirmed by legal counsel.")

    # 7. Consent and Withdrawal Rights
    pdf.section_heading("7.", "Application-Specific Consent and Withdrawal Rights")
    pdf.body_p("Each application requires independent Document Review Consent. One application's consent never applies to another.")
    pdf.body_p("Right to Decline: If consent is declined, the application is closed immediately, and temporary document binaries are purged.")
    pdf.body_p("Right of Withdrawal: In accordance with UAE legal standards, applicants may formally withdraw previously granted consent. Withdrawal halts future optional processing, prevents further reviewer access, and closes the application. Immutable audit records of consent history are retained for compliance.")

    # 8. Data Protection Rights under UAE Law
    pdf.section_heading("8.", "Data Subject Rights under UAE Law")
    pdf.body_p("Subject to legal counsel review under UAE Federal Decree-Law No. 45 of 2021 and applicable regulatory exemptions, applicants may exercise rights of access, correction, processing restriction, and withdrawal by contacting [PRIVACY CONTACT PLACEHOLDER].")

    # 9. Contact for Privacy Inquiries
    pdf.section_heading("9.", "Privacy Contact Information")
    pdf.body_p("Company Name: Docintake\nJurisdiction: United Arab Emirates\nPrivacy Inquiries: [PRIVACY CONTACT PLACEHOLDER]\nDocument Version: 1.0 (DRAFT - PENDING LEGAL APPROVAL)")

    for path in output_paths:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pdf.output(path)
        print(f"Generated Privacy PDF at: {path}")

if __name__ == "__main__":
    t_paths = ["docs/Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf", "app/static/policies/Docintake_Terms_and_Conditions_v1.0_DRAFT.pdf"]
    p_paths = ["docs/Docintake_Privacy_Policy_v1.0_DRAFT.pdf", "app/static/policies/Docintake_Privacy_Policy_v1.0_DRAFT.pdf"]
    generate_terms_pdf(t_paths)
    generate_privacy_pdf(p_paths)
