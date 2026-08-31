"""FastAPI routes for measurements."""

from __future__ import annotations

import json
from collections.abc import Callable
from secrets import compare_digest
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, status

from measurements.api.schemas import (
    AddSnapshotsRequestSchema,
    AddSnapshotsResponseSchema,
    CreateMeasurementSessionRequestSchema,
    LinkCaptureRequestSchema,
    LinkCaptureResponseSchema,
    MeasurementDiagnosticResponseSchema,
    MeasurementHeaderSchema,
    MeasurementReportResponseSchema,
    MeasurementSessionSchema,
    MeasurementSessionsResponseSchema,
    MeasurementSnapshotSchema,
    MeasurementSnapshotsResponseSchema,
    SetSourceIdentityRequestSchema,
)
from measurements.domain import (
    MeasurementHeader,
    MeasurementSession,
    MeasurementSnapshot,
    SnapshotValidationStatus,
)


def create_measurements_router(
    *,
    repository,
    validator,
    analyzer,
    report_renderer,
    auth_token: str | None = None,
) -> APIRouter:
    dependencies = []
    if auth_token:
        dependencies.append(Depends(_bearer_auth_dependency(auth_token)))
    router = APIRouter(prefix="/measurements", tags=["measurements"], dependencies=dependencies)

    @router.post("/sessions", response_model=MeasurementSessionSchema)
    async def create_session(
        payload: CreateMeasurementSessionRequestSchema,
    ) -> MeasurementSessionSchema:
        header = _header_from_schema(payload.header)
        errors = _validate_header(header)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "invalid_header", "errors": errors},
            )
        session = await repository.create_session(
            MeasurementSession(header=header)
        )
        return _session_response(session)

    @router.get("/sessions", response_model=MeasurementSessionsResponseSchema)
    async def list_sessions() -> MeasurementSessionsResponseSchema:
        sessions = await repository.list_sessions()
        return MeasurementSessionsResponseSchema(
            sessions=[_session_response(session) for session in sessions]
        )

    @router.get("/sessions/{session_id}", response_model=MeasurementSessionSchema)
    async def get_session(session_id: UUID) -> MeasurementSessionSchema:
        session = await repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return _session_response(session)

    @router.put(
        "/sessions/{session_id}/source-identity",
        response_model=MeasurementSessionSchema,
    )
    async def set_source_identity(
        session_id: UUID,
        payload: SetSourceIdentityRequestSchema,
    ) -> MeasurementSessionSchema:
        try:
            session = await repository.set_source_session_id(
                session_id,
                payload.source_session_id.strip(),
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "source_identity_conflict", "message": str(exc)},
            ) from exc
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return _session_response(session)

    @router.post(
        "/sessions/{session_id}/snapshots",
        response_model=AddSnapshotsResponseSchema,
    )
    async def add_snapshots(
        session_id: UUID,
        payload: AddSnapshotsRequestSchema,
    ) -> AddSnapshotsResponseSchema:
        session = await repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        snapshots: list[MeasurementSnapshot] = []
        errors: list[dict] = []
        for raw in payload.snapshots:
            validation = validator.validate(raw)
            raw_timestamp = raw.get("timestamp_us")
            snapshot = MeasurementSnapshot(
                id=_snapshot_id(session_id, raw),
                session_id=session_id,
                data=dict(raw),
                timestamp_us=raw_timestamp if isinstance(raw_timestamp, int) else None,
                type=validator.normalize_type(raw.get("type")) or "unknown",
                status=(
                    SnapshotValidationStatus.VALID
                    if validation.approved
                    else SnapshotValidationStatus.INVALID
                ),
                errors=validation.errors,
            )
            snapshots.append(snapshot)
            errors.extend(validation.errors)
        persistence = await repository.add_snapshots(session_id, snapshots)
        if persistence is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        inserted = persistence.inserted_ids
        return AddSnapshotsResponseSchema(
            session=_session_response(persistence.session),
            accepted=sum(
                1
                for snapshot in snapshots
                if snapshot.id in inserted
                and snapshot.status == SnapshotValidationStatus.VALID
            ),
            rejected=sum(
                1
                for snapshot in snapshots
                if snapshot.id in inserted
                and snapshot.status == SnapshotValidationStatus.INVALID
            ),
            duplicates=sum(1 for snapshot in snapshots if snapshot.id not in inserted),
            errors=errors,
        )

    @router.get(
        "/sessions/{session_id}/snapshots",
        response_model=MeasurementSnapshotsResponseSchema,
    )
    async def list_snapshots(session_id: UUID) -> MeasurementSnapshotsResponseSchema:
        session = await repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        snapshots = await repository.list_snapshots(session_id)
        return MeasurementSnapshotsResponseSchema(
            snapshots=[_snapshot_response(snapshot) for snapshot in snapshots]
        )

    @router.post(
        "/sessions/{session_id}/capture-link",
        response_model=LinkCaptureResponseSchema,
    )
    async def link_capture(
        session_id: UUID,
        payload: LinkCaptureRequestSchema,
    ) -> LinkCaptureResponseSchema:
        try:
            projection = await repository.link_capture_session(
                session_id,
                payload.capture_session_id,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "capture_link_conflict", "message": str(exc)},
            ) from exc
        if projection is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return LinkCaptureResponseSchema(
            capture_session_id=projection.capture_session_id,
            projected=projection.projected,
            already_projected=projection.already_projected,
        )

    @router.post(
        "/sessions/{session_id}/diagnose",
        response_model=MeasurementDiagnosticResponseSchema,
    )
    async def diagnose(session_id: UUID) -> MeasurementDiagnosticResponseSchema:
        session = await repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        snapshots = await repository.list_snapshots(session_id)
        diagnostic = analyzer.diagnose(session, snapshots)
        updated = await repository.save_diagnostic(session_id, diagnostic)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return MeasurementDiagnosticResponseSchema(
            session=_session_response(updated),
            diagnostic=diagnostic,
        )

    @router.post(
        "/sessions/{session_id}/report",
        response_model=MeasurementReportResponseSchema,
    )
    async def report(session_id: UUID) -> MeasurementReportResponseSchema:
        session = await repository.get_session(session_id)
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        diagnostic = session.diagnostic
        if diagnostic is None:
            snapshots = await repository.list_snapshots(session_id)
            diagnostic = analyzer.diagnose(session, snapshots)
            session = await repository.save_diagnostic(session_id, diagnostic)
        markdown = report_renderer.render(session, diagnostic)
        updated = await repository.save_report(session_id, markdown)
        if updated is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")
        return MeasurementReportResponseSchema(
            session=_session_response(updated),
            markdown=markdown,
        )

    @router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_session(session_id: UUID) -> None:
        deleted = await repository.delete_session(session_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="session not found",
            )

    return router


