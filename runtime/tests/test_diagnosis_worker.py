"""Tests for COUS diagnosis worker callback payloads."""

from __future__ import annotations

import asyncio
import json
from uuid import UUID

import httpx

from runtime.diagnosis.worker import DiagnosisWorker


def test_worker_explanation_is_json_serializable():
    asyncio.run(_test_worker_explanation_is_json_serializable())


async def _test_worker_explanation_is_json_serializable():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        explanation = await worker._build_explanation(
            [
                {
                    "description": "Atrito elevado no conjunto rotativo",
                    "confidence": 0.82,
                    "is_primary": True,
                    "source_ku_id": "00000000-0000-0000-0000-0000000000a1",
                }
            ],
            [{"type": "electromechanical_signature"}],
        )

    assert explanation is not None
    assert explanation["knowledge_units_applied"] == [
        "00000000-0000-0000-0000-0000000000a1"
    ]
    json.dumps(explanation)


def test_worker_marks_service_order_observation_as_context_only():
    asyncio.run(_test_worker_marks_service_order_observation_as_context_only())


async def _test_worker_marks_service_order_observation_as_context_only():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        explanation = await worker._build_explanation(
            [
                {
                    "description": "Sobrecarga do motor",
                    "confidence": 0.72,
                    "is_primary": True,
                }
            ],
            [
                {"type": "electromechanical_signature"},
                {
                    "type": "service_order_context",
                    "service_order_number": "1063",
                    "observations": "Bateria desarmando ao acionar o motor",
                },
            ],
        )

    assert explanation is not None
    assert "OS 1063" in explanation["narrative"]
    assert "Bateria desarmando" in explanation["narrative"]
    assert "nao como evidencia fisica independente" in explanation["narrative"]


def test_service_order_context_does_not_inflate_physical_evidence_score():
    asyncio.run(_test_service_order_context_does_not_inflate_physical_evidence_score())


async def _test_service_order_context_does_not_inflate_physical_evidence_score():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        physical = [{"type": "power_snapshot", "strength": "strong"}]
        knowledge = [
            {
                "id": "00000000-0000-0000-0000-0000000000a1",
                "statement": "Corrente elevada pode indicar sobrecarga.",
                "knowledge_level": "confirmed",
                "confidence": 0.8,
            }
        ]
        without_context = await worker._generate_hypotheses(
            physical,
            knowledge,
            [],
        )
        with_context = await worker._generate_hypotheses(
            physical
            + [
                {
                    "type": "service_order_context",
                    "strength": "weak",
                    "observations": "Cliente relata aquecimento",
                }
            ],
            knowledge,
            [],
        )

    assert with_context[0]["confidence"] == without_context[0]["confidence"]
    assert (
        with_context[0]["confidence_breakdown"]["evidence_score"]
        == without_context[0]["confidence_breakdown"]["evidence_score"]
    )


def test_worker_filters_generic_ku_and_uses_telemetry_fallback():
    asyncio.run(_test_worker_filters_generic_ku_and_uses_telemetry_fallback())


async def _test_worker_filters_generic_ku_and_uses_telemetry_fallback():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [
                {
                    "type": "electromechanical_signature",
                    "strength": "moderate",
                    "mechanical_equivalent_load_permille_avg": 341,
                    "efficiency_permille_avg": 680,
                },
                {
                    "type": "vibration_snapshot",
                    "strength": "weak",
                    "rms_norm_mg_avg": 795,
                },
            ],
            [
                {
                    "id": "00000000-0000-0000-0000-0000000000f1",
                    "statement": "Teste bem-sucedido! 🚀",
                    "knowledge_level": "confirmed",
                    "confidence": 1.0,
                }
            ],
            [],
        )

    assert hypotheses
    assert hypotheses[0]["is_primary"] is True
    assert "Teste" not in hypotheses[0]["description"]
    assert hypotheses[0]["diagnostic_kind"] == "high_vibration"
    assert "Vibração elevada" in hypotheses[0]["description"]


def test_firmware_mode_kus_do_not_create_modes_without_firmware_evidence():
    asyncio.run(
        _test_firmware_mode_kus_do_not_create_modes_without_firmware_evidence()
    )


