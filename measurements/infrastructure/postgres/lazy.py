"""Lazy PostgreSQL adapter for measurement runtime composition."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

from measurements.domain import MeasurementSession, MeasurementSnapshot
from measurements.infrastructure.postgres.repository import PostgresMeasurementRepository


class LazyPostgresMeasurementRepository:
    """Open the PostgreSQL pool and apply migrations on first use."""

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
            await _apply_migrations(repo)
            self._repo = repo
            return repo

    async def create_session(self, session: MeasurementSession) -> MeasurementSession:
        return await (await self._ensure_repo()).create_session(session)

    async def get_session(self, session_id: UUID) -> MeasurementSession | None:
        return await (await self._ensure_repo()).get_session(session_id)

    async def list_sessions(self) -> list[MeasurementSession]:
        return await (await self._ensure_repo()).list_sessions()

    async def add_snapshots(
        self,
        session_id: UUID,
        snapshots: list[MeasurementSnapshot],
    ) -> MeasurementSession | None:
        return await (await self._ensure_repo()).add_snapshots(session_id, snapshots)

    async def list_snapshots(self, session_id: UUID) -> list[MeasurementSnapshot]:
        return await (await self._ensure_repo()).list_snapshots(session_id)

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


async def _apply_migrations(repo: PostgresMeasurementRepository) -> None:
    migration_dir = Path(__file__).resolve().parent / "migrations"
    migration_files = sorted(migration_dir.glob("*.sql"))
    async with repo._pool.acquire() as conn:  # noqa: SLF001 - infrastructure-local migration
        for migration in migration_files:
            await conn.execute(migration.read_text(encoding="utf-8"))
