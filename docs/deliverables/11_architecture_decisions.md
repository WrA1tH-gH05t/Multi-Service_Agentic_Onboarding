# Section 10 Architecture & Design Decision Defense

**Document Identifier:** DOCINTAKE-ARCH-DEFENSE-01  
**Project:** DocIntake Multi-Service Agentic Onboarding System  
**Version:** 2.3.0  
**Author:** AI Application Architect  

---

## 1. Tool & Framework Selection Rationale

| Layer | Selected Technology | Alternative Rejected | Rationale for Selection |
|:---|:---|:---|:---|
| **Vision / Extraction** | **Qwen2.5-VL 7B (via Ollama)** | Tesseract OCR + Text LLM / LayoutLM | OCR + separate LLM creates a brittle two-stage pipeline where character-level OCR errors cascade into hallucinated JSON. Qwen2.5-VL natively interprets visual layout, tables, fonts, and stamps in a single inference pass. |
| **API Backend** | **FastAPI (Python 3.12)** | Flask / Django / Express | High-performance asynchronous execution for streaming LLM responses, native Pydantic schema validation, and automatic OpenAPI documentation. |
| **Relational Database** | **PostgreSQL 16 + pgvector** | MongoDB / Plain SQLite | Strong ACID compliance for identity records, foreign key constraints on `user_id`, and native `pgvector` indexing for policy semantic retrieval. |
| **Object Storage** | **MinIO (S3 API compatible)** | File system / DB BLOBs | Storing binaries in PostgreSQL causes table bloat and backup degradation. MinIO offers enterprise S3 compatibility, pre-signed URLs, Server-Side Encryption (SSE), and object tagging. |
| **Task Queue** | **Redis 7 + Celery** | RabbitMQ / Kafka | Lightweight, on-premise footprint with minimal operational overhead for document processing workers and session caching. |

---

## 2. Dynamic Routing Architecture & Catalog Scalability

### Architectural Principle: Zero Hardcoded Routing
In older monolithic implementations, routing was performed through nested `if/elif` statements (e.g., `if "rental" in text:`). This approach degrades as services grow from 3 to 15+.

### DocIntake Scalable Router Design:
1. **Dynamic Service Registry (`services/service_catalog.py`)**:
   - Services are defined as declarative JSON schemas specifying required documents, status (`AVAILABLE` vs `COMING_SOON`), and extraction targets.
2. **Intent-Driven Classifier (`services/scope_classifier.py`)**:
   - Classifies caller intention into `GREETING`, `IN_SCOPE_FAQ`, `IN_SCOPE_APPLY`, `AMBIGUOUS`, or `OUT_OF_SCOPE`.
   - Distinguishes curiosity questions (*"What is required for rental?"*) from application intent (*"I want to sign up for rental"*), adhering strictly to Section 5.
3. **Semantic Retrieval Router (`services/policy_service.py`)**:
   - Service documentation is indexed into vector embeddings. When a query is in-scope, retrieval matches the exact service definition from `docs/` rather than relying on hallucinated model weights.

---

## 3. Extraction Approach & Golden Dataset Benchmarking

1. **Extraction Ladder (`services/extraction_ladder.py`)**:
   - Primary: High-fidelity vision pass via Qwen2.5-VL.
   - Secondary: Structural validation verifying date formats, digit counts, and mandatory field presence.
   - Fallback: If vision extraction confidence is <0.50, the document is tagged for re-upload or human review rather than guessing silently.
2. **Golden Dataset Benchmarking**:
   - 45 multi-condition MIDV-500 ground-truth entries across 3 document types and 4 capture conditions.
   - Evaluated using exact string matching, date normalization, and token-level accuracy.

---

## 4. Business Rules & Validation Rationale

1. **Cross-Document Consistency**:
   - In *Premium / Cross Border*, name and DOB must agree across National ID and Passport.
   - The validation agent implements GCC patronymic tolerance (handling `Al`, `Bin`, and abbreviated middle names) to prevent false rejections of legitimate Middle Eastern identity documents.
2. **Strict Expiry Rules**:
   - Documents with expiry dates prior to application submission are rejected or escalated automatically without silent acceptance.
3. **Driving Licence Back-Page Inspection**:
   - Extracts mandatory vehicle transmission type (`Automatic Gear` vs `Manual Gear`) and spectacles restriction (`glasses logo`), essential for rental fleet insurance compliance.

---

## 5. Human Review Thresholds

- **Confidence Threshold = 50% (0.50)**:
  - If visual extraction confidence is `< 0.50`, the case routes to Human Review.
  - If confidence is `≥ 0.50` and all validation rules pass, the case is marked `COMPLETE`.
- **Field Mismatch**:
  - Any cross-document discrepancy on core identity fields (Name, DOB) triggers an immediate `NEEDS_REVIEW` escalation.

---

## 6. Trade-Offs Considered & Rejected

1. **Rejected Cloud Vision APIs (Google Cloud Vision / AWS Textract)**:
   - *Why Rejected*: Section 9 explicitly mandates fully on-premise execution with zero runtime internet dependencies and no external data exposure.
2. **Rejected Automatic Rejection on Unverified Fields**:
   - *Why Rejected*: High-noise capture conditions (e.g., shadows or folds) frequently obscure secondary fields. Outright rejection degrades customer conversion; routing to human review balances fraud mitigation with user experience.
