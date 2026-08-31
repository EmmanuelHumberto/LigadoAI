"""COUS v3.0 domain objects — mapeamento do Documento III (Modelo de Dados).

Estes dataclasses representam as tabelas do schema COUS v3.0.
Seguem o mesmo padrão de `knowledge/domain/models.py`: frozen, UUID v4,
timestamps UTC, sem dependências de infraestrutura.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── Enums ────────────────────────────────────────────────────────────────

class DomainStatus(StrEnum):
    ONBOARDING = "onboarding"
    OPERATIONAL = "operational"
    DEPRECATED = "deprecated"


class ProfileStatus(StrEnum):
    DRAFT = "draft"
    EM_VALIDACAO = "em_validacao"
    ATIVO = "ativo"
    DEPRECATED = "deprecated"


class SessionStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    FAILED = "failed"


class DiagnosisStatus(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    CONFIRMED = "confirmed"
    CLOSED = "closed"


class EvidenceStrength(StrEnum):
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"


class EvidenceType(StrEnum):
    PHYSICAL = "physical"
    DOCUMENTAL = "documental"
    HISTORICAL = "historical"
    EXPERIMENTAL = "experimental"


class KnowledgeLevel(StrEnum):
    EXPERIMENTAL = "experimental"
    OBSERVED = "observed"
    CONFIRMED = "confirmed"
    CONSOLIDATED = "consolidated"


class RelationType(StrEnum):
    REFUTES = "refuta"
    REPLACES = "substitui"
    SPECIALIZES = "especializa"
    GENERALIZES = "generaliza"
    COMPLEMENTS = "complementa"
    CORROBORATES = "corrobora"


class ContradictionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACKNOWLEDGED = "acknowledged"


class FeedbackType(StrEnum):
    CONFIRM = "confirm"
    CORRECT = "correct"
    SOLUTION = "solution"


class QueueStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Camada Física ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Domain:
    name: str
    id: UUID = field(default_factory=uuid4)
    version: str | None = None
    status: DomainStatus = DomainStatus.ONBOARDING
    config: dict[str, Any] = field(default_factory=dict)
    activated_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Entity:
    domain_id: UUID
    entity_type: str
    id: UUID = field(default_factory=uuid4)
    manufacturer: str | None = None
    model: str | None = None
    description: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Instance:
    entity_id: UUID
    serial_number: str
    id: UUID = field(default_factory=uuid4)
    firmware_version: str | None = None
    manufacture_date: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Subsystem:
    instance_id: UUID
    id: UUID = field(default_factory=uuid4)
    subsystem_type: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class ElectromechanicalProfile:
    entity_id: UUID
    domain_id: UUID
    profile_label: str
    id: UUID = field(default_factory=uuid4)
    version: int = 1
    status: ProfileStatus = ProfileStatus.DRAFT
    rpm_nominal: float | None = None
    current_nominal_ma: float | None = None
    bemf_nominal_v: float | None = None
    torque_nominal_permille: float | None = None
    resistance_nominal_mohm: float | None = None
    efficiency_nominal: float | None = None
    source_document_id: UUID | None = None
    supersedes_id: UUID | None = None
    validated_by: str | None = None
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None
    deprecation_reason: str | None = None
    created_at: datetime = field(default_factory=utcnow)


# ── Camada Operacional ───────────────────────────────────────────────────

@dataclass(frozen=True)
class OperationalSession:
    session_type: str
    id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(default_factory=utcnow)
    finished_at: datetime | None = None
    operator_name: str | None = None
    status: SessionStatus = SessionStatus.OPEN


@dataclass(frozen=True)
class CaptureSession:
    operational_session_id: UUID
    instance_id: UUID
    id: UUID = field(default_factory=uuid4)
    valid_ratio: float | None = None
    total_signatures: int = 0
    valid_signatures: int = 0
    diagnosis_status: DiagnosisStatus = DiagnosisStatus.PENDING
    diagnosis_queued_at: datetime | None = None
    diagnosis_completed_at: datetime | None = None
    diagnosis_correlation_id: UUID | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Observation:
    capture_session_id: UUID
    timestamp_us: int
    observation_type: str
    value: float
    unit: str
    id: int | None = None  # BIGSERIAL


@dataclass(frozen=True)
class Snapshot:
    capture_session_id: UUID
    timestamp_us: int
    id: int | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ElectromechanicalSignature:
    capture_session_id: UUID
    timestamp_us: int
    profile_label: str
    id: int | None = None
    valid: bool = True
    rpm: float | None = None
    motor_current_ma: float | None = None
    voltage_mv: float | None = None
    bemf_v: float | None = None
    equivalent_resistance_mohm: float | None = None
    torque_load_permille: float | None = None


@dataclass(frozen=True)
class SignatureDeviation:
    signature_id: int
    id: int | None = None
    bemf_error_permille: float | None = None
    equivalent_resistance_error_permille: float | None = None
    torque_error_permille: float | None = None
    current_error_permille: float | None = None
    produced_by: str = "firmware"


# ── Camada Epistêmica ────────────────────────────────────────────────────

@dataclass(frozen=True)
class TechnicalCase:
    domain_id: UUID
    instance_id: UUID
    id: UUID = field(default_factory=uuid4)
    capture_session_id: UUID | None = None
    reported_problem: str | None = None
    final_diagnosis: str | None = None
    solution_applied: str | None = None
    solution_type: str | None = None
    result_status: str | None = None
    status: CaseStatus = CaseStatus.OPEN
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Evidence:
    case_id: UUID
    evidence_type: EvidenceType
    id: UUID = field(default_factory=uuid4)
    evidence_strength: EvidenceStrength = EvidenceStrength.WEAK
    source_reference: str | None = None
    confidence: float = 0.0
    status: str = "active"
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class CausalChain:
    domain_id: UUID
    title: str
    condition_expression: str
    probable_cause: str
    expected_consequence: str
    id: UUID = field(default_factory=uuid4)
    confidence: float = 0.0
    version: int = 1
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class ConfidenceBreakdown:
    evidence_score: float = 0.0       # Eₑ
    document_score: float = 0.0       # Eₔ
    history_score: float = 0.0        # Eₕ
    consistency_score: float = 0.0    # Eᶜ

    def as_dict(self) -> dict[str, float]:
        return {
            "evidence_score": self.evidence_score,
            "document_score": self.document_score,
            "history_score": self.history_score,
            "consistency_score": self.consistency_score,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfidenceBreakdown:
        return cls(
            evidence_score=float(data.get("evidence_score", 0)),
            document_score=float(data.get("document_score", 0)),
            history_score=float(data.get("history_score", 0)),
            consistency_score=float(data.get("consistency_score", 0)),
        )


@dataclass(frozen=True)
class Hypothesis:
    case_id: UUID
    description: str
    id: UUID = field(default_factory=uuid4)
    causal_chain_id: UUID | None = None
    confidence: float = 0.0
    confidence_breakdown: ConfidenceBreakdown | None = None
    is_primary: bool = False
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Explanation:
    case_id: UUID
    hypothesis_id: UUID
    narrative: str
    id: UUID = field(default_factory=uuid4)
    narrative_type: str = "technical"
    confidence: float = 0.0
    created_at: datetime = field(default_factory=utcnow)


# ── Camada de Conhecimento ───────────────────────────────────────────────

@dataclass(frozen=True)
class KnowledgeUnit:
    domain_id: UUID
    title: str
    statement: str
    id: UUID = field(default_factory=uuid4)
    knowledge_level: KnowledgeLevel = KnowledgeLevel.EXPERIMENTAL
    confidence: float = 0.0
    confidence_breakdown: ConfidenceBreakdown | None = None
    version: int = 1
    superseded_by: UUID | None = None
    last_validated_at: datetime | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeUnitRelation:
    source_ku_id: UUID
    target_ku_id: UUID
    relation_type: RelationType
    id: UUID = field(default_factory=uuid4)
    confidence: float = 0.0
    source: str = "inference"
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeContradiction:
    knowledge_unit_id: UUID
    description: str
    id: UUID = field(default_factory=uuid4)
    contradicting_case_id: UUID | None = None
    contradicting_evidence_id: UUID | None = None
    resolution_status: ContradictionStatus = ContradictionStatus.OPEN
    created_at: datetime = field(default_factory=utcnow)


# ── Camada Cognitiva ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CognitiveTrace:
    request: str
    id: UUID = field(default_factory=uuid4)
    session_id: UUID | None = None
    response: str | None = None
    duration_ms: int | None = None
    confidence_final: float | None = None
    knowledge_units_used: list[UUID] = field(default_factory=list)
    causal_chains_used: list[UUID] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class KnowledgeFeedback:
    feedback_type: FeedbackType
    id: UUID = field(default_factory=uuid4)
    case_id: UUID | None = None
    trace_id: UUID | None = None
    comment: str | None = None
    operator_name: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class Golden:
    domain_id: UUID
    title: str
    input_context: str
    expected_answer: str
    id: UUID = field(default_factory=uuid4)
    trace_id: UUID | None = None
    justification: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True)
class DiagnosisQueueItem:
    capture_session_id: UUID
    instance_id: UUID
    id: UUID = field(default_factory=uuid4)
    queued_at: datetime = field(default_factory=utcnow)
    status: QueueStatus = QueueStatus.PENDING
    attempts: int = 0
    last_attempt_at: datetime | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class AuditLogEntry:
    entity_type: str
    entity_id: UUID
    action: str
    id: int | None = None  # BIGSERIAL
    operator: str | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime = field(default_factory=utcnow)
