|Multi-Service Agentic Onboarding System v2.0|
|A conversational agent that guides customers through sign up, document upload, and verification across multiple services — now with **vision AI** for direct image understanding and structured field extraction.|
|Built for fully on-premise deployment with Docker Desktop. Runs on consumer GPUs (RTX 4060 Laptop).|

## 🎯 What This System Does (v2.0 — Vision AI)

This system helps you:
- **Discover services**: Ask about available services and what documents they require
- **Apply through guided conversation**: Upload documents step-by-step with real-time feedback
- **Vision-based field extraction**: Upload document images (PDF, PNG, JPG) → Qwen2.5-VL 3B extracts all fields directly from the image — no separate OCR pipeline needed
- **Validate applications**: Cross-document consistency checks (e.g., name/DOB match across ID+passport)
- **Chat**: Interact with an AI assistant that understands your application status

**Key change from v1**: We replaced the text-only `qwen3:0.6b` model with the multimodal `qwen2.5vl:3b` vision model. This eliminates the need for a separate OCR pipeline — documents are now processed as images directly.

## 🏗️ System Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Streamlit UI  │───▶│   FastAPI Server │ ───▶│  PostgreSQL   │
│  (Web Interface)│    │   (API Backend)  │    │  (Database +    │
└─────────────────┘    └──────────────────┘    │   pgvector)     │
                              │                └─────────────────┘
                              ▼                         │
                       ┌──────────────────┐             │
                       │   SeaweedFS      │             │
                       │  (File Storage)  │             │
                       └──────────────────┘             │
                              │                         │
                              ▼                         ▼
                       ┌──────────────────┐    ┌─────────────────┐
                       │   Ollama         │    │   Redis         │
                       │  (AI Embeddings) │    │  (Cache/Queue)  │
                       └──────────────────┘    └─────────────────┘

New Components (Phase 2-6):
┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐
│ Collection Agent│  │ Validation Agent │  │ Auth Service    │
│ (Service routing│  │ (Cross-doc checks│  │ (Login, signup, │
│  state tracking)│  │  , field match)  │  │  session mgmt)  │
└─────────────────┘  └──────────────────┘  └─────────────────┘
```

## 📋 Prerequisites

Before you start, make sure you have:

1. **Docker Desktop** - For running databases and services
2. **Python 3.10+** - For running the application
3. **Ollama** - For running the Qwen2.5-VL 7B vision model
   - Install from: https://ollama.ai/
   - Pull model: `ollama pull qwen2.5vl:7b`
4. **FFmpeg** - For PDF-to-image conversion (optional but recommended)
   ```bash
   sudo apt install ffmpeg
   ```

> **Note**: Tesseract OCR is no longer required — the vision model handles image understanding directly.

## 🚀 Quick Start

### Step 1: Install Dependencies

```bash
# Navigate to the project folder
cd "C:/Users/arvin/Desktop/Work and Uni/WORK/task 1"

# Create a virtual environment (isolates your project)
python -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On WSL/Linux:
source venv/bin/activate

# Install Python packages
pip install -r requirements.txt
```

### Step 2: Start Docker Services

```bash
# Make sure Docker Desktop is running

# Start all services (PostgreSQL, Redis, SeaweedFS, etc.)
docker compose up -d

# Wait a few seconds for services to initialize
sleep 5

# Verify everything is running
docker ps
```

### Step 3: Initialize the Database

**Good news: this happens automatically.** The compose file mounts `scripts/init_db.sql`
into `/docker-entrypoint-initdb.d/`, and PostgreSQL runs everything in that folder the
first time it starts. You can verify the tables exist:

```bash
docker exec doc-intake-postgres psql -U intake -d doc_intake -c "\dt"
# Expected: documents, processing_log, chat_history
```

If you ever need to re-run it manually (safe - the script uses IF NOT EXISTS):

```bash
# Note the path: inside the container the file lives at /docker-entrypoint-initdb.d/,
# NOT /scripts/ (that folder is only on your computer)
docker exec -i doc-intake-postgres psql -U intake -d doc_intake -f /docker-entrypoint-initdb.d/init_db.sql

