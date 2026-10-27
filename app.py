"""
DocIntake Streamlit Frontend Application.

Module Purpose & Role in the Project:
------------------------------------
This module serves as the primary user-facing web interface for the DocIntake
multi-service agentic onboarding system. Built with Streamlit, it provides:
  1. Service Discovery (Home): Overview of supported onboarding services, required
     documentation, and processing expectations.
  2. Interactive Chat (Chat): Conversational interface powered by the backend agentic
     pipeline for FAQs, multi-turn application onboarding, and contextual PDF attachments.
  3. Document Management (Documents & Upload): File upload to backend API (MinIO + PGVector)
     and document status tracking/deletion.
  4. Application Dashboard (Applications): Status monitoring for multi-service onboarding
     applications associated with the authenticated user.
  5. Golden Dataset Management (Golden Dataset): Evaluation test suite UI.
  6. Authentication (Login / Sign Up): Session management for secure API interactions.

Interconnections with Other Components:
---------------------------------------
- Backend FastAPI Service (`http://localhost:8000/api/v1`):
    * `GET /health` -> Checked by `check_api_connection()` for liveness indicator.
    * `GET /documents` -> Fetched by `fetch_documents()` to populate document lists.
    * `POST /documents/upload` -> Executed via `upload_file_to_api()` streaming PDFs.
    * `POST /documents/{doc_id}/delete` -> Triggered by JS fetch in document card delete button.
    * `GET /services` -> Fetched by `fetch_services()` to display service catalog.
    * `GET /user/applications` -> Fetched by `fetch_applications()` for the user's ongoing onboarding.
    * `POST /auth/login` & `POST /auth/signup` -> Invoked by `login_user()` and `signup_user()`.
    * `POST /chat/message` -> Invoked by `send_chat_message()` to query the backend LangGraph/Ollama agent.
- `app/golden_dataset_page.py`:
    * Imports `render_golden_dataset_page()` to render the benchmark & evaluation screen.
"""

# Chat-style interface for the Multi-Service Agentic Onboarding System
# Updated with: service discovery, guided onboarding, application management,
# document upload with feedback, auth integration, and sidebar subdivisions.

import streamlit as st
import requests
import time
import os
import re

# ============================================================
# Configuration
# ============================================================
API_BASE = "http://localhost:8000/api/v1"

