-- OpenTracy knowledge vertical — cartridges schema.
-- Extends knowledge_documents with structured fields extracted from cartridge manuals.

CREATE TABLE IF NOT EXISTS cartridges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,

    -- Identificação
    manufacturer_name        TEXT NOT NULL,
    manufacturer_country     TEXT,
    importer_name            TEXT,
    model                    TEXT NOT NULL,
    article_numbers          TEXT[],

    -- Configuração
    cartridge_type           TEXT NOT NULL,
    needle_count             INTEGER NOT NULL,
    needle_diameter_mm       NUMERIC NOT NULL,
    needle_diameter_code     TEXT,
    needle_configuration     TEXT,
    taper                    TEXT,

    -- Materiais
    needle_material          TEXT,
    body_material            TEXT,
    packaging_material       TEXT,

    -- Membrana
    has_membrane             BOOLEAN,
    membrane_material        TEXT,
    transparent              BOOLEAN,

    -- Esterilização
    sterilization_method     TEXT,
    sterile_individual       BOOLEAN,
    sterility_shelf_life_years INTEGER,
    single_use               BOOLEAN,

    -- Embalagem
    units_per_box            INTEGER,
    blister_pack             BOOLEAN,

    -- Procedimento
    procedure_type           TEXT,

    -- Compatibilidade
    compatible_machines      TEXT[],
    cartridge_standard       TEXT,

    -- Regulatório
    anvisa_registration      TEXT,
    ce_directives            TEXT[],
    certifications           TEXT[],

    -- Armazenamento
    storage_temp_min_c       INTEGER,
    storage_temp_max_c       INTEGER,

    -- Garantia
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
CREATE INDEX IF NOT EXISTS idx_cartridges_document_id
    ON cartridges(document_id);
CREATE INDEX IF NOT EXISTS idx_cartridges_manufacturer
    ON cartridges(manufacturer_name);
CREATE INDEX IF NOT EXISTS idx_cartridges_type
    ON cartridges(cartridge_type);
CREATE INDEX IF NOT EXISTS idx_cartridges_needle_count
    ON cartridges(needle_count);
CREATE INDEX IF NOT EXISTS idx_cartridges_diameter
    ON cartridges(needle_diameter_mm);
CREATE INDEX IF NOT EXISTS idx_cartridges_anvisa
    ON cartridges(anvisa_registration)
    WHERE anvisa_registration IS NOT NULL;