async def _test_firmware_mode_kus_do_not_create_modes_without_firmware_evidence():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [
                {
                    "type": "electromechanical_signature",
                    "strength": "weak",
                    "rpm_hall_avg": 5545,
                    "rpm_mpu_avg": 5559,
                    "motor_current_ma_avg": 65,
                    "torque_uNm_avg": 458,
                    "required_torque_uNm_avg": 2462,
                    "electrical_power_mw_avg": 523,
                    "mechanical_power_mw_avg": 297,
                    "required_mechanical_power_mw_avg": 1594,
                    "efficiency_permille_avg": 508,
                }
            ],
            [
                {
                    "id": "00000000-0000-0000-0000-00000000a101",
                    "title": "Hipotese de rotor travado",
                    "statement": (
                        "Rotor travado quando o firmware publica "
                        "locked_rotor_hypothesis."
                    ),
                    "knowledge_level": "confirmed",
                    "confidence": 0.75,
                },
                {
                    "id": "00000000-0000-0000-0000-00000000a103",
                    "title": "Hipotese de sobrecarga",
                    "statement": (
                        "Sobrecarga quando o firmware publica "
                        "motor_nominal_overload_hypothesis."
                    ),
                    "knowledge_level": "confirmed",
                    "confidence": 0.75,
                },
            ],
            [],
        )

    assert len(hypotheses) == 1
    assert hypotheses[0]["diagnostic_kind"] == "low_efficiency"
    assert "Rotor travado" not in hypotheses[0]["description"]
    assert "torque requerido" not in hypotheses[0]["description"].lower()
    assert sum(bool(item["is_primary"]) for item in hypotheses) == 1


def test_worker_ignores_unavailable_mechanical_demand():
    asyncio.run(_test_worker_ignores_unavailable_mechanical_demand())


async def _test_worker_ignores_unavailable_mechanical_demand():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [
                {
                    "type": "electromechanical_signature",
                    "strength": "moderate",
                    "mechanical_equivalent_load_permille_avg": 1250,
                    "torque_load_permille_avg": 1250,
                    "efficiency_permille_avg": 760,
                    "motor_current_ma_avg": 65,
                },
            ],
            [],
            [],
        )

    assert hypotheses
    assert hypotheses[0]["is_primary"] is True
    assert hypotheses[0]["diagnostic_kind"] == "normal_signature"
    assert "torque requerido" not in hypotheses[0]["description"].lower()


def test_worker_requires_informed_reference_for_electrical_limit():
    asyncio.run(_test_worker_requires_informed_reference_for_electrical_limit())


async def _test_worker_requires_informed_reference_for_electrical_limit():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        without_reference = await worker._generate_hypotheses(
            [
                {
                    "type": "power_snapshot",
                    "strength": "moderate",
                    "bus_voltage_mv_avg": 13000,
                    "current_ma_avg": 500,
                    "power_mw_avg": 6500,
                }
            ],
            [],
            [],
        )
        with_reference = await worker._generate_hypotheses(
            [
                {
                    "type": "power_snapshot",
                    "strength": "moderate",
                    "bus_voltage_mv_avg": 13000,
                    "current_ma_avg": 500,
                    "power_mw_avg": 6500,
                    "nominal_voltage_mv_avg": 12000,
                    "nominal_current_ma_avg": 420,
                }
            ],
            [],
            [],
        )

    assert without_reference[0]["diagnostic_kind"] == "normal_signature"
    assert with_reference[0]["diagnostic_kind"] == "voltage_above_informed_reference"


def test_worker_reads_nested_v3_profile_and_observations():
    asyncio.run(_test_worker_reads_nested_v3_profile_and_observations())


async def _test_worker_reads_nested_v3_profile_and_observations():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = worker._generate_telemetry_hypotheses(
            [
                {
                    "type": "electromechanical_correlation_frame",
                    "strength": "moderate",
                    "profile": {
                        "valid": True,
                        "nominal_voltage_mv": 12000,
                        "nominal_current_ma": 420,
                    },
                    "closure": {
                        "valid": True,
                        "electrical": {
                            "valid": True,
                            "bus_voltage_mv": 13000,
                            "motor_current_ma": 100,
                            "electrical_power_mw": 1300,
                        },
                        "motor": {"valid": True, "rpm_mpu": 6000},
                        "cartridge": {
                            "valid": False,
                            "required_torque_uNm": 9999,
                        },
                    },
                },
                {
                    "type": "electromechanical_observation_frame",
                    "strength": "moderate",
                    "latest_observation": {
                        "valid": True,
                        "hall": {"valid": True, "rpm_inferred": 6000},
                        "vibration": {"valid": True, "rms_norm_mg": 300},
                    },
                },
            ],
        )

    assert hypotheses[0]["diagnostic_kind"] == "voltage_above_informed_reference"
    assert "13000 mV" in hypotheses[0]["description"]