# ============================================================
# Page setup
# ============================================================
st.set_page_config(
    page_title="DocIntake - AI Document Onboarding",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# CSS - Modern dark theme
# ============================================================
st.markdown("""
<style>
    /* ===== General ===== */
    [data-testid="stAppViewContainer"] {
        background: #0f1117;
        color: #e4e6eb;
    }
    
    [data-testid="stSidebar"] {
        background: #1a1d2e;
        border-right: 1px solid #2a2d3e;
    }
    
    [data-testid="stSidebarContent"] {
        padding-top: 1rem;
    }
    
    /* ===== Navigation ===== */
    .stRadio > label {
        color: #c9ccd3;
        font-size: 0.95rem;
    }
    .stRadio > div[role="radiogroup"] {
        gap: 0.25rem;
    }
    .stRadio > div[role="radiogroup"] > label {
        padding: 0.6rem 1rem;
        border-radius: 8px;
        cursor: pointer;
        transition: background 0.2s;
    }
    .stRadio > div[role="radiogroup"] > label:hover {
        background: #252840;
    }
    .stRadio > div[role="radiogroup"] > label[aria-checked="true"] {
        background: #3b82f6;
        color: white;
    }
    
    /* ===== Main content area ===== */
    section.main {
        padding: 1.5rem 2rem;
    }
    
    /* ===== Chat bubbles ===== */
    .user-bubble {
        background: linear-gradient(135deg, #3b82f6, #2563eb);
        color: white;
        padding: 12px 18px;
        border-radius: 18px 18px 4px 18px;
        margin: 8px 0;
        max-width: 85%;
        align-self: flex-end;
        box-shadow: 0 2px 8px rgba(59,130,246,0.3);
        line-height: 1.5;
    }
    
    .assistant-bubble {
        background: #1e2132;
        color: #e4e6eb;
        padding: 12px 18px;
        border-radius: 18px 18px 18px 4px;
        margin: 8px 0;
        max-width: 85%;
        align-self: flex-start;
        border: 1px solid #2a2d3e;
        line-height: 1.5;
    }
    
    /* ===== Chat input ===== */
    .chat-input-area {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: #1a1d2e;
        border-radius: 24px;
        border: 1px solid #2a2d3e;
        margin-top: 1rem;
    }
    
    .chat-input-area textarea {
        flex: 1;
        background: transparent;
        border: none;
        color: #e4e6eb;
        font-size: 1rem;
        resize: none;
        outline: none;
        padding: 8px;
    }
    
    /* ===== Buttons ===== */
    .stButton > button {
        border-radius: 8px;
        font-weight: 500;
        transition: all 0.2s;
    }
    
    button[kind="primary"] {
        background: #3b82f6;
        border: none;
    }
    button[kind="primary"]:hover {
        background: #2563eb;
    }
    
    button[kind="secondary"] {
        background: #2a2d3e;
        border: 1px solid #3a3d4e;
        color: #c9ccd3;
    }
    
    /* ===== File uploader ===== */
    .stFileUploader > div {
        background: #1e2132;
        border: 2px dashed #2a2d3e;
        border-radius: 12px;
        padding: 2rem;
        transition: border-color 0.2s;
    }
    .stFileUploader > div:hover {
        border-color: #3b82f6;
    }
    
    /* ===== Metrics ===== */
    [data-testid="metric"] {
        background: #1e2132;
        border-radius: 8px;
        padding: 12px 16px;
        border: 1px solid #2a2d3e;
    }
    
    /* ===== Expanders ===== */
    [data-testid="stExpander"] {
        background: #1e2132;
        border: 1px solid #2a2d3e;
        border-radius: 8px;
    }
    
    /* ===== Cards for services/applications ===== */
    .service-card {
        background: #1e2132;
        border: 1px solid #2a2d3e;
        border-radius: 12px;
        padding: 16px;
        margin: 8px 0;
        transition: border-color 0.2s;
        cursor: pointer;
    }
    .service-card:hover {
        border-color: #3b82f6;
    }
    
    .application-card {
        background: #1e2132;
        border: 1px solid #2a2d3e;
        border-radius: 12px;
        padding: 16px;
        margin: 8px 0;
        transition: border-color 0.2s;
    }
    .application-card:hover {
        border-color: #3b82f6;
    }
    
    /* ===== Headers ===== */
    h1, h2, h3 {
        color: #e4e6eb;
    }
    
    /* ===== Status indicators ===== */
    .status-healthy { color: #22c55e; }
    .status-error { color: #ef4444; }
    
    /* ===== Progress bar ===== */
    .stProgress > div > div > div {
        background: #3b82f6;
    }
    
    /* ===== Scrollbar ===== */
    ::-webkit-scrollbar {
        width: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #0f1117;
    }
    ::-webkit-scrollbar-thumb {
        background: #2a2d3e;
        border-radius: 4px;
    }
    ::-webkit-scrollbar-thumb:hover {
        background: #3a3d4e;
    }
    
    /* ===== Caption / small text ===== */
    .stCaption {
        color: #6b7280;
    }
    
    /* ===== Sidebar title ===== */
    .sidebar-title {
        color: #e4e6eb;
        font-size: 1.5rem;
        font-weight: 600;
        margin-bottom: 1.5rem;
        padding-bottom: 0.75rem;
        border-bottom: 1px solid #2a2d3e;
    }
    
    /* ===== Section headers in sidebar ===== */
    .sidebar-section-title {
        color: #6b7280;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin: 1.5rem 0 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ============================================================
# Session state
# ============================================================
if "messages" not in st.session_state:
    st.session_state.messages = []

if "sidebar_page" not in st.session_state:
    st.session_state.sidebar_page = "home"

if "documents_cache" not in st.session_state:
    st.session_state.documents_cache = None
    st.session_state.documents_cache_time = 0

if "upload_status" not in st.session_state:
    st.session_state.upload_status = None
    st.session_state.upload_error = None

if "current_application" not in st.session_state:
    st.session_state.current_application = None

if "user_id" not in st.session_state:
    st.session_state.user_id = None

if "user_token" not in st.session_state:
    st.session_state.user_token = None

if "user_email" not in st.session_state:
    st.session_state.user_email = None

if "user_username" not in st.session_state:
    st.session_state.user_username = None

# ============================================================
# API helpers
# ============================================================
@st.cache_data(ttl=10)
def check_api_connection() -> bool:
    """
    Check if the FastAPI backend service is alive and healthy.

    Interconnections:
    - Calls: `GET {API_BASE}/health` on the backend FastAPI server (`app.api.main`).
    - Called By: Streamlit sidebar status renderer to display system connectivity indicator.

    Returns:
        bool: True if backend responds with HTTP 200 within timeout; False otherwise.
    """
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False

@st.cache_data(ttl=15)
def fetch_documents() -> list:
    """
    Fetch the list of registered and ingested documents from the backend API.

    Interconnections:
    - Calls: `GET {API_BASE}/documents` (handled by `app.api.routes.documents.get_documents`).
    - Touches: PostgreSQL `documents` table via the backend.
    - Called By: Streamlit sidebar document counter and the '📁 Documents' page card view.

    Returns:
        list: A list of document metadata dictionaries (id, filename, file_size, status, etc.).
    """
    try:
        resp = requests.get(f"{API_BASE}/documents", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("documents", [])
    except Exception:
        pass
    return []

@st.cache_data(ttl=60)
def fetch_services() -> list:
    """
    Fetch available onboarding services configuration from the backend.

    Interconnections:
    - Calls: `GET {API_BASE}/services` (handled by `app.api.routes.services` or catalog router).
    - Touches: PostgreSQL `services` / `service_definitions` table via backend.
    - Called By: Streamlit sidebar service listing and the '🏠 Home' service card view.

    Returns:
        list: List of service dictionaries containing id, name, description,
              documents_required, and processing_time.
    """
    try:
        resp = requests.get(f"{API_BASE}/services", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("services", [])
    except Exception:
        pass
    return []

@st.cache_data(ttl=15)
def fetch_applications() -> list:
    """
    Retrieve onboarding applications for the currently authenticated user.

    Interconnections:
    - Reads: `st.session_state.user_id`.
    - Calls: `GET {API_BASE}/user/applications?user_id=...` (handled by `app.api.routes.applications`).
    - Touches: PostgreSQL `applications` table filtered by `user_id`.
    - Called By: '📋 Applications' view and the application dropdown in the '📤 Upload' view.

    Returns:
        list: List of application dicts with status, created_at, documents list, etc.
    """
    try:
        if st.session_state.user_id:
            resp = requests.get(f"{API_BASE}/user/applications?user_id={st.session_state.user_id}", timeout=10)
            if resp.status_code == 200:
                return resp.json().get("data", [])
    except Exception:
        pass
    return []

def login_user(username: str, password: str) -> dict:
    """
    Authenticate an existing user against the backend auth endpoint.

    Interconnections:
    - Calls: `POST {API_BASE}/auth/login` (handled by `app.api.routes.auth.login`).
    - Touches: PostgreSQL `users` table verifying hashed passwords (bcrypt).
    - Called By: '🔐 Login' page submission button.
    - Updates: `st.session_state` with `user_id`, `user_token`, `user_email`, `user_username`.

    Args:
        username (str): Username or email string.
        password (str): Plaintext password to verify.

    Returns:
        dict: API JSON response containing success flag, token, user details, or error message.
    """
    try:
        resp = requests.post(
            f"{API_BASE}/auth/login",
            json={"username": username, "password": password},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Login failed"}

def signup_user(username: str, password: str, email: str) -> dict:
    """
    Register a new user account via the backend authentication service.

    Interconnections:
    - Calls: `POST {API_BASE}/auth/signup` (handled by `app.api.routes.auth.signup`).
    - Touches: Inserts new user record into PostgreSQL `users` table.
    - Called By: '🔐 Login' page under the 'Sign Up' tab.

    Args:
        username (str): Alphanumeric username.
        password (str): Password meeting security complexity constraints.
        email (str): Valid email address.

    Returns:
        dict: Response payload indicating registration success or validation failure.
    """
    try:
        resp = requests.post(
            f"{API_BASE}/auth/signup",
            json={"username": username, "password": password, "email": email},
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Signup failed"}

def upload_file_to_api(file, application_id=None) -> dict:
    """
    Upload a PDF document to the backend API for ingestion, OCR/extraction, and indexing.

    Interconnections:
    - Calls: `POST {API_BASE}/documents/upload` as multipart/form-data.
    - Touches: Backend streams raw PDF bytes to MinIO object storage, saves metadata
      to PostgreSQL `documents`, and enqueues document chunks into PGVector.
    - Called By:
        * '💬 Chat' page when a PDF is attached alongside chat prompts.
        * '📤 Upload' page for standalone document onboarding.

    Args:
        file: UploadedFile object from Streamlit `st.file_uploader`.
        application_id (str, optional): ID of the application to link document to.

    Returns:
        dict: JSON response with `success`, `data` (document info), or `error`.
    """
    try:
        files = {"file": (file.name, file, "application/pdf")}
        data = {}
        if application_id:
            data["application_id"] = application_id
        resp = requests.post(
            f"{API_BASE}/documents/upload",
            files=files,
            data=data,
            timeout=300
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": f"HTTP {resp.status_code}"}

def send_chat_message(query: str) -> dict:
    """
    Dispatch a conversational query to the backend agentic chat endpoint.

    Interconnections:
    - Calls: `POST {API_BASE}/chat/message` (handled by `app.api.routes.chat.chat_message`).
    - Touches: Backend LangGraph multi-agent supervisor/workflow, Ollama LLM, PGVector
      semantic search index, and application state machines.
    - Called By: Streamlit '💬 Chat' interface on prompt submission.

    Args:
        query (str): User text prompt/inquiry.

    Returns:
        dict: Response payload containing assistant `response`, `sources`,
              `confidence`, `intent`, and `matched_service`.
    """
    try:
        resp = requests.post(
            f"{API_BASE}/chat/message",
            json={"query": query, "context_limit": 5},
            timeout=120
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception as e:
        return {"response": f"Error: {str(e)}", "sources": [], "confidence": 0.0}
    return {"response": "Error: Could not get response", "sources": [], "confidence": 0.0}

def format_size(bytes_val: float) -> str:
    """
    Format byte counts into human-readable strings (B, KB, MB, GB, TB).

    Interconnections:
    - Called By: Document rendering tables, file metrics cards in '📤 Upload' and '📁 Documents'.

    Args:
        bytes_val (float): Size in bytes.

    Returns:
        str: Scaled and formatted string representation (e.g., '14.2 MB').
    """
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

# ============================================================
# Validation helpers
# ============================================================
def validate_password_strength(password: str) -> tuple[bool, str]:
    """
    Validate that password meets security complexity requirements.

    Requirements:
    - At least 8 characters.
    - At least 1 uppercase letter.
    - At least 1 lowercase letter.
    - At least 1 digit.
    - At least 1 special character.

    Interconnections:
    - Called By: '🔐 Login' -> 'Sign Up' form validation logic.

    Args:
        password (str): The candidate password string.

    Returns:
        tuple[bool, str]: (is_valid, error_message).
    """
    errors = []
    if len(password) < 8:
        errors.append("At least 8 characters")
    if not re.search(r'[A-Z]', password):
        errors.append("1 uppercase letter")
    if not re.search(r'[a-z]', password):
        errors.append("1 lowercase letter")
    if not re.search(r'[0-9]', password):
        errors.append("1 number")
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};\'\\:"|,.<>\/?`~]', password):
        errors.append("1 special character (!@#$%^&* etc.)")
    
    if errors:
        return False, "Password needs: " + ", ".join(errors)
    return True, ""

def validate_username_format(username: str) -> tuple[bool, str]:
    """
    Validate username format ensuring alphanumeric characters and underscores only.

    Interconnections:
    - Called By: '🔐 Login' -> 'Sign Up' form validation logic.

    Args:
        username (str): Candidate username string.

    Returns:
        tuple[bool, str]: (is_valid, error_message).
    """
    if not username:
        return False, "Username cannot be empty"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Username can only contain letters, numbers, and underscores. No special characters."
    return True, ""

def validate_email_format(email: str) -> tuple[bool, str]:
    """
    Validate email address format using standard regex matching.

    Interconnections:
    - Called By: '🔐 Login' -> 'Sign Up' form validation logic.

    Args:
        email (str): Candidate email string.

    Returns:
        tuple[bool, str]: (is_valid, error_message).
    """
    if not email:
        return False, "Email cannot be empty"
    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        return False, "Please enter a valid email address"
    return True, ""

# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    st.markdown('<div class="sidebar-title">📄 DocIntake</div>', unsafe_allow_html=True)
    
    st.markdown('<div class="sidebar-section-title">Navigation</div>', unsafe_allow_html=True)
    
    page = st.radio(
        "",
        ["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏆 Golden Dataset", "🔐 Login"],
        index=["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏆 Golden Dataset", "🔐 Login"].index(st.session_state.sidebar_page) if st.session_state.sidebar_page in ["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏆 Golden Dataset", "🔐 Login"] else 0,
        label_visibility="collapsed"
    )
    
    # Persist the selected page
    st.session_state.sidebar_page = page
    
    st.markdown('<div class="sidebar-section-title">Services</div>', unsafe_allow_html=True)
    services = fetch_services()
    for svc in services:
        status_icon = "✅" if svc.get("status") == "available" else "⏳"
        st.caption(f"{status_icon} {svc.get('name', svc.get('id', 'Unknown'))}")
    
    st.markdown('<div class="sidebar-section-title">System</div>', unsafe_allow_html=True)
    
    api_ok = check_api_connection()
    if api_ok:
        st.success("● Connected", icon="✅")
    else:
        st.error("● Disconnected", icon="❌")
    
    if page == "📁 Documents":
        docs = fetch_documents()
        st.caption(f"{len(docs)} documents")
    
    if st.session_state.user_id:
        st.caption(f"Logged in as: {st.session_state.user_username or st.session_state.user_id}")
        if st.button("Logout", type="secondary", use_container_width=True):
            st.session_state.user_id = None
            st.session_state.user_token = None
            st.session_state.user_email = None
            st.session_state.user_username = None
            st.rerun()

# ============================================================
# Page routing
# ============================================================

from app.golden_dataset_page import render_golden_dataset_page

# Home page
if page == "🏠 Home":
    st.markdown('<h2 style="color:#e4e6eb">🏠 Welcome to DocIntake</h2>', unsafe_allow_html=True)
    st.caption("Multi-Service Agentic Onboarding System")
    
    st.markdown("---")
    st.markdown("### Available Services")
    
    services = fetch_services()
    if services:
        for svc in services:
            status_text = "Available" if svc.get("status") == "available" else "Coming Soon"
            st.markdown(f'''
<div class="service-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <div style="font-size:1rem;font-weight:500;color:#e4e6eb;">📋 {svc.get('name', svc.get('id', 'Service'))}</div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">{svc.get('description', '')}</div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">
                Documents: {', '.join(svc.get('documents_required', []))}
            </div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">
                Processing time: {svc.get('processing_time', 'N/A')}
            </div>
        </div>
        <div style="text-align:center;">
            <div style="font-size:1.5rem;">{"✅" if svc.get('status') == 'available' else '⏳'}</div>
            <div style="font-size:0.85rem;color:#6b7280;">{status_text}</div>
        </div>
    </div>
</div>
''', unsafe_allow_html=True)
    else:
        st.info("No services available")

# Chat page
elif page == "💬 Chat":
    st.markdown('<h2 style="color:#e4e6eb">💬 Chat</h2>', unsafe_allow_html=True)
    st.caption("Ask questions about services or have a conversation.")
    
    # Chat messages area
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.markdown(f'<div class="user-bubble">{msg["content"]}</div>', unsafe_allow_html=True)
            else:
                bubble_html = msg.get("response", "")
                if msg.get("confidence"):
                    conf = msg["confidence"]
                    color = "#22c55e" if conf > 0.7 else "#f59e0b" if conf > 0.4 else "#ef4444"
                    bubble_html += f'<div style="margin-top:8px;font-size:0.85rem;color:{color}">🎯 Confidence: {conf:.1%}</div>'
                if msg.get("intent"):
                    intent_text = {"faq": "FAQ", "apply": "Application"}
                    bubble_html += f'<div style="margin-top:4px;font-size:0.85rem;color:#6b7280">Intent: {intent_text.get(msg["intent"], msg["intent"])}</div>'
                if msg.get("matched_service"):
                    bubble_html += f'<div style="margin-top:4px;font-size:0.85rem;color:#6b7280">Service: {msg["matched_service"]}</div>'
                if msg.get("sources"):
                    sources_html = ""
                    for src in msg["sources"]:
                        sim = src.get("similarity", 0)
                        sources_html += f'<div style="margin-top:4px;font-size:0.85rem;color:#6b7280">📚 <b>{src["filename"]}</b> ({sim:.2%})</div>'
                    bubble_html += sources_html
                st.markdown(f'<div class="assistant-bubble">{bubble_html}</div>', unsafe_allow_html=True)
    
    # Input area
    chat_col1, chat_col2 = st.columns([9, 1])
    
    with chat_col1:
        file_uploader = st.file_uploader(
            "📎 Attach PDF",
            type=["pdf"],
            label_visibility="collapsed",
            key="chat_file_uploader",
            help="Attach a PDF to upload and include in context"
        )
        send_prompt = st.chat_input("Type your message...")
    
    # Handle send
    if send_prompt:
        # Upload attached file first if present
        if file_uploader:
            with st.spinner("📤 Uploading document..."):
                result = upload_file_to_api(file_uploader)
            if result.get("success"):
                st.session_state.messages.append({"role": "system", "content": f"✅ Document uploaded: {result.get('data', {}).get('filename', file_uploader.name)}"})
            else:
                st.session_state.messages.append({"role": "system", "content": f"⚠️ Upload failed: {result.get('error', 'Unknown')}"})
        
        # Add user message
        st.session_state.messages.append({"role": "user", "content": send_prompt})
        
        # Get AI response with spinner
        with st.spinner("🤔 Thinking..."):
            response = send_chat_message(send_prompt)
        
        st.session_state.messages.append({
            "role": "assistant",
            "content": send_prompt,
            "response": response.get("response", "No response"),
            "sources": response.get("sources", []),
            "confidence": response.get("confidence", 0.0),
            "intent": response.get("intent"),
            "matched_service": response.get("matched_service")
        })
        
        st.rerun()
    
    # Clear button
    if st.session_state.messages:
        if st.button("🗑️ Clear Chat", type="secondary", use_container_width=False):
            st.session_state.messages = []
            st.rerun()

# Documents page
elif page == "📁 Documents":
    st.markdown('<h2 style="color:#e4e6eb">📁 Documents</h2>', unsafe_allow_html=True)
    st.caption("Manage and view your uploaded documents.")
    
    # Refresh button
    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("🔄 Refresh", use_container_width=True):
            st.session_state.documents_cache = None
            st.rerun()
    
    docs = fetch_documents()
    
    if not docs:
        st.info("📭 No documents yet. Go to Upload to add some!")
    else:
        for doc in docs:
            with st.container():
                st.markdown(f'''
<div class="doc-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <div style="font-size:1rem;font-weight:500;color:#e4e6eb;">📄 {doc.get('filename', 'Unknown')}</div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">
                Uploaded: {doc.get('upload_date', 'N/A')}
            </div>
        </div>
        <div style="display:flex;gap:2rem;align-items:center;">
            <div style="text-align:center;">
                <div style="font-size:0.75rem;color:#6b7280;">Size</div>
                <div style="font-size:1rem;color:#e4e6eb;">{format_size(doc.get('file_size', 0))}</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size:0.75rem;color:#6b7280;">Status</div>
                <div style="font-size:1rem;color:#3b82f6;">{doc.get('status', 'Unknown')}</div>
            </div>
            <button 
                onclick="fetch('{API_BASE}/documents/{doc.get('id','')}/delete', {{method:'POST'}}).then(()=>location.reload())"
                style="background:#ef4444;color:white;border:none;padding:6px 12px;border-radius:6px;cursor:pointer;font-size:0.85rem;"
            >🗑️ Delete</button>
        </div>
    </div>
</div>
''', unsafe_allow_html=True)

# Upload page
elif page == "📤 Upload":
    if not st.session_state.user_id:
        st.markdown('<h2 style="color:#e4e6eb">📤 Upload Document</h2>', unsafe_allow_html=True)
        st.caption("Document ingestion requires authentication.")
        st.info("🔐 Please login to upload and ingest documents. Unauthenticated users can still chat with the bot.")
        if st.button("🔐 Go to Login", type="primary", use_container_width=True):
            st.session_state.sidebar_page = "🔐 Login"
            st.rerun()
    else:
        st.markdown('<h2 style="color:#e4e6eb">📤 Upload Document</h2>', unsafe_allow_html=True)
        st.caption("Upload PDF files for processing and search. (Max 200MB per file)")
        
        uploaded_file = st.file_uploader(
            "",
            type=["pdf"],
            label_visibility="collapsed"
        )
        
        if uploaded_file:
            st.markdown("---")
            
            # File info cards
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Filename", uploaded_file.name[:40] + "..." if len(uploaded_file.name) > 40 else uploaded_file.name)
            with c2:
                st.metric("Size", format_size(uploaded_file.size))
            with c3:
                st.metric("Type", "PDF Document")
            
            st.markdown("")
            
            # Application selector if user has applications
            application_id = None
            if st.session_state.user_id and st.session_state.current_application:
                application_id = st.session_state.current_application
            
            if not application_id:
                apps = fetch_applications()
                if apps:
                    app_select = st.selectbox(
                        "Select Application",
                        options=[None] + [a.get("id") for a in apps],
                        format_func=lambda x: f"Application {x}" if x else "No Application",
                        key="app_select"
                    )
                    application_id = app_select
            
            upload_btn = st.button("📤 Upload & Process", type="primary", use_container_width=True)
            
            if upload_btn:
                with st.spinner("🔄 Uploading and processing..."):
                    result = upload_file_to_api(uploaded_file, application_id)
                
                if result.get("success"):
                    st.success(f"✅ {result.get('message', 'Uploaded!')}")
                    st.json(result.get("data", {}))
                else:
                    st.error(f"⚠️ Upload failed: {result.get('error', 'Unknown error')}")

# Applications page
elif page == "📋 Applications":
    st.markdown('<h2 style="color:#e4e6eb">📋 Applications</h2>', unsafe_allow_html=True)
    st.caption("View and manage your service applications.")
    
    if not st.session_state.user_id:
        st.info("🔐 Please login to view your applications.")
    else:
        apps = fetch_applications()
        
        if not apps:
            st.info("📭 No applications yet. Chat with us to start one!")
        else:
            for app in apps:
                status_color = {
                    "incomplete": "#3b82f6",
                    "validating": "#f59e0b",
                    "needs_human_review": "#f97316",
                    "complete": "#22c55e",
                    "rejected": "#ef4444",
                    "unverifiable": "#6b7280"
                }
                status_color_val = status_color.get(app.get("status", ""), "#6b7280")
                
                st.markdown(f'''
<div class="application-card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
        <div>
            <div style="font-size:1rem;font-weight:500;color:#e4e6eb;">📋 Application #{app.get('id', 'N/A')}</div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">
                Service: {app.get('service_id', 'Unknown')}
            </div>
            <div style="font-size:0.85rem;color:#6b7280;margin-top:4px;">
                Created: {app.get('created_at', 'N/A')[:10]}
            </div>
        </div>
        <div style="display:flex;gap:2rem;align-items:center;">
            <div style="text-align:center;">
                <div style="font-size:0.75rem;color:#6b7280;">Status</div>
                <div style="font-size:1rem;color:{status_color_val};">{app.get('status', 'Unknown').replace('_', ' ').title()}</div>
            </div>
            <div style="text-align:center;">
                <div style="font-size:0.75rem;color:#6b7280;">Documents</div>
                <div style="font-size:1rem;color:#e4e6eb;">{len(app.get('documents', []))}</div>
            </div>
        </div>
    </div>
</div>
''', unsafe_allow_html=True)

# Golden Dataset page
elif page == "🏆 Golden Dataset":
    render_golden_dataset_page()

# Login page - with back button and email support
elif page == "🔐 Login":
    st.markdown('<h2 style="color:#e4e6eb">🔐 Authentication</h2>', unsafe_allow_html=True)
    st.caption("Login or create an account to manage applications and upload documents.")
    
    # Back button - returns to chat without losing messages
    # Uses a hidden key to trigger a rerun that switches the sidebar page
    if st.button("← Back to Chat", key="_back_to_chat", type="secondary", use_container_width=True):
        st.session_state.sidebar_page = "💬 Chat"
        st.rerun()
    
    st.markdown("")  # spacer
    
    action = st.radio("", ["Login", "Sign Up"])
    
    # Show password requirements on Sign Up
    if action == "Sign Up":
        with st.expander("📋 Password Requirements", expanded=False):
            st.markdown("""
            Your password must include:
            - ✅ At least 8 characters
            - ✅ At least 1 uppercase letter (A-Z)
            - ✅ At least 1 lowercase letter (a-z)
            - ✅ At least 1 number (0-9)
            - ✅ At least 1 special character (!@#$%^&* etc.)
            
            **Username**: Only letters, numbers, and underscores allowed. No special characters.
            """)
    
    username = st.text_input("Username", key="login_username")
    email = st.text_input("Email", key="login_email", help="Used for account identification")
    password = st.text_input("Password", type="password", key="login_password")
    
    if st.button("Submit", type="primary", use_container_width=True):
        if not username or not password:
            st.error("Please enter username and password")
        else:
            with st.spinner("Processing..."):
                if action == "Login":
                    # Login: use username field for both username or email
                    result = login_user(username, password)
                    
                    if result.get("success"):
                        data = result.get("data", {})
                        st.session_state.user_id = data.get("user_id")
                        st.session_state.user_token = data.get("token")
                        st.session_state.user_email = data.get("email", username)
                        st.session_state.user_username = data.get("username", username)
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error(f"Login failed: {result.get('error', result.get('detail', 'Unknown error'))}")
                else:
                    # Sign Up: validate all fields
                    errors = []
                    
                    # Validate username
                    valid, msg = validate_username_format(username)
                    if not valid:
                        errors.append(msg)
                    
                    # Validate email
                    valid, msg = validate_email_format(email)
                    if not valid:
                        errors.append(msg)
                    
                    # Validate password
                    valid, msg = validate_password_strength(password)
                    if not valid:
                        errors.append(msg)
                    
                    if errors:
                        st.error("Validation errors:\n- " + "\n- ".join(errors))
                    else:
                        result = signup_user(username, password, email)
                        
                        if result.get("success"):
                            st.success("Account created! You can now login.")
                            st.rerun()
                        else:
                            error_msg = result.get('error', result.get('detail', 'Unknown error'))
                            st.error(f"Signup failed: {error_msg}")

# Footer
st.markdown("---")
st.caption("Multi-Service Agentic Onboarding | Built with FastAPI & Streamlit | Powered by Ollama")
