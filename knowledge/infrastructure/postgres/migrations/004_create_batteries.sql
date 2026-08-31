-- OpenTracy knowledge vertical — batteries schema.
-- Extends knowledge_documents with structured fields extracted from battery manuals/specs.

CREATE TABLE IF NOT EXISTS batteries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,

    -- Identificação
    manufacturer_name        TEXT NOT NULL,
    model                    TEXT NOT NULL,
    article_numbers          TEXT[],

    -- Especificações
    battery_type             TEXT,
    battery_model            TEXT,
    capacity_mah             INTEGER,
    nominal_voltage_v        NUMERIC,

    -- Carga
    charge_port              TEXT,
    charge_input_v           NUMERIC,
    charge_input_a           NUMERIC,
    charge_time_min_h        NUMERIC,
    charge_time_max_h        NUMERIC,

    -- Autonomia
    battery_life_low_v_h     NUMERIC,
    battery_life_high_v_h    NUMERIC,
    auto_off_min             INTEGER,

    -- Compatibilidade
    removable                BOOLEAN,
    compatible_machines      TEXT[],
    compatible_power_supplies TEXT[],

    -- Dimensões
    weight_g                 INTEGER,
    length_mm                NUMERIC,
    width_mm                 NUMERIC,
    height_mm                NUMERIC,
    diameter_mm              NUMERIC,

    -- Segurança
    operating_temp_min_c     INTEGER,
    operating_temp_max_c     INTEGER,
    storage_temp_min_c       INTEGER,
    storage_temp_max_c       INTEGER,
    max_altitude_m           INTEGER,

    -- Regulatório
    ce_directives            TEXT[],
    applied_standards        TEXT[],
    certifications           TEXT[],

    -- Garantia
    warranty_months          INTEGER,
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
CREATE INDEX IF NOT EXISTS idx_batteries_document_id
    ON batteries(document_id);
CREATE INDEX IF NOT EXISTS idx_batteries_manufacturer
    ON batteries(manufacturer_name);
CREATE INDEX IF NOT EXISTS idx_batteries_model
    ON batteries(model);
CREATE INDEX IF NOT EXISTS idx_batteries_type
    ON batteries(battery_type);