def test_worker_explanation_uses_physical_chain_not_sensor_list():
    asyncio.run(_test_worker_explanation_uses_physical_chain_not_sensor_list())


async def _test_worker_explanation_uses_physical_chain_not_sensor_list():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        hypotheses = await worker._generate_hypotheses(
            [
                {
                    "type": "electromechanical_signature",
                    "strength": "moderate",
                    "torque_uNm_avg": 707,
                    "required_torque_uNm_avg": 2473,
                    "mechanical_equivalent_load_permille_avg": 3498,
                    "torque_load_permille_avg": 3498,
                    "efficiency_permille_avg": 756,
                    "motor_current_ma_avg": 70,
                    "electrical_power_mw_avg": 560,
                    "mechanical_power_mw_avg": 423,
                    "required_mechanical_power_mw_avg": 1481,
                    "equivalent_resistance_error_permille_avg": 290,
                },
                {"type": "hall_snapshot", "strength": "weak"},
                {"type": "power_snapshot", "strength": "weak"},
            ],
            [],
            [],
        )
        explanation = await worker._build_explanation(
            hypotheses,
            [
                {
                    "type": "electromechanical_signature",
                    "strength": "moderate",
                    "torque_uNm_avg": 707,
                    "required_torque_uNm_avg": 2473,
                    "mechanical_equivalent_load_permille_avg": 3498,
                    "efficiency_permille_avg": 756,
                    "motor_current_ma_avg": 70,
                    "electrical_power_mw_avg": 560,
                    "mechanical_power_mw_avg": 423,
                    "required_mechanical_power_mw_avg": 1481,
                    "equivalent_resistance_error_permille_avg": 290,
                },
                {"type": "hall_snapshot", "strength": "weak"},
                {"type": "power_snapshot", "strength": "weak"},
            ],
        )

    assert explanation is not None
    narrative = explanation["narrative"]
    assert "torque inferido da corrente" in narrative
    assert "707 uNm" in narrative
    assert "2473 uNm" not in narrative
    assert "torque requerido" in narrative
    assert "não participam desta hipótese" in narrative
    assert hypotheses[0]["diagnostic_kind"] == "electrical_model_deviation"
    assert "3498‰" not in narrative
    assert "hall_snapshot" not in narrative


def test_worker_computes_motor_efficiency_without_mechanical_demand():
    asyncio.run(_test_worker_computes_motor_efficiency_without_mechanical_demand())


async def _test_worker_computes_motor_efficiency_without_mechanical_demand():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        evidences = [
            {
                "type": "electromechanical_signature",
                "strength": "moderate",
                "torque_uNm_avg": 732,
                "required_torque_uNm_avg": 1649,
                "mechanical_equivalent_load_permille_avg": 345,
                "efficiency_permille_avg": 471,
                "electrical_power_mw_avg": 682,
                "mechanical_power_mw_avg": 415,
            }
        ]
        hypotheses = await worker._generate_hypotheses(evidences, [], [])
        explanation = await worker._build_explanation(hypotheses, evidences)

    assert hypotheses
    assert "60.9%" in hypotheses[0]["description"]
    assert "2.3x" not in hypotheses[0]["description"]
    assert explanation is not None
    assert "60.9%" in explanation["narrative"]
    assert "1649" not in explanation["narrative"]


def test_worker_prioritizes_electrical_residual_over_legacy_mechanical_fields():
    asyncio.run(
        _test_worker_prioritizes_electrical_residual_over_legacy_mechanical_fields()
    )


