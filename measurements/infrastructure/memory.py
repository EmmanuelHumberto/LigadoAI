"""In-memory repository for measurement sessions.

This adapter is intended for contract tests and the first local runtime
composition. PostgreSQL can replace it behind the same methods.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from measurements.domain import (
    MeasurementSession,
    MeasurementSnapshot,
    MeasurementStatus,
    SnapshotValidationStatus,
    utcnow,
)


class InMemoryMeasurementRepository:
    def __init__(self) -> None:
        self._sessions: dict[UUID, MeasurementSession] = {}
        self._snapshots: dict[UUID, list[MeasurementSnapshot]] = {}

    async def create_session(self, session: MeasurementSession) -> MeasurementSession:
        self._sessions[session.id] = session
        self._snapshots.setdefault(session.id, [])
        return session

    async def get_session(self, session_id: UUID) -> MeasurementSession | None:
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list[MeasurementSession]:
        return sorted(self._sessions.values(), key=lambda item: item.created_at, reverse=True)

    async def add_snapshots(
        self,
        session_id: UUID,
        snapshots: list[MeasurementSnapshot],
    ) -> MeasurementSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        existing = self._snapshots.setdefault(session_id, [])
        existing.extend(snapshots)
        updated = replace(
            session,
            status=MeasurementStatus.CAPTURED,
            total_snapshots=len(existing),
            valid_snapshots=sum(
                1 for snapshot in existing if snapshot.status == SnapshotValidationStatus.VALID
            ),
            invalid_snapshots=sum(
                1 for snapshot in existing if snapshot.status == SnapshotValidationStatus.INVALID
            ),
            updated_at=utcnow(),
        )
        self._sessions[session_id] = updated
        return updated

    async def list_snapshots(self, session_id: UUID) -> list[MeasurementSnapshot]:
        return list(self._snapshots.get(session_id, []))

    async def save_diagnostic(
        self,
        session_id: UUID,
        diagnostic: dict,
    ) -> MeasurementSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        updated = replace(
            session,
            status=MeasurementStatus.DIAGNOSED,
            diagnostic=diagnostic,
            updated_at=utcnow(),
        )
        self._sessions[session_id] = updated
        return updated

    async def save_report(
        self,
        session_id: UUID,
        report_markdown: str,
    ) -> MeasurementSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        updated = replace(
            session,
            status=MeasurementStatus.REPORTED,
            report_markdown=report_markdown,
            updated_at=utcnow(),
        )
        self._sessions[session_id] = updated
        return updated
