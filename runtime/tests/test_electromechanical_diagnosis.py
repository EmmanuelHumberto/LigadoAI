"""Tests for firmware-mode participation in OpenTracy diagnosis."""

from __future__ import annotations

import asyncio
from uuid import UUID

import httpx

from runtime.diagnosis.electromechanical import (
    build_persisted_correlation_evidence,
    correlation_contract_state,
    extract_causal_metrics,
    extract_firmware_modes,
    summarize_persisted_relations,
)
from runtime.diagnosis.worker import DiagnosisWorker


def _correlation_evidence(
    *,
    mode_id: str = "locked_rotor_hypothesis",
    assessment: str = "critical",
    persistent: bool = True,
    active_now: bool = True,
) -> dict:
    return {
        "type": "electromechanical_correlation_frame",
        "version": 3,
        "strength": "strong",
        "confidence": 0.85,
        "profile": {
            "id": "motor-test",
            "nominal_current_ma": 400,
        },
        "closure": {
            "electrical": {
                "bus_voltage_mv": 6000,
                "motor_current_ma": 900,
            },
            "motor": {
                "rpm_mpu": 0,
                "bemf_error_permille": 220,
            },
        },
        "diagnostic_modes": [
            {
                "id": mode_id,
                "label": "Rotor travado",
                "description": "Rotacao ausente com corrente elevada.",
                "assessment": assessment,
                "confidence_permille_max": 850,
                "persistent": persistent,
                "active_now": active_now,
                "active_frames": 2,
                "max_consecutive_frames": 2,
                "observed": 900,
                "reference": 800,
                "residual": 100,
                "source_channels": "mpu,power,motor_nominal_current",
                "limitation": "requires independent confirmation",
            }
        ],
    }


def test_extracts_only_known_active_firmware_modes():
    evidence = _correlation_evidence()
    consistent = _correlation_evidence(assessment="consistent")
    unknown = _correlation_evidence(mode_id="invented_mode")

    modes = extract_firmware_modes([consistent, unknown, evidence])

    assert len(modes) == 1
    assert modes[0].mode_id == "locked_rotor_hypothesis"
    assert modes[0].persistent is True


def test_rebuilds_persistent_mode_from_normalized_relation_rows():
    rows = [
        {
            "snapshot_id": f"frame-{index}",
            "timestamp_us": index * 1_000_000,
            "relation_id": "locked_rotor_hypothesis",
            "assessment": assessment,
            "confidence_permille": 850,
            "observed": 900,
            "reference": 800,
            "residual": 100,
            "source_channels": "mpu,power",
            "limitation": "confirm independently",
            "valid": True,
        }
        for index, assessment in enumerate((3, 3, 1), start=1)
    ]

    modes = summarize_persisted_relations(rows)
    evidence = build_persisted_correlation_evidence(rows)

    assert len(modes) == 1
    assert modes[0]["assessment"] == "critical"
    assert modes[0]["active_frames"] == 2
    assert modes[0]["max_consecutive_frames"] == 2
    assert modes[0]["persistent"] is True
    assert modes[0]["active_now"] is False
    assert evidence is not None
    assert evidence["version"] == 4
    assert evidence["strength"] == "strong"
    assert extract_firmware_modes([evidence])[0].mode_id == "locked_rotor_hypothesis"


def test_exposes_nested_closure_to_causal_engine():
    metrics = extract_causal_metrics([_correlation_evidence()])

    assert metrics["bus_voltage_mv"] == 6000
    assert metrics["motor_current_ma"] == 900
    assert metrics["rpm_mpu"] == 0
    assert metrics["bemf_error_permille"] == 220
    assert metrics["locked_rotor_hypothesis"] == 1


def test_distinguishes_valid_and_invalid_correlation_contracts():
    valid = _correlation_evidence(assessment="consistent")
    invalid = dict(valid)
    invalid.pop("diagnostic_modes")

    assert correlation_contract_state([valid]) == "valid"
    assert correlation_contract_state([invalid]) == "invalid"
    assert correlation_contract_state([]) == "absent"


def test_firmware_mode_is_not_replaced_by_unrelated_knowledge_unit():
    asyncio.run(_test_firmware_mode_is_not_replaced_by_unrelated_knowledge_unit())