async def _test_worker_prioritizes_electrical_residual_over_legacy_mechanical_fields():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        evidences = [
            {
                "type": "electromechanical_signature",
                "strength": "moderate",
                "torque_uNm_avg": 707,
                "required_torque_uNm_avg": 3881,
                "electrical_power_mw_avg": 696,
                "mechanical_power_mw_avg": 555,
                "required_mechanical_power_mw_avg": 3048,
                "winding_resistance_error_permille_avg": 903,
                "vibration_rms_mg_avg": 2222,
                "vibration_peak_mg_avg": 2353,
            }
        ]
        hypotheses = await worker._generate_hypotheses(evidences, [], [])
        explanation = await worker._build_explanation(hypotheses, evidences)

    assert hypotheses
    assert hypotheses[0]["diagnostic_kind"] == "electrical_model_deviation"
    assert "erro de resistência da bobina 903‰" in hypotheses[0]["description"]
    assert explanation is not None
    assert "3881" not in explanation["narrative"]
    assert "3048" not in explanation["narrative"]
    assert "modelo mecânico está indisponível" in explanation["narrative"]


def test_worker_does_not_diagnose_from_legacy_mechanical_model():
    asyncio.run(_test_worker_does_not_diagnose_from_legacy_mechanical_model())


async def _test_worker_does_not_diagnose_from_legacy_mechanical_model():
    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=None, http_client=client)
        evidences = [
            {
                "type": "electromechanical_signature",
                "strength": "moderate",
                "mechanical_model_level_avg": 1,
                "torque_uNm_avg": 707,
                "required_torque_uNm_avg": 3881,
                "electrical_power_mw_avg": 696,
                "mechanical_power_mw_avg": 555,
                "required_mechanical_power_mw_avg": 3048,
                "motor_current_ma_avg": 65,
            }
        ]
        hypotheses = await worker._generate_hypotheses(evidences, [], [])
        explanation = await worker._build_explanation(hypotheses, evidences)

    assert hypotheses
    assert hypotheses[0]["diagnostic_kind"] == "normal_signature"
    assert "fechamento" not in hypotheses[0]["description"].lower()
    assert explanation is not None
    assert "3881" not in explanation["narrative"]
    assert "3048" not in explanation["narrative"]
    assert "carga de cartucho não participam" in explanation["narrative"]


def test_worker_persists_failure_for_callback_outbox_after_retries():
    asyncio.run(_test_worker_persists_failure_for_callback_outbox_after_retries())


async def _test_worker_persists_failure_for_callback_outbox_after_retries():
    item_id = UUID("00000000-0000-0000-0000-0000000000d1")
    capture_session_id = UUID("00000000-0000-0000-0000-0000000000c1")
    instance_id = UUID("00000000-0000-0000-0000-0000000000a1")
    failed: list[tuple[UUID, str, dict]] = []

    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(
            repository=None,
            http_client=client,
            max_retries=1,
        )

        async def fail_run(*args, **kwargs):
            raise RuntimeError("boom")

        async def mark_failed(callback_item_id, error, result):
            failed.append((callback_item_id, error, result))

        worker._run_diagnosis = fail_run
        worker._mark_failed = mark_failed

        await worker._process_one(
            {
                "id": item_id,
                "capture_session_id": capture_session_id,
                "instance_id": instance_id,
                "evidence_set": [],
                "context": {},
            }
        )

    assert len(failed) == 1
    callback_item_id, error, payload = failed[0]
    assert callback_item_id == item_id
    assert error == "RuntimeError: boom"
    assert payload["correlation_id"] == str(item_id)
    assert payload["capture_session_id"] == str(capture_session_id)
    assert payload["hypotheses"] == []
    assert payload["error"] == "RuntimeError: boom"


def test_worker_callback_http_error_raises():
    asyncio.run(_test_worker_callback_http_error_raises())


