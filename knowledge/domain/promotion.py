"""Motor de Promoção/Rebaixamento de KnowledgeUnits — COUS v3.0 (Documento I, Seção I.5.4).

Define as regras de transição entre níveis de conhecimento:
experimental → observed → confirmed → consolidated
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from knowledge.domain.cous_models import KnowledgeLevel, KnowledgeUnit


def utcnow() -> datetime:
    return datetime.now(UTC)


# ── Regras de promoção ──────────────────────────────────────────────────

@dataclass(frozen=True)
class PromotionResult:
    """Resultado de uma tentativa de promoção/rebaixamento."""

    allowed: bool
    current_level: KnowledgeLevel
    target_level: KnowledgeLevel | None = None
    reason: str = ""


def check_promotion(
    ku: KnowledgeUnit,
    target: KnowledgeLevel,
    *,
    confirmed_source_count: int = 0,
    has_human_validation: bool = False,
    has_open_contradictions: bool = False,
    has_specialist_review: bool = False,
) -> PromotionResult:
    """Verifica se uma KU pode ser promovida ao nível alvo."""

    transitions = {
        (KnowledgeLevel.EXPERIMENTAL, KnowledgeLevel.OBSERVED): _check_to_observed,
        (KnowledgeLevel.OBSERVED, KnowledgeLevel.CONFIRMED): _check_to_confirmed,
        (KnowledgeLevel.CONFIRMED, KnowledgeLevel.CONSOLIDATED): _check_to_consolidated,
    }

    checker = transitions.get((ku.knowledge_level, target))
    if checker is None:
        return PromotionResult(
            allowed=False,
            current_level=ku.knowledge_level,
            target_level=target,
            reason=f"Transição {ku.knowledge_level.value} → {target.value} não é permitida",
        )

    return checker(
        ku,
        confirmed_source_count=confirmed_source_count,
        has_human_validation=has_human_validation,
        has_open_contradictions=has_open_contradictions,
        has_specialist_review=has_specialist_review,
    )


def _check_to_observed(
    ku: KnowledgeUnit,
    confirmed_source_count: int,
    has_human_validation: bool,
    has_open_contradictions: bool,
    has_specialist_review: bool,
) -> PromotionResult:
    """experimental → observed: ≥ 3 casos confirmados, sem contradição aberta."""
    if confirmed_source_count < 3:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.EXPERIMENTAL,
            target_level=KnowledgeLevel.OBSERVED,
            reason=f"Necessário ≥ 3 casos confirmados. Atual: {confirmed_source_count}",
        )
    if has_open_contradictions:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.EXPERIMENTAL,
            target_level=KnowledgeLevel.OBSERVED,
            reason="Contradição aberta impede promoção",
        )
    return PromotionResult(
        allowed=True,
        current_level=KnowledgeLevel.EXPERIMENTAL,
        target_level=KnowledgeLevel.OBSERVED,
        reason="≥ 3 casos confirmados, sem contradição",
    )


def _check_to_confirmed(
    ku: KnowledgeUnit,
    confirmed_source_count: int,
    has_human_validation: bool,
    has_open_contradictions: bool,
    has_specialist_review: bool,
) -> PromotionResult:
    """observed → confirmed: ≥ 10 casos confirmados, validação humana, sem contradição."""
    if confirmed_source_count < 10:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.OBSERVED,
            target_level=KnowledgeLevel.CONFIRMED,
            reason=f"Necessário ≥ 10 casos confirmados. Atual: {confirmed_source_count}",
        )
    if not has_human_validation:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.OBSERVED,
            target_level=KnowledgeLevel.CONFIRMED,
            reason="Validação humana explícita é obrigatória",
        )
    if has_open_contradictions:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.OBSERVED,
            target_level=KnowledgeLevel.CONFIRMED,
            reason="Contradição aberta impede promoção",
        )
    return PromotionResult(
        allowed=True,
        current_level=KnowledgeLevel.OBSERVED,
        target_level=KnowledgeLevel.CONFIRMED,
        reason="≥ 10 casos confirmados, validação humana, sem contradição",
    )


def _check_to_consolidated(
    ku: KnowledgeUnit,
    confirmed_source_count: int,
    has_human_validation: bool,
    has_open_contradictions: bool,
    has_specialist_review: bool,
) -> PromotionResult:
    """confirmed → consolidated: ≥ 6 meses de uso, sem contradição, revisão especialista."""
    if ku.created_at is None:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.CONFIRMED,
            target_level=KnowledgeLevel.CONSOLIDATED,
            reason="KU sem data de criação",
        )
    age_months = (utcnow() - ku.created_at).days / 30.0
    if age_months < 6:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.CONFIRMED,
            target_level=KnowledgeLevel.CONSOLIDATED,
            reason=f"Necessário ≥ 6 meses de uso. Idade atual: {age_months:.1f} meses",
        )
    if has_open_contradictions:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.CONFIRMED,
            target_level=KnowledgeLevel.CONSOLIDATED,
            reason="Contradição aberta impede promoção",
        )
    if not has_specialist_review:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.CONFIRMED,
            target_level=KnowledgeLevel.CONSOLIDATED,
            reason="Revisão de especialista é obrigatória",
        )
    return PromotionResult(
        allowed=True,
        current_level=KnowledgeLevel.CONFIRMED,
        target_level=KnowledgeLevel.CONSOLIDATED,
        reason="≥ 6 meses de uso, revisão especialista, sem contradição",
    )


# ── Rebaixamento ─────────────────────────────────────────────────────────

def check_demotion(
    ku: KnowledgeUnit,
    *,
    has_open_contradictions: bool = False,
    has_new_refutation: bool = False,
) -> PromotionResult:
    """Verifica se uma KU deve ser rebaixada.

    Rebaixamento ocorre quando:
    - Nova contradição é registrada (has_new_refutation = True)
    - KU tem contradições abertas e está acima de experimental
    """
    if ku.knowledge_level == KnowledgeLevel.EXPERIMENTAL:
        return PromotionResult(
            allowed=False,
            current_level=KnowledgeLevel.EXPERIMENTAL,
            reason="Nível experimental não pode ser rebaixado",
        )

    if has_new_refutation or has_open_contradictions:
        level_order = [
            KnowledgeLevel.EXPERIMENTAL,
            KnowledgeLevel.OBSERVED,
            KnowledgeLevel.CONFIRMED,
            KnowledgeLevel.CONSOLIDATED,
        ]
        current_idx = level_order.index(ku.knowledge_level)
        if current_idx > 0:
            new_level = level_order[current_idx - 1]
            return PromotionResult(
                allowed=True,
                current_level=ku.knowledge_level,
                target_level=new_level,
                reason=f"Rebaixado para {new_level.value} devido a contradição",
            )

    return PromotionResult(
        allowed=False,
        current_level=ku.knowledge_level,
        reason="Sem condição de rebaixamento",
    )
