"""reranking technique — re-score retrieved docs with a cross-encoder.

``cross_encoder`` variant — P1.10. Loads a sentence-transformers
CrossEncoder once (process-singleton, cached after first build) and
scores ``(request, doc.content)`` pairs. Docs below
``score_threshold`` are dropped; the rest are sorted descending and
truncated to ``top_n``.

If the cross-encoder model can't load (offline, dep missing, network
error), the stage falls back to the previous stub behavior: keep the
order from retrieve, top_n only. Same shape, same contract, no crash.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Optional

from runtime.protocols import BaseTechnique, Context, Stage


logger = logging.getLogger("techniques.reranking")

_DEFAULT_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class _CrossEncoderPool:
    """Process-wide cache for the CrossEncoder. ~30MB model; load once."""

    _model: Optional[Any] = None
    _model_name: Optional[str] = None
    _lock = threading.Lock()
    _load_failed: bool = False

    @classmethod
    def get(cls, model_name: str) -> Optional[Any]:
        if cls._load_failed:
            return None
        if cls._model is not None and cls._model_name == model_name:
            return cls._model
        with cls._lock:
            if cls._model is not None and cls._model_name == model_name:
                return cls._model
            try:
                from sentence_transformers import CrossEncoder
                logger.info("loading CrossEncoder %s (first call, ~30MB)", model_name)
                cls._model = CrossEncoder(model_name)
                cls._model_name = model_name
                return cls._model
            except Exception as e:
                logger.warning("CrossEncoder load failed (%s) — falling back to stub", e)
                cls._load_failed = True
                return None

    @classmethod
    def reset(cls) -> None:  # for tests
        with cls._lock:
            cls._model = None
            cls._model_name = None
            cls._load_failed = False


class _CrossEncoderReranker:
    def __init__(self, knobs: dict[str, Any]) -> None:
        self.top_n: int = int(knobs.get("top_n", 4))
        self.score_threshold: float = float(knobs.get("score_threshold", 0.0))
        self.model_name: str = str(knobs.get("model", _DEFAULT_MODEL))
        if self.model_name in {"bge-reranker-v2", "default"}:
            self.model_name = _DEFAULT_MODEL

    def execute(self, context: Context) -> Context:
        docs = context.documents
        if not docs:
            return context

        model = _CrossEncoderPool.get(self.model_name)
        if model is None:
            return self._stub_fallback(context)

        try:
            pairs = [(context.request, d.content) for d in docs]
            scores = model.predict(pairs)
        except Exception as e:
            logger.warning("cross-encoder predict failed (%s) — stub fallback", e)
            return self._stub_fallback(context)

        scored = list(zip(docs, [float(s) for s in scores]))
        scored.sort(key=lambda x: x[1], reverse=True)

        kept = []
        for d, s in scored:
            if s < self.score_threshold:
                continue
            d.score = s
            d.metadata["reranked"] = True
            d.metadata["reranker_variant"] = "cross_encoder"
            d.metadata["reranker_model"] = self.model_name
            kept.append(d)
            if len(kept) >= self.top_n:
                break

        if not kept and docs:
            logger.info(
                "cross-encoder filtered all %d docs — keeping top_n retrieve hits",
                len(docs),
            )
            return self._stub_fallback(context)

        context.documents = kept
        return context

    def _stub_fallback(self, context: Context) -> Context:
        kept = [d for d in context.documents if d.score >= self.score_threshold][: self.top_n]
        for d in kept:
            d.metadata["reranked"] = True
            d.metadata["reranker_variant"] = "cross_encoder"
            d.metadata["reranker_fallback"] = "stub"
        context.documents = kept
        return context


class _CompositeReranker:
    """COUS v3.0 — Composite scoring reranker.

    Combina 4 dimensões de score:
      S_final = w_sem·S_sem + w_doc·S_doc + w_hist·S_hist + w_caus·S_caus

    Configuração (knobs):
      - weights: dict com pesos por dimensão (default: COUS v3)
      - top_n: máximo de documentos no resultado final (default: 5)
      - diversity: dict com max_per_document e exceptions
    """

    def __init__(self, knobs: dict[str, Any]) -> None:
        from techniques.scoring import DEFAULT_WEIGHTS, compute_composite_score, apply_diversity_rule

        self.weights: dict[str, float] = dict(DEFAULT_WEIGHTS)
        user_weights = knobs.get("weights", {})
        if isinstance(user_weights, dict):
            self.weights.update({k: float(v) for k, v in user_weights.items()})

        self.top_n: int = int(knobs.get("top_n", 5))
        self.diversity_config: dict[str, Any] = dict(knobs.get("diversity", {}))
        self.max_per_document: int = int(self.diversity_config.get("max_per_document", 2))
        self.exceptions: list[dict[str, Any]] = list(
            self.diversity_config.get("exceptions", [])
        )

    def execute(self, context: Context) -> Context:
        from techniques.scoring import compute_composite_score, apply_diversity_rule

        docs = context.documents
        if not docs:
            return context

        # Acessar cadeia causal ativa do state (se disponível)
        causal_state = context.state.get("causal", {})
        active_chain_id = causal_state.get("active_causal_chain_id")
        related_ids = set(causal_state.get("related_chain_ids", []))

        # Calcular score composto para cada documento
        for doc in docs:
            composite = compute_composite_score(
                doc,
                doc.score,  # S_semântico (do retrieve ou cross-encoder)
                weights=self.weights,
                active_causal_chain_id=str(active_chain_id) if active_chain_id else None,
                related_chain_ids=related_ids,
            )
            doc.score = composite
            doc.metadata["reranked"] = True
            doc.metadata["reranker_variant"] = "composite"
            doc.metadata["composite_breakdown"] = {
                "semantic": doc.metadata.get("_semantic_score", doc.score),
                "document": doc.metadata.get("_document_score", 0.0),
                "historical": doc.metadata.get("_history_score", 0.0),
                "causal": doc.metadata.get("_causal_score", 0.0),
            }

        # Ordenar por score composto
        docs.sort(key=lambda d: d.score, reverse=True)

        # Aplicar regra de diversidade
        docs = apply_diversity_rule(
            docs,
            max_per_document=self.max_per_document,
            exceptions=self.exceptions,
        )

        # Truncar para top_n
        context.documents = docs[: self.top_n]
        return context


class RerankingTechnique(BaseTechnique):
    name = "reranking"
    variants = ("cross_encoder", "composite")

    def compile(self, variant: str, knobs: dict[str, Any]) -> Stage:
        if variant not in self.variants:
            raise ValueError(
                f"reranking: unknown variant {variant!r}; expected one of {self.variants}"
            )
        if variant == "composite":
            return _CompositeReranker(knobs)
        return _CrossEncoderReranker(knobs)
