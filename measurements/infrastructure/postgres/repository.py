"""PostgreSQL repository for measurement sessions."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import asyncpg

from measurements.domain import (
    MeasurementHeader,
    MeasurementSession,
    MeasurementSnapshot,
    MeasurementStatus,
    SnapshotValidationStatus,
)


class PostgresMeasurementRepository:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str, **kwargs: Any) -> PostgresMeasurementRepository:
        pool = await asyncpg.create_pool(dsn=dsn, **kwargs)
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def create_session(self, session: MeasurementSession) -> MeasurementSession:
        header = session.header
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO measurement_sessions (
                    id, status, fabricante, modelo, numero_serie, tipo_maquina,
                    tipo_motor, sistema_transmissao, curso_nominal_mm,
                    curso_min_mm, curso_max_mm, tipo_coleta, peca_substituida,
                    observacoes, tecnico, porta_serial, baudrate, duracao_seg,
                    verticais, total_snapshots, valid_snapshots,
                    invalid_snapshots, diagnostic, report_markdown,
                    created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16, $17, $18,
                    $19::jsonb, $20, $21,
                    $22, $23::jsonb, $24,
                    $25, $26
                )
                RETURNING *
                """,
                session.id,
                session.status.value,
                header.fabricante,
                header.modelo,
                header.numero_serie,
                header.tipo_maquina,
                header.tipo_motor,
                header.sistema_transmissao,
                header.curso_nominal_mm,
                header.curso_min_mm,
                header.curso_max_mm,
                header.tipo_coleta,
                header.peca_substituida,
                header.observacoes,
                header.tecnico,
                header.porta_serial,
                header.baudrate,
                header.duracao_seg,
                _json_list(header.verticais),
                session.total_snapshots,
                session.valid_snapshots,
                session.invalid_snapshots,
                _json_dict(session.diagnostic) if session.diagnostic is not None else None,
                session.report_markdown,
                session.created_at,
                session.updated_at,
            )
        return _session_from_row(row)

    async def get_session(self, session_id: UUID) -> MeasurementSession | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM measurement_sessions WHERE id = $1",
                session_id,
            )
        return _session_from_row(row) if row else None

    async def list_sessions(self) -> list[MeasurementSession]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM measurement_sessions ORDER BY updated_at DESC"
            )
        return [_session_from_row(row) for row in rows]

    async def add_snapshots(
        self,
        session_id: UUID,
        snapshots: list[MeasurementSnapshot],
    ) -> MeasurementSession | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                session_row = await conn.fetchrow(
                    "SELECT * FROM measurement_sessions WHERE id = $1 FOR UPDATE",
                    session_id,
                )
                if session_row is None:
                    return None
                for snapshot in snapshots:
                    await conn.execute(
                        """
                        INSERT INTO measurement_snapshots (
                            id, session_id, type, timestamp_us, status,
                            errors, data, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
                        """,
                        snapshot.id,
                        snapshot.session_id,
                        snapshot.type,
                        snapshot.timestamp_us,
                        snapshot.status.value,
                        _json_list(snapshot.errors),
                        _json_dict(snapshot.data),
                        snapshot.created_at,
                    )
                row = await conn.fetchrow(
                    """
                    UPDATE measurement_sessions
                    SET status = $2,
                        total_snapshots = counts.total_snapshots,
                        valid_snapshots = counts.valid_snapshots,
                        invalid_snapshots = counts.invalid_snapshots,
                        updated_at = NOW()
                    FROM (
                        SELECT
                            COUNT(*)::int AS total_snapshots,
                            COUNT(*) FILTER (WHERE status = 'valid')::int
                                AS valid_snapshots,
                            COUNT(*) FILTER (WHERE status = 'invalid')::int
                                AS invalid_snapshots
                        FROM measurement_snapshots
                        WHERE session_id = $1
                    ) counts
                    WHERE measurement_sessions.id = $1
                    RETURNING measurement_sessions.*
                    """,
                    session_id,
                    MeasurementStatus.CAPTURED.value,
                )
        return _session_from_row(row) if row else None

    async def list_snapshots(self, session_id: UUID) -> list[MeasurementSnapshot]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM measurement_snapshots
                WHERE session_id = $1
                ORDER BY created_at ASC
                """,
                session_id,
            )
        return [_snapshot_from_row(row) for row in rows]

    async def save_diagnostic(
        self,
        session_id: UUID,
        diagnostic: dict,
    ) -> MeasurementSession | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE measurement_sessions
                SET status = $2, diagnostic = $3::jsonb, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                session_id,
                MeasurementStatus.DIAGNOSED.value,
                _json_dict(diagnostic),
            )
        return _session_from_row(row) if row else None

    async def save_report(
        self,
        session_id: UUID,
        report_markdown: str,
    ) -> MeasurementSession | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE measurement_sessions
                SET status = $2, report_markdown = $3, updated_at = NOW()
                WHERE id = $1
                RETURNING *
                """,
                session_id,
                MeasurementStatus.REPORTED.value,
                report_markdown,
            )
        return _session_from_row(row) if row else None


def _session_from_row(row: asyncpg.Record) -> MeasurementSession:
    header = MeasurementHeader(
        fabricante=row["fabricante"],
        modelo=row["modelo"],
        numero_serie=row["numero_serie"],
        tipo_maquina=row["tipo_maquina"],
        tipo_motor=row["tipo_motor"],
        sistema_transmissao=row["sistema_transmissao"],
        curso_nominal_mm=row["curso_nominal_mm"],
        curso_min_mm=row["curso_min_mm"],
        curso_max_mm=row["curso_max_mm"],
        tipo_coleta=row["tipo_coleta"],
        peca_substituida=row["peca_substituida"],
        observacoes=row["observacoes"],
        tecnico=row["tecnico"],
        porta_serial=row["porta_serial"],
        baudrate=row["baudrate"],
        duracao_seg=row["duracao_seg"],
        verticais=_json_list_value(row["verticais"]),
    )
    return MeasurementSession(
        id=row["id"],
        header=header,
        status=MeasurementStatus(row["status"]),
        total_snapshots=row["total_snapshots"],
        valid_snapshots=row["valid_snapshots"],
        invalid_snapshots=row["invalid_snapshots"],
        diagnostic=_json_dict_value(row["diagnostic"]) if row["diagnostic"] else None,
        report_markdown=row["report_markdown"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _snapshot_from_row(row: asyncpg.Record) -> MeasurementSnapshot:
    snapshot = MeasurementSnapshot(
        id=row["id"],
        session_id=row["session_id"],
        type=row["type"],
        timestamp_us=row["timestamp_us"],
        status=SnapshotValidationStatus(row["status"]),
        errors=_json_list_value(row["errors"]),
        data=_json_dict_value(row["data"]),
    )
    return replace(snapshot, created_at=row["created_at"])


def _json_dict(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, default=str)


def _json_list(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False, default=str)


def _json_dict_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return dict(value)


def _json_list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, list) else []
    return list(value)
