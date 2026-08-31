-- OpenTracy knowledge vertical — power supplies schema.
-- Extends knowledge_documents with structured fields extracted from power supply manuals.

CREATE TABLE IF NOT EXISTS power_supplies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,

    -- Identificação
    manufacturer_name        TEXT NOT NULL,
    model                    TEXT NOT NULL,
    article_numbers          TEXT[],

    -- Elétrica
    input_voltage_v          NUMERIC,
    input_current_a          NUMERIC,
    output_voltage_min_v     NUMERIC,
    output_voltage_max_v     NUMERIC,
    output_voltage_step_v    NUMERIC,
    output_current_continuous_a NUMERIC,
    output_current_peak_a    NUMERIC,
    outputs                  INTEGER,

    -- Controles
    has_display              BOOLEAN,
    has_footswitch           BOOLEAN,
    footswitch_modes         TEXT[],
    has_start_pause          BOOLEAN,
    has_memory_presets       BOOLEAN,
    memory_presets_count     INTEGER,

    -- Funções
    has_nitro                BOOLEAN,
    has_timer                BOOLEAN,
    timer_max_h              NUMERIC,
    auto_power_off_min       INTEGER,
    has_overcurrent_protection BOOLEAN,

    -- Conexão
    connection_type          TEXT,

    -- Regulatório
    ce_directives            TEXT[],
    applied_standards        TEXT[],
    certifications           TEXT[],

    -- Garantia
    warranty_years           INTEGER,
    warranty_notes           TEXT,

    -- Manual
    manual_version           TEXT,
    manual_date              DATE,
    original_language        TEXT,
    available_languages      TEXT[],

    -- Overflow
    raw_specs                JSONB NOT NULL DEFAULT '{}',
    extra                    JSONB NOT NULL DEFAULT '{}',

    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_power_supplies_document_id
    ON power_supplies(document_id);
CREATE INDEX IF NOT EXISTS idx_power_supplies_manufacturer
    ON power_supplies(manufacturer_name);
CREATE INDEX IF NOT EXISTS idx_power_supplies_model
    ON power_supplies(model);
