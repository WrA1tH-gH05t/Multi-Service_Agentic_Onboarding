-- init_db.sql
-- Multi-Service Agentic Onboarding System Database Schema
-- Updated to support: users, applications, service catalogue, sessions, audit trails

-- Connect to the 'postgres' database (default admin database)
\c doc_intake;

-- Enable pgvector extension for vector embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================
-- Phase 6: User accounts and authentication
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,  -- Never store plain text passwords
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS users_username_index ON users (username);

-- ============================================================
-- Applications: one per user per service
-- ============================================================
CREATE TABLE IF NOT EXISTS applications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    service_id VARCHAR(100) NOT NULL,      -- e.g., 'basic_registration'
    status VARCHAR(50) DEFAULT 'incomplete', -- incomplete, validating, needs_human_review, complete, rejected, unverifiable
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS applications_user_id_index ON applications (user_id);
CREATE INDEX IF NOT EXISTS applications_status_index ON applications (status);

-- ============================================================
-- Documents (existing table, enhanced)
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_type VARCHAR(50),
    file_size INTEGER,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'uploaded',
    content_hash VARCHAR(64),              -- SHA256 hash for duplicate detection (Phase 3)
    metadata JSONB,                        -- Extra info (classification, confidence, etc.)
    extracted_fields JSONB,                -- OCR-extracted fields from identity documents
    embedding VECTOR(1536),                -- AI vector representation
    content TEXT,                          -- Extracted text from the document
    application_id INTEGER REFERENCES applications(id)  -- Link to application if associated
);

CREATE INDEX IF NOT EXISTS document_embedding_index 
ON documents USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS document_status_index ON documents (status);
CREATE INDEX IF NOT EXISTS document_filename_index ON documents (filename);
CREATE INDEX IF NOT EXISTS document_content_hash_index ON documents (content_hash);

-- ============================================================
-- Session state tracking (collection agent state, Phase 2)
-- ============================================================
CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE NOT NULL,
    application_id INTEGER REFERENCES applications(id),
    user_id INTEGER REFERENCES users(id),
    current_step VARCHAR(100),
    collected_documents JSONB,             -- List of uploaded document IDs
    conversation_history JSONB,            -- Chat history for this session
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_id_index ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_session_id_index ON sessions (session_id);

-- ============================================================
-- Processing log (audit trail, Phase 7: Observability)
-- ============================================================
CREATE TABLE IF NOT EXISTS processing_log (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    application_id INTEGER REFERENCES applications(id),
    action VARCHAR(100) NOT NULL,          -- e.g., 'uploaded', 'ocr_done', 'validated'
    details JSONB,                         -- Extra details about the action
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS processing_log_timestamp_index ON processing_log (timestamp);
CREATE INDEX IF NOT EXISTS processing_log_application_index ON processing_log (application_id);

-- ============================================================
-- Chat history (conversation log, Phase 7)
-- ============================================================
CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    session_id VARCHAR(255),
    document_id INTEGER REFERENCES documents(id),
    user_query TEXT NOT NULL,
    assistant_response TEXT,
    intent VARCHAR(50),                   -- Detected intent (faq, apply, etc.)
    matched_service VARCHAR(100),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_timestamp_index ON chat_history (timestamp);
CREATE INDEX IF NOT EXISTS chat_user_id_index ON chat_history (user_id);

-- ============================================================
-- Evaluation results tracking (Phase 7: Continuous improvement)
-- ============================================================
CREATE TABLE IF NOT EXISTS eval_results (
    id SERIAL PRIMARY KEY,
    test_name VARCHAR(255) NOT NULL,       -- e.g., 'routing_accuracy', 'extraction_golden'
    test_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_tests INTEGER,
    passed INTEGER,
    failed INTEGER,
    details JSONB                          -- Per-test breakdown
);

CREATE INDEX IF NOT EXISTS eval_results_date_index ON eval_results (test_date);

-- ============================================================
-- You're done! The database is now ready to use.
-- Next steps:
-- 1. Start the Docker containers (docker compose up -d)
-- 2. Run this script once (psql -U intake -d doc_intake -f init_db.sql)
-- 3. Start the FastAPI server (uvicorn app.main:app --reload)
-- 4. Open the Streamlit app (streamlit run app.py)