# Or run it directly from your computer (needs psql installed locally)
psql -h 127.0.0.1 -U intake -d doc_intake -f scripts/init_db.sql
```

### Step 4: AI Model — Qwen2.5-VL 3B (Vision)

```bash
# Pull the vision-language model (accepts images + text, outputs structured JSON)
ollama pull qwen2.5vl:3b
```

**Model details:**
- **Architecture**: Vision-language model (multimodal)
- **VRAM requirement**: ~3.5GB (fits on RTX 4060 Laptop, 8GB VRAM)
- **Capabilities**: Understands document images, extracts structured fields, generates JSON responses
- **License**: Apache 2.0 (permissive)
- **DocVQA accuracy**: 91.6% on document visual question answering benchmarks

The model handles both text chat and image understanding from a single endpoint. No separate embedding or OCR models needed.

**Legacy note (v1):** The old setup used `qwen3:0.6b` for text generation and `qwen3-embedding:0.6b` for embeddings. Both have been removed in favor of the single vision model.

### Step 5: Start the Application

```bash
# Start the FastAPI server (backend)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# In a new terminal, start the Streamlit interface (frontend)
streamlit run app.py
```

### Step 6: Open the Web Interface

Open your browser and go to:
- **React Frontend**: http://localhost:8000/ (embedded in FastAPI)
- **Streamlit UI**: http://localhost:8501
- **API Documentation**: http://localhost:8000/docs

## 📁 Project Structure (v2.0)

```
task 1/
├── app/                    # FastAPI application
│   ├── __init__.py
│   ├── main.py             # Main application entry point
│   ├── routes.py           # API endpoints (upload, chat, extract, auth, services)
│   ├── schemas.py          # Data validation models
│   ├── golden_dataset_page.py  # Streamlit golden dataset viewer
│   └── static/             # React frontend (single-page app)
│       └── index.html      # Main frontend file
├── agents/                 # Agentic reasoning components
│   ├── __init__.py
│   ├── collection_agent.py  # State machine for guided document collection
│   └── validation_agent.py  # Cross-document validation and consistency checks
├── services/               # Business logic
│   ├── __init__.py
│   ├── auth.py             # Authentication & authorization
│   ├── service_catalog.py  # Service definitions & FAQ data
│   ├── validation.py       # File type/size validation (supports images)
│   ├── ocr.py              # OCR fallback (unused in main flow)
│   ├── generation.py       # Vision model (Qwen2.5-VL 3B) — replaces qwen3
│   ├── golden_dataset.py   # Golden dataset management
│   └── user_store.py       # User storage
├── workers/                # Background task processing (placeholder)
│   ├── __init__.py
│   └── tasks.py            # Celery tasks (not active)
├── data/                   # Golden dataset & test data
│   ├── golden_dataset.json   # Ground truth for extraction eval
│   └── identity_pairs.json   # Matched/mismatched test pairs
├── docs/                   # Service definitions & design decisions
│   ├── MIDV_Sourcing_Selection_Note.md
│   ├── service_definitions.md
│   └── field_selection_note.md
├── scripts/                # Database scripts
│   └── init_db.sql         # Database initialization
├── uploads/                # Uploaded documents (gitignored)
├── .env.example            # Environment template (no secrets)
├── .env                    # Your secrets (gitignored)
├── config.yaml             # Configuration settings
├── docker-compose.yml      # Docker service definitions
├── requirements.txt        # Python dependencies
├── README.md               # This file
└── app.py                  # Streamlit web interface
```

**Removed in v2.0:**
- `services/search.py` — Vector DB search replaced by vision model extraction
- `services/embedding.py` — Embedding service removed (vision model embeds internally)
- `services/classifier.py` — Document classification via vision prompts
- `services/confidence.py` — OCR confidence scoring removed
- `services/storage.py` — SeaweedFS not implemented

## 🎓 How It Works (v2.0 — Vision AI Flow)

### Vision-Based Document Processing (v2.0)
1. **You upload a document** (PDF, PNG, JPG, TIFF, BMP)
2. **Vision Model Processing** → Qwen2.5-VL 3B receives the image directly — no OCR step needed
3. **Structured Field Extraction** → Model outputs JSON with all identified fields (name, DOB, document number, etc.)
4. **Document Type Detection** → System classifies as passport, driving license, or national ID based on extracted fields
5. **Response** → Extracted fields shown in chat with confidence score

### Multi-Service Agentic Mode
1. **Service Discovery**: Ask "what services do you offer?" → System lists all services from the catalogue
2. **Intent Detection**: System tells apart FAQ questions from application intent
3. **Guided Onboarding**:
   - "I want to apply for Basic Registration" → System checks required documents (National ID Card)
   - System asks for each document one at a time, with feedback on upload success
   - If wrong document uploaded: "That doesn't look like a National ID Card. Please upload a government-issued ID card."
   - If unclear image: "The image is blurry. Please take a clearer photo with all text visible."
4. **Vision Extraction**: Qwen2.5-VL 3B extracts fields from uploaded image (replaces separate OCR pipeline)
5. **Validation Agent**:
   - For Premium/Cross Border: Checks ID card AND passport fields match (name, DOB, etc.)
   - Checks document validity (not expired)
   - Cross-field consistency (name matches across documents)
6. **Outcome**: Application is marked `complete`, `incomplete`, or `needs_human_review` with specific reasons
7. **Audit Trail**: Every step is logged for traceability

## 🏢 Service Catalogue

### Available Services
| Service | Documents Required | Processing Time |
|---------|-------------------|-----------------|
| Basic Registration | National ID Card | 1-2 business days |
| Premium / Cross Border | National ID Card + Passport | 3-5 business days |
| Mobility / Rental | Driving Licence | 2-3 business days |

### Coming Soon Services (Not Available Yet)
The agent will recognize these and clearly state they are not yet available:
- Business Registration (Business License)
- Travel Visa Application (Passport + Visa Form)
- Credit Card Application (Income Proof + ID)
- Insurance Enrollment (Medical Records + ID)
- Utility Connection (Utility Bill + ID)
- Gym Membership (ID + Photo)
- Library Card (ID + Address Proof)
- Student Enrollment (Student ID + Transcript)

## 🌐 API Endpoints (v2.0)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/documents/upload` | POST | Upload a document (saved to filesystem) |
| `/api/v1/documents/extract` | POST | Extract fields from image (returns JSON, no save) |
| `/api/v1/documents` | GET | List all uploaded documents |
| `/api/v1/documents/{id}/delete` | POST | Delete a document |
| `/api/v1/chat/message` | POST | Chat with the AI assistant |
| `/api/v1/golden-dataset/*` | GET/POST | Golden dataset operations (search, validate, compare) |
| `/api/v1/health` | GET | System health check |
| `/docs` | GET | Interactive API documentation |

