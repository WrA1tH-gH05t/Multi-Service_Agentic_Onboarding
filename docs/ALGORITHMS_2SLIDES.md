# Moro Hub — Algorithms (2 Slides)

---

## SLIDE 1: Core AI & Extraction Algorithms

**Vision-Language Model — Qwen2.5-VL 3B**
- Family: Multimodal foundation models (decoder-only transformer, next-token prediction)
- Examples: Qwen2.5-VL, LLaVA, Phi-3-Vision
- Strength: Extracts structured fields directly from scanned document images — no separate OCR or layout model needed. Runs fully offline on a laptop GPU.

**Model Quantization — Q4_K_M**
- Family: Model compression (quantisation, pruning, distillation)
- Examples: Q4_K_M, AWQ, GGUF, INT8
- Strength: Cuts model size from ~6 GB to ~3.5 GB with minimal accuracy loss. Makes a 3B-parameter model feasible on consumer hardware.

**Extraction Ladder (4-Rung Ensemble)**
- Family: Consensus/voting — independent candidate generation and aggregation
- Examples: Vision model → MRZ crop re-extraction → MRZ parser → Tesseract OCR
- Strength: No single method is 100% reliable. Running four methods and merging by highest confidence achieved 100% field accuracy on EID and 80% on passport — far above any single method alone.

**Structured Generation — JSON Schema-Guided Decoding**
- Family: Constrained generation for controlled output
- Examples: Grammar-guided decoding, JSON schema prompting, tool-calling with typed parameters
- Strength: Ensures the vision model outputs parseable JSON — not free text. Low temperature (0.1) keeps the model tightly focused on extraction.

**OCR Fallback Stack — PyMuPDF + Tesseract**
- Family: Document AI — OCR, layout-aware parsing, table extraction
- Examples: Tesseract, PyMuPDF (fitz), EasyOCR, PaddleOCR
- Strength: PyMuPDF is instant for PDFs with embedded text. Tesseract handles images. Lightweight fallbacks when the vision model is unavailable.

**MRZ Parsing — ICAO TD1/TD2/TD3 Spec Parser**
- Family: Schema-based entity extraction
- Examples: MRZ parser (python-mrz), barcode decoder, format-specific extractor
- Strength: MRZ fields are machine-printed and standardized — parsing is fully deterministic at 90% confidence. No hallucination possible. Higher accuracy than AI models on passport fields.

**Policy Grounding Engine — Keyword-Scoring Retrieval**
- Family: Lexical retrieval and evidence-grounded generation
- Examples: BM25, TF-IDF, citation-constrained prompting, relevance scoring
- Strength: Every chatbot answer is grounded in actual policy text — never invented. Token-efficient: only the most relevant sections are sent to the LLM.

**Levenshtein Distance — Fuzzy String Matching**
- Family: Text similarity — local neighbourhood matching
- Examples: k-NN, edit distance, fuzzy matching within 15% tolerance
- Strength: Detects agreement between extraction methods despite typos or formatting differences. Enables confidence boosting when multiple rungs agree on a field value.

---

## SLIDE 2: Engineering, Validation & Infrastructure Algorithms

**Deterministic Service Routing — Keyword Matching**
- Family: Rule-based systems (expert systems with IF-THEN logic)
- Examples: Intent-to-tool maps, keyword index lookup, regex routing
- Strength: Instant (<1 ms), fully auditable, and deterministic — zero risk of sending a user to the wrong service. Critical for onboarding accuracy.

**Rule-Based Validation Agent — Deterministic Rules Engine**
- Family: Expert systems (IF-THEN rules) and constraint solving
- Examples: Field presence checks, expiry validation, cross-document matching, golden dataset comparison
- Strength: Identical results on every run — no LLM hallucination risk. Each rule is testable, traceable, and adjustable via config.yaml without code changes.

**Finite State Machine — Application Wizard (4 Steps)**
- Family: Workflow orchestration and autonomous decision-making
- Examples: Finite-state machines, behaviour trees, directed acyclic graphs
- Strength: Full audit trail at every step (name → upload → review → submitted). Predictable transitions and easy rollback on failure.

**SHA-256 Duplicate Detection**
- Family: Deduplication and data governance
- Examples: SHA-256, MD5, MinHash, locality-sensitive hashing
- Strength: Prevents duplicate storage of identical documents. A unique database constraint on the hash returns the existing record if a user re-uploads the same ID card.

**PostgreSQL + SQLAlchemy ORM**
- Family: Structured retrieval and knowledge representation
- Examples: PostgreSQL + pgvector, SQLAlchemy declarative models, foreign key joins
- Strength: ACID-compliant storage for applications, documents, chat history, and audit trails. User-scoped queries enforced at the database level. pgvector column ready for future semantic search.

**Graceful Degradation Architecture**
- Family: Serving and routing — fallback models and dynamic batching
- Examples: Exponential back-off, health probes, middleware interception
- Strength: If one service fails, the rest still start. Background watchdog retries every 5 seconds (doubling to 60s). The API becomes fully functional as soon as all dependencies recover.

**Idempotency Keys + Race-Safe Transitions**
- Family: Transaction patterns and compensating workflows
- Examples: Idempotency keys with TTL, row-level locking (SELECT FOR UPDATE), retry with back-off
- Strength: Prevents duplicate processing on network retries. Row locking ensures two agents updating the same application status simultaneously don't overwrite each other.

**Cross-Document Validation**
- Family: Information extraction and text similarity
- Examples: Unicode normalization (NFKD), multi-format date parsing, set-based name comparison
- Strength: Validates that a national ID and passport belong to the same person by comparing names (accent-insensitive) and dates (multi-format tolerance). Three mismatches trigger automatic reject.
