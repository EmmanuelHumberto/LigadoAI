"""PostgreSQL repository for measurement sessions."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

import asyncpg

from measurements.domain import (
    AddSnapshotsResult,
    CaptureProjectionResult,
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
                    id, status, source_session_id, fabricante, modelo, numero_serie, tipo_maquina,
                    tipo_motor, sistema_transmissao, curso_nominal_mm,
                    curso_min_mm, curso_max_mm, tipo_coleta, peca_substituida,
                    observacoes, tecnico, porta_serial, baudrate, duracao_seg,
                    verticais, total_snapshots, valid_snapshots,
                    invalid_snapshots, diagnostic, report_markdown,
                    created_at, updated_at
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10,
                    $11, $12, $13, $14,
                    $15, $16, $17, $18, $19,
                    $20::jsonb, $21, $22,
                    $23, $24::jsonb, $25,
                    $26, $27
                )
                RETURNING *
                """,
                session.id,
                session.status.value,
                header.source_session_id,
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

    async def delete_session(self, session_id: UUID) -> bool:
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM measurement_sessions WHERE id = $1",
                session_id,
            )
            return result == "DELETE 1"

    async def add_snapshots(
        self,
        session_id: UUID,
        snapshots: list[MeasurementSnapshot],
    ) -> AddSnapshotsResult | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                session_row = await conn.fetchrow(
                    "SELECT * FROM measurement_sessions WHERE id = $1 FOR UPDATE",
                    session_id,
                )
                if session_row is None:
                    return None
                inserted_ids: set[UUID] = set()
                for snapshot in snapshots:
                    inserted_id = await conn.fetchval(
                        """
                        INSERT INTO measurement_snapshots (
                            id, session_id, type, timestamp_us, status,
                            errors, data, created_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8)
                        ON CONFLICT (id) DO NOTHING
                        RETURNING id
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
                    if inserted_id is not None:
                        inserted_ids.add(inserted_id)
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
        if row is None:
            return None
        return AddSnapshotsResult(
            session=_session_from_row(row),
            inserted_ids=frozenset(inserted_ids),
        )

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

    async def set_source_session_id(
        self,
        session_id: UUID,
        source_session_id: str,
    ) -> MeasurementSession | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                UPDATE measurement_sessions
                SET source_session_id = $2, updated_at = NOW()
                WHERE id = $1
                  AND (source_session_id = '' OR source_session_id = $2)
                RETURNING *
                """,
                session_id,
                source_session_id,
            )
            if row is not None:
                return _session_from_row(row)
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM measurement_sessions WHERE id = $1)",
                session_id,
            )
            if not exists:
                return None
            raise ValueError("measurement session has another source_session_id")

    async def link_capture_session(
        self,
        session_id: UUID,
        capture_session_id: UUID,
    ) -> CaptureProjectionResult | None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                capture_exists = await conn.fetchval(
                    "SELECT EXISTS(SELECT 1 FROM capture_sessions WHERE id = $1)",
                    capture_session_id,
                )
                if not capture_exists:
                    raise ValueError(f"capture session not found: {capture_session_id}")
                linked = await conn.fetchval(
                    """
                    UPDATE measurement_sessions
                    SET capture_session_id = $2, updated_at = NOW()
                    WHERE id = $1
                      AND (capture_session_id IS NULL OR capture_session_id = $2)
                    RETURNING id
                    """,
                    session_id,
                    capture_session_id,
                )
                if linked is None:
                    exists = await conn.fetchval(
                        "SELECT EXISTS(SELECT 1 FROM measurement_sessions WHERE id = $1)",
                        session_id,
                    )
                    if not exists:
                        return None
                    raise ValueError("measurement session is linked to another capture")

                rows = await conn.fetch(
                    """
                    SELECT ms.id, ms.timestamp_us, ms.data
                    FROM measurement_snapshots ms
                    LEFT JOIN measurement_snapshot_projections p
                        ON p.snapshot_id = ms.id
                    WHERE ms.session_id = $1
                      AND ms.status = 'valid'
                      AND ms.type = 'electromechanical_correlation_frame'
                      AND p.snapshot_id IS NULL
                    ORDER BY ms.created_at ASC
                    """,
                    session_id,
                )
                total_candidates = await conn.fetchval(
                    """
                    SELECT COUNT(*)::int
                    FROM measurement_snapshots
                    WHERE session_id = $1
                      AND status = 'valid'
                      AND type = 'electromechanical_correlation_frame'
                    """,
                    session_id,
                )
                projected = 0
                for row in rows:
                    data = _json_dict_value(row["data"])
                    projection = _correlation_projection(data)
                    if projection is None:
                        continue
                    timestamp_us = int(row["timestamp_us"] or data.get("timestamp_us") or 0)
                    signature_id = await conn.fetchval(
                        """
                        INSERT INTO electromechanical_signatures_default (
                            capture_session_id, timestamp_us, profile_label, valid,
                            rpm, motor_current_ma, voltage_mv, bemf_v,
                            winding_resistance_mohm, torque_load_permille
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NULL)
                        RETURNING id
                        """,
                        capture_session_id,
                        timestamp_us,
                        projection["profile_label"],
                        projection["valid"],
                        projection["rpm"],
                        projection["motor_current_ma"],
                        projection["voltage_mv"],
                        projection["bemf_v"],
                        projection["winding_resistance_mohm"],
                    )
                    await conn.execute(
                        """
                        INSERT INTO signature_deviations (
                            signature_id, bemf_error_permille,
                            winding_resistance_error_permille,
                            rpm_error_permille, electrical_power_error_permille,
                            torque_error_permille, current_error_permille,
                            produced_by
                        ) VALUES ($1, $2, $3, $4, $5, NULL, NULL, 'firmware')
                        """,
                        signature_id,
                        projection["bemf_error_permille"],
                        projection["resistance_error_permille"],
                        projection["rpm_error_permille"],
                        projection["electrical_power_error_permille"],
                    )
                    for relation_index, relation in enumerate(projection["relations"]):
                        await conn.execute(
                            """
                            INSERT INTO electromechanical_correlation_relations (
                                snapshot_id, capture_session_id, signature_id,
                                timestamp_us, relation_index, relation_id,
                                layer, assessment, observed, reference, residual,
                                error_permille, confidence_permille,
                                source_channels, limitation, valid
                            ) VALUES (
                                $1, $2, $3, $4, $5, $6,
                                $7, $8, $9, $10, $11,
                                $12, $13, $14, $15, $16
                            )
                            """,
                            row["id"],
                            capture_session_id,
                            signature_id,
                            timestamp_us,
                            relation_index,
                            relation["relation_id"],
                            relation["layer"],
                            relation["assessment"],
                            relation["observed"],
                            relation["reference"],
                            relation["residual"],
                            relation["error_permille"],
                            relation["confidence_permille"],
                            relation["source_channels"],
                            relation["limitation"],
                            relation["valid"],
                        )
                    await conn.execute(
                        """
                        INSERT INTO measurement_snapshot_projections (
                            snapshot_id, capture_session_id, signature_id, timestamp_us
                        ) VALUES ($1, $2, $3, $4)
                        """,
                        row["id"],
                        capture_session_id,
                        signature_id,
                        timestamp_us,
                    )
                    projected += 1

                counts = await conn.fetchrow(
                    """
                    SELECT COUNT(*)::int AS total,
                           COUNT(*) FILTER (WHERE valid)::int AS valid
                    FROM electromechanical_signatures_default
                    WHERE capture_session_id = $1
                    """,
                    capture_session_id,
                )
                await conn.execute(
                    """
                    UPDATE capture_sessions
                    SET total_signatures = $2::integer,
                        valid_signatures = $3::integer,
                        valid_ratio = CASE
                            WHEN $2::integer > 0
                            THEN $3::numeric / $2::numeric
                            ELSE NULL
                        END
                    WHERE id = $1
                    """,
                    capture_session_id,
                    int(counts["total"] or 0),
                    int(counts["valid"] or 0),
                )
        return CaptureProjectionResult(
            capture_session_id=capture_session_id,
            projected=projected,
            already_projected=max(0, int(total_candidates or 0) - len(rows)),
        )

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
        source_session_id=row["source_session_id"],
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