async def _test_firmware_mode_is_not_replaced_by_unrelated_knowledge_unit():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [_correlation_evidence()],
            [
                {
                    "id": "00000000-0000-0000-0000-0000000000a1",
                    "title": "Limpeza do equipamento",
                    "statement": "Procedimento de higienizacao externa.",
                    "knowledge_level": "confirmed",
                    "confidence": 0.95,
                    "authority": "alta",
                }
            ],
            [],
        )

    assert len(hypotheses) == 1
    assert hypotheses[0]["diagnostic_kind"] == "locked_rotor_hypothesis"
    assert hypotheses[0]["source"] == "firmware_mode_correlation"
    assert hypotheses[0]["corroborating_knowledge_units"] == []
    assert "corroboracao OpenTracy: 0" in hypotheses[0]["description"]


def test_valid_correlation_without_active_mode_does_not_use_legacy_fallback():
    asyncio.run(_test_valid_correlation_without_active_mode_does_not_use_legacy_fallback())


async def _test_valid_correlation_without_active_mode_does_not_use_legacy_fallback():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [_correlation_evidence(assessment="consistent")],
            [],
            [],
        )

    assert hypotheses[0]["diagnostic_kind"] == "no_active_firmware_mode"
    assert "Nenhum modo de falha" in hypotheses[0]["description"]
    assert "operação normal" not in hypotheses[0]["description"]


def test_invalid_correlation_is_reported_as_inconclusive():
    asyncio.run(_test_invalid_correlation_is_reported_as_inconclusive())


async def _test_invalid_correlation_is_reported_as_inconclusive():
    evidence = _correlation_evidence()
    evidence.pop("diagnostic_modes")
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses([evidence], [], [])

    assert hypotheses[0]["diagnostic_kind"] == "invalid_correlation_evidence"
    assert hypotheses[0]["firmware_assessment"] == "indeterminate"


def test_relevant_knowledge_corroborates_mode_and_open_tracy_explains_it():
    asyncio.run(_test_relevant_knowledge_corroborates_mode_and_open_tracy_explains_it())


async def _test_relevant_knowledge_corroborates_mode_and_open_tracy_explains_it():
    ku_id = "00000000-0000-0000-0000-0000000000a2"
    chain_id = "00000000-0000-0000-0000-0000000000c2"
    evidence = _correlation_evidence()
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [evidence],
            [
                {
                    "id": ku_id,
                    "title": "Motor travado",
                    "statement": "Corrente de bloqueio caracteriza rotor travado.",
                    "knowledge_level": "confirmed",
                    "confidence": 0.9,
                    "authority": "alta",
                }
            ],
            [
                {
                    "id": chain_id,
                    "title": "Rotor travado por bloqueio mecanico",
                    "probable_cause": "motor travado",
                    "confidence": 0.8,
                }
            ],
        )
        explanation = await worker._build_explanation(hypotheses, [evidence])

    assert hypotheses[0]["corroborating_knowledge_units"] == [ku_id]
    assert hypotheses[0]["causal_chain_id"] == chain_id
    assert hypotheses[0]["confidence"] >= 0.61
    assert hypotheses[0]["is_primary"] is True
    assert explanation is not None
    assert "O OpenTracy encontrou 1 unidade" in explanation["narrative"]
    assert "requer confirmacao" in explanation["narrative"]


def test_run_diagnosis_consumes_cous_v3_evidence_end_to_end():
    asyncio.run(_test_run_diagnosis_consumes_cous_v3_evidence_end_to_end())


