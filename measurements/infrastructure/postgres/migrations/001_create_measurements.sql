CREATE TABLE IF NOT EXISTS measurement_sessions (
    id UUID PRIMARY KEY,
    status TEXT NOT NULL,
    fabricante TEXT NOT NULL DEFAULT '',
    modelo TEXT NOT NULL DEFAULT '',
    numero_serie TEXT NOT NULL DEFAULT '',
    tipo_maquina TEXT NOT NULL DEFAULT '',
    tipo_motor TEXT NOT NULL DEFAULT '',
    sistema_transmissao TEXT NOT NULL DEFAULT '',
    curso_nominal_mm DOUBLE PRECISION,
    curso_min_mm DOUBLE PRECISION,
    curso_max_mm DOUBLE PRECISION,
    tipo_coleta TEXT NOT NULL DEFAULT 'desempenho',
    peca_substituida TEXT NOT NULL DEFAULT '',
    observacoes TEXT NOT NULL DEFAULT '',
    tecnico TEXT NOT NULL DEFAULT '',
    porta_serial TEXT NOT NULL DEFAULT '',
    baudrate INTEGER NOT NULL DEFAULT 115200,
    duracao_seg DOUBLE PRECISION NOT NULL DEFAULT 30,
    verticais JSONB NOT NULL DEFAULT '[]'::jsonb,
    total_snapshots INTEGER NOT NULL DEFAULT 0,
    valid_snapshots INTEGER NOT NULL DEFAULT 0,
    invalid_snapshots INTEGER NOT NULL DEFAULT 0,
    diagnostic JSONB,
    report_markdown TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS measurement_snapshots (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES measurement_sessions(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    timestamp_us BIGINT,
    status TEXT NOT NULL,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_measurement_sessions_updated_at
    ON measurement_sessions(updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_measurement_snapshots_session_created_at
    ON measurement_snapshots(session_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_measurement_snapshots_session_type
    ON measurement_snapshots(session_id, type);
