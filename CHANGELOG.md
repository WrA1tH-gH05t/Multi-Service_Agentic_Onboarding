# CHANGELOG — Multi-Service Agentic Onboarding System

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
