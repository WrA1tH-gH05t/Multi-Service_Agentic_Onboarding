"""DocIntake Streamlit Frontend Application."""

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

if "user_role" not in st.session_state:
    st.session_state.user_role = "applicant"

if "user_agency" not in st.session_state:
    st.session_state.user_agency = None

# ============================================================
# API helpers
# ============================================================
@st.cache_data(ttl=10)
def check_api_connection() -> bool:
    """Check if the FastAPI backend service is alive and healthy."""
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False

@st.cache_data(ttl=15)
def fetch_documents() -> list:
    """Fetch the list of registered and ingested documents from the backend API."""
    try:
        resp = requests.get(f"{API_BASE}/documents", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("documents", [])
    except Exception:
        pass
    return []

@st.cache_data(ttl=60)
def fetch_services() -> list:
    """Fetch available onboarding services configuration from the backend."""
    try:
        resp = requests.get(f"{API_BASE}/services", timeout=10)
        if resp.status_code == 200:
            return resp.json().get("data", {}).get("services", [])
    except Exception:
        pass
    return []

@st.cache_data(ttl=15)
def fetch_applications() -> list:
    """Retrieve onboarding applications for the currently authenticated user."""
    try:
        if st.session_state.user_id:
            resp = requests.get(f"{API_BASE}/user/applications?user_id={st.session_state.user_id}", timeout=10)
            if resp.status_code == 200:
                return resp.json().get("data", [])
    except Exception:
        pass
    return []

def login_user(username: str, password: str) -> dict:
    """Authenticate an existing user against the backend auth endpoint."""
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

def signup_user(username: str, password: str, email: str, accept_terms: bool = False, role: str = "applicant", agency_id: str = None) -> dict:
    """Register a new user account via the backend authentication service."""
    try:
        resp = requests.post(
            f"{API_BASE}/auth/signup",
            json={
                "username": username,
                "password": password,
                "email": email,
                "accept_terms": accept_terms,
                "role": role,
                "agency_id": agency_id
            },
            timeout=10
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            try:
                err_data = resp.json()
                return {"success": False, "error": err_data.get("detail", "Signup failed")}
            except Exception:
                return {"success": False, "error": resp.text}
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Signup failed"}

def upload_file_to_api(file, application_id=None) -> dict:
    """Upload a PDF document to the backend API for ingestion, OCR/extraction, and indexing."""
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
    """Dispatch a conversational query to the backend agentic chat endpoint."""
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
    """Format byte counts into human-readable strings (B, KB, MB, GB, TB)."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"

# ============================================================
# Validation helpers
# ============================================================
def validate_password_strength(password: str) -> tuple[bool, str]:
    """Validate that password meets security complexity requirements."""
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
    """Validate username format ensuring alphanumeric characters and underscores only."""
    if not username:
        return False, "Username cannot be empty"
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Username can only contain letters, numbers, and underscores. No special characters."
    return True, ""

def validate_email_format(email: str) -> tuple[bool, str]:
    """Validate email address format using standard regex matching."""
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
        ["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏛️ Agency Review", "📜 Legal Policies", "🏆 Golden Dataset", "🔐 Login"],
        index=["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏛️ Agency Review", "📜 Legal Policies", "🏆 Golden Dataset", "🔐 Login"].index(st.session_state.sidebar_page) if st.session_state.sidebar_page in ["🏠 Home", "💬 Chat", "📁 Documents", "📤 Upload", "📋 Applications", "🏛️ Agency Review", "📜 Legal Policies", "🏆 Golden Dataset", "🔐 Login"] else 0,
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
        role_label = f" ({st.session_state.user_role.replace('_', ' ').title()})" if st.session_state.user_role else ""
        agency_label = f" [{st.session_state.user_agency}]" if st.session_state.user_agency else ""
        st.caption(f"Logged in: **{st.session_state.user_username or st.session_state.user_id}**{role_label}{agency_label}")
        if st.button("Logout", type="secondary", use_container_width=True):
            st.session_state.user_id = None
            st.session_state.user_token = None
            st.session_state.user_email = None
            st.session_state.user_username = None
            st.session_state.user_role = "applicant"
            st.session_state.user_agency = None
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

                # Application-Specific Document Review Consent Flow
                app_id = app.get("id") or app.get("application_id")
                app_status = app.get("status", "")

                with st.expander(f"🛡️ Document Review Consent & Routing - App #{app_id}", expanded=(app_status in ("incomplete", "needs_review", "complete", "validating"))):
                    # Fetch consent info
                    consent_resp = None
                    try:
                        c_get = requests.get(f"{API_BASE}/applications/{app_id}/consent-info", headers={"token": st.session_state.user_token or ""}, params={"token": st.session_state.user_token or ""}, timeout=5)
                        if c_get.status_code == 200:
                            consent_resp = c_get.json().get("data", {})
                    except Exception:
                        pass

                    if consent_resp:
                        st.markdown(f"### {consent_resp.get('consent_screen_title', 'DOCUMENT REVIEW CONSENT')}")
                        st.info(f"**Designated Reviewing Body**: {consent_resp.get('designated_agency_name')} ({consent_resp.get('designated_agency_id')})\n\n{consent_resp.get('designated_agency_description')}")
                        st.markdown(consent_resp.get("consent_text", ""))

                        st.markdown("---")
                        st.markdown(f"**Legal References:** [Terms & Conditions]({API_BASE}/policies/terms) | [Privacy Policy]({API_BASE}/policies/privacy)")

                        curr_consent = consent_resp.get("current_consent_status")
                        if curr_consent == "agreed":
                            st.success(f"✅ Document Review Consent has been granted. Application routed to {consent_resp.get('designated_agency_name')}.")
                            if st.button(f"Withdraw Consent for #{app_id}", key=f"withdraw_{app_id}", type="secondary"):
                                w_res = requests.post(
                                    f"{API_BASE}/applications/{app_id}/withdraw-consent",
                                    headers={"token": st.session_state.user_token or ""},
                                    params={"token": st.session_state.user_token or ""},
                                    json={"withdrawal_reason": "Applicant exercised statutory withdrawal right."},
                                    timeout=10
                                )
                                if w_res.status_code == 200:
                                    st.warning("Consent withdrawn. Application processing halted.")
                                    st.rerun()
                                else:
                                    st.error(f"Withdrawal failed: {w_res.text}")
                        elif curr_consent == "declined" or app_status == "rejected_consent_declined":
                            st.error("❌ Document Review Consent was declined. This application is closed and staged document binaries were purged. A new application is required.")
                        elif curr_consent == "withdrawn" or app_status == "cancelled_consent_withdrawn":
                            st.warning("⚠️ Consent has been formally withdrawn. This application is cancelled.")
                        else:
                            st.warning("⚠️ Pending Document Review Authorization: Before your application can proceed to government inspection, you must provide your explicit consent.")
                            user_consented = st.checkbox(
                                consent_resp.get("checkbox_wording", "I authorize Docintake to make the documents submitted with this specific application available to the designated authorized reviewers."),
                                value=False,
                                key=f"consent_check_{app_id}"
                            )
                            c1, c2 = st.columns(2)
                            with c1:
                                if st.button("Agree and Continue", key=f"btn_agree_{app_id}", type="primary", use_container_width=True):
                                    if not user_consented:
                                        st.error("Please actively check the consent checkbox to agree and continue.")
                                    else:
                                        with st.spinner("Authorizing and routing application..."):
                                            agree_resp = requests.post(
                                                f"{API_BASE}/applications/{app_id}/consent",
                                                headers={"token": st.session_state.user_token or ""},
                                                params={"token": st.session_state.user_token or ""},
                                                json={"application_id": app_id, "agreed": True, "consent_version": "1.0"},
                                                timeout=10
                                            )
                                            if agree_resp.status_code == 200:
                                                st.success("Consent recorded! Application routed to agency review.")
                                                st.rerun()
                                            else:
                                                st.error(f"Error submitting consent: {agree_resp.text}")
                            with c2:
                                if st.button("Decline Consent", key=f"btn_decline_{app_id}", type="secondary", use_container_width=True):
                                    with st.spinner("Closing application and purging staged files..."):
                                        dec_resp = requests.post(
                                            f"{API_BASE}/applications/{app_id}/consent",
                                            headers={"token": st.session_state.user_token or ""},
                                            params={"token": st.session_state.user_token or ""},
                                            json={"application_id": app_id, "agreed": False, "consent_version": "1.0"},
                                            timeout=10
                                        )
                                        if dec_resp.status_code == 200:
                                            st.warning("Consent declined. Application closed and temporary files purged.")
                                            st.rerun()
                                        else:
                                            st.error(f"Error declining consent: {dec_resp.text}")
                    else:
                        st.caption("Consent information currently loading...")

# Agency Review Page (Government Reviewer Portal)
elif page == "🏛️ Agency Review":
    st.markdown('<h2 style="color:#e4e6eb">🏛️ Government Agency Review Portal</h2>', unsafe_allow_html=True)
    st.caption("Secure document inspection portal for authorized government bodies.")

    if not st.session_state.user_id:
        st.info("🔐 Please sign in with an authorized Government Reviewer account.")
    elif st.session_state.user_role == "developer":
        st.error("🚫 Access Forbidden: Application Developers are strictly prohibited from accessing customer document review portals.")
    elif st.session_state.user_role != "government_reviewer":
        st.warning(f"⚠️ Access Restricted: Current role is '{st.session_state.user_role}'. This portal is restricted exclusively to authorized Government Agency Reviewers.")
    else:
        st.markdown(f"**Assigned Agency:** `{st.session_state.user_agency or 'Unassigned'}`")
        try:
            resp = requests.get(
                f"{API_BASE}/agency/applications",
                headers={"token": st.session_state.user_token or ""},
                params={"token": st.session_state.user_token or ""},
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                apps = data.get("data", [])
                st.caption(f"Showing {len(apps)} applications designated for {data.get('agency_id')}.")
                if not apps:
                    st.info("📭 No applications currently awaiting review for your agency queue.")
                else:
                    for a in apps:
                        with st.expander(f"📋 Application #{a['application_id']} - {a['applicant_name']} ({a['service_id']})"):
                            st.write(f"**Applicant:** {a['applicant_name']}")
                            st.write(f"**Service:** {a['service_id']}")
                            st.write(f"**Status:** {a['status']}")
                            st.write(f"**Created:** {a.get('created_at', 'N/A')}")
                            st.markdown("---")
                            st.markdown("#### Authorized Documents")
                            for d in a.get("documents", []):
                                col_d1, col_d2 = st.columns([3, 1])
                                with col_d1:
                                    st.write(f"📄 **{d['filename']}** ({d['document_type']}) - {format_size(d['file_size'])}")
                                with col_d2:
                                    doc_url = f"{API_BASE}/documents/{d['document_id']}/view?token={st.session_state.user_token}"
                                    st.markdown(f"[👁️ Inspect Document]({doc_url})")
            else:
                st.error(f"Failed to fetch agency applications: {resp.text}")
        except Exception as e:
            st.error(f"Error connecting to review queue: {e}")

# Legal Policies Page
elif page == "📜 Legal Policies":
    st.markdown('<h2 style="color:#e4e6eb">📜 Legal Policies & Compliance Framework</h2>', unsafe_allow_html=True)
    st.caption("Formal legal drafts and statutory data protection disclosures for Docintake.")

    tab1, tab2 = st.tabs(["📄 Terms & Conditions", "🛡️ Privacy Policy"])

    with tab1:
        st.markdown("### Docintake Terms & Conditions and Service Policy (v1.0 DRAFT)")
        st.markdown("""
        - **Company Name:** Docintake
        - **Registered Address:** N/A
        - **Jurisdiction:** United Arab Emirates
        - **Support Email:** `[SUPPORT EMAIL PLACEHOLDER]`
        - **Document Status:** `DRAFT — PENDING LEGAL APPROVAL`
        """)
        st.markdown(f"[📥 Download Official PDF Document (v1.0 DRAFT)]({API_BASE}/policies/terms/download)")
        st.markdown(f"[🌐 Open Full In-App HTML Policy View]({API_BASE}/policies/terms)")

    with tab2:
        st.markdown("### Docintake Privacy Policy & Data Protection Framework (v1.0 DRAFT)")
        st.markdown("""
        - **Private On-Premise Infrastructure:** MinIO object storage & PostgreSQL database.
        - **Zero Cloud Leakage:** Documents are never sent to external third-party public AI APIs.
        - **Developer Restriction:** Developers strictly prohibited from customer document binaries.
        - **Government Agency Routing:** Compartmentalized access by assigned agency with immutable audit logging.
        - **Privacy Inquiries:** `[PRIVACY CONTACT PLACEHOLDER]`
        """)
        st.markdown(f"[📥 Download Official PDF Document (v1.0 DRAFT)]({API_BASE}/policies/privacy/download)")
        st.markdown(f"[🌐 Open Full In-App HTML Policy View]({API_BASE}/policies/privacy)")

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
    
    accept_terms = False
    selected_role = "applicant"
    selected_agency = None

    if action == "Sign Up":
        # Role selection
        st.markdown("---")
        st.markdown("**Account Role & Review Scope**")
        role_display = st.selectbox(
            "Select Account Role",
            ["Applicant (Standard Onboarding)", "Government Agency Reviewer", "Platform Developer (Restricted Content Access)", "Platform Administrator", "Compliance Reviewer"],
            index=0,
            key="signup_role_display"
        )
        role_map = {
            "Applicant (Standard Onboarding)": "applicant",
            "Government Agency Reviewer": "government_reviewer",
            "Platform Developer (Restricted Content Access)": "developer",
            "Platform Administrator": "platform_admin",
            "Compliance Reviewer": "compliance_reviewer"
        }
        selected_role = role_map[role_display]

        if selected_role == "government_reviewer":
            agency_map = {
                "Roads & Transport Authority (RTA) - Mobility / Rental": "mobility_rta",
                "Identity & Onboarding Review Authority - Basic Registration": "identity_authority",
                "Cross-Border Inspection Authority - Premium / Cross Border": "crossborder_authority"
            }
            agency_choice = st.selectbox("Assigned Government Agency", list(agency_map.keys()), key="signup_agency_choice")
            selected_agency = agency_map[agency_choice]
            st.caption(f"Reviewer permissions will be restricted exclusively to applications routed to {agency_choice}.")

        if selected_role == "developer":
            st.info("⚠️ Developer Notice: Developers have access to logs, metrics, code, and synthetic tests. Access to real customer document binaries and extractions is strictly prohibited by security policy.")

        st.markdown("---")
        st.markdown("**Legal Policies & Terms of Service**")
        st.markdown("""
        Please review the formal legal drafts before creating your account:
        - 📄 [View / Download Terms & Conditions (PDF)]({api}/policies/terms/download) | [HTML View]({api}/policies/terms)
        - 📄 [View / Download Privacy Policy (PDF)]({api}/policies/privacy/download) | [HTML View]({api}/policies/privacy)
        """.format(api=API_BASE))

        accept_terms = st.checkbox(
            "I have read and agree to the Docintake Terms & Conditions.",
            value=False,
            key="signup_accept_terms"
        )

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
                        st.session_state.user_role = data.get("role", "applicant")
                        st.session_state.user_agency = data.get("agency_id", None)
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error(f"Login failed: {result.get('error', result.get('detail', 'Unknown error'))}")
                else:
                    # Sign Up: validate all fields
                    errors = []
                    
                    if not accept_terms:
                        errors.append("You must read and agree to the Docintake Terms & Conditions to register.")

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
                        result = signup_user(
                            username=username,
                            password=password,
                            email=email,
                            accept_terms=accept_terms,
                            role=selected_role,
                            agency_id=selected_agency if selected_role == "government_reviewer" else None
                        )
                        
                        if result.get("success"):
                            data = result.get("data", {})
                            st.session_state.user_id = data.get("user_id")
                            st.session_state.user_token = data.get("token")
                            st.session_state.user_email = data.get("email", email)
                            st.session_state.user_username = data.get("username", username)
                            st.session_state.user_role = data.get("role", selected_role)
                            st.session_state.user_agency = data.get("agency_id", None)
                            st.success("Account created successfully! Terms & Conditions acceptance recorded.")
                            st.rerun()
                        else:
                            error_msg = result.get('error', result.get('detail', 'Unknown error'))
                            st.error(f"Signup failed: {error_msg}")

# Footer
st.markdown("---")
st.caption("Multi-Service Agentic Onboarding | Built with FastAPI & Streamlit | Powered by Ollama")
