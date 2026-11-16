# System Handoff Documentation: Setup, Operations & Known Limitations

**Project:** DocIntake Multi-Service Agentic Onboarding Platform  
**Target Audience:** DevOps Engineers, Backend Maintainers, Deployment Auditors  
**Release:** v2.3.0  

---

## 1. Clean-Machine Setup & Execution (Verified Commands)

Follow these exact verified steps on a clean host with Docker Desktop and Python 3.10+ installed.

### Step 1: Clone Repository
```bash
git clone https://github.com/WrA1tH-gH05t/Multi-Service_Agentic_Onboarding.git
cd Multi-Service_Agentic_Onboarding
```

### Step 2: Configure Environment
Copy the example environment configuration:
```bash
cp .env.example .env
```
*(Default settings configure on-premise PostgreSQL on port 5432, MinIO on 9000/9001, and Redis on 6379).*

### Step 3: Start Infrastructure via Docker Compose
Bring up the backing containers:
```bash
docker-compose up -d postgres redis minio
```
Verify all containers are healthy:
```bash
docker-compose ps
```

### Step 4: Setup Python Virtual Environment
```bash
python -m venv venv

# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Pull Ollama Vision Model (On-Premise)
Ensure Ollama is running locally:
```bash
ollama pull qwen2.5vl:7b
```

### Step 6: Initialize Database & Seed Services
Apply Alembic database migrations and seed default service catalogs:
```bash
python scripts/seed_services.py
python scripts/setup_admin_user.py
```

### Step 7: Launch Applications
**Terminal 1 — FastAPI Backend Server:**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Streamlit Frontend Interface:**
```bash
streamlit run app.py --server.port 8501
```

Access the application in your browser at `http://localhost:8501`.

---

## 2. Running Automated Validation & Security Tests

Run the complete regression suite (56 tests):
```bash
pytest tests/ -v
```

Run specific session isolation and security checks:
```bash
pytest tests/test_hardening.py -k "isolation or injection" -v
```

---

## 3. Known Limitations & Operational Considerations

1. **GPU Memory Allocation for Vision Model**:
   - The primary vision model `qwen2.5vl:7b` requires approximately 6.5 GB of VRAM. On machines with limited GPU memory, configure `ollama.model: qwen2.5vl:3b` in `config.yaml` as an authorized lightweight fallback.
2. **Severely Degraded Capture Artifacts**:
   - Documents with >40% physical occlusion or extreme specular glare may yield extraction confidence <0.50, correctly triggering human review routing as per business policy.
3. **Database Fallback Mode**:
   - In environments where PostgreSQL Docker containers are not running, the system supports an authorized development fallback (`allow_sqlite_fallback: true` in `config.yaml`). In production deployments, ensure PostgreSQL with `pgvector` is active for semantic embeddings.
4. **Third-Party External Registries**:
   - Real-time checking against government civil registries is specified in the Phase 5 Reconciliation Agent architecture and deliberately decoupled from the local intake runtime.
