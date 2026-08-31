"""Detector automático de contradições — COUS v3.0.

Detecta quando um novo CasoConfirmado contradiz uma KnowledgeUnit existente,
baseado em regras de inferência e thresholds de confiança.

Classificação (Documento V, Seção V.5):
- Exceção: caso isolado que não segue o padrão
- Especialização: padrão válido em subconjunto específico
- Refutação: padrão não se sustenta empiricamente
- Substituição: novo padrão mais preciso disponível
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ContradictionClass(StrEnum):
    EXCEPTION = "excecao"
    SPECIALIZATION = "especializacao"
    REFUTATION = "refutacao"
    REPLACEMENT = "substituicao"


@dataclass(frozen=True)
class ContradictionDetection:
    """Resultado da detecção de contradição."""

    detected: bool
    classification: ContradictionClass | None = None
    knowledge_unit_id: UUID | None = None
    contradicting_case_id: UUID | None = None
    confidence_drop: float = 0.0
    description: str = ""
    action: str = ""


class ContradictionDetector:
    """Detector de contradições entre novos casos e KnowledgeUnits existentes.

    Analisa se um novo CasoConfirmado (com suas hipóteses, evidências e confiança)
    contradiz alguma KnowledgeUnit existente no mesmo domínio.
    """

    def __init__(
        self,
        confidence_threshold: float = 0.20,
        min_confidence_drop: float = 0.15,
    ) -> None:
        self.confidence_threshold = confidence_threshold
        self.min_confidence_drop = min_confidence_drop

    def detect(
        self,
        new_case: dict[str, Any],
        existing_kus: list[dict[str, Any]],
    ) -> list[ContradictionDetection]:
        """Detecta contradições entre um novo caso e KUs existentes.

        Args:
            new_case: dados do novo CasoConfirmado
                - id: UUID
                - domain_id: UUID
                - hypotheses: lista de hipóteses com confidence e description
                - evidences: lista de evidências
            existing_kus: KnowledgeUnits existentes no mesmo domínio
                - id, title, statement, knowledge_level, confidence, domain_id

        Returns:
            Lista de contradições detectadas, ordenadas por impacto.
        """
        detections: list[ContradictionDetection] = []

        case_hypotheses = new_case.get("hypotheses", [])
        if not case_hypotheses:
            return detections

        for ku in existing_kus:
            ku_confidence = float(ku.get("confidence", 0))
            ku_level = ku.get("knowledge_level", "experimental")

            # KUs experimentais ou observadas são mais suscetíveis
            for hyp in case_hypotheses:
                hyp_confidence = float(hyp.get("confidence", 0))
                hyp_desc = str(hyp.get("description", ""))

                # Verificar se a hipótese contradiz semanticamente a KU
                # (simplificado: comparação de confidence + palavras-chave)
                if self._is_contradictory(hyp_desc, str(ku.get("statement", ""))):
                    confidence_drop = ku_confidence - hyp_confidence
                    # Se a hipótese é mais confiável que a KU, é uma substituição
                    hyp_is_better = hyp_confidence > ku_confidence

                    detection = self._classify(
                        ku=ku,
                        confidence_drop=confidence_drop,
                        hyp_confidence=hyp_confidence,
                        hyp_is_better=hyp_is_better,
                        case_id=new_case.get("id"),
                        hyp_description=hyp_desc,
                    )

                    if detection.detected:
                        detections.append(detection)

        # Ordenar por queda de confiança (maior impacto primeiro)
        detections.sort(key=lambda d: d.confidence_drop, reverse=True)
        return detections

    def _is_contradictory(self, text_a: str, text_b: str) -> bool:
        """Verificação simplificada de contradição semântica.

        Em produção, usar embeddings + similaridade + LLM para classificação.
        Aqui usamos palavras-chave de negação/oposição como heurística.
        """
        negation_words = [
            "não", "nunca", "jamais", "impossível", "incompatível",
            "contrário", "oposto", "refuta", "nega", "falso",
            "incorreto", "inadequado", "improvável",
        ]

        a_lower = text_a.lower()
        b_lower = text_b.lower()

        # Heurística: uma contém negação e compartilha termos com a outra
        has_negation_a = any(w in a_lower for w in negation_words)
        has_negation_b = any(w in b_lower for w in negation_words)

        if has_negation_a or has_negation_b:
            # Verificar sobreposição de termos significativos
            a_terms = set(a_lower.split()) - {"de", "da", "do", "em", "no", "na", "e", "ou", "que", "um", "uma", "o", "a", "os", "as"}
            b_terms = set(b_lower.split()) - {"de", "da", "do", "em", "no", "na", "e", "ou", "que", "um", "uma", "o", "a", "os", "as"}
            overlap = a_terms & b_terms
            return len(overlap) >= 3  # Pelo menos 3 termos em comum

        return False

    def _classify(
        self,
        ku: dict[str, Any],
        confidence_drop: float,
        hyp_confidence: float,
        hyp_is_better: bool,
        case_id: UUID | None,
        hyp_description: str,
    ) -> ContradictionDetection:
        """Classifica o tipo de contradição detectada."""
        ku_level = ku.get("knowledge_level", "experimental")
        ku_confidence = float(ku.get("confidence", 0))
        abs_drop = abs(confidence_drop)

        # Substituição: hipótese supera KU com margem significativa
        if hyp_is_better and abs_drop > self.min_confidence_drop:
            return ContradictionDetection(
                detected=True,
                classification=ContradictionClass.REPLACEMENT,
                knowledge_unit_id=ku.get("id"),
                contradicting_case_id=case_id,
                confidence_drop=abs_drop,
                description=f"Nova hipótese supera KU existente (ΔC={abs_drop:.2f})",
                action="Criar nova KU via relação substitui; depreciar KU antiga",
            )

        # Refutação: hipótese contradiz KU confirmada/consolidada
        # Se a hipótese tem alta confiança (>0.60), é uma refutação mesmo com delta pequeno
        if ku_level in ("confirmed", "consolidated") and (
            confidence_drop > self.min_confidence_drop or hyp_confidence > 0.60
        ):
            return ContradictionDetection(
                detected=True,
                classification=ContradictionClass.REFUTATION,
                knowledge_unit_id=ku.get("id"),
                contradicting_case_id=case_id,
                confidence_drop=confidence_drop,
                description=f"Hipótese contradiz KU {ku.get('title', '?')} (nível {ku_level})",
                action="Rebaixar nível da KU; registrar relação refuta",
            )

        # Especialização: queda moderada, KU é de nível inferior
        if ku_level in ("experimental", "observed") and confidence_drop > 0.10:
            return ContradictionDetection(
                detected=True,
                classification=ContradictionClass.SPECIALIZATION,
                knowledge_unit_id=ku.get("id"),
                contradicting_case_id=case_id,
                confidence_drop=confidence_drop,
                description=f"Caso pode especializar KU existente",
                action="Criar KU especializada via relação especializa",
            )

        # Exceção: caso isolado
        if confidence_drop > 0.05:
            return ContradictionDetection(
                detected=True,
                classification=ContradictionClass.EXCEPTION,
                knowledge_unit_id=ku.get("id"),
                contradicting_case_id=case_id,
                confidence_drop=confidence_drop,
                description="Caso isolado — não altera KU",
                action="Registrar como exceção; não alterar KU",
            )

        return ContradictionDetection(detected=False)
