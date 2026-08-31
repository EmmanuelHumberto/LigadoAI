-- Align the operational projection with firmware correlation frame v4.
-- Legacy equivalent/torque/current deviation columns remain for old records only.
ALTER TABLE electromechanical_signatures
    ADD COLUMN IF NOT EXISTS winding_resistance_mohm NUMERIC;

ALTER TABLE signature_deviations
    ADD COLUMN IF NOT EXISTS winding_resistance_error_permille NUMERIC,
    ADD COLUMN IF NOT EXISTS rpm_error_permille NUMERIC,
    ADD COLUMN IF NOT EXISTS electrical_power_error_permille NUMERIC;

UPDATE electromechanical_signatures
SET winding_resistance_mohm = equivalent_resistance_mohm
WHERE winding_resistance_mohm IS NULL
  AND equivalent_resistance_mohm IS NOT NULL;

UPDATE signature_deviations
SET winding_resistance_error_permille = equivalent_resistance_error_permille
WHERE winding_resistance_error_permille IS NULL
  AND equivalent_resistance_error_permille IS NOT NULL;

COMMENT ON COLUMN electromechanical_signatures.equivalent_resistance_mohm IS
    'Deprecated compatibility field; use winding_resistance_mohm.';
COMMENT ON COLUMN signature_deviations.equivalent_resistance_error_permille IS
    'Deprecated compatibility field; use winding_resistance_error_permille.';
