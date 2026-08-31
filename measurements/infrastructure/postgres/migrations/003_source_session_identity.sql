ALTER TABLE measurement_sessions
    ADD COLUMN IF NOT EXISTS source_session_id TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_measurement_sessions_source_session_id
    ON measurement_sessions(source_session_id)
    WHERE source_session_id <> '';
