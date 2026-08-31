CREATE TABLE IF NOT EXISTS electromechanical_correlation_relations (
    id BIGSERIAL PRIMARY KEY,
    snapshot_id UUID NOT NULL
        REFERENCES measurement_snapshots(id) ON DELETE CASCADE,
    capture_session_id UUID NOT NULL,
    signature_id BIGINT NOT NULL,
    timestamp_us BIGINT NOT NULL,
    relation_index SMALLINT NOT NULL,
    relation_id TEXT NOT NULL,
    layer SMALLINT NOT NULL CHECK (layer BETWEEN 0 AND 3),
    assessment SMALLINT NOT NULL CHECK (assessment BETWEEN 0 AND 4),
    observed DOUBLE PRECISION,
    reference DOUBLE PRECISION,
    residual DOUBLE PRECISION,
    error_permille INTEGER,
    confidence_permille INTEGER NOT NULL
        CHECK (confidence_permille BETWEEN 0 AND 1000),
    source_channels TEXT NOT NULL DEFAULT '',
    limitation TEXT NOT NULL DEFAULT '',
    valid BOOLEAN NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (snapshot_id, relation_index)
);

CREATE INDEX IF NOT EXISTS idx_correlation_relations_capture_time
    ON electromechanical_correlation_relations(capture_session_id, timestamp_us);

CREATE INDEX IF NOT EXISTS idx_correlation_relations_capture_mode
    ON electromechanical_correlation_relations(
        capture_session_id,
        relation_id,
        assessment,
        timestamp_us
    );
