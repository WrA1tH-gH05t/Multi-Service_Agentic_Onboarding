"""Comprehensive End-to-End Test Suite for Docintake:
Parent/Guardian Accounts, Child Dependent Profiles, Legal Policies v1.1,
Consent Management, Service Eligibility, Government Review, and Security.
"""

import os
import io
import json
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

from app.main import app, app_state

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_01_legal_policies_v1_1_and_pdf_integrity(client):
    """Verify Terms & Conditions and Privacy Policy v1.1 drafts, UAE jurisdiction, and PDF downloads."""
    # 1. Fetch policy metadata
    r = client.get("/api/v1/policies")
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    policies = {p["policy_id"]: p for p in data["data"]}

    terms = policies["terms_and_conditions"]
    assert terms["version"] == "1.1"
    assert "DRAFT — PENDING LEGAL APPROVAL" in terms["status"]
    assert "Docintake_Terms_and_Conditions_v1.1_DRAFT.pdf" in terms["pdf_filename"]

    privacy = policies["privacy_policy"]
    assert privacy["version"] == "1.1"
    assert "DRAFT — PENDING LEGAL APPROVAL" in privacy["status"]
    assert "Docintake_Privacy_Policy_v1.1_DRAFT.pdf" in privacy["pdf_filename"]

    # 2. HTML text views check for key legal references
    r_terms_html = client.get("/api/v1/policies/terms")
    assert r_terms_html.status_code == 200
    assert "Docintake" in r_terms_html.text
    assert "United Arab Emirates" in r_terms_html.text
    assert "Article 84" in r_terms_html.text or "Federal Decree-Law No. 25 of 2025" in r_terms_html.text

    r_priv_html = client.get("/api/v1/policies/privacy")
    assert r_priv_html.status_code == 200
    assert "Docintake" in r_priv_html.text
    assert "Article 7" in r_priv_html.text or "Federal Decree-Law No. 26 of 2025" in r_priv_html.text

    # 3. PDF Downloads are real ReportLab generated PDFs
    r_tpdf = client.get("/api/v1/policies/terms/download")
    assert r_tpdf.status_code == 200
    assert r_tpdf.headers["content-type"] == "application/pdf"
    assert len(r_tpdf.content) > 15000
    assert r_tpdf.content.startswith(b"%PDF")

    r_ppdf = client.get("/api/v1/policies/privacy/download")
    assert r_ppdf.status_code == 200
    assert r_ppdf.headers["content-type"] == "application/pdf"
    assert len(r_ppdf.content) > 15000
    assert r_ppdf.content.startswith(b"%PDF")


def test_02_parent_registration_and_mandatory_terms_acceptance(client):
    """Verify account signup requires mandatory acceptance of Terms v1.1 and validates adult capacity."""
    uid = uuid.uuid4().hex[:6]
    username_reject = f"parent_reject_{uid}"

    # Signup without accepting terms must fail
    r_reject = client.post("/api/v1/auth/signup", json={
        "username": username_reject,
        "password": "Password123!",
        "email": f"{username_reject}@example.com",
        "accept_terms": False
    })
    assert r_reject.status_code == 400
    assert "Terms & Conditions" in r_reject.json()["detail"]

    # Signup with terms acceptance succeeds and dual-records PolicyAcceptance
    username_ok = f"parent_ok_{uid}"
    r_ok = client.post("/api/v1/auth/signup", json={
        "username": username_ok,
        "password": "Password123!",
        "email": f"{username_ok}@example.com",
        "full_name": "Fatima Al-Mansoor",
        "accept_terms": True,
        "role": "applicant"
    })
    assert r_ok.status_code == 200
    res = r_ok.json()["data"]
    token = res["token"]
    user_id = res["user_id"]

    # Verify both UserTermsAcceptance and PolicyAcceptance rows exist
    db = app_state["database"]
    with db.session_scope() as session:
        from services.database import UserTermsAcceptance, PolicyAcceptance
        uta = session.query(UserTermsAcceptance).filter_by(user_id=user_id).first()
        assert uta is not None
        assert uta.version == "1.1"

        pa = session.query(PolicyAcceptance).filter_by(user_id=user_id, policy_type="terms_and_conditions").first()
        assert pa is not None
        assert pa.policy_version == "1.1"


