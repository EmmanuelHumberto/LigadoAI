-- COUS v3.0 — Camada de Conhecimento (Documento III, Seção III.7)
-- Migration 009: knowledge_units, knowledge_unit_sources, knowledge_unit_relations,
--   knowledge_contradictions
-- Representa o Knowledge Graph como entidade de primeira classe no PostgreSQL.

-- Knowledge Units (unidade formal de conhecimento consolidado)
CREATE TABLE IF NOT EXISTS knowledge_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id),
    title VARCHAR(255) NOT NULL,
    statement TEXT NOT NULL,
    knowledge_level VARCHAR(50) NOT NULL DEFAULT 'experimental',
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    confidence_breakdown JSONB,
    version INTEGER NOT NULL DEFAULT 1,
    superseded_by UUID REFERENCES knowledge_units(id),
    last_validated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_ku_confidence CHECK (confidence >= 0.0 AND confidence <= 1.0),
    CONSTRAINT chk_ku_level CHECK (knowledge_level IN ('experimental', 'observed', 'confirmed', 'consolidated'))
);

CREATE INDEX IF NOT EXISTS idx_ku_domain ON knowledge_units(domain_id);
CREATE INDEX IF NOT EXISTS idx_ku_level ON knowledge_units(knowledge_level);
CREATE INDEX IF NOT EXISTS idx_ku_domain_level ON knowledge_units(domain_id, knowledge_level);

-- Origens de KnowledgeUnits (casos confirmados que as originaram)
CREATE TABLE IF NOT EXISTS knowledge_unit_sources (
    knowledge_unit_id UUID NOT NULL REFERENCES knowledge_units(id),
    case_id UUID NOT NULL REFERENCES technical_cases(id),
    PRIMARY KEY (knowledge_unit_id, case_id)
);

-- Relações entre KnowledgeUnits (Knowledge Graph — arestas tipadas)
-- Tipos: refuta | substitui | especializa | generaliza | complementa | corrobora
CREATE TABLE IF NOT EXISTS knowledge_unit_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_ku_id UUID NOT NULL REFERENCES knowledge_units(id),
    target_ku_id UUID NOT NULL REFERENCES knowledge_units(id),
    relation_type VARCHAR(50) NOT NULL,
    confidence NUMERIC NOT NULL DEFAULT 0.0,
    source VARCHAR(50) NOT NULL DEFAULT 'inference',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT no_self_relation CHECK (source_ku_id != target_ku_id),
    CONSTRAINT chk_relation_type CHECK (
        relation_type IN ('refuta', 'substitui', 'especializa', 'generaliza', 'complementa', 'corrobora')
    )
);

CREATE INDEX IF NOT EXISTS idx_kur_source ON knowledge_unit_relations(source_ku_id);
CREATE INDEX IF NOT EXISTS idx_kur_target ON knowledge_unit_relations(target_ku_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_kur_unique
    ON knowledge_unit_relations(source_ku_id, target_ku_id, relation_type);

-- Contradições formais (evidência que contradiz uma KnowledgeUnit)
CREATE TABLE IF NOT EXISTS knowledge_contradictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    knowledge_unit_id UUID NOT NULL REFERENCES knowledge_units(id),
    contradicting_case_id UUID REFERENCES technical_cases(id),
    contradicting_evidence_id UUID REFERENCES evidences(id),
    description TEXT NOT NULL,
    resolution_status VARCHAR(50) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kc_ku ON knowledge_contradictions(knowledge_unit_id);
CREATE INDEX IF NOT EXISTS idx_kc_status ON knowledge_contradictions(resolution_status);