def _correlation_projection(data: dict[str, Any]) -> dict[str, Any] | None:
    if data.get("type") != "electromechanical_correlation_frame" or data.get("version") != 4:
        return None
    profile = data.get("profile") if isinstance(data.get("profile"), dict) else {}
    closure = data.get("closure") if isinstance(data.get("closure"), dict) else {}
    electrical = (
        closure.get("electrical") if isinstance(closure.get("electrical"), dict) else {}
    )
    motor = closure.get("motor") if isinstance(closure.get("motor"), dict) else {}
    bemf_mv = _valid_number(
        electrical,
        "bemf_electrical_mv",
        "bemf_electrical_valid",
    )
    return {
        "profile_label": str(profile.get("label") or profile.get("id") or "unidentified"),
        "valid": data.get("valid") is True,
        "rpm": _valid_number(motor, "rpm_mpu", "valid"),
        "motor_current_ma": _valid_number(electrical, "motor_current_ma", "valid"),
        "voltage_mv": _valid_number(electrical, "bus_voltage_mv", "valid"),
        "bemf_v": bemf_mv / 1000.0 if bemf_mv is not None else None,
        "winding_resistance_mohm": _valid_number(
            electrical,
            "resistance_mohm",
            "resistance_measured",
        ),
        "bemf_error_permille": _valid_number(
            motor,
            "bemf_error_permille",
            "bemf_model_valid",
        ),
        "resistance_error_permille": _valid_number(
            motor,
            "winding_resistance_error_permille",
            "winding_resistance_error_valid",
        ),
        "rpm_error_permille": _valid_number(
            motor,
            "rpm_error_permille",
            "rpm_error_valid",
        ),
        "electrical_power_error_permille": _valid_number(
            motor,
            "electrical_power_error_permille",
            "electrical_power_error_valid",
        ),
        "relations": _relation_projections(data.get("relations")),
    }