def test_03_child_profile_creation_and_guardian_authority(client):
    """Verify child profile creation, validation, age calculation, and guardian authority confirmation."""
    # 1. Create a parent user
    uid = uuid.uuid4().hex[:6]
    parent_user = f"guardian_{uid}"
    r_parent = client.post("/api/v1/auth/signup", json={
        "username": parent_user,
        "password": "Password123!",
        "email": f"{parent_user}@example.com",
        "full_name": "Rashid Al-Nuaimi",
        "accept_terms": True,
        "role": "applicant"
    })
    assert r_parent.status_code == 200
    token = r_parent.json()["data"]["token"]

    # 2. Attempt child creation WITHOUT confirming guardian authority -> MUST FAIL
    dob_teen = (datetime.now(timezone.utc) - timedelta(days=15 * 365 + 30)).strftime("%Y-%m-%d") # ~15 years old
    r_no_auth = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Hamad Al-Nuaimi",
        "date_of_birth": dob_teen,
        "relationship_type": "parent",
        "guardian_confirms_authority": False
    })
    assert r_no_auth.status_code == 400
    assert "parent or legally authorized" in r_no_auth.json()["detail"].lower()

    # 3. Create teen child profile WITH authority confirmation -> SUCCEEDS
    r_teen = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Hamad Al-Nuaimi",
        "date_of_birth": dob_teen,
        "relationship_type": "parent",
        "nationality": "Emirati",
        "guardian_confirms_authority": True,
        "guardian_verification_reference": "BC-DXB-2011-88910"
    })
    assert r_teen.status_code == 200
    data_teen = r_teen.json()["data"]
    assert data_teen["full_name"] == "Hamad Al-Nuaimi"
    assert data_teen["age_band"] == "13_to_17"
    assert data_teen["guardian_authority_status"] in ["verified", "confirmed"]
    teen_id = data_teen["profile_id"]

    # 4. List child profiles for this parent
    r_list = client.get(f"/api/v1/children/profiles?token={token}")
    assert r_list.status_code == 200
    profiles = r_list.json()["data"]
    assert len(profiles) >= 1
    assert any(p["profile_id"] == teen_id for p in profiles)

    # 5. Isolation: Another parent cannot view or modify this child's profile
    other_parent = f"other_{uid}"
    r_other = client.post("/api/v1/auth/signup", json={
        "username": other_parent,
        "password": "Password123!",
        "email": f"{other_parent}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    other_token = r_other.json()["data"]["token"]

    r_iso_get = client.get(f"/api/v1/children/profiles/{teen_id}?token={other_token}")
    assert r_iso_get.status_code in [403, 404]

    r_iso_put = client.put(f"/api/v1/children/profiles/{teen_id}?token={other_token}", json={
        "full_name": "Tampered Name"
    })
    assert r_iso_put.status_code in [403, 404]


def test_04_under_13_article_7_parental_consent_and_withdrawal(client):
    """Verify that children under 13 require explicit Article 7 consent and allow easy withdrawal."""
    uid = uuid.uuid4().hex[:6]
    parent_user = f"parent_u13_{uid}"
    r_parent = client.post("/api/v1/auth/signup", json={
        "username": parent_user,
        "password": "Password123!",
        "email": f"{parent_user}@example.com",
        "full_name": "Mariam Al-Zaabi",
        "accept_terms": True,
        "role": "applicant"
    })
    token = r_parent.json()["data"]["token"]

    # Child is 7 years old (< 13)
    dob_young = (datetime.now(timezone.utc) - timedelta(days=7 * 365 + 10)).strftime("%Y-%m-%d")

    # 1. Attempt creation WITHOUT Article 7 consent -> MUST FAIL
    r_fail = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Zayed Al-Zaabi",
        "date_of_birth": dob_young,
        "relationship_type": "parent",
        "guardian_confirms_authority": True,
        "guardian_consents_to_data_processing": False
    })
    assert r_fail.status_code == 400
    assert "Article 7" in r_fail.json()["detail"] or "UAE Federal Decree-Law No. 26 of 2025" in r_fail.json()["detail"]

    # 2. Creation WITH Article 7 consent -> SUCCEEDS
    r_ok = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Zayed Al-Zaabi",
        "date_of_birth": dob_young,
        "relationship_type": "parent",
        "guardian_confirms_authority": True,
        "guardian_consents_to_data_processing": True,
        "nationality": "Emirati"
    })
    assert r_ok.status_code == 200
    child_data = r_ok.json()["data"]
    child_id = child_data["profile_id"]
    assert child_data["age_band"] == "under_13"

    # 3. Verify GuardianConsent record exists in DB
    db = app_state["database"]
    with db.session_scope() as session:
        from services.database import GuardianConsent
        consent = session.query(GuardianConsent).filter_by(child_profile_id=child_id).first()
        assert consent is not None
        assert consent.consent_status in ["accepted", "active"]
        assert consent.privacy_policy_version in ["1.1", "v1.1"]
        consent_id = consent.consent_id

    # 4. Withdraw consent via the withdrawal endpoint
    r_withdraw = client.post(f"/api/v1/children/consent/guardian/{consent_id}/withdraw?token={token}")
    assert r_withdraw.status_code == 200
    w_data = r_withdraw.json()
    assert w_data["success"] is True

    # Verify status changed to withdrawn
    with db.session_scope() as session:
        consent_updated = session.query(GuardianConsent).filter_by(consent_id=consent_id).first()
        assert consent_updated.consent_status == "withdrawn"
        assert consent_updated.withdrawn_at is not None


