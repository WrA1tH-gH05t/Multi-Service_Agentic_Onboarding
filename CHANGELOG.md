# CHANGELOG — Multi-Service Agentic Onboarding System

## [v2.2.0] — 2026-11-11 (Extremity Hardening: Multi-Format Date Parsing, Name Variant Tolerances, S3 Disambiguation & Self-Healing Connections)

### Major Changes
- **S3 Key Collision Prevention on Same-Day Re-uploads**:
  - Added object existence checking via `StorageService.file_exists()`.
  - When a user resubmits or re-uploads a corrected document on the same calendar day, a deterministic short hash token (`v_<sha256[:6]>`) is automatically appended as a suffix in both `app/routes/documents.py` and `app/routes/wizard.py`, preventing silent overwrites and maintaining audit history.
- **Enhanced International & Regional Date Parsing**:
  - Expanded `_is_valid_expiry` and `_normalize_date` in `agents/validation_agent.py` to support dot-delimited formats (`%d.%m.%Y`, `%Y.%m.%d`), hyphenated formats (`%d-%m-%Y`), English textual months (`%d-%b-%Y`, `%d %b %Y`, `%d %B %Y`), comma variants (`%d %b, %Y`), and month-year notations (`%m-%Y`, `%Y-%m`).
- **Tolerant Identity Name Cross-Checking**:
  - Added `_names_match_detailed` in `agents/validation_agent.py` handling GCC/regional patronymics and honorifics (`Al`, `Bin`, `Bint`, `Ibn`, `Mr`, etc.).
  - Evaluates token subsets and partial intersections ($\ge 60\%$), allowing cross-document variations (e.g. Passport with middle name vs ID with given + surname) to escalate smoothly to human review (`needs_human_review`) rather than triggering false-positive critical rejections.
- **Robust Field Lock Enforcement**:
  - Normalized field aliases (`emirates_id_number`, `id_number`, `card_number`, `license_no`, `license_number`, `date_of_expiry`, `date_of_issue`) in `app/routes/wizard.py` to prevent unauthorized client modifications on verified document fields.
- **Self-Healing Lazy Database Connections**:
  - Updated `DatabaseService.get_session()` to automatically connect if uninitialized, preventing `RuntimeError("Database not connected")` on detached tasks or workers.
- **UI Version Indicator**:
  - Added a persistent bottom-right version badge displaying `v2.2.0` on the web interface.

---

## [v2.1.0] — 2026-11-10 (Enterprise Storage Hardening, Standardized S3 Naming & Health Probes)

### Major Changes
- **Standardized MinIO S3 Object Naming (`<name>_<idnumber>_<date>.<ext>`)**:
  - Replaced cluttered/nested directory structures (`docs/<uuid>_<raw_filename>` and `wizard/<user>/<session>/<sha>_<filename>`) with a clean, flat, audit-ready naming standard: `<name>_<idnumber>_<date>.<ext>` (e.g. `layla_ahmed_784199012345671_20261110.pdf`, `layla_ahmed_n98765432_20261110.jpg`).
  - Pre-flight vision extraction automatically resolves applicant full names and national ID/passport numbers before streaming to object storage.
  - Added centralized key generator `format_object_name()` in `services/storage.py` used by both `app/routes/documents.py` and `app/routes/wizard.py`.
- **True MinIO Server-Side Encryption (SSE)**:
  - Added native cryptographic server-side encryption via `minio.sse.SseS3` and `minio.sse.SseKMS` passed directly to `put_object(..., sse=...)`.
- **Dual Health & Telemetry Probes**:
  - Added Kubernetes / Docker readiness probe at `/health/ready` (and root `/ready`) returning HTTP 200 when MinIO & PostgreSQL are responsive, and HTTP 503 if degraded.
  - Added `/api/v1/metrics/storage` telemetry endpoint exposing Prometheus-style operation counters, latency percentiles, and transferred byte totals.

### Added
- **Bucket Reorganization Utility**: Added `scripts/reorganize_minio_bucket.py` CLI utility and `StorageService.reorganize_clustered_objects()` to migrate existing cluttered bucket files to the new `name_idnumber_date.ext` format and synchronize the database.
- **Enterprise Storage Hardening Suite**: Added `TestH13_EnterpriseStorageAndProbes` in `tests/test_hardening.py` covering key generation, sanitation, fallbacks, SSE providers, metadata normalization, and bucket reorganization (84 total tests passing).

