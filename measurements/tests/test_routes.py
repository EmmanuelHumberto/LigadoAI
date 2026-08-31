import asyncio

import httpx
from fastapi import FastAPI

from measurements.api import create_measurements_router
from measurements.infrastructure import (
    BasicMeasurementAnalyzer,
    BasicSnapshotValidator,
    InMemoryMeasurementRepository,
    MarkdownMeasurementReportRenderer,
)
from measurements.runtime import MeasurementsRuntimeConfig, create_default_measurements_router


def _app(*, auth_token: str | None = None) -> FastAPI:
    app = FastAPI()
    if auth_token:
        app.include_router(
            create_measurements_router(
                repository=InMemoryMeasurementRepository(),
                validator=BasicSnapshotValidator(),
                analyzer=BasicMeasurementAnalyzer(),
                report_renderer=MarkdownMeasurementReportRenderer(),
                auth_token=auth_token,
            )
        )
    else:
        app.include_router(
            create_default_measurements_router(
                MeasurementsRuntimeConfig(
                    enabled=True,
                    backend="memory",
                    database_url=None,
                    auth_token=None,
                )
            )
        )
    return app


def _transport_client(app: FastAPI) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def test_measurement_session_lifecycle():
    asyncio.run(_test_measurement_session_lifecycle())


async def _test_measurement_session_lifecycle():
    app = _app()

    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/measurements/sessions",
                json={
                    "header": {
                        "fabricante": "FK Irons",
                        "modelo": "Flux",
                        "numero_serie": "SN123",
                        "tipo_maquina": "pen",
                        "tipo_motor": "brushless",
                        "sistema_transmissao": "direct",
                        "curso_nominal_mm": 3.5,
                        "tipo_coleta": "desempenho",
                        "porta_serial": "/dev/ttyACM0",
                        "tecnico": "Emmanuel",
                        "verticais": ["hall", "power", "course", "vibration"],
                    }
                },
            )
        ).json()
        session_id = created["id"]

        identified = (
            await client.put(
                f"/measurements/sessions/{session_id}/source-identity",
                json={"source_session_id": "med_20260707_004430_98fbcc"},
            )
        ).json()

        added = (
            await client.post(
                f"/measurements/sessions/{session_id}/snapshots",
                json={
                    "snapshots": [
                        {"type": "hall", "timestamp_us": 100, "frequency_hz": 120.0},
                        {"type": "power_snapshot", "timestamp_us": 120, "current_ma": 80.0},
                        {"type": "course_snapshot", "timestamp_us": 130, "course_mm": 3.5},
                        {
                            "type": "vibration_snapshot",
                            "timestamp_us": 140,
                            "rms_g": 0.12,
                        },
                        {"type": "bad"},
                    ]
                },
            )
        ).json()
        snapshots = (
            await client.get(f"/measurements/sessions/{session_id}/snapshots")
        ).json()
        diagnosed = (
            await client.post(f"/measurements/sessions/{session_id}/diagnose")
        ).json()
        report = (
            await client.post(f"/measurements/sessions/{session_id}/report")
        ).json()

    assert created["status"] == "created"
    assert identified["header"]["source_session_id"] == "med_20260707_004430_98fbcc"
    assert added["accepted"] == 4
    assert added["rejected"] == 1
    assert len(snapshots["snapshots"]) == 5
    assert snapshots["snapshots"][1]["type"] == "power"
    assert snapshots["snapshots"][2]["type"] == "course"
    assert snapshots["snapshots"][3]["type"] == "vibration"
    assert diagnosed["diagnostic"]["total_snapshots"] == 5
    assert diagnosed["diagnostic"]["header"]["sistema_transmissao"] == "direct"
    assert "Flux" in report["markdown"]
    assert "Sistema de transmissao: direct" in report["markdown"]
    assert "Curso nominal: 3.5 mm" in report["markdown"]
    assert "TMA_DATA selecionados: hall, power, course, vibration" in report["markdown"]


