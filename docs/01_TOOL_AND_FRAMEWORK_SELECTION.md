# Document 1: Tool & Framework Selection and Architectural Roles

**Project:** Moro Hub Multi-Service Document Intake & Verification System  
**Version:** 2.1 (Vision-AI & Real-Time Security Verification)  
**Author:** AI Engineering & Architecture Team  
**Scope:** Architecture, Core Frameworks, Rationale, and Component Roles

---

## Executive Summary

The Moro Hub Document Intake & Onboarding Platform processes identity credentials and service requests under stringent enterprise requirements: **zero data exfiltration**, **strict latency SLAs**, **cross-service scalability**, **state persistence across restarts**, and **verifiable malware protection**.

Every tool and framework in the stack was selected to satisfy on-premise governance, asynchronous I/O throughput, schema safety, and deterministic execution.

```
                      ┌────────────────────────────────────────┐
                      │    React 18 SPA (Zero-Build CDN)      │
                      │   - Sign-Up / Auth / Persistent UI     │
                      │   - Live Inspection & Score Badges     │
                      └───────────────────┬────────────────────┘
                                          │ HTTP / SSE / REST
                                          ▼
                      ┌────────────────────────────────────────┐
                      │       FastAPI Core Server (:8000)      │
                      │   - Async ASGI Pipeline & Routers      │
                      │   - Dynamic Service Catalog Engine     │
                      │   - Real-time ClamAV Stream Scanner    │
                      └────┬──────────────┬──────────────┬─────┘
                           │              │              │
             ┌─────────────┴──┐    ┌──────┴──────┐    ┌──┴─────────────┐
             ▼                ▼    ▼             ▼    ▼                ▼
     ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
     │  PostgreSQL  │ │    MinIO     │ │    ClamAV    │ │ Ollama Vision│
     │  (SQLAlchemy │ │ (S3-Compliant│ │  (TCP :3310  │ │ (Qwen2.5-VL  │
     │  Persistence)│ │  Storage)    │ │   INSTREAM)  │ │  Multimodal) │
     └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

---

## 1. Core Frameworks & System Components

### 1.1 FastAPI (Backend API Framework)
* **Role:** Serves as the central ASGI web framework powering `/api/v1/*` endpoints, routing, dependency injection, and schema enforcement.
* **Why Chosen:**
  1. **Async Non-Blocking Architecture:** Document onboarding involves high-latency I/O operations (PDF parsing, neural vision inference via HTTP, anti-malware TCP streaming, S3 object transmission). FastAPI’s native `async`/`await` model paired with `asyncio.to_thread` guarantees that compute-intensive tasks (e.g., OpenCV Laplacian blur variance calculations, PyMuPDF page rendering) execute in a background thread pool without starving the primary event loop.
  2. **Strict Schema Contracts with Pydantic v2:** Automatic request/response deserialization and validation. Enforces strict input validation on identity payloads, user registration fields, and structured responses.
  3. **High Concurrency & Low Footprint:** Benchmarks consistently show FastAPI (Starlette + Uvicorn) outperforming Flask/Django for asynchronous microservices while requiring significantly lower CPU and memory resources.

### 1.2 React 18 Single Page Application (Frontend Layer)
* **Role:** Interactive, responsive single-page web UI delivered directly from `/static/index.html`. Handles real-time customer onboarding, dynamic sign-up/login modals, session resumption, document inspection feedback, and application tracking.
* **Why Chosen:**
  1. **Zero-Build Dependency Architecture:** Delivered via standalone CDN bundles (`react.production.min.js`, `react-dom.production.min.js`, and Babel Standalone). Eliminates Node.js build pipelines, webpack/Vite configuration overhead, and node_modules vulnerabilities while preserving React’s declarative component hierarchy.
  2. **Granular Component-Level State Management:** Encapsulates wizard steps (`WizardUpload`, `CheckResults`, `WizardReview`, `ApplicationsList`) using native React hooks (`useState`, `useEffect`, `useRef`). Eliminates cross-step data leakage.
  3. **Fault-Tolerant Error Handling:** Sanitizes backend error structures (e.g., FastAPI 422 validation arrays) into clean user messages, preventing React tree unmounting or blank screen crashes.

### 1.3 Ollama + Qwen2.5-VL Multimodal Vision AI
* **Role:** Extracts dense, multi-field structured information directly from rendered document images without relying on brittle, multi-stage OCR pipelines.
* **Why Chosen:**
  1. **100% On-Premise Air-Gapped Operation:** Runs locally on consumer-grade and enterprise GPUs (RTX 4060, A100, H100) via Ollama. Ensures that sovereign citizen data (names, IDs, dates of birth) never traverses public clouds.
  2. **Direct Visual Spatial Understanding:** Legacy OCR engines (Tesseract, PaddleOCR) extract raw bounding boxes that scramble non-linear multi-column layouts, bilingual tables (English/Arabic), and back-of-card stamps. Qwen2.5-VL parses typography, tabular grids, watermarks, and graphical symbols (e.g., the eyeglasses icon on driving licenses) natively.
  3. **Schema-Guided Extraction:** System prompts inject rigorous JSON schemas (such as `DRIVING_LICENSE_SCHEMA`), constraining model output strictly to required attributes and preventing conversational hallucinations.

### 1.4 PyMuPDF (`pymupdf`)
* **Role:** Performs PDF structural validation, encryption checks, page boundary enforcement, active malicious content inspection, and rasterization to high-resolution PNG buffers (200 DPI) for model consumption.
* **Why Chosen:**
  1. **Elimination of Deprecation Warnings:** Upgraded from the legacy `import fitz` namespace to the modern `import pymupdf as fitz` standard, future-proofing the application against library obsolescence and removing stderr startup clutter.
  2. **High-Fidelity Rendering Performance:** Outperforms `pypdf`, `pdf2image`, and `pdfplumber` in rendering speed by up to 10x due to its underlying C MuPDF engine.
  3. **Deep Structural Introspection:** Enables deterministic extraction of low-level PDF metadata, embedded JavaScript hooks, and Launch Actions, which are leveraged in the validation security gate.

### 1.5 ClamAV Antivirus Daemon (Dockerized Stream Scanning)
* **Role:** Real-time malware protection engine scanning all incoming binary buffers before storage or document parsing.
* **Why Chosen:**
  1. **True TCP Streaming (`zINSTREAM`):** Connects to `127.0.0.1:3310` via raw TCP sockets, chunk-streaming binary files directly from memory without writing temp files to disk. Prevents malicious executables or macro payloads from touching physical disk storage.
  2. **Open-Source Enterprise Standard:** Backed by Cisco Talos signatures with automated daily database updates, providing reliable protection against trojans, exploit PDFs, and polyglot files.

### 1.6 MinIO Object Storage
* **Role:** S3-compatible, high-performance object store serving as the definitive repository for accepted document binaries.
* **Why Chosen:**
  1. **Strict Content-Addressable & Namespaced Storage:** Objects are stored using tenant-isolated keys: `wizard/{user_id}/{session_id}/{doc_type}_{sha256[:12]}_{filename}`.
  2. **Gated Upload Pipeline:** Files are committed to MinIO **only after** successfully passing validation, malware scanning, quality inspection, and vision extraction. Unsafe, corrupted, or unreadable files never pollute permanent storage.

### 1.7 PostgreSQL with SQLAlchemy & PersistentUserStore Fallback
* **Role:** Dual-tier persistence engine ensuring that user accounts, active sessions, uploaded document metadata, and completed applications survive server restarts.
* **Why Chosen:**
  1. **Relational Data Integrity (PostgreSQL):** Enforces foreign-key constraints linking users, applications, and documents. Uses SQLAlchemy ORM `session_scope()` context managers for atomic transaction management.
  2. **Zero-Downtime JSON Store Fallback (`PersistentUserStore`):** If PostgreSQL is temporarily unreachable in development or edge deployments, the system seamlessly persists user hashes and session tokens to encrypted local JSON storage. On reboot, active session tokens are restored immediately to memory, preventing forced logouts.

---

## 2. Component Responsibility Matrix

| Component | Layer | Primary Responsibility | Input | Output |
|---|---|---|---|---|
| **React SPA** | Client | Presentation, user authentication, live check visualizer, field edit/confirm | User inputs, files | HTTP Requests, UI state |
| **AuthService** | Core Service | Password hashing (salt+hash), session token issuance, restart recovery | Login/Signup payloads | Session tokens, authenticated users |
| **CatalogEngine** | Domain | Service registry, required document mapping, SLA definitions | Service ID | Service specifications, rules |
| **FileValidation** | Security Gate | Magic byte verification, PDF structural check, ClamAV socket scan | Raw bytes | Validation boolean, risk scores |
| **QualityService** | Inspection Gate| Laplacian variance blur check, page count/boundary checks | Rendered image buffers | Quality score, blur status |
| **GenerationService**| AI Vision Gate | Schema-constrained multimodal extraction via Qwen2.5-VL | Image buffers, typed schema | Normalized JSON fields, confidence score |
| **WizardManager** | State Engine | State machine transitions (Name → Upload → Review → Submitted) | Step payloads, tokens | Immutable session state |
| **Database/MinIO** | Persistence | Permanent multi-tenant data storage & application history | Structured entities, streams | Saved records, presigned URLs |

---

## 3. Architecture Design Decisions & Trade-offs

1. **Why Not Cloud-Native Document AI (AWS Textract / Google Document AI)?**
   * *Trade-off:* Cloud APIs require zero GPU infrastructure but violate data sovereignty regulations for government and utility customers (Moro Hub / UAE compliance).
   * *Resolution:* Fully local, air-gapped deployment using Ollama and ClamAV running inside containerized infrastructure.
2. **Why Direct Multimodal Vision over OCR + LLM Pipeline?**
   * *Trade-off:* Vision LLM inference requires more VRAM (~5.5GB for Qwen2.5-VL 7B/3B) than Tesseract OCR (~100MB).
   * *Resolution:* Vision LLMs eliminate cascade errors (OCR misreading characters -> LLM receiving corrupted tokens). Vision models infer semantic context directly from pixel layouts, successfully extracting visual emblems like the driving license eyeglasses icon.
3. **Why Token-in-Memory with Persistent Re-Hydration over Stateless JWT?**
   * *Trade-off:* JWTs require no server-side token state.
   * *Resolution:* Pure stateless JWTs cannot be instantly revoked upon logout or security breach. By combining server-side token state with persistent disk recovery on startup, we achieve immediate revocation control alongside 100% restart persistence.
