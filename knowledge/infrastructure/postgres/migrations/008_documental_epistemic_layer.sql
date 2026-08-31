-- COUS v3.0 — Camadas Documental e Epistêmica (Documento III, Seções III.5-III.6)
-- Migration 008: estende knowledge_documents/chunks + technical_cases, evidences,
--   causal_chains, hypotheses, explanations

-- Estender knowledge_documents com colunas do COUS v3
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES domains(id);
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS authority VARCHAR(50) NOT NULL DEFAULT 'low';
ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS language VARCHAR(10) DEFAULT 'pt';

-- Estender knowledge_chunks com coluna de uso histórico (score composto RAG)
ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS usage_count_confirmed INTEGER NOT NULL DEFAULT 0;

-- Casos Técnicos (unidade de aprendizado operacional)
CREATE TABLE IF NOT EXISTS technical_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id),
    instance_id UUID NOT NULL REFERENCES instances(id),
    capture_session_id UUID REFERENCES capture_sessions(id),
    reported_problem TEXT,
    final_diagnosis TEXT,
    solution_applied TEXT,
    solution_type VARCHAR(50),
    result_status VARCHAR(100),
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_technical_cases_domain ON technical_cases(domain_id);
CREATE INDEX IF NOT EXISTS idx_technical_cases_instance ON technical_cases(instance_id);
CREATE INDEX IF NOT EXISTS idx_technical_cases_status ON technical_cases(status);

-- Evidências (classificadas por tipo e força)
CREATE TABLE IF NOT EXISTS evidences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES technical_cases(id),
    evidence_type VARCHAR(100) NOT NULL,
    evidence_strength VARCHAR(50) NOT NULL DEFAULT 'weak',
    source_reference TEXT,
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    status VARCHAR(50) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_evidence_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_evidences_case ON evidences(case_id);

-- Cadeias Causais (condição → causa → consequência)
CREATE TABLE IF NOT EXISTS causal_chains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id),
    title VARCHAR(255) NOT NULL,
    condition_expression TEXT NOT NULL,
    probable_cause TEXT NOT NULL,
    expected_consequence TEXT NOT NULL,
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_causal_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_causal_chains_domain ON causal_chains(domain_id);

-- Hipóteses (com confidence_breakdown para sistema formal de confiança)
CREATE TABLE IF NOT EXISTS hypotheses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES technical_cases(id),
    causal_chain_id UUID REFERENCES causal_chains(id),
    description TEXT NOT NULL,
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    confidence_breakdown JSONB,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_hypothesis_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_hypotheses_case ON hypotheses(case_id);
CREATE INDEX IF NOT EXISTS idx_hypotheses_primary ON hypotheses(case_id) WHERE is_primary = TRUE;

-- Explicações (hipótese + narrativa causal)
CREATE TABLE IF NOT EXISTS explanations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id UUID NOT NULL REFERENCES technical_cases(id),
    hypothesis_id UUID NOT NULL REFERENCES hypotheses(id),
    narrative TEXT NOT NULL,
    narrative_type VARCHAR(50) DEFAULT 'technical',
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_explanation_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0)
);

CREATE INDEX IF NOT EXISTS idx_explanations_case ON explanations(case_id);
CREATE INDEX IF NOT EXISTS idx_explanations_hypothesis ON explanations(hypothesis_id);
