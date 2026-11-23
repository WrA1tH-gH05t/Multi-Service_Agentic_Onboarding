"""Comprehensive End-to-End Test Suite for Legal Policies, Consent, Government Reviewer Routing, and Developer Restrictions."""

import os
import io
import json
import uuid
import pytest
from fastapi.testclient import TestClient

from app.main import app, app_state

@pytest.fixture(scope="module", autouse=True)
def client_fixture():
    with TestClient(app) as test_client:
        yield test_client

def test_01_legal_policies_and_downloads(client_fixture):
    """Verify that both legal policies are available, have correct version/status, and PDFs are downloadable."""
    client = client_fixture
    # List policies
    r = client.get("/api/v1/policies")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    policies = {p["policy_id"]: p for p in data["data"]}
    assert "terms_and_conditions" in policies
    assert "privacy_policy" in policies

    # Check Terms & Conditions
    t = policies["terms_and_conditions"]
    assert t["version"] in ["1.0", "1.1"]
    assert "DRAFT" in t["status"]
    assert "Docintake_Terms_and_Conditions" in t["pdf_filename"]

    # Check Privacy Policy
    p = policies["privacy_policy"]
    assert p["version"] in ["1.0", "1.1"]
    assert "DRAFT" in p["status"]
    assert "Docintake_Privacy_Policy" in p["pdf_filename"]

    # HTML Views
    r_thtml = client.get("/api/v1/policies/terms")
    assert r_thtml.status_code == 200
    assert "DOCINTAKE" in r_thtml.text
    assert "United Arab Emirates" in r_thtml.text

    r_phtml = client.get("/api/v1/policies/privacy")
    assert r_phtml.status_code == 200
    assert "DOCINTAKE" in r_phtml.text
    assert "On-Premise" in r_phtml.text

    # PDF Downloads
    r_tpdf = client.get("/api/v1/policies/terms/download")
    assert r_tpdf.status_code == 200
    assert r_tpdf.headers["content-type"] == "application/pdf"
    assert len(r_tpdf.content) > 1000

    r_ppdf = client.get("/api/v1/policies/privacy/download")
    assert r_ppdf.status_code == 200
    assert r_ppdf.headers["content-type"] == "application/pdf"
    assert len(r_ppdf.content) > 1000


