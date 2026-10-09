\c doc_intake;

DROP TABLE IF EXISTS eval_results CASCADE;
DROP TABLE IF EXISTS chat_history CASCADE;
DROP TABLE IF EXISTS processing_log CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS applications CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS documents CASCADE;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP
);

CREATE INDEX IF NOT EXISTS users_username_index ON users (username);

CREATE TABLE IF NOT EXISTS applications (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    service_id VARCHAR(100) NOT NULL,
    status VARCHAR(50) DEFAULT 'incomplete',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS applications_user_id_index ON applications (user_id);
CREATE INDEX IF NOT EXISTS applications_status_index ON applications (status);

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_type VARCHAR(50),
    file_size INTEGER,
    upload_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT 'uploaded',
    content_hash VARCHAR(64),
    metadata JSONB,
    extracted_fields JSONB,
    embedding VECTOR(1536),
    content TEXT,
    application_id INTEGER REFERENCES applications(id)
);

CREATE INDEX IF NOT EXISTS document_embedding_index 
ON documents USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS document_status_index ON documents (status);
CREATE INDEX IF NOT EXISTS document_filename_index ON documents (filename);
CREATE INDEX IF NOT EXISTS document_content_hash_index ON documents (content_hash);

CREATE TABLE IF NOT EXISTS sessions (
    id SERIAL PRIMARY KEY,
    session_id VARCHAR(255) UNIQUE NOT NULL,
    application_id INTEGER REFERENCES applications(id),
    user_id INTEGER REFERENCES users(id),
    current_step VARCHAR(100),
    collected_documents JSONB,
    conversation_history JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS sessions_user_id_index ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_session_id_index ON sessions (session_id);

CREATE TABLE IF NOT EXISTS processing_log (
    id SERIAL PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    application_id INTEGER REFERENCES applications(id),
    action VARCHAR(100) NOT NULL,
    details JSONB,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS processing_log_timestamp_index ON processing_log (timestamp);
CREATE INDEX IF NOT EXISTS processing_log_application_index ON processing_log (application_id);

CREATE TABLE IF NOT EXISTS chat_history (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    session_id VARCHAR(255),
    document_id INTEGER REFERENCES documents(id),
    user_query TEXT NOT NULL,
    assistant_response TEXT,
    intent VARCHAR(50),
    matched_service VARCHAR(100),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS chat_timestamp_index ON chat_history (timestamp);
CREATE INDEX IF NOT EXISTS chat_user_id_index ON chat_history (user_id);

CREATE TABLE IF NOT EXISTS eval_results (
    id SERIAL PRIMARY KEY,
    test_name VARCHAR(255) NOT NULL,
    test_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total_tests INTEGER,
    passed INTEGER,
    failed INTEGER,
    details JSONB
);

CREATE INDEX IF NOT EXISTS eval_results_date_index ON eval_results (test_date);