> **Key change**: `/api/v1/documents/extract` is the primary extraction endpoint. It uses the vision model to process images and return structured JSON.

## 🔧 Troubleshooting (v2.0)

### "Vision model not responding"
- Verify Qwen2.5-VL 3B is running: `ollama list | grep qwen2.5vl`
- Check Ollama is running: `docker ps | grep ollama` or `ollama serve`
- Model not found? Run: `ollama pull qwen2.5vl:3b`
- VRAM overflow? Check GPU usage: `nvidia-smi`

### "File upload fails"
- Check file size is under 200MB
- Verify file type is allowed (PDF, PNG, JPG, JPEG, TIFF, BMP)
- Check Ollama/vision model is responding: `curl http://localhost:11434/api/chat`

### "Extraction returns empty fields"
- Image quality: Ensure document is clearly visible in the image
- Try different image: Sometimes JPEG artifacts cause issues
- Check system logs: `uvicorn` console shows extraction errors

### "Old embedding/search not working"
- This is expected! Search and embedding services were removed in v2.0.
- Vision model handles both extraction and understanding — no vector DB needed.

### "Cannot connect to database"
- Make sure PostgreSQL container is running: `docker ps`
- Check if port 5432 is accessible: `telnet 127.0.0.1 5432`

## 📚 Learning Resources

- **FastAPI Documentation**: https://fastapi.tiangolo.com/
- **Streamlit Documentation**: https://docs.streamlit.io/
- **PostgreSQL + pgvector**: https://github.com/pgvector/pgvector
- **Ollama Documentation**: https://ollama.ai/
- **Qwen2.5-VL Documentation**: https://qwenlm.github.io/blog/qwen2.5vl/
- **React Documentation**: https://react.dev/

## 📝 Next Steps

After getting this working, you can:
1. Add multi-language support for vision extraction
2. Implement document versioning
3. Add bulk upload functionality
4. Connect to cloud vision models (AWS Textract, GCP Document AI) for comparison
5. Build a mobile app frontend (React Native / Flutter)
6. Add document processing analytics dashboard

## 📄 License

This project is open-source and available for educational purposes.

---

## 🔒 Permitted Documents & Data Handling Guidelines

When uploading documents or testing the onboarding intake pipeline, adhere to the following data compliance and file specifications:

### 1. Supported Document Types & Formats
- **Document Categories**:
  - Driving License (`driving_license`): Front and back of official driver's license.
  - Emirates ID (`emirates_id`): Front and back national identity cards.
  - Passports (`passport`): Main biometric photo page / MRZ data page.
  - Proof of Address / Tenancy: Ejari contracts, utility bills (DEWA/SEWA).
  - Corporate Documents: Trade licenses, VAT registration certificates.
- **Allowed File Extensions**:
  - Strictly `.pdf` (standard PDFs and scanned/raster PDF documents).
- **File Size Limit**: Maximum 200 MB per file.

### 2. Privacy, PII & Testing Restrictions
- **Do Not Upload Real Personal Identifiable Information (PII)**:
  - Never upload real citizen IDs, personal passports, personal bank statements, or confidential customer records to public or shared environments.
- **Allowed Test Media**:
  - Use synthetic, mocked, or public benchmark identity datasets (e.g., MIDV-500 sample cards).
  - Use redacted/dummy documents where full names, passport numbers, and national identification numbers are obscured or clearly marked as test data.
- **Data Retention & Storage**:
  - Document binaries are streamed to S3/MinIO/SeaweedFS storage, and metadata/extracted entities are stored in PostgreSQL.
  - Clean up temporary test files and avoid checking sample documents containing personal information into Git.

---

**v2.0 — Upgraded to Vision AI with Qwen2.5-VL 3B**
**Built with ❤️ for learning system design and document processing**
