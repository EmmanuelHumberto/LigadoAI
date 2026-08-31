-- COUS v3.2 - separa o resultado do diagnostico da entrega do callback.

ALTER TABLE diagnosis_queue
    ADD COLUMN IF NOT EXISTS callback_status VARCHAR(50) NOT NULL DEFAULT 'pending';
ALTER TABLE diagnosis_queue
    ADD COLUMN IF NOT EXISTS callback_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE diagnosis_queue
    ADD COLUMN IF NOT EXISTS callback_last_attempt_at TIMESTAMPTZ;
ALTER TABLE diagnosis_queue
    ADD COLUMN IF NOT EXISTS callback_next_attempt_at TIMESTAMPTZ;
ALTER TABLE diagnosis_queue
    ADD COLUMN IF NOT EXISTS callback_error TEXT;

UPDATE diagnosis_queue
SET callback_status = CASE
    WHEN status = 'completed' THEN 'delivered'
    WHEN status = 'failed' AND result_payload IS NULL THEN 'not_available'
    ELSE callback_status
END
WHERE callback_attempts = 0;

CREATE INDEX IF NOT EXISTS idx_dq_callback_outbox
    ON diagnosis_queue(callback_status, callback_next_attempt_at)
    WHERE callback_status IN ('pending', 'failed');