def _snapshot_id(session_id: UUID, payload: dict) -> UUID:
    explicit_id = str(payload.get("event_id") or payload.get("source_event_id") or "").strip()
    if explicit_id:
        identity = explicit_id
    else:
        identity = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return uuid5(NAMESPACE_URL, f"tma:{session_id}:{identity}")


def _bearer_auth_dependency(expected_token: str) -> Callable[[str | None], None]:
    async def require_bearer(
        authorization: str | None = Header(default=None),
    ) -> None:
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_authorization",
            )
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bad_authorization",
            )
        if not compare_digest(token.strip(), expected_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid_token",
            )

    return require_bearer


def _header_from_schema(schema: MeasurementHeaderSchema) -> MeasurementHeader:
    return MeasurementHeader(**schema.model_dump())


def _header_response(header: MeasurementHeader) -> MeasurementHeaderSchema:
    return MeasurementHeaderSchema(**header.__dict__)


def _session_response(session: MeasurementSession) -> MeasurementSessionSchema:
    return MeasurementSessionSchema(
        id=session.id,
        status=session.status.value,
        header=_header_response(session.header),
        total_snapshots=session.total_snapshots,
        valid_snapshots=session.valid_snapshots,
        invalid_snapshots=session.invalid_snapshots,
        diagnostic=session.diagnostic,
        report_markdown=session.report_markdown,
    )


def _snapshot_response(snapshot: MeasurementSnapshot) -> MeasurementSnapshotSchema:
    return MeasurementSnapshotSchema(
        id=snapshot.id,
        session_id=snapshot.session_id,
        type=snapshot.type,
        timestamp_us=snapshot.timestamp_us,
        status=snapshot.status.value,
        errors=snapshot.errors,
        data=snapshot.data,
    )


def _validate_header(header: MeasurementHeader) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not header.tipo_coleta.strip():
        errors.append({"code": "missing_tipo_coleta", "message": "tipo_coleta is required"})
    if header.tipo_coleta in {"reparo", "pos-reparo"} and not header.peca_substituida.strip():
        errors.append(
            {
                "code": "missing_peca_substituida",
                "message": "peca_substituida is required for repair collections",
            }
        )
    if not header.verticais:
        errors.append({"code": "missing_verticais", "message": "at least one vertical is required"})
    if header.baudrate <= 0:
        errors.append({"code": "invalid_baudrate", "message": "baudrate must be positive"})
    if header.duracao_seg <= 0:
        errors.append({"code": "invalid_duracao_seg", "message": "duracao_seg must be positive"})
    if (
        header.curso_nominal_mm is not None
        and header.curso_min_mm is not None
        and header.curso_max_mm is not None
        and not (header.curso_min_mm <= header.curso_nominal_mm <= header.curso_max_mm)
    ):
        errors.append(
            {
                "code": "invalid_curso_interval",
                "message": "curso_nominal_mm must stay between curso_min_mm and curso_max_mm",
            }
        )
    return errors