### Fixed
- **Storage Metrics Double-Counting**: Added `StorageMetricsCollector.record_bytes()` to decouple transferred byte totals from operation counts, ensuring latency averages and request counts are strictly accurate.
- **SHA-256 Metadata Normalization**: Added case-insensitive normalization for S3/MinIO `x-amz-meta-` header prefixes on object download verification to prevent silent checksum bypasses.
- **Document Route Syntax Bug**: Fixed a syntax typo in `app/routes/documents.py` (`"selected_service": None,*`) that prevented module import.
- **Removed Duplicate Code**: Purged legacy duplicated code block at the bottom of `migrate_from_filesystem` in `services/storage.py`.

---

## [v2.0.0] — 2026-01-XX (Vision AI Upgrade)

### Major Changes
- **Model Upgrade**: Replaced `qwen3:0.6b` (text-only) with `qwen2.5vl:3b` (multimodal vision model)
- **Eliminated OCR Pipeline**: Vision model processes document images directly — no separate OCR step needed
- **Removed Obsolete Services**: `services/search.py`, `services/embedding.py` — vision model handles both extraction and understanding internally

### Added
- **Vision Model Integration**: `services/generation.py` updated to accept image bytes and output structured JSON field extraction
- **New API Endpoint**: `/api/v1/documents/extract` — Standalone field extraction endpoint that returns JSON without saving files
- **Frontend Image Support**: `app/static/index.html` updated to accept `.png,.jpg,.jpeg,.tiff,.bmp` in addition to `.pdf`
- **Frontend Extraction Display**: Uploaded documents now show extracted fields in chat with bullet-point formatting
- **OCR Fallback Updated**: `services/ocr.py` marked as fallback-only with updated docstring

### Modified
- **`config.yaml`**: `ollama.model` changed from `qwen3:0.6b` to `qwen2.5vl:3b`
- **`.env.example`**: `GENERATION_MODEL` changed to `qwen2.5vl:3b`, removed `EMBEDDING_MODEL`
- **`requirements.txt`**: Added `PyMuPDF` and `Pillow` for image processing; removed `python-magic` (replaced by `python-magic-bin` for cross-platform)
- **`app/main.py`**: Removed `EmbeddingService` and `SearchService` from app initialization; generation service now uses vision model
- **`app/routes.py`**: 
  - `/documents/upload` now converts PDFs to images for vision model extraction
  - `/documents/extract` added for standalone extraction
  - `/chat/message` simplified — no more source/vector search fallback
  - Removed vector similarity calculations from chat responses
  - All document handlers updated for async-safe operation
- **`app/golden_dataset_page.py`**: No functional changes (golden dataset is in-memory)
- **`services/__init__.py`**: Removed `SearchService` export, updated `GenerationService` to use vision model
- **`services/ocr.py`**: Updated docstring to reflect fallback-only status
- **`services/validation.py`**: Added image extensions (`.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`) to `allowed_extensions`
- **`workers/tasks.py`**: Updated comments to reflect removed imports

### Deleted
- **`services/search.py`**: Vector DB search service (replaced by vision model)
- **`services/embedding.py`**: Ollama embedding service (vision model embeds internally)
- **`models/blobs/*`**: 7 old `qwen3:0.6b` model blobs (~450MB freed)
- **`models/manifests/registry.ollama.ai/library/qwen3/`**: Old model manifest
- **`models/manifests/registry.ollama.ai/library/qwen3-embedding/`**: Old embedding model manifest
- **`models/metadata/*`**: Old model metadata files

### Updated Documentation
- **`README.md`**: 
  - Updated prerequisites (Tesseract no longer needed; Ollama + Qwen2.5-VL required)
  - Updated architecture diagram to reflect removed services
  - Updated "How It Works" section to describe vision-based flow
  - Updated API endpoints table
  - Updated troubleshooting guide
  - Updated project structure listing
  - Updated next steps and learning resources

### Technical Notes
- **VRAM**: `qwen2.5vl:3b` uses ~3.5GB VRAM (vs ~2GB for `qwen3:0.6b`)
- **Capabilities**: Vision model handles text chat, image understanding, and structured JSON extraction in a single model
- **Compatibility**: All existing endpoints preserved (backwards compatible for text-only users)
- **Golden Dataset**: Unchanged — in-memory JSON storage, no DB dependency

### Migration Steps
1. Run `ollama pull qwen2.5vl:3b`
2. Delete old model: `ollama rm qwen3:0.6b` and `ollama rm qwen3-embedding:0.6b`
3. Update `config.yaml` (already done)
4. Restart FastAPI server

---

## [v1.0.0] — Initial Release

### Features
- FastAPI backend with React frontend
- PostgreSQL database with pgvector for semantic search
- Ollama integration for text generation and embeddings
- OCR pipeline (Tesseract) for text extraction from images
- Multi-service agentic onboarding flow
- Golden dataset for extraction validation
- Service catalog with FAQ system
- Authentication and authorization
- Docker Compose for multi-service deployment
