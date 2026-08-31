-- COUS v3.2 - conhecimento minimo dos modos publicados pelo firmware.
-- Estes registros descrevem hipoteses, nao confirmacoes automaticas de defeito.

INSERT INTO domains (name, version, status)
VALUES ('tattoo_machines', 'v1', 'active')
ON CONFLICT (name) DO NOTHING;

INSERT INTO knowledge_units (
    id, domain_id, title, statement, knowledge_level, confidence,
    confidence_breakdown, last_validated_at
)
SELECT seed.id, d.id, seed.title, seed.statement, 'confirmed', 0.75,
       '{"evidence_score":0.8,"document_score":0.5,"history_score":0.5,"consistency_score":0.8}'::jsonb,
       NOW()
FROM domains d
CROSS JOIN (
    VALUES
    (
        '00000000-0000-0000-0000-00000000a101'::uuid,
        'Hipotese de rotor travado',
        'Rotor travado ou motor travado e uma hipotese quando o firmware publica locked_rotor_hypothesis; requer inspecao ou ensaio independente.'
    ),
    (
        '00000000-0000-0000-0000-00000000a102'::uuid,
        'Hipotese de desacoplamento mecanico',
        'Desacoplamento mecanico, eixo quebrado, came solto ou giro em falso e uma hipotese quando o firmware publica mechanical_decoupling_hypothesis; requer confirmacao independente.'
    ),
    (
        '00000000-0000-0000-0000-00000000a103'::uuid,
        'Hipotese de sobrecarga do motor',
        'Sobrecarga do motor ou sobrecorrente e uma hipotese quando o firmware publica motor_nominal_overload_hypothesis; requer confirmacao independente.'
    ),
    (
        '00000000-0000-0000-0000-00000000a104'::uuid,
        'Hipotese de sobretensao da fonte',
        'Sobretensao ou tensao acima da nominal e uma hipotese quando o firmware publica source_overvoltage_hypothesis; requer confirmacao independente.'
    ),
    (
        '00000000-0000-0000-0000-00000000a105'::uuid,
        'Hipotese de interrupcao da fonte',
        'Interrupcao de tensao ou queda a zero e uma hipotese quando o firmware publica source_interruption_hypothesis; requer confirmacao independente.'
    ),
    (
        '00000000-0000-0000-0000-00000000a106'::uuid,
        'Hipotese de queda de tensao sob carga',
        'Queda de tensao sob carga, afundamento de tensao ou fonte incapaz de sustentar carga e uma hipotese quando o firmware publica source_sag_under_load_hypothesis; requer confirmacao independente.'
    )
) AS seed(id, title, statement)
WHERE d.name = 'tattoo_machines'
ON CONFLICT (id) DO NOTHING;

INSERT INTO causal_chains (
    id, domain_id, title, condition_expression, probable_cause,
    expected_consequence, confidence
)
SELECT seed.id, d.id, seed.title, seed.condition_expression,
       seed.probable_cause, seed.expected_consequence, 0.75
FROM domains d
CROSS JOIN (
    VALUES
    (
        '00000000-0000-0000-0000-00000000b101'::uuid,
        'Modo publicado: rotor travado',
        'locked_rotor_hypothesis >= 1',
        'Rotor travado ou bloqueio mecanico',
        'Rotacao ausente com corrente elevada e risco termico'
    ),
    (
        '00000000-0000-0000-0000-00000000b102'::uuid,
        'Modo publicado: desacoplamento mecanico',
        'mechanical_decoupling_hypothesis >= 1',
        'Eixo, came ou stroke desacoplado',
        'Motor gira sem transferir movimento util ao mecanismo'
    ),
    (
        '00000000-0000-0000-0000-00000000b103'::uuid,
        'Modo publicado: sobrecarga do motor',
        'motor_nominal_overload_hypothesis >= 1',
        'Carga mecanica ou corrente acima do envelope nominal',
        'Aquecimento, perda de rotacao e reducao de vida util'
    ),
    (
        '00000000-0000-0000-0000-00000000b104'::uuid,
        'Modo publicado: sobretensao da fonte',
        'source_overvoltage_hypothesis >= 1',
        'Tensao aplicada acima do limite do perfil',
        'Estresse eletrico e aumento de velocidade ou dissipacao'
    ),
    (
        '00000000-0000-0000-0000-00000000b105'::uuid,
        'Modo publicado: interrupcao da fonte',
        'source_interruption_hypothesis >= 1',
        'Interrupcao do fornecimento eletrico',
        'Perda momentanea ou total do movimento'
    ),
    (
        '00000000-0000-0000-0000-00000000b106'::uuid,
        'Modo publicado: queda de tensao sob carga',
        'source_sag_under_load_hypothesis >= 1',
        'Fonte ou conexao incapaz de sustentar a carga',
        'Queda de rotacao e instabilidade sob esforco'
    )
) AS seed(
    id, title, condition_expression, probable_cause, expected_consequence
)
WHERE d.name = 'tattoo_machines'
ON CONFLICT (id) DO NOTHING;
