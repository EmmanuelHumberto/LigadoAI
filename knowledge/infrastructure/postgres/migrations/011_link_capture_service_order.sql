-- COUS v3.2 - vinculo rastreavel entre medicao e ordem de servico.
-- A OS continua sendo um knowledge_document; a captura referencia esse documento.

ALTER TABLE capture_sessions
    ADD COLUMN IF NOT EXISTS service_order_document_id UUID
        REFERENCES knowledge_documents(id);

ALTER TABLE capture_sessions
    ADD COLUMN IF NOT EXISTS header_observations TEXT;

CREATE INDEX IF NOT EXISTS idx_capture_sessions_service_order
    ON capture_sessions(service_order_document_id);
