"""Sistema Formal de Confiança — COUS v3.0 (Documento I, Seção I.7).

Implementa a função de confiança C = w₁·Eₑ + w₂·Eₔ + w₃·Eₕ + w₄·Eᶜ
com pesos configuráveis por domínio e escala interpretável de 0 a 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from knowledge.domain.cous_models import ConfidenceBreakdown


# ── Pesos padrão por domínio ────────────────────────────────────────────

@dataclass(frozen=True)
class DomainWeights:
    """Pesos configuráveis por domínio. w_evidence + w_document + w_history + w_consistency = 1.0"""

    w_evidence: float = 0.40
    w_document: float = 0.25
    w_history: float = 0.25
    w_consistency: float = 0.10

    def __post_init__(self) -> None:
        total = self.w_evidence + self.w_document + self.w_history + self.w_consistency
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Pesos devem somar 1.0. Soma atual: {total}")

    @classmethod
    def for_domain(cls, domain_name: str) -> DomainWeights:
        """Retorna pesos padrão para o domínio. Extensível por domínio."""
        return _DOMAIN_WEIGHTS.get(domain_name, cls())

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DomainWeights:
        return cls(
            w_evidence=float(config.get("w_evidence", 0.40)),
            w_document=float(config.get("w_document", 0.25)),
            w_history=float(config.get("w_history", 0.25)),
            w_consistency=float(config.get("w_consistency", 0.10)),
        )


_DOMAIN_WEIGHTS: dict[str, DomainWeights] = {
    "tattoo_machines": DomainWeights(
        w_evidence=0.40,   # evidência física tem maior peso
        w_document=0.25,   # documentação técnica
        w_history=0.25,    # histórico de casos
        w_consistency=0.10,  # consistência interna
    ),
}


# ── Cálculo de cada dimensão ────────────────────────────────────────────

def compute_evidence_score(
    n_strong: int = 0,
    n_moderate: int = 0,
    n_weak: int = 0,
    n_max: int = 5,
) -> float:
    """Score de Evidência Física (Eₑ).

    Eₑ = (n_strong·1.0 + n_moderate·0.6 + n_weak·0.3) / min(n_total, n_max)
    """
    n_total = n_strong + n_moderate + n_weak
    if n_total == 0:
        return 0.0
    raw = (n_strong * 1.0 + n_moderate * 0.6 + n_weak * 0.3) / min(n_total, n_max)
    return min(raw, 1.0)


_AUTHORITY_WEIGHTS: dict[str, float] = {
    "alta": 1.0,
    "média": 0.6,
    "baixa": 0.3,
}


def compute_document_score(authorities: list[str]) -> float:
    """Score de Evidência Documental (Eₔ).

    Eₔ = max(autoridade_docs_consultados)
    """
    if not authorities:
        return 0.0
    scores = [_AUTHORITY_WEIGHTS.get(a.lower(), 0.0) for a in authorities]
    return max(scores)


def compute_history_score(
    confirmed_similar: int = 0,
    refuted_similar: int = 0,
) -> float:
    """Score de Histórico de Casos (Eₕ).

    Eₕ = confirmados / (confirmados + refutados + 1)
    """
    denominator = confirmed_similar + refuted_similar + 1
    return confirmed_similar / denominator


def compute_consistency_score(
    open_contradictions: int = 0,
    total_evidences: int = 0,
) -> float:
    """Score de Consistência Interna (Eᶜ).

    Eᶜ = 1 - (contradições_abertas / (total_evidências + 1))
    """
    if total_evidences < 0:
        total_evidences = 0
    return 1.0 - (open_contradictions / (total_evidences + 1))


# ── Função composta ─────────────────────────────────────────────────────

def compute_confidence(
    breakdown: ConfidenceBreakdown,
    weights: DomainWeights | None = None,
) -> float:
    """Confiança composta: C = w₁·Eₑ + w₂·Eₔ + w₃·Eₕ + w₄·Eᶜ

    Retorna valor entre 0 e 1, truncado.
    """
    w = weights or DomainWeights()
    raw = (
        w.w_evidence * breakdown.evidence_score
        + w.w_document * breakdown.document_score
        + w.w_history * breakdown.history_score
        + w.w_consistency * breakdown.consistency_score
    )
    return max(0.0, min(raw, 1.0))


# ── Escala interpretável ─────────────────────────────────────────────────

def interpret_confidence(c: float) -> str:
    """Interpreta o valor de confiança conforme escala do COUS v3.0."""
    if c < 0.20:
        return "especulativo"
    elif c < 0.40:
        return "fraco"
    elif c < 0.60:
        return "moderado"
    elif c < 0.80:
        return "robusto"
    else:
        return "consolidado"


def can_auto_diagnose(c: float) -> bool:
    """Diagnóstico automático permitido apenas se C >= 0.20."""
    return c >= 0.20


def can_be_primary_hypothesis(c: float) -> bool:
    """Hipótese pode ser principal se C >= 0.61."""
    return c >= 0.61


def can_be_consolidated(c: float) -> bool:
    """KU pode atingir nível consolidated se C >= 0.81."""
    return c >= 0.81


# ── Builders ─────────────────────────────────────────────────────────────

def build_breakdown(
    n_strong: int = 0,
    n_moderate: int = 0,
    n_weak: int = 0,
    authorities: list[str] | None = None,
    confirmed_similar: int = 0,
    refuted_similar: int = 0,
    open_contradictions: int = 0,
    total_evidences: int = 0,
) -> ConfidenceBreakdown:
    """Constrói ConfidenceBreakdown a partir de dados brutos."""
    return ConfidenceBreakdown(
        evidence_score=compute_evidence_score(n_strong, n_moderate, n_weak),
        document_score=compute_document_score(authorities or []),
        history_score=compute_history_score(confirmed_similar, refuted_similar),
        consistency_score=compute_consistency_score(open_contradictions, total_evidences),
    )
