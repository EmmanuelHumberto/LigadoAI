"""Endpoints de Cadeias Causais — COUS v3.1.

POST /v3/causal-chains/candidate — gera cadeia candidata a partir de OS similares
GET  /v3/causal-chains           — lista cadeias existentes
"""

from __future__ import annotations

from collections.abc import Callable
from secrets import compare_digest
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel


# ── Schemas (nível do módulo para FastAPI resolver) ────────────────────

class DeviationInput(BaseModel):
    bemf_error_permille: float | None = None
    equivalent_resistance_error_permille: float | None = None
    torque_error_permille: float | None = None
    motor_current_ma: float | None = None
    rpm_hall: float | None = None
    bus_voltage_mv: float | None = None
    efficiency_permille: float | None = None
    course_mm: float | None = None
    rpm_cross_error_permille: float | None = None
    torque_load_permille: float | None = None


class CandidateRequest(BaseModel):
    domain_id: UUID
    deviations: DeviationInput
    max_candidates: int = 3


class CandidateResponse(BaseModel):
    ku_id: UUID
    title: str
    statement: str
    condition_expression: str
    source_os: str
    confidence: float
    knowledge_level: str = "experimental"


# ── Router factory ─────────────────────────────────────────────────────

def create_causal_chains_router(
    repository,
    auth_token: str | None = None,
) -> APIRouter:
    def _bearer(expected: str) -> Callable:
        async def verify(authorization: str = Header(...)) -> None:
            if not authorization.startswith("Bearer "):
                raise HTTPException(status_code=401)
            if not compare_digest(authorization.removeprefix("Bearer "), expected):
                raise HTTPException(status_code=401)
        return verify

    deps = [Depends(_bearer(auth_token))] if auth_token else []
    router = APIRouter(prefix="/v3/causal-chains", tags=["causal-chains"], dependencies=deps)

    @router.post("/candidate", response_model=list[CandidateResponse])
    async def generate_candidates(payload: CandidateRequest) -> list[CandidateResponse]:
        deviations_dict = payload.deviations.model_dump(exclude_none=True)
        if not deviations_dict:
            raise HTTPException(status_code=400, detail="Nenhum desvio informado")

        pool = await repository.get_pool()

        # 1. Buscar documentos do tipo service_order
        async with pool.acquire() as conn:
            os_rows = await conn.fetch(
                """
                SELECT kd.id, kd.title, kd.source_uri, kc.text as chunk_text
                FROM knowledge_documents kd
                JOIN knowledge_chunks kc ON kc.document_id = kd.id
                WHERE kd.document_type = 'service_order'
                ORDER BY kc.usage_count_confirmed DESC, kd.created_at DESC
                LIMIT 30
                """
            )

        if not os_rows:
            async with pool.acquire() as conn:
                os_rows = await conn.fetch(
                    """
                    SELECT kd.id, kd.title, kd.source_uri, kc.text as chunk_text
                    FROM knowledge_documents kd
                    JOIN knowledge_chunks kc ON kc.document_id = kd.id
                    ORDER BY kc.usage_count_confirmed DESC
                    LIMIT 10
                    """
                )

        if not os_rows:
            raise HTTPException(status_code=404, detail="Nenhum documento indexado")

        candidates = []
        seen_docs = set()

        for row in os_rows:
            doc_id = row["id"]
            if doc_id in seen_docs:
                continue
            seen_docs.add(doc_id)

            chunk_text = (row["chunk_text"] or "").lower()
            title = (row["title"] or row["source_uri"] or "")

            condition = _extract_condition_from_text(chunk_text, deviations_dict)
            cause = _extract_cause_from_text(chunk_text)
            if not cause:
                continue

            ku_id = uuid4()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO knowledge_units (id, domain_id, title, statement, knowledge_level, confidence)
                       VALUES ($1, $2, $3, $4, 'experimental', $5) ON CONFLICT (id) DO NOTHING""",
                    ku_id, payload.domain_id, f"[OS] {cause[:80]}",
                    f"Extraído da OS: {title}. {cause}", 0.65,
                )

            if condition:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """INSERT INTO causal_chains (id, domain_id, title, condition_expression, probable_cause, expected_consequence, confidence)
                           VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING""",
                        uuid4(), payload.domain_id, f"[Candidata] {cause[:80]}",
                        condition, cause, f"OS: {title}", 0.65,
                    )

            candidates.append(CandidateResponse(
                ku_id=ku_id, title=f"[OS] {cause[:80]}",
                statement=f"Extraído da OS: {title}. {cause}",
                condition_expression=condition or "não extraída",
                source_os=title, confidence=0.65,
            ))

            if len(candidates) >= payload.max_candidates:
                break

        return candidates

    @router.get("")
    async def list_chains(domain_id: UUID | None = Query(None)) -> list[dict]:
        pool = await repository.get_pool()
        async with pool.acquire() as conn:
            query = "SELECT * FROM causal_chains"
            params = []
            if domain_id:
                query += " WHERE domain_id = $1"
                params.append(domain_id)
            query += " ORDER BY confidence DESC"
            rows = await conn.fetch(query, *params)
            return [dict(r) for r in rows]

    return router


# ── Heurísticas de extração a partir do texto da OS ─────────────────────

def _extract_condition_from_text(text: str, deviations: dict) -> str | None:
    text_lower = text.lower()
    conditions = []

    if "corrente" in text_lower:
        if "superior a 200" in text_lower or "acima de 200" in text_lower:
            conditions.append("motor_current_ma > 200")
        elif "elevada" in text_lower and "5a" in text_lower:
            conditions.append("motor_current_ma > 500")
        elif "proteção" in text_lower:
            conditions.append("motor_current_ma > 200")

    if "mau contato" in text_lower or "eletrodo" in text_lower:
        if "afundado" in text_lower or "danificado" in text_lower:
            conditions.append("bus_voltage_mv < 4000")

    if "motor parou" in text_lower or "motor não" in text_lower:
        if "quebrado" in text_lower or "eixo" in text_lower:
            conditions.append("rpm_hall < 100")
        elif "escovas" in text_lower:
            conditions.append("motor_current_ma > 180")

    if "desgaste" in text_lower:
        if "escovas" in text_lower or "comutador" in text_lower:
            conditions.append("bemf_error_permille < -80")
        if "came" in text_lower:
            conditions.append("course_mm > 4.0")

    if "consumo" in text_lower and ("elevado" in text_lower or "excessivo" in text_lower):
        conditions.append("efficiency_permille < 700")

    if "vibração" in text_lower or "ruído" in text_lower:
        conditions.append("rpm_cross_error_permille > 30")

    return " AND ".join(conditions) if conditions else None


def _extract_cause_from_text(text: str) -> str | None:
    text_lower = text.lower()
    patterns = [
        ("curto", "Curto-circuito interno"),
        ("eixo do motor está quebrado", "Eixo do motor quebrado"),
        ("escovas desgastadas", "Desgaste das escovas do motor"),
        ("escovas do motor", "Desgaste das escovas do motor"),
        ("ausência de lubrificação", "Ausência de lubrificação interna"),
        ("sem lubrificação", "Ausência de lubrificação interna"),
        ("falta de lubrificação", "Ausência de lubrificação interna"),
        ("eletrodo", "Mau contato nos eletrodos"),
        ("mau contato", "Mau contato elétrico"),
        ("oxidação", "Oxidação de componentes internos"),
        ("contaminação", "Contaminação por tinta e resíduos"),
        ("acúmulo de tinta", "Contaminação por tinta e resíduos"),
        ("sobrecarga", "Sobrecarga elétrica do motor"),
        ("proteção da bateria", "Sobrecarga elétrica — proteção da bateria"),
        ("bateria desliga", "Sobrecarga elétrica — proteção da bateria"),
        ("fonte armando proteção", "Curto-circuito ou sobrecarga severa"),
        ("desgaste do came", "Desgaste mecânico do came"),
        ("came não se encontrava", "Came ausente ou não instalado"),
        ("resistência na regulagem", "Falta de lubrificação no grip"),
        ("tinta endurecida", "Contaminação por tinta endurecida"),
    ]
    for keyword, cause in patterns:
        if keyword in text_lower:
            return cause
    return None
