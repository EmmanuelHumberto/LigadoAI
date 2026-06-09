"""Runtime composition for the measurements vertical."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import APIRouter
from pydantic import BaseModel

from measurements.api import create_measurements_router
from measurements.infrastructure import (
    BasicMeasurementAnalyzer,
    BasicSnapshotValidator,
    InMemoryMeasurementRepository,
    MarkdownMeasurementReportRenderer,
)


@dataclass(frozen=True)
class MeasurementsRuntimeConfig:
    enabled: bool = True
    backend: str = "memory"
    database_url: str | None = None
    auth_token: str | None = None

    @classmethod
    def from_env(cls) -> MeasurementsRuntimeConfig:
        enabled_raw = os.environ.get("OPENTRACY_MEASUREMENTS_ENABLED", "1").strip().lower()
        backend = os.environ.get("OPENTRACY_MEASUREMENTS_BACKEND")
        backend = backend or os.environ.get("OPENTRACY_KNOWLEDGE_BACKEND", "memory")
        backend = backend.strip().lower()
        database_url = os.environ.get("OPENTRACY_MEASUREMENTS_DATABASE_URL")
        database_url = database_url or os.environ.get("OPENTRACY_KNOWLEDGE_DATABASE_URL")
        auth_token = os.environ.get("OPENTRACY_MEASUREMENTS_AUTH_TOKEN")
        auth_token = auth_token or os.environ.get("OPENTRACY_KNOWLEDGE_AUTH_TOKEN")
        return cls(
            enabled=enabled_raw not in {"0", "false", "no", "off"},
            backend=backend or "memory",
            database_url=database_url.strip() if database_url else None,
            auth_token=auth_token.strip() if auth_token else None,
        )


class MeasurementsStatusResponse(BaseModel):
    enabled: bool
    backend: str
    database_configured: bool
    auth_configured: bool


def create_default_measurements_router(
    config: MeasurementsRuntimeConfig | None = None,
) -> APIRouter:
    config = config or MeasurementsRuntimeConfig.from_env()
    router = APIRouter()

    @router.get("/measurements/status", response_model=MeasurementsStatusResponse)
    async def measurements_status() -> MeasurementsStatusResponse:
        return MeasurementsStatusResponse(
            enabled=config.enabled,
            backend=config.backend,
            database_configured=bool(config.database_url),
            auth_configured=bool(config.auth_token),
        )

    if not config.enabled:
        return router
    if config.backend == "memory":
        repository = InMemoryMeasurementRepository()
    elif config.backend == "postgres":
        if not config.database_url:
            raise RuntimeError(
                "OPENTRACY_MEASUREMENTS_DATABASE_URL or "
                "OPENTRACY_KNOWLEDGE_DATABASE_URL is required when "
                "OPENTRACY_MEASUREMENTS_BACKEND=postgres"
            )
        from measurements.infrastructure.postgres import LazyPostgresMeasurementRepository

        repository = LazyPostgresMeasurementRepository(config.database_url)
    else:
        raise RuntimeError(
            "unsupported measurements backend "
            f"{config.backend!r}; expected 'memory' or 'postgres'"
        )
    router.include_router(
        create_measurements_router(
            repository=repository,
            validator=BasicSnapshotValidator(),
            analyzer=BasicMeasurementAnalyzer(),
            report_renderer=MarkdownMeasurementReportRenderer(),
            auth_token=config.auth_token,
        )
    )
    return router
