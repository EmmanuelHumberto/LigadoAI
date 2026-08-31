-- COUS v3.0 — Camada Operacional (Documento III, Seção III.4)
-- Migration 007: operational_sessions, capture_sessions, observations, snapshots,
--   electromechanical_signatures, signature_deviations

-- Sessões operacionais genéricas (captura, conversa, diagnóstico, laudo)
CREATE TABLE IF NOT EXISTS operational_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_type VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    operator_name VARCHAR(255),
    status VARCHAR(100) NOT NULL DEFAULT 'open'
);

CREATE INDEX IF NOT EXISTS idx_op_sessions_type ON operational_sessions(session_type);
CREATE INDEX IF NOT EXISTS idx_op_sessions_status ON operational_sessions(status);

-- Sessões de captura (especialização de operational_sessions com métricas)
CREATE TABLE IF NOT EXISTS capture_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operational_session_id UUID NOT NULL REFERENCES operational_sessions(id),
    instance_id UUID NOT NULL REFERENCES instances(id),
    valid_ratio NUMERIC,
    total_signatures INTEGER NOT NULL DEFAULT 0,
    valid_signatures INTEGER NOT NULL DEFAULT 0,
    diagnosis_status VARCHAR(50) DEFAULT 'pending',
    diagnosis_queued_at TIMESTAMPTZ,
    diagnosis_completed_at TIMESTAMPTZ,
    diagnosis_correlation_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_valid_ratio CHECK (valid_ratio IS NULL OR (valid_ratio >= 0.0 AND valid_ratio <= 1.0))
);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_instance ON capture_sessions(instance_id);
CREATE INDEX IF NOT EXISTS idx_capture_sessions_diagnosis ON capture_sessions(diagnosis_status);

-- Observações (alto volume — particionado por timestamp_us)
CREATE TABLE IF NOT EXISTS observations (
    id BIGSERIAL,
    capture_session_id UUID NOT NULL,
    timestamp_us BIGINT NOT NULL,
    observation_type VARCHAR(100) NOT NULL,
    value NUMERIC NOT NULL,
    unit VARCHAR(50) NOT NULL,
    PRIMARY KEY (id, timestamp_us)
) PARTITION BY RANGE (timestamp_us);

-- Partição inicial cobrindo 2024-2030
CREATE TABLE IF NOT EXISTS observations_default PARTITION OF observations
    DEFAULT;

CREATE INDEX IF NOT EXISTS idx_observations_session ON observations(capture_session_id);

-- Snapshots (alto volume — particionado por timestamp_us)
CREATE TABLE IF NOT EXISTS snapshots (
    id BIGSERIAL,
    capture_session_id UUID NOT NULL,
    timestamp_us BIGINT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (id, timestamp_us)
) PARTITION BY RANGE (timestamp_us);

CREATE TABLE IF NOT EXISTS snapshots_default PARTITION OF snapshots
    DEFAULT;

CREATE INDEX IF NOT EXISTS idx_snapshots_session ON snapshots(capture_session_id);

-- Assinaturas Eletromecânicas (alto volume — particionado por timestamp_us)
CREATE TABLE IF NOT EXISTS electromechanical_signatures (
    id BIGSERIAL,
    capture_session_id UUID NOT NULL,
    timestamp_us BIGINT NOT NULL,
    profile_label VARCHAR(255) NOT NULL,
    valid BOOLEAN NOT NULL DEFAULT TRUE,
    rpm NUMERIC,
    motor_current_ma NUMERIC,
    voltage_mv NUMERIC,
    bemf_v NUMERIC,
    equivalent_resistance_mohm NUMERIC,
    torque_load_permille NUMERIC,
    PRIMARY KEY (id, timestamp_us),

    CONSTRAINT chk_profile_exists CHECK (profile_label IS NOT NULL)
) PARTITION BY RANGE (timestamp_us);

CREATE TABLE IF NOT EXISTS electromechanical_signatures_default PARTITION OF electromechanical_signatures
    DEFAULT;

CREATE INDEX IF NOT EXISTS idx_signatures_session ON electromechanical_signatures(capture_session_id);

-- Desvios (produzidos exclusivamente pelo Firmware)
CREATE TABLE IF NOT EXISTS signature_deviations (
    id BIGSERIAL PRIMARY KEY,
    signature_id BIGINT NOT NULL,
    bemf_error_permille NUMERIC,
    equivalent_resistance_error_permille NUMERIC,
    torque_error_permille NUMERIC,
    current_error_permille NUMERIC,
    produced_by VARCHAR(50) NOT NULL DEFAULT 'firmware',

    CONSTRAINT chk_firmware_only CHECK (produced_by = 'firmware')
);