def test_measurement_session_rejects_invalid_header():
    asyncio.run(_test_measurement_session_rejects_invalid_header())


async def _test_measurement_session_rejects_invalid_header():
    app = _app()

    async with _transport_client(app) as client:
        response = await client.post(
            "/measurements/sessions",
            json={
                "header": {
                    "tipo_coleta": "reparo",
                    "peca_substituida": "",
                    "baudrate": 0,
                    "duracao_seg": 0,
                    "verticais": [],
                }
            },
        )

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"]["code"] == "invalid_header"
    codes = {item["code"] for item in payload["detail"]["errors"]}
    assert "missing_peca_substituida" in codes
    assert "invalid_baudrate" in codes
    assert "invalid_duracao_seg" in codes
    assert "missing_verticais" in codes


def test_missing_measurement_session_returns_404():
    asyncio.run(_test_missing_measurement_session_returns_404())


async def _test_missing_measurement_session_returns_404():
    app = _app()

    async with _transport_client(app) as client:
        response = await client.get(
            "/measurements/sessions/00000000-0000-0000-0000-000000000000"
        )

    assert response.status_code == 404


def test_measurement_routes_require_token_when_configured():
    asyncio.run(_test_measurement_routes_require_token_when_configured())


async def _test_measurement_routes_require_token_when_configured():
    app = _app(auth_token="secret")

    async with _transport_client(app) as client:
        unauthorized = await client.get("/measurements/sessions")
        authorized = await client.get(
            "/measurements/sessions",
            headers={"Authorization": "Bearer secret"},
        )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_electromechanical_contracts_are_validated_and_idempotent():
    asyncio.run(_test_electromechanical_contracts_are_validated_and_idempotent())


async def _test_electromechanical_contracts_are_validated_and_idempotent():
    app = _app()
    observation = {
        "type": "electromechanical_observation_frame",
        "version": 3,
        "timestamp_us": 1000,
        "valid": True,
        "channels": {},
        "hall": {},
        "power": {},
        "vibration": {},
    }
    correlation = {
        "type": "electromechanical_correlation_frame",
        "version": 4,
        "timestamp_us": 1100,
        "valid": True,
        "profile": {},
        "axes": [],
        "physical_signature": {},
        "closure": {},
        "relation_count": 0,
        "relations": [],
    }
    invalid_version = {**observation, "version": 2, "timestamp_us": 1200}

    async with _transport_client(app) as client:
        created = (
            await client.post(
                "/measurements/sessions",
                json={"header": {"verticais": ["signature"]}},
            )
        ).json()
        endpoint = f"/measurements/sessions/{created['id']}/snapshots"
        first = (
            await client.post(
                endpoint,
                json={"snapshots": [observation, correlation, invalid_version]},
            )
        ).json()
        repeated = (
            await client.post(
                endpoint,
                json={"snapshots": [observation, correlation, invalid_version]},
            )
        ).json()
        linked = (
            await client.post(
                f"/measurements/sessions/{created['id']}/capture-link",
                json={
                    "capture_session_id": "00000000-0000-0000-0000-000000000456"
                },
            )
        ).json()
        relinked = (
            await client.post(
                f"/measurements/sessions/{created['id']}/capture-link",
                json={
                    "capture_session_id": "00000000-0000-0000-0000-000000000456"
                },
            )
        ).json()

    assert first["accepted"] == 2
    assert first["rejected"] == 1
    assert first["duplicates"] == 0
    assert first["session"]["total_snapshots"] == 3
    assert repeated["accepted"] == 0
    assert repeated["rejected"] == 0
    assert repeated["duplicates"] == 3
    assert repeated["session"]["total_snapshots"] == 3
    assert linked["projected"] == 1
    assert linked["already_projected"] == 0
    assert relinked["projected"] == 0
    assert relinked["already_projected"] == 1
