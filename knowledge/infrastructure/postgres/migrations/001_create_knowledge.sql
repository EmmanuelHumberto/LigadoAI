-- OpenTracy knowledge vertical schema.
-- Source of truth lives in these tables; vector indexes are derived/versioned.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS knowledge_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_uri TEXT NOT NULL,
    canonical_path TEXT,
    title TEXT,
    manufacturer TEXT,
    model TEXT,
    category TEXT,
    document_type TEXT,
    content_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    error_details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status
    ON knowledge_documents(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_content_hash
    ON knowledge_documents(content_hash);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_manufacturer
    ON knowledge_documents(manufacturer);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_model
    ON knowledge_documents(model);
CREATE INDEX IF NOT EXISTS idx_knowledge_documents_metadata
    ON knowledge_documents USING GIN(metadata);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document_id
    ON knowledge_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_text_hash
    ON knowledge_chunks(text_hash);
CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_text_search
    ON knowledge_chunks USING GIN(to_tsvector('simple', text));

CREATE TABLE IF NOT EXISTS knowledge_embeddings (
    chunk_id UUID PRIMARY KEY REFERENCES knowledge_chunks(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    vector_raw FLOAT4[] NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_embeddings_model_dimension
    ON knowledge_embeddings(embedding_model, dimension);

CREATE TABLE IF NOT EXISTS knowledge_corpus_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version BIGSERIAL UNIQUE,
    status TEXT NOT NULL,
    document_count INTEGER NOT NULL DEFAULT 0,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    embedding_model TEXT NOT NULL,
    vector_dimension INTEGER NOT NULL,
    chunking_strategy TEXT NOT NULL,
    ranking_strategy TEXT NOT NULL,
    prompt_version TEXT,
    converter_version TEXT,
    ocr_profile TEXT,
    schema_version TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    source_uri TEXT,
    document_id UUID REFERENCES knowledge_documents(id),
    status TEXT NOT NULL,
    stage TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER NOT NULL DEFAULT 0,
    idempotency_key TEXT,
    metadata JSONB NOT NULL DEFAULT '{}',
    error_details JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_status
    ON knowledge_jobs(status);
CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_idempotency_active
    ON knowledge_jobs(idempotency_key)
    WHERE status IN ('queued', 'running', 'processing');