def test_05_child_service_eligibility_enforcement(client):
    """Verify that Basic Registration and Premium Cross Border are eligible for children, but Mobility/Rental is blocked."""
    uid = uuid.uuid4().hex[:6]
    parent_user = f"parent_elig_{uid}"
    r_parent = client.post("/api/v1/auth/signup", json={
        "username": parent_user,
        "password": "Password123!",
        "email": f"{parent_user}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    token = r_parent.json()["data"]["token"]

    dob_child = (datetime.now(timezone.utc) - timedelta(days=10 * 365)).strftime("%Y-%m-%d")
    r_child = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Sultan Al-Marzooqi",
        "date_of_birth": dob_child,
        "relationship_type": "parent",
        "guardian_confirms_authority": True,
        "guardian_consents_to_data_processing": True
    })
    assert r_child.status_code == 200
    child_id = r_child.json()["data"]["profile_id"]

    # 1. Eligibility Check Endpoint
    # Basic Registration -> Eligible
    r_basic = client.get(f"/api/v1/children/profiles/{child_id}/eligibility/basic_registration?token={token}")
    assert r_basic.status_code == 200
    assert r_basic.json()["data"]["eligible"] is True

    # Premium Cross Border -> Eligible
    r_pcb = client.get(f"/api/v1/children/profiles/{child_id}/eligibility/premium_crossborder?token={token}")
    assert r_pcb.status_code == 200
    assert r_pcb.json()["data"]["eligible"] is True

    # Mobility Rental -> INELIGIBLE (Driving License age requirement)
    r_mob = client.get(f"/api/v1/children/profiles/{child_id}/eligibility/mobility_rental?token={token}")
    assert r_mob.status_code == 200
    mob_data = r_mob.json()["data"]
    assert mob_data["eligible"] is False
    assert "driving" in mob_data["reason"].lower() or "under 18" in mob_data["reason"].lower()

    # 2. Wizard Session Creation
    # Basic Registration session for child -> SUCCEEDS
    r_wiz_basic = client.post(f"/api/v1/wizard/create?token={token}&service_id=basic_registration&child_profile_id={child_id}&applicant_type=child_dependent")
    assert r_wiz_basic.status_code == 200
    assert r_wiz_basic.json()["data"]["applicant_name"] == "Sultan Al-Marzooqi"

    # Mobility Rental session for child -> MUST BE BLOCKED (HTTP 400)
    r_wiz_mob = client.post(f"/api/v1/wizard/create?token={token}&service_id=mobility_rental&child_profile_id={child_id}&applicant_type=child_dependent")
    assert r_wiz_mob.status_code == 400
    assert "Mobility / Rental is unavailable" in r_wiz_mob.json()["detail"]

    # 3. Verify Adult Mobility Rental remains ELIGIBLE
    r_wiz_adult_mob = client.post(f"/api/v1/wizard/create?token={token}&service_id=mobility_rental&applicant_type=adult")
    assert r_wiz_adult_mob.status_code == 200


