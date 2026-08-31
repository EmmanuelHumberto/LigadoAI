"""Endpoints de diagnóstico local — COUS v3.1 (motor offline, sem LLM).

POST /v3/diagnosis/local
    Recebe deviations e retorna diagnóstico baseado em causal_chains + Knowledge Graph.
    Não depende de LLM externo — usa apenas o banco PostgreSQL.
"""

from __future__ import annotations

import re
import operator as op
from json import loads as json_loads
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from knowledge.infrastructure.postgres.cous_repository import CousKnowledgeRepository

# ── Schemas ──────────────────────────────────────────────────────────────


class LocalDiagnosisRequest(BaseModel):
    deviations: dict[str, float]  # ex: {"bemf_error_permille": -180, ...}
    domain_id: str = "00000000-0000-0000-0000-000000000001"
    max_candidates: int = 5


class CausalChainResult(BaseModel):
    title: str
    confidence: float
    probable_cause: str
    expected_consequence: str
    condition_expression: str


class DiagnosisHypothesis(BaseModel):
    description: str
    confidence: float
    is_primary: bool
    source: str  # "causal_chain" | "knowledge_unit"


class LocalDiagnosisResponse(BaseModel):
    deviations_analyzed: int
    matched_chains: list[CausalChainResult]
    hypotheses: list[DiagnosisHypothesis]
    narrative: str


# ── Cadeias causais padrão (fallback offline) ────────────────────────────

_DEFAULT_CAUSAL_CHAINS = [
    {"title": "Curto-circuito ou falha catastrófica",
     "condition_expression": "motor_current_ma > 500",
     "probable_cause": "Curto-circuito interno no motor ou nos terminais.",
     "expected_consequence": "Fumaça, aquecimento extremo, danos irreversíveis.",
     "confidence": 0.95},
    {"title": "Falha do eixo do motor",
     "condition_expression": "motor_current_ma < 5 AND rpm_hall < 100",
     "probable_cause": "Eixo do motor quebrado ou desacoplado.",
     "expected_consequence": "Motor gira em falso, came não se move.",
     "confidence": 0.93},
    {"title": "Mau contato elétrico",
     "condition_expression": "bus_voltage_mv < 4000 AND motor_current_ma < 10",
     "probable_cause": "Eletrodo afundado ou danificado impede contato com bateria.",
     "expected_consequence": "Máquina não liga ou funciona intermitentemente.",
     "confidence": 0.92},
    {"title": "Sobrecarga elétrica por falta de lubrificação",
     "condition_expression": "motor_current_ma > 200",
     "probable_cause": "Atrito excessivo por falta de lubrificação interna.",
     "expected_consequence": "Aquecimento, desligamento da bateria, desgaste acelerado.",
     "confidence": 0.90},
    {"title": "Desgaste avançado das escovas",
     "condition_expression": "motor_current_ma > 180 AND bemf_error_permille < -80",
     "probable_cause": "Escovas severamente desgastadas ou fraturadas.",
     "expected_consequence": "Parada iminente do motor, oxidação progressiva.",
     "confidence": 0.88},
    {"title": "Desgaste do conjunto rotativo (detectado por desvios)",
     "condition_expression": "bemf_error_permille < -150 AND equivalent_resistance_error_permille > 20",
     "probable_cause": "Queda do Back EMF combinada com aumento da resistência equivalente.",
     "expected_consequence": "Queda gradual de torque e eficiência.",
     "confidence": 0.85},
    {"title": "Eficiência eletromecânica degradada",
     "condition_expression": "efficiency_permille < 700",
     "probable_cause": "Múltiplas causas: acúmulo de tinta, falta de lubrificação, desgaste natural.",
     "expected_consequence": "Consumo elevado, autonomia reduzida da bateria.",
     "confidence": 0.85},
    {"title": "Desgaste do came",
     "condition_expression": "rpm_cross_error_permille > 30 OR course_mm > 4.5",
     "probable_cause": "Desgaste do polímero do came por atrito com o pistão.",
     "expected_consequence": "Folga progressiva, vibração crescente.",
     "confidence": 0.82},
    {"title": "Resistência de contato elevada (oxidação)",
     "condition_expression": "equivalent_resistance_error_permille > 50 AND motor_current_ma > 150",
     "probable_cause": "Oxidação nos terminais combinada com resíduos de tinta.",
     "expected_consequence": "Aquecimento localizado, queda de tensão.",
     "confidence": 0.78},
]


# ── Motor de avaliação inline ────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""(-?\d+\.?\d*)|(>=|<=|!=|==|>|<)|(AND|OR)|([a-z_][a-z0-9_]*)""",
    re.IGNORECASE,
)
_OP_MAP = {">": op.gt, "<": op.lt, ">=": op.ge, "<=": op.le, "==": op.eq, "!=": op.ne}


