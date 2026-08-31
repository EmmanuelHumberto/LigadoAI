-- OpenTracy knowledge vertical — machine manuals schema.
-- Extends knowledge_documents with structured fields extracted from tattoo machine manuals.

CREATE TABLE IF NOT EXISTS machine_manuals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,

    -- Identificação
    commercial_name          TEXT,
    technical_name           TEXT,
    model                    TEXT NOT NULL,
    manufacturer_name        TEXT NOT NULL,
    manufacturer_country     TEXT,
    manufacturer_address     TEXT,

    -- Regulatório
    anvisa_registration      TEXT,
    ce_directives            TEXT[],
    applied_standards        TEXT[],
    certifications           TEXT[],
    machine_classification   TEXT,
    machine_category         TEXT NOT NULL,

    -- Motor
    motor_type               TEXT,
    motor_brand              TEXT,
    motor_power_w            NUMERIC,
    motor_efficiency_pct     NUMERIC,

    -- Corpo
    body_material            TEXT,
    manufacturing_process    TEXT,
    weight_g                 INTEGER,
    weight_without_battery_g INTEGER,
    length_mm                NUMERIC,
    width_mm                 NUMERIC,
    height_mm                NUMERIC,
    diameter_mm              NUMERIC,
    wired                    BOOLEAN,
    wireless                 BOOLEAN,
    max_altitude_m           INTEGER,

    -- Curso e mecânica
    system_type              TEXT,
    stroke_mm                NUMERIC,
    stroke_options_mm        NUMERIC[],
    stroke_adjustable        BOOLEAN,
    give_adjustable          BOOLEAN,
    give_range_mm            NUMERIC,
    has_interchangeable_springs BOOLEAN,
    spring_types             TEXT[],

    -- Agulha
    needle_compatibility     TEXT[],
    needle_depth_adjustable  BOOLEAN,
    needle_depth_per_click_mm NUMERIC,
    max_needle_configuration TEXT,
    max_tube_diam_mm         NUMERIC,

    -- Elétrica
    voltage_min_v            NUMERIC,
    voltage_max_v            NUMERIC,
    startup_voltage_v        NUMERIC,
    voltage_step_v           NUMERIC,
    current_max_a            NUMERIC,
    current_startup_ma       INTEGER,
    power_consumption_w      NUMERIC,

    -- Frequência / RPM
    frequency_min_hz         NUMERIC,
    frequency_max_hz         NUMERIC,
    rpm_min                  INTEGER,
    rpm_max                  INTEGER,

    -- Conectividade
    has_bluetooth            BOOLEAN,
    bluetooth_app            TEXT,
    bluetooth_purpose        TEXT,
    connection_type          TEXT,

    -- Give (eGive FK Irons)
    has_egive                BOOLEAN,
    egive_levels             INTEGER[],

    -- Display
    has_display              BOOLEAN,
    display_type             TEXT,
    display_features         TEXT[],
    display_timeout_s        INTEGER,
    has_timer                BOOLEAN,

    -- Bateria
    has_battery              BOOLEAN,
    battery_removable        BOOLEAN,
    battery_type             TEXT,
    battery_model            TEXT,
    battery_capacity_mah     INTEGER,
    battery_nominal_voltage_v NUMERIC,
    battery_life_low_v_h     NUMERIC,
    battery_life_high_v_h    NUMERIC,
    battery_auto_off_min     INTEGER,
    battery_warranty_months  INTEGER,
    charge_port              TEXT,
    charge_input_a           NUMERIC,
    charge_time_min_h        NUMERIC,
    charge_time_max_h        NUMERIC,

    -- Operação
    suggested_voltage_min_v  NUMERIC,
    suggested_voltage_max_v  NUMERIC,
    operating_temp_min_c     INTEGER,
    operating_temp_max_c     INTEGER,
    operating_humidity_min_pct INTEGER,
    operating_humidity_max_pct INTEGER,
    operation_mode           TEXT,

    -- Manutenção
    maintenance_interval_h   INTEGER,
    autoclavable             BOOLEAN,
    autoclave_temp_max_c     NUMERIC,
    sterilization_note       TEXT,
    grip_autoclavable        BOOLEAN,

    -- Acessórios e ergonomia
    accessories              TEXT[],
    left_handed_support      BOOLEAN,
    grip_material            TEXT,

    -- Garantia
    warranty_years           INTEGER,
    warranty_notes           TEXT,
    motor_warranty_years     INTEGER,
    lifetime_warranty_parts  TEXT[],

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
CREATE INDEX IF NOT EXISTS idx_machine_manuals_document_id
    ON machine_manuals(document_id);
CREATE INDEX IF NOT EXISTS idx_machine_manuals_manufacturer
    ON machine_manuals(manufacturer_name);
CREATE INDEX IF NOT EXISTS idx_machine_manuals_model
    ON machine_manuals(model);
CREATE INDEX IF NOT EXISTS idx_machine_manuals_category
    ON machine_manuals(machine_category);
CREATE INDEX IF NOT EXISTS idx_machine_manuals_anvisa
    ON machine_manuals(anvisa_registration)
    WHERE anvisa_registration IS NOT NULL;