def test_02_account_registration_terms_acceptance_mandatory(client_fixture):
    """Verify that registration is BLOCKED if Terms are not accepted, and SUCCEEDS when accepted."""
    client = client_fixture
    test_user_no_terms = f"user_noterms_{uuid.uuid4().hex[:6]}"
    
    # 1. Attempt signup WITHOUT accepting Terms -> MUST BE BLOCKED
    r_block = client.post("/api/v1/auth/signup", json={
        "username": test_user_no_terms,
        "password": "Password123!",
        "email": f"{test_user_no_terms}@example.com",
        "accept_terms": False
    })
    assert r_block.status_code == 400
    assert "Terms & Conditions" in r_block.json()["detail"]

    # 2. Signup WITH Terms acceptance -> MUST SUCCEED
    test_user_ok = f"user_ok_{uuid.uuid4().hex[:6]}"
    r_ok = client.post("/api/v1/auth/signup", json={
        "username": test_user_ok,
        "password": "Password123!",
        "email": f"{test_user_ok}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    assert r_ok.status_code == 200
    res_data = r_ok.json()["data"]
    assert res_data["terms_accepted"] is True
    assert "token" in res_data
    token = res_data["token"]
    user_id = res_data["user_id"]

    # Verify acceptance was saved in database
    db = app_state["database"]
    with db.session_scope() as session:
        from services.database import UserTermsAcceptance
        acc = session.query(UserTermsAcceptance).filter_by(user_id=user_id).first()
        assert acc is not None
        assert acc.accepted is True
        assert acc.policy_id == "terms_and_conditions"
        assert acc.version in ["1.0", "1.1"]


def test_03_developer_access_restrictions(client_fixture):
    """Verify that accounts with 'developer' role are strictly forbidden from viewing or downloading customer documents."""
    client = client_fixture
    dev_username = f"dev_{uuid.uuid4().hex[:6]}"
    r_dev = client.post("/api/v1/auth/signup", json={
        "username": dev_username,
        "password": "Password123!",
        "email": f"{dev_username}@example.com",
        "accept_terms": True,
        "role": "developer"
    })
    assert r_dev.status_code == 200
    dev_token = r_dev.json()["data"]["token"]
    dev_user_id = r_dev.json()["data"]["user_id"]

    # Create an applicant and upload a synthetic document
    app_username = f"appuser_{uuid.uuid4().hex[:6]}"
    r_app = client.post("/api/v1/auth/signup", json={
        "username": app_username,
        "password": "Password123!",
        "email": f"{app_username}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    app_token = r_app.json()["data"]["token"]
    app_user_id = r_app.json()["data"]["user_id"]

    # Seed a document row for this applicant
    db = app_state["database"]
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    with db.session_scope() as session:
        from services.database import Document, DocumentAccessAudit
        d = Document(
            document_id=doc_id,
            user_id=app_user_id,
            filename="national_id_sample.pdf",
            object_name=f"docs/{doc_id}_national_id_sample.pdf",
            file_size=1024,
            content_type="application/pdf",
            document_type="national_id",
            status="processed",
            storage="local"
        )
        session.add(d)

    # 1. Developer tries to view document -> MUST RETURN 403 FORBIDDEN
    r_view = client.get(f"/api/v1/documents/{doc_id}/view?token={dev_token}")
    assert r_view.status_code == 403
    assert "strictly restricted" in r_view.json()["detail"]

    # 2. Developer tries to download document -> MUST RETURN 403 FORBIDDEN
    r_dl = client.get(f"/api/v1/documents/{doc_id}/download?token={dev_token}")
    assert r_dl.status_code == 403
    assert "strictly restricted" in r_dl.json()["detail"]

    # 3. Developer tries to get presigned URL -> MUST RETURN 403 FORBIDDEN
    r_pre = client.get(f"/api/v1/documents/{doc_id}/presigned-url?token={dev_token}")
    assert r_pre.status_code == 403

    # 4. Developer tries to access agency review portal -> MUST RETURN 403 FORBIDDEN
    r_agency = client.get(f"/api/v1/agency/applications?token={dev_token}")
    assert r_agency.status_code == 403

    # Verify security audit trail recorded the violation
    with db.session_scope() as session:
        audits = session.query(DocumentAccessAudit).filter_by(user_id=dev_user_id, user_role="developer").all()
        assert len(audits) >= 3
        for a in audits:
            assert a.access_granted is False
            assert a.denial_reason == "developer_access_forbidden"


def test_04_application_consent_workflow_three_services(client_fixture):
    """Verify application-specific consent disclosure, agree routing, decline purging, and withdrawal across services."""
    client = client_fixture
    db = app_state["database"]

    # Create applicant
    uname = f"applicant_svc_{uuid.uuid4().hex[:6]}"
    r_u = client.post("/api/v1/auth/signup", json={
        "username": uname,
        "password": "Password123!",
        "email": f"{uname}@example.com",
        "accept_terms": True,
    })
    token = r_u.json()["data"]["token"]
    uid = r_u.json()["data"]["user_id"]

    # Test Service 1: Mobility / Rental (Routes to mobility_rta)
    r_mr = client.post(f"/api/v1/applications?service_id=mobility_rental&applicant_name=Mobility+Applicant&token={token}")
    assert r_mr.status_code == 200
    mr_app_id = r_mr.json()["data"]["id"]

    # Check consent info disclosure
    r_cinfo = client.get(f"/api/v1/applications/{mr_app_id}/consent-info?token={token}")
    assert r_cinfo.status_code == 200
    c_data = r_cinfo.json()["data"]
    assert c_data["designated_agency_id"] == "mobility_rta"
    assert "Roads & Transport Authority" in c_data["designated_agency_name"]
    assert c_data["consent_screen_title"] == "DOCUMENT REVIEW CONSENT"

    # User agrees to consent
    r_agree = client.post(f"/api/v1/applications/{mr_app_id}/consent?token={token}", json={
        "application_id": mr_app_id,
        "agreed": True,
        "consent_version": "1.0"
    })
    assert r_agree.status_code == 200
    assert r_agree.json()["data"]["status"] == "under_agency_review"
    assert r_agree.json()["data"]["designated_agency"] == "mobility_rta"

    # Test Service 2: Basic Registration - Decline Flow (Closes application & purges files)
    r_br = client.post(f"/api/v1/applications?service_id=basic_registration&applicant_name=Basic+Applicant&token={token}")
    br_app_id = r_br.json()["data"]["id"]

    # Attach dummy document
    doc_br_id = f"doc_{uuid.uuid4().hex[:8]}"
    with db.session_scope() as session:
        from services.database import Document
        session.add(Document(
            document_id=doc_br_id,
            application_id=br_app_id,
            user_id=uid,
            filename="national_id_card.pdf",
            file_size=512,
            content_type="application/pdf",
            document_type="national_id",
            status="staged"
        ))

    # Applicant DECLINES consent
    r_dec = client.post(f"/api/v1/applications/{br_app_id}/consent?token={token}", json={
        "application_id": br_app_id,
        "agreed": False,
        "consent_version": "1.0"
    })
    assert r_dec.status_code == 200
    assert r_dec.json()["data"]["status"] == "rejected"

    # Verify document was purged and application marked rejected
    with db.session_scope() as session:
        doc_row = session.query(Document).filter_by(document_id=doc_br_id).first()
        assert doc_row.status == "purged"
        assert "_purged" in doc_row.extracted_fields

    # Attempt to re-consent closed application -> MUST FAIL 409
    r_reopen = client.post(f"/api/v1/applications/{br_app_id}/consent?token={token}", json={
        "application_id": br_app_id,
        "agreed": True,
        "consent_version": "1.0"
    })
    assert r_reopen.status_code == 409

    # Test Service 3: Premium / Cross Border - Consent Agreement and Legal Withdrawal
    r_pcb = client.post(f"/api/v1/applications?service_id=premium_crossborder&applicant_name=CrossBorder+Applicant&token={token}")
    pcb_app_id = r_pcb.json()["data"]["id"]

    # Agree
    r_pcb_agree = client.post(f"/api/v1/applications/{pcb_app_id}/consent?token={token}", json={
        "application_id": pcb_app_id,
        "agreed": True,
        "consent_version": "1.0"
    })
    assert r_pcb_agree.status_code == 200
    assert r_pcb_agree.json()["data"]["designated_agency"] == "crossborder_authority"

    # Withdraw consent
    r_withdraw = client.post(f"/api/v1/applications/{pcb_app_id}/withdraw-consent?token={token}", json={
        "withdrawal_reason": "Applicant requested immediate withdrawal under UAE data protection regulations."
    })
    assert r_withdraw.status_code == 200
    assert r_withdraw.json()["data"]["status"] == "cancelled"


def test_05_government_reviewer_compartmentalization(client_fixture):
    """Verify that reviewers see only applications assigned to their agency and cross-agency access is forbidden."""
    client = client_fixture
    # Register RTA Reviewer
    rta_user = f"rev_rta_{uuid.uuid4().hex[:6]}"
    r_rta = client.post("/api/v1/auth/signup", json={
        "username": rta_user,
        "password": "Password123!",
        "email": f"{rta_user}@example.com",
        "accept_terms": True,
        "role": "government_reviewer",
        "agency_id": "mobility_rta"
    })
    rta_token = r_rta.json()["data"]["token"]

    # Register Cross-Border Reviewer
    pcb_user = f"rev_pcb_{uuid.uuid4().hex[:6]}"
    r_pcb = client.post("/api/v1/auth/signup", json={
        "username": pcb_user,
        "password": "Password123!",
        "email": f"{pcb_user}@example.com",
        "accept_terms": True,
        "role": "government_reviewer",
        "agency_id": "crossborder_authority"
    })
    pcb_token = r_pcb.json()["data"]["token"]

    # Create applicant with Mobility application & agreed consent
    app_u = f"applicant_mobility_{uuid.uuid4().hex[:6]}"
    r_app_u = client.post("/api/v1/auth/signup", json={
        "username": app_u,
        "password": "Password123!",
        "email": f"{app_u}@example.com",
        "accept_terms": True,
    })
    app_token = r_app_u.json()["data"]["token"]
    app_uid = r_app_u.json()["data"]["user_id"]

    r_app = client.post(f"/api/v1/applications?service_id=mobility_rental&applicant_name=Driver+Applicant&token={app_token}")
    mobility_app_id = r_app.json()["data"]["id"]

    # Attach driving licence document
    db = app_state["database"]
    dl_doc_id = f"doc_dl_{uuid.uuid4().hex[:8]}"
    with db.session_scope() as session:
        from services.database import Document
        session.add(Document(
            document_id=dl_doc_id,
            application_id=mobility_app_id,
            user_id=app_uid,
            filename="driving_licence.pdf",
            file_size=2048,
            content_type="application/pdf",
            document_type="driving_license",
            status="processed",
            storage="local"
        ))

    # Applicant gives consent
    client.post(f"/api/v1/applications/{mobility_app_id}/consent?token={app_token}", json={
        "application_id": mobility_app_id,
        "agreed": True,
        "consent_version": "1.0"
    })

    # 1. RTA Reviewer lists agency applications -> MUST contain mobility_app_id
    r_rta_list = client.get(f"/api/v1/agency/applications?token={rta_token}")
    assert r_rta_list.status_code == 200
    listed_ids = [a["application_id"] for a in r_rta_list.json()["data"]]
    assert mobility_app_id in listed_ids

    # 2. Cross-Border Reviewer lists agency applications -> MUST NOT contain mobility_app_id
    r_pcb_list = client.get(f"/api/v1/agency/applications?token={pcb_token}")
    assert r_pcb_list.status_code == 200
    pcb_listed_ids = [a["application_id"] for a in r_pcb_list.json()["data"]]
    assert mobility_app_id not in pcb_listed_ids

    # 3. Cross-Border Reviewer attempts direct access to RTA document -> MUST BE FORBIDDEN (HTTP 403)
    r_cross_access = client.get(f"/api/v1/documents/{dl_doc_id}/view?token={pcb_token}")
    assert r_cross_access.status_code == 403
    assert "crossborder_authority" in r_cross_access.json()["detail"] or "Access denied" in r_cross_access.json()["detail"]
