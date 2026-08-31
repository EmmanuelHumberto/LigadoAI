"""In-memory repository for measurement sessions.

This adapter is intended for contract tests and the first local runtime
composition. PostgreSQL can replace it behind the same methods.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from measurements.domain import (
    AddSnapshotsResult,
    CaptureProjectionResult,
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
        self._capture_links: dict[UUID, UUID] = {}
        self._projected_snapshots: set[UUID] = set()

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
    ) -> AddSnapshotsResult | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        existing = self._snapshots.setdefault(session_id, [])
        existing_ids = {snapshot.id for snapshot in existing}
        inserted = [snapshot for snapshot in snapshots if snapshot.id not in existing_ids]
        existing.extend(inserted)
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
        return AddSnapshotsResult(
            session=updated,
            inserted_ids=frozenset(snapshot.id for snapshot in inserted),
        )

    async def list_snapshots(self, session_id: UUID) -> list[MeasurementSnapshot]:
        return list(self._snapshots.get(session_id, []))

    async def set_source_session_id(
        self,
        session_id: UUID,
        source_session_id: str,
    ) -> MeasurementSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        current = session.header.source_session_id
        if current and current != source_session_id:
            raise ValueError("measurement session has another source_session_id")
        updated = replace(
            session,
            header=replace(session.header, source_session_id=source_session_id),
            updated_at=utcnow(),
        )
        self._sessions[session_id] = updated
        return updated

    async def link_capture_session(
        self,
        session_id: UUID,
        capture_session_id: UUID,
    ) -> CaptureProjectionResult | None:
        if session_id not in self._sessions:
            return None
        previous = self._capture_links.get(session_id)
        if previous is not None and previous != capture_session_id:
            raise ValueError("measurement session is linked to another capture")
        self._capture_links[session_id] = capture_session_id
        candidates = [
            snapshot
            for snapshot in self._snapshots.get(session_id, [])
            if snapshot.status == SnapshotValidationStatus.VALID
            and snapshot.type == "electromechanical_correlation_frame"
        ]
        pending = [item for item in candidates if item.id not in self._projected_snapshots]
        self._projected_snapshots.update(item.id for item in pending)
        return CaptureProjectionResult(
            capture_session_id=capture_session_id,
            projected=len(pending),
            already_projected=len(candidates) - len(pending),
        )

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

    async def delete_session(self, session_id: UUID) -> bool:
        if session_id not in self._sessions:
            return False
        del self._sessions[session_id]
        if session_id in self._snapshots:
            del self._snapshots[session_id]
        return True

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
