-- COUS v3.0 — Camada Cognitiva e Infraestrutura (Documento III, Seção III.8)
-- Migration 010: cognitive_traces, trace_evidences, trace_documents,
--   knowledge_feedback, goldens, diagnosis_queue, audit_log

-- Traces Cognitivos (registro completo de execução cognitiva)
CREATE TABLE IF NOT EXISTS cognitive_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES operational_sessions(id),
    request TEXT NOT NULL,
    response TEXT,
    duration_ms INTEGER,
    confidence_final NUMERIC,
    knowledge_units_used JSONB,
    causal_chains_used JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_traces_session ON cognitive_traces(session_id);
CREATE INDEX IF NOT EXISTS idx_traces_created ON cognitive_traces(created_at DESC);

-- Evidências referenciadas em um trace (N:M)
CREATE TABLE IF NOT EXISTS trace_evidences (
    trace_id UUID NOT NULL REFERENCES cognitive_traces(id) ON DELETE CASCADE,
    evidence_id UUID NOT NULL REFERENCES evidences(id),
    PRIMARY KEY (trace_id, evidence_id)
);

-- Documentos consultados em um trace (com score de recuperação)
CREATE TABLE IF NOT EXISTS trace_documents (
    trace_id UUID NOT NULL REFERENCES cognitive_traces(id) ON DELETE CASCADE,
    document_id UUID NOT NULL REFERENCES knowledge_documents(id),
    retrieval_score NUMERIC,
    PRIMARY KEY (trace_id, document_id)
);

-- Feedback humano estruturado
CREATE TABLE IF NOT EXISTS knowledge_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID REFERENCES technical_cases(id),
    trace_id UUID REFERENCES cognitive_traces(id),
    feedback_type VARCHAR(100) NOT NULL,
    comment TEXT,
    operator_name VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_case ON knowledge_feedback(case_id);
CREATE INDEX IF NOT EXISTS idx_feedback_trace ON knowledge_feedback(trace_id);
CREATE INDEX IF NOT EXISTS idx_feedback_type ON knowledge_feedback(feedback_type);

-- Goldens (exemplos corretos para avaliação)
CREATE TABLE IF NOT EXISTS goldens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trace_id UUID REFERENCES cognitive_traces(id),
    domain_id UUID NOT NULL REFERENCES domains(id),
    title VARCHAR(255) NOT NULL,
    input_context TEXT NOT NULL,
    expected_answer TEXT NOT NULL,
    justification TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_goldens_domain ON goldens(domain_id);

-- Fila de Diagnóstico (assíncrono, com retry)
CREATE TABLE IF NOT EXISTS diagnosis_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    capture_session_id UUID NOT NULL REFERENCES capture_sessions(id),
    instance_id UUID NOT NULL REFERENCES instances(id),
    domain_id UUID REFERENCES domains(id),
    callback_endpoint TEXT,
    priority VARCHAR(50) NOT NULL DEFAULT 'normal',
    evidence_set JSONB NOT NULL DEFAULT '[]'::jsonb,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_payload JSONB,
    queued_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    error_message TEXT
);

ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES domains(id);
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS callback_endpoint TEXT;
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS priority VARCHAR(50) NOT NULL DEFAULT 'normal';
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS evidence_set JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS context JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS request_payload JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE diagnosis_queue ADD COLUMN IF NOT EXISTS result_payload JSONB;

CREATE INDEX IF NOT EXISTS idx_dq_status ON diagnosis_queue(status);
CREATE INDEX IF NOT EXISTS idx_dq_queued ON diagnosis_queue(queued_at) WHERE status = 'pending';

-- Log de Auditoria (append-only, toda ação relevante)
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGSERIAL PRIMARY KEY,
    entity_type VARCHAR(100) NOT NULL,
    entity_id UUID NOT NULL,
    action VARCHAR(100) NOT NULL,
    operator VARCHAR(255),
    payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at DESC);
