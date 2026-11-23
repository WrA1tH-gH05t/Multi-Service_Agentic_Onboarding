# CHANGELOG — Multi-Service Agentic Onboarding System

## [v2.5.0] — 2026-11-23 (Slightly Major Update: Child Dependent Profiles, Statutory 3-Tier Consent Architecture & Unified Legal Policy v1.1)

### Major Changes
- **Child Dependent Profiles & Parent/Guardian Management**:
  - Implemented parent/guardian account governance under UAE Federal Decree-Law No. 25 of 2025 (Article 84 age-of-majority enforcement).
  - Added full lifecycle management for child dependent profiles with age-band safeguards: `<13` (Child Digital Safety protections), `13–17` (adolescent safeguards), and `18+` (automatic adulthood transition with cessation of guardian authority).
  - Complete document and application data isolation per child dependent profile across database records and MinIO storage paths.
  - Dedicated guardian verification workflows distinguishing legal parents from court-appointed guardians/caregivers.
- **Three-Event Statutory Consent Architecture**:
  - Integrated a formal three-tier consent framework:
    - **Consent Event A**: General Platform Terms and Privacy Policy acceptance upon user registration.
    - **Consent Event B**: Explicit, verifiable parental consent under Article 7 of UAE Federal Decree-Law No. 26 of 2025 prior to collecting or processing any child personal data.
    - **Consent Event C**: Application-specific document review consent per submission before forwarding dossiers to designated government reviewing bodies.
  - Added dynamic consent withdrawal with automated purging of temporary staged documents and in-memory extraction data upon revoked consent.
- **Unified Terms & Conditions v1.1 & Policy Gap Closure**:
  - Consolidated the official `Docintake_Terms_and_Conditions_v1.1_DRAFT` (both Markdown master and 10-page ReportLab PDF), seamlessly bridging all operational specifications from v1.0.
  - Codified active service SLAs (Basic Registration: 1–2 days, Premium: 3–5 days, Mobility: same-day), demonstrator coming-soon catalog entries, strict unexpired document requirements with auto-purge, and zero-routine developer document access controls.
  - Synchronized in-app HTML policies (`/policies/terms` and `/policies/privacy`).
- **Autonomous Service Orchestration on Startup**:
  - Enhanced `start.py` with proactive health checks that automatically launch Docker Desktop, start compose containers (`docker compose up -d`), and spawn the Ollama background daemon if not already online.
  - Cleaned up obsolete one-time migration and debug scripts from the repository.
- **UI Version Indicator**:
  - Updated the persistent bottom-right status tag to `TASK 1 • v2.5.0`.

---

## [v2.4.2] — 2026-11-16 (Patch Release: Model Scope Boundary Enforcement & Out-of-Scope Leakage Prevention)

### Bug Fixes
- **Model Project Scope Boundary Enforcement**:
  - Fixed an issue where the conversational assistant answered questions outside project scope (such as providing gym plans, workout splits, recipes, coding scripts, and trivia) instead of staying strictly bound to DocIntake onboarding, document verification, application tracking, and platform support.
  - Replaced the allow-by-default fallback in `ScopeClassifier` with zero-trust domain anchor validation: any query lacking contextual anchors to DocIntake services, documents, onboarding workflows, or platform architecture is rejected immediately with `OUT_OF_SCOPE_RESPONSE` without invoking the LLM.
  - Added explicit regex triggers for gym routines, workouts, fitness splits, diet/nutrition, medical queries, academic homework, and gaming.
  - Expanded in-scope conversational greetings to include assistant identity and name recognition (`"hi Lynx"`).
  - Hardened LLM system prompt directives in `app/routes/chat_message.py` with strict refusal mandates for non-DocIntake topics.
  - Implemented post-generation output guardrail `is_out_of_scope_reply()` in `services/scope_classifier.py` and wired it into `app/routes/chat_message.py` to intercept and replace any leaked workout routines or recipes before response delivery.
  - Added a comprehensive 66-case regression test suite in `tests/test_scope_boundaries.py`.

- **UI Version Indicator**:
  - Updated the persistent bottom-right status tag to `TASK 1 • v2.4.2`.

---

## [v2.4.0] — 2026-11-16 (Minor Release: Conversational Details Guard, Expired Document Auto-Purge, Review Lock & Verification Scoring Hardening)

### Major Changes
- **Conversational Service Details Guard**:
  - Refined service inquiry handling so that when users ask for service details (or the assistant asks if the user would like more details), it no longer prematurely triggers the *"Would you like me to start a new application for you?"* offer card.
- **Expired Document Detection & Immediate Purge**:
  - Implemented pre-flight and upload-time expiry date checks (`_is_valid_expiry_date`) in the onboarding wizard workflow.
  - Expired IDs/passports are promptly flagged with explicit user notification, and previous expired document rows/files are automatically deleted from both MinIO storage and the database.
- **Confirmation State & Locked Consent UX**:
  - In the review interface, once the agreement checkbox is ticked and "Confirm and submit" is pressed, the interactive options transition to a static **✓ Reviewed** badge.
  - The consent checkbox and inline edits are strictly locked and disabled, preventing post-confirmation unticking or modifications.
- **Accurate Extraction Score & Auto-Completion Routing**:
  - Re-engineered extraction confidence scoring to calculate true field accuracy and semantic validation (checking valid date formats, gender values, and field lengths) across expected schema fields.
  - Standardized passport canonical type mapping (`passport_type = 'P'`) and enriched identity name cross-matching in `ValidationAgent`, allowing verified applications with full document extraction to transition directly to `complete` status instead of false-positive human review escalation.
- **Frontend Version Tag Update**:
  - Updated the persistent UI status badge at the bottom right of the web application to display `TASK 1 • v2.4.0`.

---

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
