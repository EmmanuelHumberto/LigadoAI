ALTER TABLE measurement_sessions
    ADD COLUMN IF NOT EXISTS capture_session_id UUID;

CREATE UNIQUE INDEX IF NOT EXISTS uq_measurement_sessions_capture
    ON measurement_sessions(capture_session_id)
    WHERE capture_session_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS measurement_snapshot_projections (
    snapshot_id UUID PRIMARY KEY
        REFERENCES measurement_snapshots(id) ON DELETE CASCADE,
    capture_session_id UUID NOT NULL,
    signature_id BIGINT NOT NULL,
    timestamp_us BIGINT NOT NULL,
    projected_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_measurement_projections_capture
    ON measurement_snapshot_projections(capture_session_id, timestamp_us);
