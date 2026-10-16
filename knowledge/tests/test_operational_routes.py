"""Tests for COUS v3 operational identity routes."""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException

from knowledge.api.cous_routes import create_cous_v3_router
from knowledge.api.cous_schemas import CaptureIdentityResolveRequestSchema
from knowledge.infrastructure.postgres.cous_repository import (
    ServiceOrderNotFoundError,
    ServiceOrderSerialMismatchError,
    _normalized_serial,
    _service_order_serial,
)


class FakeRepository:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def resolve_capture_identity(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "domain_id": UUID("00000000-0000-0000-0000-0000000000d1"),
            "entity_id": UUID("00000000-0000-0000-0000-0000000000e1"),
            "instance_id": UUID("00000000-0000-0000-0000-0000000000a1"),
            "operational_session_id": UUID("00000000-0000-0000-0000-0000000000b1"),
            "capture_session_id": UUID("00000000-0000-0000-0000-0000000000c1"),
            "service_order_document_id": UUID("00000000-0000-0000-0000-0000000000f1"),
        }


def _resolve_endpoint(repository):
    router = create_cous_v3_router(repository=repository)
    route = next(
        item
        for item in router.routes
        if item.path == "/v3/operational/resolve-capture"
    )
    return route.endpoint


def test_service_order_serial_prefers_metadata_and_supports_legacy_text():
    assert (
        _service_order_serial(
            {"extra": {"equipment_serial": "SN-METADATA"}},
            "N DE SERIE: SN-TEXT",
        )
        == "SN-METADATA"
    )
    assert (
        _service_order_serial(
            {},
            "CURSO: Ajustavel  N° DE SÉRIE: P3PRO-122304516  COR: Dourado",
        )
        == "P3PRO-122304516"
    )


def test_normalized_serial_strips_color_column_and_excess_whitespace():
    assert (
        _normalized_serial("W1NP2403464                               COR: DOURADA")
        == "w1np2403464"
    )
    assert _normalized_serial("  EP10757 040523 ") == "ep10757 040523"
    assert _normalized_serial("P3PRO-122300799  COR: Cinza") == "p3pro-122300799"
    assert _normalized_serial("DKNW1S90732") == "dknw1s90732"


def test_resolve_capture_identity_route():
    repo = FakeRepository()
    response = asyncio.run(
        _resolve_endpoint(repo)(
            CaptureIdentityResolveRequestSchema(
                domain_name="tattoo_machines",
                manufacturer="DKLAB",
                model="W1PRO",
                serial_number="1199",
                service_order_number="1063",
                measurement_observations="Bateria desarmando",
                operator_name="tech",
            )
        )
    )

    assert str(response.capture_session_id) == "00000000-0000-0000-0000-0000000000c1"
    assert repo.calls[0]["manufacturer"] == "DKLAB"
    assert repo.calls[0]["serial_number"] == "1199"
    assert repo.calls[0]["service_order_number"] == "1063"


def test_resolve_capture_identity_rejects_unknown_service_order():
    class MissingOrderRepository(FakeRepository):
        async def resolve_capture_identity(self, **kwargs):
            raise ServiceOrderNotFoundError("ordem de servico nao indexada: 9999")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _resolve_endpoint(MissingOrderRepository())(
                CaptureIdentityResolveRequestSchema(
                    serial_number="1199",
                    service_order_number="9999",
                )
            )
        )

    assert exc_info.value.status_code == 404


def test_resolve_capture_identity_rejects_serial_mismatch():
    class MismatchRepository(FakeRepository):
        async def resolve_capture_identity(self, **kwargs):
            raise ServiceOrderSerialMismatchError(
                "numero de serie da medicao diverge da OS 1063"
            )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            _resolve_endpoint(MismatchRepository())(
                CaptureIdentityResolveRequestSchema(
                    serial_number="OUTRA-SERIE",
                    service_order_number="1063",
                )
            )
        )

    assert exc_info.value.status_code == 409


SCOPE = {
    "source_system": "systemos",
    "organization_id": "10000000-0000-0000-0000-000000000001",
    "service_order_id": "20000000-0000-0000-0000-000000000001",
}


def test_scoped_identity_preserves_external_ids():
    repo = FakeRepository()
    asyncio.run(_resolve_endpoint(repo)(CaptureIdentityResolveRequestSchema(
        serial_number="1199", service_order_number="1063", service_order_scope=SCOPE,
    )))
    assert repo.calls[0]["service_order_scope"] == SCOPE


@pytest.mark.parametrize("scope", [
    {}, {"source_system": "systemos"},
    {**SCOPE, "organization_id": "not-a-uuid"},
    {**SCOPE, "source_system": "unknown"},
    {**SCOPE, "extra": "unsupported"},
])
def test_partial_or_invalid_scope_is_never_accepted(scope):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        CaptureIdentityResolveRequestSchema(
            serial_number="1199", service_order_number="1063", service_order_scope=scope,
        )