def _relation_projections(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    projections: list[dict[str, Any]] = []
    for relation in value:
        if not isinstance(relation, dict):
            continue
        relation_id = relation.get("id")
        layer = relation.get("layer")
        assessment = relation.get("assessment")
        confidence = relation.get("confidence_permille")
        valid = relation.get("valid")
        if (
            not isinstance(relation_id, str)
            or not relation_id
            or isinstance(layer, bool)
            or not isinstance(layer, int)
            or layer not in range(4)
            or isinstance(assessment, bool)
            or not isinstance(assessment, int)
            or assessment not in range(5)
            or isinstance(confidence, bool)
            or not isinstance(confidence, int)
            or not 0 <= confidence <= 1000
            or not isinstance(valid, bool)
        ):
            continue
        projections.append(
            {
                "relation_id": relation_id,
                "layer": layer,
                "assessment": assessment,
                "observed": _number_or_none(relation.get("observed")),
                "reference": _number_or_none(relation.get("reference")),
                "residual": _number_or_none(relation.get("residual")),
                "error_permille": _integer_or_none(relation.get("error_permille")),
                "confidence_permille": confidence,
                "source_channels": str(relation.get("source_channels") or ""),
                "limitation": str(relation.get("limitation") or ""),
                "valid": valid,
            }
        )
    return projections


def _number_or_none(value: object) -> int | float | None:
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def _integer_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _valid_number(mapping: dict[str, Any], key: str, valid_key: str) -> int | float | None:
    value = mapping.get(key)
    if mapping.get(valid_key) is not True or isinstance(value, bool):
        return None
    return value if isinstance(value, int | float) else None
