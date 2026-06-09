"""Domain objects for technical measurement sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


class MeasurementStatus(StrEnum):
    CREATED = "created"
    CAPTURING = "capturing"
    CAPTURED = "captured"
    FAILED = "failed"
    DIAGNOSED = "diagnosed"
    REPORTED = "reported"


class SnapshotValidationStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class MeasurementHeader:
    fabricante: str = ""
    modelo: str = ""
    numero_serie: str = ""
    tipo_maquina: str = ""
    tipo_motor: str = ""
    sistema_transmissao: str = ""
    curso_nominal_mm: float | None = None
    curso_min_mm: float | None = None
    curso_max_mm: float | None = None
    tipo_coleta: str = "desempenho"
    peca_substituida: str = ""
    observacoes: str = ""
    tecnico: str = ""
    porta_serial: str = ""
    baudrate: int = 115200
    duracao_seg: float = 30.0
    verticais: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class MeasurementSession:
    header: MeasurementHeader
    id: UUID = field(default_factory=uuid4)
    status: MeasurementStatus = MeasurementStatus.CREATED
    total_snapshots: int = 0
    valid_snapshots: int = 0
    invalid_snapshots: int = 0
    diagnostic: dict[str, Any] | None = None
    report_markdown: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class MeasurementSnapshot:
    session_id: UUID
    data: dict[str, Any]
    id: UUID = field(default_factory=uuid4)
    timestamp_us: int | None = None
    type: str = "unknown"
    status: SnapshotValidationStatus = SnapshotValidationStatus.VALID
    errors: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class SnapshotValidationResult:
    approved: bool
    errors: list[dict[str, Any]] = field(default_factory=list)