def _evaluate_condition(expression: str, fields: dict[str, float]) -> bool:
    expr_str = expression.strip()
    if not expr_str:
        return False

    # Parentheses
    while expr_str.startswith("(") and expr_str.endswith(")"):
        depth = 0
        balanced = True
        for i, ch in enumerate(expr_str):
            if ch == "(": depth += 1
            elif ch == ")": depth -= 1
            if depth == 0 and i < len(expr_str) - 1: balanced = False; break
        if balanced: expr_str = expr_str[1:-1].strip()
        else: break

    # OR
    depth = 0
    for i, ch in enumerate(expr_str):
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        elif depth == 0 and expr_str[i:].upper().startswith("OR"):
            return _evaluate_condition(expr_str[:i].strip(), fields) or \
                   _evaluate_condition(expr_str[i+2:].strip(), fields)

    # AND
    depth = 0
    for i, ch in enumerate(expr_str):
        if ch == "(": depth += 1
        elif ch == ")": depth -= 1
        elif depth == 0 and expr_str[i:].upper().startswith("AND"):
            return _evaluate_condition(expr_str[:i].strip(), fields) and \
                   _evaluate_condition(expr_str[i+3:].strip(), fields)

    # Comparison
    tokens = _TOKEN_RE.findall(expr_str)
    parts: list[str] = []
    for t in tokens:
        for p in t:
            if p: parts.append(p); break
    if len(parts) < 3: return False
    field_name = parts[0].lower()
    op_str = parts[1]
    try: value = float(parts[2])
    except ValueError: return False
    if field_name not in fields: return False
    func = _OP_MAP.get(op_str)
    if func is None: return False
    try: return func(fields[field_name], value)
    except Exception: return False


def _find_matching_chains(deviations: dict[str, float], chains: list[dict]) -> list[dict]:
    matches = []
    for chain in chains:
        cond = chain.get("condition_expression", "")
        try:
            if _evaluate_condition(cond, deviations):
                matches.append(chain)
        except Exception:
            pass
    matches.sort(key=lambda c: float(c.get("confidence", 0)), reverse=True)
    return matches


# ── Router ────────────────────────────────────────────────────────────────


def create_local_diagnosis_router(repository: CousKnowledgeRepository) -> APIRouter:
    router = APIRouter(prefix="/v3/diagnosis", tags=["diagnosis"])

    @router.post("/local", response_model=LocalDiagnosisResponse)
    async def local_diagnosis(payload: LocalDiagnosisRequest) -> LocalDiagnosisResponse:
        """Diagnóstico local: avalia deviations contra causal_chains e Knowledge Graph."""
        deviations = payload.deviations
        if not deviations:
            raise HTTPException(status_code=400, detail="deviations is required")

        # Buscar cadeias causais do banco
        chains = []
        try:
            async with repository._pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT title, condition_expression, probable_cause, "
                    "expected_consequence, confidence FROM causal_chains "
                    "WHERE domain_id = $1 ORDER BY confidence DESC",
                    payload.domain_id,
                )
                chains = [dict(r) for r in rows]
        except Exception:
            pass

        if not chains:
            chains = _DEFAULT_CAUSAL_CHAINS

        # Avaliar
        matches = _find_matching_chains(deviations, chains)
        max_candidates = max(1, min(payload.max_candidates, 10))

        # Construir hipóteses
        hypotheses: list[DiagnosisHypothesis] = []
        for i, m in enumerate(matches[:max_candidates]):
            hypotheses.append(DiagnosisHypothesis(
                description=m.get("probable_cause", ""),
                confidence=float(m.get("confidence", 0)),
                is_primary=(i == 0),
                source="causal_chain",
            ))

        # Buscar KUs relacionadas
        if matches:
            try:
                primary_cause = matches[0].get("probable_cause", "")
                async with repository._pool.acquire() as conn:
                    ku_rows = await conn.fetch(
                        "SELECT statement, confidence FROM knowledge_units "
                        "WHERE knowledge_level IN ('confirmed','consolidated') "
                        "ORDER BY confidence DESC LIMIT 5"
                    )
                    for row in ku_rows:
                        hypotheses.append(DiagnosisHypothesis(
                            description=row["statement"],
                            confidence=float(row["confidence"]),
                            is_primary=False,
                            source="knowledge_unit",
                        ))
            except Exception:
                pass

        # Narrativa
        narrative = "Nenhuma cadeia causal ativada. A máquina parece operar dentro dos parâmetros normais."
        if matches:
            primary = matches[0]
            cause = primary.get("probable_cause", "")
            consequence = primary.get("expected_consequence", "")
            narrative = f"Hipótese principal (C={primary.get('confidence',0):.0%}): {cause}"
            if consequence:
                narrative += f" Se ignorado: {consequence}"

        return LocalDiagnosisResponse(
            deviations_analyzed=len(deviations),
            matched_chains=[
                CausalChainResult(
                    title=m.get("title", ""),
                    confidence=float(m.get("confidence", 0)),
                    probable_cause=m.get("probable_cause", ""),
                    expected_consequence=m.get("expected_consequence", ""),
                    condition_expression=m.get("condition_expression", ""),
                )
                for m in matches[:max_candidates]
            ],
            hypotheses=hypotheses,
            narrative=narrative,
        )

    return router