async def _test_run_diagnosis_consumes_cous_v3_evidence_end_to_end():
    evidence = _correlation_evidence()
    queued = [
        {
            "evidence_id": "00000000-0000-0000-0000-0000000000e1",
            "evidence_type": "physical",
            "evidence_strength": "strong",
            "confidence": 0.85,
            "source_reference": "capture:test:electromechanical_correlation_frame",
            "data": {
                key: value
                for key, value in evidence.items()
                if key not in {"strength", "confidence"}
            },
        }
    ]
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)

        async def no_database_evidence(_capture_session_id):
            return []

        async def relevant_knowledge(_instance_id):
            return [
                {
                    "id": "00000000-0000-0000-0000-0000000000a2",
                    "title": "Motor travado",
                    "statement": "Corrente de stall caracteriza rotor travado.",
                    "knowledge_level": "confirmed",
                    "confidence": 0.9,
                    "authority": "alta",
                }
            ]

        async def no_causal_chains(_instance_id, _deviations=None):
            return []

        worker._collect_evidences = no_database_evidence
        worker._find_similar_kus = relevant_knowledge
        worker._find_causal_chains = no_causal_chains
        result = await worker._run_diagnosis(
            UUID("00000000-0000-0000-0000-0000000000d1"),
            UUID("00000000-0000-0000-0000-0000000000c1"),
            UUID("00000000-0000-0000-0000-0000000000a1"),
            queued_evidence_set=queued,
            queued_context={"reported_problem": "motor nao gira"},
        )

    assert result["hypotheses"][0]["diagnostic_kind"] == "locked_rotor_hypothesis"
    assert result["hypotheses"][0]["source"] == "firmware_mode_correlation"
    assert result["explanation"]["knowledge_units_applied"] == [
        "00000000-0000-0000-0000-0000000000a2"
    ]
    assert "O OpenTracy encontrou 1 unidade" in result["explanation"]["narrative"]
    assert result["context"]["reported_problem"] == "motor nao gira"


def test_empty_unknown_invalid_and_final_empty_frames_break_temporal_modes():
    def row(t, **extra):
        return {"snapshot_id": str(t), "timestamp_us": t * 1_000_000,
                "relation_id": "locked_rotor_hypothesis", "assessment": 3,
                "confidence_permille": 900, "valid": True, "frame_valid": True, **extra}
    for barrier in [row(2, relation_id=None, valid=None),
                    row(2, relation_id="unknown_mode"), row(2, frame_valid=False),
                    row(2, valid=False), row(2, assessment=1)]:
        mode = summarize_persisted_relations([row(1), barrier, row(3)])[0]
        assert mode["max_consecutive_frames"] == 1
        assert mode["persistent"] is False
    mode = summarize_persisted_relations([row(1), row(2), row(3, relation_id=None)])[0]
    assert mode["persistent"] is True  # happened historically
    assert mode["active_now"] is False  # not present in the last frame
    mode = summarize_persisted_relations([row(1), row(1, snapshot_id="duplicate")])[0]
    assert mode["persistent"] is False
    mode = summarize_persisted_relations([row(1, source_session_id="a"), row(2, source_session_id="b")])[0]
    assert mode["persistent"] is False



def test_compact_systemos_timeline_uses_full_sequence_and_keeps_historical_scope():
    from runtime.diagnosis.electromechanical import decode_systemos_timeline
    data={"version":1,"sessao":"s1","data":"2026-10-16","tipoColeta":"DESEMPENHO","current_collection":True,
          "catalogo":[["locked_rotor_hypothesis",3,"mpu,power","valid RPM required"]],
          "frames":[["a",1000000,True,True,True,[[0,3,True,900,900,800,100,125]]],
                    ["b",2000000,True,True,True,[]],
                    ["c",3000000,True,True,True,[[0,3,True,900,900,800,100,125]]]]}
    evidence=decode_systemos_timeline(data)
    mode=evidence["diagnostic_modes"][0]
    assert evidence["count"]==3 and mode["active_frames"]==2
    assert mode["max_consecutive_frames"]==1 and mode["persistent"] is False
    assert mode["active_now"] is True
    data["current_collection"]=False
    mode=decode_systemos_timeline(data)["diagnostic_modes"][0]
    assert mode["active_now"] is False and mode["active_at_collection_end"] is True
    data["frames"][-1][3]=False
    assert decode_systemos_timeline(data)["diagnostic_modes"][0]["active_at_collection_end"] is False


def test_compact_systemos_contract_rejects_broken_dictionary_and_duplicate_frames():
    import pytest
    from runtime.diagnosis.electromechanical import decode_systemos_timeline
    data={"version":1,"sessao":"s","current_collection":True,"catalogo":[],
          "frames":[["a",1,True,True,True,[[9,3,True,900,900,800,100,1]]]]}
    with pytest.raises(ValueError): decode_systemos_timeline(data)
    data["frames"]=[['a',1,True,False,False,[]],['a',1,True,False,False,[]]]
    with pytest.raises(ValueError): decode_systemos_timeline(data)