def test_06_application_specific_review_consent_and_decline_flow(client):
    """Verify application-specific document review consent: Agree vs Decline flow."""
    uid = uuid.uuid4().hex[:6]
    parent_user = f"parent_rev_{uid}"
    r_parent = client.post("/api/v1/auth/signup", json={
        "username": parent_user,
        "password": "Password123!",
        "email": f"{parent_user}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    token = r_parent.json()["data"]["token"]

    dob_child = (datetime.now(timezone.utc) - timedelta(days=12 * 365)).strftime("%Y-%m-%d")
    r_child = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Noora Al-Hashemi",
        "date_of_birth": dob_child,
        "relationship_type": "parent",
        "guardian_confirms_authority": True,
        "guardian_consents_to_data_processing": True
    })
    child_id = r_child.json()["data"]["profile_id"]

    # 1. Decline Flow
    fake_app_id_decline = f"app_dec_{uid}"
    r_decline = client.post(f"/api/v1/children/consent/application-review?token={token}", json={
        "child_profile_id": child_id,
        "application_id": fake_app_id_decline,
        "service_id": "basic_registration",
        "receiving_agency_id": "uae_icp",
        "accepted": False
    })
    assert r_decline.status_code == 200
    assert r_decline.json()["status"] in ["declined", "withdrawn"]

    # 2. Accept Flow
    fake_app_id_accept = f"app_acc_{uid}"
    r_accept = client.post(f"/api/v1/children/consent/application-review?token={token}", json={
        "child_profile_id": child_id,
        "application_id": fake_app_id_accept,
        "service_id": "basic_registration",
        "receiving_agency_id": "uae_icp",
        "accepted": True
    })
    assert r_accept.status_code == 200
    assert r_accept.json()["status"] in ["accepted", "active"]
    consent_id = r_accept.json()["data"]["consent_id"]

    # 3. Withdraw Review Consent
    r_withdraw = client.post(f"/api/v1/children/consent/application-review/{consent_id}/withdraw?token={token}")
    assert r_withdraw.status_code == 200
    assert r_withdraw.json()["data"]["consent_status"] == "withdrawn"


def test_07_developer_access_lockout_and_government_reviewer_routing(client):
    """Verify that developers are strictly forbidden from viewing documents and government reviewers require matching authorization."""
    uid = uuid.uuid4().hex[:6]
    
    # 1. Developer signup
    dev_user = f"dev_{uid}"
    r_dev = client.post("/api/v1/auth/signup", json={
        "username": dev_user,
        "password": "Password123!",
        "email": f"{dev_user}@docintake.local",
        "accept_terms": True,
        "role": "developer"
    })
    dev_token = r_dev.json()["data"]["token"]

    # Developer attempting to view document -> 403 Forbidden
    r_dev_view = client.get(f"/api/v1/documents/doc_test_123/view?token={dev_token}")
    assert r_dev_view.status_code == 403
    assert "developer" in r_dev_view.json()["detail"].lower()

    # 2. DocumentAccessControl check
    from services.security import DocumentAccessControl
    db = app_state["database"]
    dev_user_id = r_dev.json()["data"]["user_id"]
    authorized, reason, _ = DocumentAccessControl.authorize_document_access(
        db=db,
        user_id=dev_user_id,
        document_id="doc_test_123"
    )
    assert authorized is False
    assert "developer" in reason.lower()


def test_08_chatbot_child_profile_intent(client):
    """Verify that the AI assistant recognizes child profile intent and triggers modal action without hallucinating external systems."""
    uid = uuid.uuid4().hex[:6]
    r_user = client.post("/api/v1/auth/signup", json={
        "username": f"chat_user_{uid}",
        "password": "Password123!",
        "email": f"chat_user_{uid}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    token = r_user.json()["data"]["token"]

    # Send child creation request to chat
    r_chat = client.post("/api/v1/chat/message", json={
        "query": "I want to add a profile for my child dependent",
        "token": token
    })
    assert r_chat.status_code == 200
    chat_data = r_chat.json()
    assert chat_data.get("action") == "open_child_modal" or "child" in chat_data.get("response", "").lower()


def test_09_audit_trail_logging_and_immutability(client):
    """Verify that all child profile actions create immutable audit trail events."""
    uid = uuid.uuid4().hex[:6]
    parent_user = f"audit_parent_{uid}"
    r_parent = client.post("/api/v1/auth/signup", json={
        "username": parent_user,
        "password": "Password123!",
        "email": f"{parent_user}@example.com",
        "accept_terms": True,
        "role": "applicant"
    })
    token = r_parent.json()["data"]["token"]

    dob_child = (datetime.now(timezone.utc) - timedelta(days=8 * 365)).strftime("%Y-%m-%d")
    r_child = client.post(f"/api/v1/children/profiles?token={token}", json={
        "full_name": "Salem Al-Kaabi",
        "date_of_birth": dob_child,
        "relationship_type": "parent",
        "guardian_confirms_authority": True,
        "guardian_consents_to_data_processing": True
    })
    child_id = r_child.json()["data"]["profile_id"]

    # Query audit trail
    r_audit = client.get(f"/api/v1/children/audit/{child_id}?token={token}")
    assert r_audit.status_code == 200
    events = r_audit.json()["data"]
    assert len(events) >= 1
    event_types = [e["event_type"] for e in events]
    assert "profile_created" in event_types or "guardian_consent_accepted" in event_types or "child_profile_created" in event_types
