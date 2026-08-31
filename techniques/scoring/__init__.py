"""Scores compostos para RAG — COUS v3.0 (Documento I, Seção I.8).

Implementa as três dimensões além da semântica:
- S_documental: autoridade do documento × relevância do tipo
- S_histórico: log(1 + n_usos) / log(1 + n_max), saturação logarítmica
- S_causal: compatibilidade com cadeia causal ativa (1.0 | 0.5 | 0.0)
"""

from __future__ import annotations

import math
from typing import Any

from runtime.protocols import Document


# ── Score Documental ─────────────────────────────────────────────────────

AUTHORITY_WEIGHTS: dict[str, float] = {
    "alta": 1.0,
    "média": 0.6,
    "baixa": 0.3,
}

TYPE_RELEVANCE: dict[str, float] = {
    "datasheet_motor": 1.0,
    "datasheet_sensor": 0.9,
    "service_order": 0.8,
    "manual": 0.7,
    "artigo": 0.6,
    "livro": 0.5,
    "generico": 0.3,
}


def compute_document_score(doc: Document) -> float:
    """S_documental = autoridade(documento) × relevância(tipo).

    Lê `authority` e `document_type` do metadata do documento.
    Valores padrão: authority='baixa', document_type='generico'.
    """
    authority = doc.metadata.get("authority", "baixa")
    doc_type = doc.metadata.get("document_type", "generico")

    auth_score = AUTHORITY_WEIGHTS.get(str(authority).lower(), 0.3)
    type_score = TYPE_RELEVANCE.get(str(doc_type).lower(), 0.3)

    return auth_score * type_score


# ── Score Histórico ──────────────────────────────────────────────────────

def compute_history_score(doc: Document, n_max: int = 100) -> float:
    """S_histórico = log(1 + n_usos) / log(1 + n_max).

    Lê `usage_count_confirmed` do metadata do documento.
    Satura logaritmicamente — crescimento desacelera com uso elevado.
    """
    n = int(doc.metadata.get("usage_count_confirmed", 0))
    if n <= 0:
        return 0.0
    return math.log(1 + n) / math.log(1 + n_max)


# ── Score Causal ─────────────────────────────────────────────────────────

def compute_causal_score(
    doc: Document,
    active_causal_chain_id: str | None = None,
    related_chain_ids: set[str] | None = None,
) -> float:
    """S_causal = compatibilidade com cadeia causal ativa.

    1.0 → chunk pertence à cadeia causal ativa
    0.5 → chunk pertence a cadeia relacionada
    0.0 → sem relação causal identificada

    Lê `causal_chain_id` do metadata do documento.
    """
    if active_causal_chain_id is None:
        return 0.0

    chain_id = doc.metadata.get("causal_chain_id")
    if chain_id is None:
        return 0.0

    chain_id = str(chain_id)
    if chain_id == active_causal_chain_id:
        return 1.0

    if related_chain_ids and chain_id in related_chain_ids:
        return 0.5

    return 0.0


# ── Score Composto ───────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "semantic": 0.40,
    "document": 0.25,
    "historical": 0.25,
    "causal": 0.10,
}


def compute_composite_score(
    doc: Document,
    semantic_score: float,
    *,
    weights: dict[str, float] | None = None,
    active_causal_chain_id: str | None = None,
    related_chain_ids: set[str] | None = None,
    history_n_max: int = 100,
) -> float:
    """S_final = w_sem·S_sem + w_doc·S_doc + w_hist·S_hist + w_caus·S_caus

    Retorna score entre 0 e 1.
    """
    w = weights or DEFAULT_WEIGHTS

    s_doc = compute_document_score(doc)
    s_hist = compute_history_score(doc, n_max=history_n_max)
    s_caus = compute_causal_score(
        doc,
        active_causal_chain_id=active_causal_chain_id,
        related_chain_ids=related_chain_ids,
    )

    composite = (
        w.get("semantic", 0.40) * semantic_score
        + w.get("document", 0.25) * s_doc
        + w.get("historical", 0.25) * s_hist
        + w.get("causal", 0.10) * s_caus
    )

    return max(0.0, min(composite, 1.0))


# ── Regra de Diversidade ─────────────────────────────────────────────────

def apply_diversity_rule(
    docs: list[Document],
    max_per_document: int = 2,
    exceptions: list[dict[str, Any]] | None = None,
) -> list[Document]:
    """Garante no máximo `max_per_document` chunks do mesmo documento.

    Exceções: documentos com S_documental >= threshold especificado
    (ex: datasheet do fabricante com authority='alta').

    Preserva a ordem de score (já ordenados).
    """
    exceptions = exceptions or []
    doc_counts: dict[str, int] = {}
    result: list[Document] = []

    for doc in docs:
        doc_id = doc.metadata.get("document_id", doc.metadata.get("source_uri", ""))
        if not doc_id:
            result.append(doc)
            continue

        # Verificar exceções
        is_exception = False
        for exc in exceptions:
            if exc.get("document_score_gte") is not None:
                s_doc = compute_document_score(doc)
                if s_doc >= exc["document_score_gte"]:
                    is_exception = True
                    break

        if is_exception:
            result.append(doc)
            continue

        count = doc_counts.get(doc_id, 0)
        if count < max_per_document:
            doc_counts[doc_id] = count + 1
            result.append(doc)

    return result
