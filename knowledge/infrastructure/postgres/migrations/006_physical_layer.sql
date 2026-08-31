-- COUS v3.0 — Camada Física (Documento III, Seção III.3)
-- Migration 006: domains, entities, instances, subsystems, electromechanical_profiles

-- Domínios operacionais (tattoo_machines, power_tools, etc.)
CREATE TABLE IF NOT EXISTS domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL UNIQUE,
    version VARCHAR(50),
    status VARCHAR(50) NOT NULL DEFAULT 'onboarding',
    config JSONB NOT NULL DEFAULT '{}',
    activated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_domains_status ON domains(status);

-- Entidades físicas (modelos abstratos: Motor, Máquina, Sensor, etc.)
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain_id UUID NOT NULL REFERENCES domains(id),
    entity_type VARCHAR(100) NOT NULL,
    manufacturer VARCHAR(255),
    model VARCHAR(255),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_entities_domain ON entities(domain_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_manufacturer_model ON entities(manufacturer, model);

-- Instâncias concretas (número de série)
CREATE TABLE IF NOT EXISTS instances (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id),
    serial_number VARCHAR(255) NOT NULL,
    firmware_version VARCHAR(100),
    manufacture_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_instances_serial ON instances(serial_number);
CREATE INDEX IF NOT EXISTS idx_instances_entity ON instances(entity_id);

-- Subsistemas (parte funcional de uma instância)
CREATE TABLE IF NOT EXISTS subsystems (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES instances(id),
    subsystem_type VARCHAR(100),
    description TEXT
);

CREATE INDEX IF NOT EXISTS idx_subsystems_instance ON subsystems(instance_id);

-- Perfis Eletromecânicos (referência para desvios)
CREATE TABLE IF NOT EXISTS electromechanical_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES entities(id),
    domain_id UUID NOT NULL REFERENCES domains(id),
    profile_label VARCHAR(255) NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(50) NOT NULL DEFAULT 'draft',
    rpm_nominal NUMERIC,
    current_nominal_ma NUMERIC,
    bemf_nominal_v NUMERIC,
    torque_nominal_permille NUMERIC,
    resistance_nominal_mohm NUMERIC,
    efficiency_nominal NUMERIC,
    source_document_id UUID,
    supersedes_id UUID REFERENCES electromechanical_profiles(id),
    validated_by VARCHAR(255),
    activated_at TIMESTAMPTZ,
    deprecated_at TIMESTAMPTZ,
    deprecation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_profiles_entity ON electromechanical_profiles(entity_id);
CREATE INDEX IF NOT EXISTS idx_profiles_domain ON electromechanical_profiles(domain_id);
CREATE INDEX IF NOT EXISTS idx_profiles_status ON electromechanical_profiles(status);
CREATE INDEX IF NOT EXISTS idx_profiles_label ON electromechanical_profiles(profile_label);
CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_label_version
    ON electromechanical_profiles(profile_label, version);