async def _test_worker_callback_http_error_raises():
    item_id = UUID("00000000-0000-0000-0000-0000000000d1")

    class FakeAcquire:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def fetchrow(self, query, *args):
            assert args == (item_id,)
            return {"callback_endpoint": "http://callback/cous/diagnosis/callback"}

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    class FakeRepository:
        _pool = FakePool()

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://callback/cous/diagnosis/callback"
        return httpx.Response(409, json={"detail": "not persisted"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        worker = DiagnosisWorker(repository=FakeRepository(), http_client=client)
        try:
            await worker._send_callback(
                item_id,
                {
                    "correlation_id": str(item_id),
                    "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
                    "trace_id": "00000000-0000-0000-0000-0000000000e1",
                    "duration_ms": 0,
                    "hypotheses": [],
                    "explanation": None,
                },
            )
        except httpx.HTTPStatusError as exc:
            assert exc.response.status_code == 409
        else:
            raise AssertionError("callback HTTP error should fail the worker")


def test_callback_outbox_failure_does_not_reclassify_diagnosis():
    asyncio.run(_test_callback_outbox_failure_does_not_reclassify_diagnosis())


async def _test_callback_outbox_failure_does_not_reclassify_diagnosis():
    item_id = UUID("00000000-0000-0000-0000-0000000000d1")
    callback_failures: list[tuple[UUID, str]] = []

    class FakeAcquire:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def fetch(self, query, *args):
            return [
                {
                    "id": item_id,
                    "result_payload": {
                        "correlation_id": str(item_id),
                        "capture_session_id": "00000000-0000-0000-0000-0000000000c1",
                    },
                }
            ]

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    class FakeRepository:
        _pool = FakePool()

    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=FakeRepository(), http_client=client)

        async def fail_callback(*args, **kwargs):
            raise httpx.ConnectError("callback unavailable")

        async def mark_callback_failed(callback_item_id, error):
            callback_failures.append((callback_item_id, error))

        worker._send_callback = fail_callback
        worker._mark_callback_failed = mark_callback_failed
        await worker._process_callback_outbox()

    assert callback_failures
    assert callback_failures[0][0] == item_id
    assert "callback unavailable" in callback_failures[0][1]


def test_worker_mark_completed_persists_result_payload():
    asyncio.run(_test_worker_mark_completed_persists_result_payload())


async def _test_worker_mark_completed_persists_result_payload():
    item_id = UUID("00000000-0000-0000-0000-0000000000d1")
    executed: list[tuple[str, tuple]] = []

    class FakeAcquire:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, *args):
            executed.append((query, args))
            return "UPDATE 1"

    class FakePool:
        def acquire(self):
            return FakeAcquire()

    class FakeRepository:
        _pool = FakePool()

    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=FakeRepository(), http_client=client)
        await worker._mark_completed(
            item_id,
            {
                "correlation_id": str(item_id),
                "hypotheses": [{"description": "Atrito elevado"}],
            },
        )

    assert len(executed) == 1
    query, args = executed[0]
    assert "result_payload" in query
    assert "delivery_mode" in query and "not_required" in query and "ELSE 'pending'" in query
    assert args[0] == item_id
    assert "Atrito elevado" in args[1]


def test_worker_recovers_firmware_modes_from_persisted_relations():
    asyncio.run(_test_worker_recovers_firmware_modes_from_persisted_relations())


async def _test_worker_recovers_firmware_modes_from_persisted_relations():
    class FakeAcquire:
        def __init__(self):
            self.calls = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def fetch(self, query, *args):
            self.calls += 1
            if "electromechanical_correlation_relations" not in query:
                return []
            return [
                {
                    "snapshot_id": "frame-1",
                    "timestamp_us": 1_000_000,
                    "relation_index": 0,
                    "relation_id": "source_overvoltage_hypothesis",
                    "layer": 3,
                    "assessment": 2,
                    "observed": 12_500,
                    "reference": 12_000,
                    "residual": 500,
                    "error_permille": 42,
                    "confidence_permille": 900,
                    "source_channels": "power,motor_nominal_voltage",
                    "limitation": "sustained INA219 measurement",
                    "valid": True,
                }
            ]

    connection = FakeAcquire()

    class FakePool:
        def acquire(self):
            return connection

    class FakeRepository:
        _pool = FakePool()

    async with httpx.AsyncClient() as client:
        worker = DiagnosisWorker(repository=FakeRepository(), http_client=client)
        evidences = await worker._collect_evidences(
            UUID("00000000-0000-0000-0000-0000000000c1")
        )

    assert connection.calls == 3
    assert len(evidences) == 1
    assert evidences[0]["type"] == "electromechanical_correlation_frame"
    assert evidences[0]["diagnostic_modes"][0]["id"] == (
        "source_overvoltage_hypothesis"
    )
