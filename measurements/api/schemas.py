"""Pydantic schemas for measurement HTTP contracts."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MeasurementHeaderSchema(BaseModel):
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
    verticais: list[str] = Field(default_factory=list)


class CreateMeasurementSessionRequestSchema(BaseModel):
    header: MeasurementHeaderSchema = Field(default_factory=MeasurementHeaderSchema)


class MeasurementSessionSchema(BaseModel):
    id: UUID
    status: str
    header: MeasurementHeaderSchema
    total_snapshots: int = 0
    valid_snapshots: int = 0
    invalid_snapshots: int = 0
    diagnostic: dict[str, Any] | None = None
    report_markdown: str | None = None


class MeasurementSessionsResponseSchema(BaseModel):
    sessions: list[MeasurementSessionSchema] = Field(default_factory=list)


class AddSnapshotsRequestSchema(BaseModel):
    snapshots: list[dict[str, Any]] = Field(default_factory=list)


class AddSnapshotsResponseSchema(BaseModel):
    session: MeasurementSessionSchema
    accepted: int = 0
    rejected: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class MeasurementSnapshotSchema(BaseModel):
    id: UUID
    session_id: UUID
    type: str
    timestamp_us: int | None = None
    status: str
    errors: list[dict[str, Any]] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)


class MeasurementSnapshotsResponseSchema(BaseModel):
    snapshots: list[MeasurementSnapshotSchema] = Field(default_factory=list)


class MeasurementDiagnosticResponseSchema(BaseModel):
    session: MeasurementSessionSchema
    diagnostic: dict[str, Any]


class MeasurementReportResponseSchema(BaseModel):
    session: MeasurementSessionSchema
    markdown: str

