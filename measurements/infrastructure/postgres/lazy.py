"""Lazy PostgreSQL adapter for measurement runtime composition."""

from __future__ import annotations

import asyncio
from uuid import UUID

from measurements.domain import (
    AddSnapshotsResult,
    CaptureProjectionResult,
    MeasurementSession,
    MeasurementSnapshot,
)
from measurements.infrastructure.postgres.repository import PostgresMeasurementRepository


class LazyPostgresMeasurementRepository:
    """Open the PostgreSQL pool and validate its schema without changing it."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._repo: PostgresMeasurementRepository | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        if self._repo is not None:
            await self._repo.close()
            self._repo = None

    async def _ensure_repo(self) -> PostgresMeasurementRepository:
        if self._repo is not None:
            return self._repo
        async with self._lock:
            if self._repo is not None:
                return self._repo
            repo = await PostgresMeasurementRepository.connect(self._dsn)
            try:
                await _validate_schema(repo)
            except BaseException:
                await repo.close()
                raise
            self._repo = repo
            return repo

    async def create_session(self, session: MeasurementSession) -> MeasurementSession:
        return await (await self._ensure_repo()).create_session(session)

    async def get_session(self, session_id: UUID) -> MeasurementSession | None:
        return await (await self._ensure_repo()).get_session(session_id)

    async def list_sessions(self) -> list[MeasurementSession]:
        return await (await self._ensure_repo()).list_sessions()

    async def delete_session(self, session_id: UUID) -> bool:
        return await (await self._ensure_repo()).delete_session(session_id)

    async def add_snapshots(
        self,
        session_id: UUID,
        snapshots: list[MeasurementSnapshot],
    ) -> AddSnapshotsResult | None:
        return await (await self._ensure_repo()).add_snapshots(session_id, snapshots)

    async def list_snapshots(self, session_id: UUID) -> list[MeasurementSnapshot]:
        return await (await self._ensure_repo()).list_snapshots(session_id)

    async def set_source_session_id(
        self,
        session_id: UUID,
        source_session_id: str,
    ) -> MeasurementSession | None:
        return await (await self._ensure_repo()).set_source_session_id(
            session_id,
            source_session_id,
        )

    async def link_capture_session(
        self,
        session_id: UUID,
        capture_session_id: UUID,
    ) -> CaptureProjectionResult | None:
        return await (await self._ensure_repo()).link_capture_session(
            session_id,
            capture_session_id,
        )

    async def save_diagnostic(
        self,
        session_id: UUID,
        diagnostic: dict,
    ) -> MeasurementSession | None:
        return await (await self._ensure_repo()).save_diagnostic(session_id, diagnostic)

    async def save_report(
        self,
        session_id: UUID,
        report_markdown: str,
    ) -> MeasurementSession | None:
        return await (await self._ensure_repo()).save_report(session_id, report_markdown)


async def _validate_schema(repo: PostgresMeasurementRepository) -> None:
    """Fail before serving requests if the deployed schema is incomplete.

    Schema changes belong to scripts/migrate-postgres.py, run by the owner.
    LIMIT 0 checks relations/columns without reading customer records.
    """
    probes = (
        'SELECT capture_session_id, source_session_id FROM public.measurement_sessions LIMIT 0',
        'SELECT * FROM public.measurement_snapshots LIMIT 0',
        'SELECT * FROM public.measurement_snapshot_projections LIMIT 0',
        'SELECT * FROM public.electromechanical_correlation_relations LIMIT 0',
    )
    async with repo._pool.acquire() as conn:  # noqa: SLF001
        async with conn.transaction(readonly=True):
            for query in probes:
                await conn.execute(query)
