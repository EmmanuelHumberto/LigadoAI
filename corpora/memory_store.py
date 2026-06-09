"""CorpusMemoryStore — in-memory FAISS singleton for HTTP-driven reloads.

Instead of reading from disk, this store receives chunks + vectors via
``reload()``, typically called from ``POST /corpus/reload``. Uses
``asyncio.Lock`` so a reload never races with a query.

Interface is identical to ``CorpusStore`` so ``_DenseRetriever`` can use
either without code changes beyond how it obtains the store instance.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Optional

import numpy as np

from corpora.store import CorpusHit

logger = logging.getLogger("corpora.memory_store")


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize rows in-place (or copy if needed)."""
    vec = vec.astype(np.float32, copy=False)
    norms = np.linalg.norm(vec, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return vec / norms


def _aplicar_filtro(
    hits: list[CorpusHit],
    filtro: dict[str, str],
) -> list[CorpusHit]:
    """Post-filter hits by metadata fields (case-insensitive).

    Each key in ``filtro`` must match the corresponding field in
    ``hit.metadata``.  A hit passes when ALL filter keys match.
    """
    resultado: list[CorpusHit] = []
    for hit in hits:
        passa = True
        for chave, valor_esperado in filtro.items():
            valor_real = hit.metadata.get(chave)
            if valor_real is None:
                passa = False
                break
            if str(valor_real).lower() != valor_esperado.lower():
                passa = False
                break
        if passa:
            resultado.append(hit)
    return resultado


def _query_terms(query_text: str) -> list[str]:
    """Extract relevant lexical terms from a user query."""
    terms = []
    for term in re.findall(r"[\w.-]+", query_text.lower()):
        if len(term) < 4:
            continue
        if term in {"entao", "então", "veja", "liste", "banco", "motor", "motores"}:
            continue
        terms.append(term)

    # Common typo observed in Portuguese requests.
    if "portscape" in terms and "portescap" not in terms:
        terms.append("portescap")
    return terms


def _lexical_score(row: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 0.0

    metadata = row.get("metadata", {})
    haystack = " ".join(
        str(part)
        for part in [
            row.get("text", ""),
            row.get("source", ""),
            metadata.get("fabricante", ""),
            metadata.get("modelo", ""),
            metadata.get("tipo", ""),
        ]
    ).lower()

    score = 0.0
    for term in terms:
        if term in haystack:
            score += 2.0
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            score += 1.0
    return score


class CorpusMemoryStore:
    """Singleton FAISS index held entirely in memory.

    Thread-safe via ``asyncio.Lock``: ``reload`` blocks ``query`` and
    vice-versa, so the retriever never sees a half-built index.

    ``query()`` is synchronous by design — it's called inside the
    pipeline executor which runs sequentially per request. For async
    safety the lock is class-level and ``reload()`` acquires it.
    """

    _instance: Optional[CorpusMemoryStore] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self) -> None:
        self._index: Any = None          # faiss.Index or None (numpy fallback)
        self._vectors: Optional[np.ndarray] = None
        self._manifest: list[dict[str, Any]] = []
        self._dim: int = 0

    # ---- singleton ----

    @classmethod
    def instance(cls) -> CorpusMemoryStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ---- public API (mirrors CorpusStore) ----

    @property
    def empty(self) -> bool:
        return len(self._manifest) == 0

    @property
    def size(self) -> int:
        return len(self._manifest)

    @property
    def dimension(self) -> int:
        return self._dim

    async def reload(
        self,
        chunks: list[dict[str, Any]],
        vectors: list[list[float]],
    ) -> dict[str, Any]:
        """Atomically replace the index with new chunks + vectors.

        ``chunks`` — list of manifest dicts, same shape as CorpusStore
        manifest rows: ``{id, text, source, chunk_index, n_chunks, metadata}``.

        ``vectors`` — list of ``float`` lists, one per chunk. All must
        have the same length.

        Returns ``{loaded: N, dimension: D}`` on success.
        """
        async with self._lock:
            if not chunks:
                self._index = None
                self._vectors = None
                self._manifest = []
                self._dim = 0
                logger.info("corpus reloaded: 0 chunks (cleared)")
                return {"loaded": 0, "dimension": 0}

            vecs = np.asarray(vectors, dtype=np.float32)
            if vecs.ndim != 2 or vecs.shape[0] != len(chunks):
                raise ValueError(
                    f"vectors shape {vecs.shape} doesn't match chunks count {len(chunks)}"
                )

            vecs = _normalize(vecs)
            dim = int(vecs.shape[1])

            # Build FAISS index
            try:
                import faiss

                idx = faiss.IndexFlatIP(dim)
                idx.add(vecs)
                self._index = idx
                self._vectors = None
            except Exception as e:
                logger.warning("faiss build failed (%s) — falling back to numpy", e)
                self._index = None
                self._vectors = vecs

            self._manifest = list(chunks)
            self._dim = dim
            logger.info("corpus reloaded: %d chunks, dim=%d", len(chunks), dim)
            return {"loaded": len(chunks), "dimension": dim}

    def query(
        self,
        vector: np.ndarray,
        k: int = 8,
        filtro: Optional[dict[str, str]] = None,
        query_text: str = "",
    ) -> list[CorpusHit]:
        """Top-k cosine similarity search with optional metadata filter.

        When ``filtro`` is provided (e.g. ``{"fabricante": "Cheyenne"}``),
        fetches ``k * 3`` candidates from FAISS, then post-filters in memory
        against ``_manifest`` metadata. This keeps the FAISS index
        unfragmented (single reload, no per-query rebuild) while still
        narrowing results to a specific manufacturer, model, or type.

        Filter keys are matched case-insensitively against the corresponding
        metadata field of each chunk.
        """
        if self.empty:
            return []

        q = _normalize(vector.astype(np.float32, copy=False).reshape(1, -1))

        terms = _query_terms(query_text)

        # Quando ha filtro ou termos literais, busca mais candidatos para ter margem.
        fetch_k = k * 3 if filtro else k
        if terms:
            fetch_k = max(fetch_k, k * 20, 80)
        kk = min(int(fetch_k), self.size)

        if self._index is not None:
            scores, ids = self._index.search(q, kk)
            scores = scores[0].tolist()
            ids = ids[0].tolist()
        else:
            sims = (self._vectors @ q.T).ravel()
            ids_arr = np.argsort(-sims)[:kk]
            ids = ids_arr.tolist()
            scores = [float(sims[i]) for i in ids]

        candidates: dict[int, float] = {}
        for idx, score in zip(ids, scores):
            if idx < 0 or idx >= len(self._manifest):
                continue
            candidates[idx] = max(candidates.get(idx, float("-inf")), float(score))

        if terms:
            for idx, row in enumerate(self._manifest):
                lexical = _lexical_score(row, terms)
                if lexical <= 0:
                    continue
                base = candidates.get(idx, 0.0)
                candidates[idx] = max(base, base + lexical)

            ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
            ids = [idx for idx, _ in ranked[:kk]]
            scores = [score for _, score in ranked[:kk]]

        hits: list[CorpusHit] = []
        for rank, (idx, score) in enumerate(zip(ids, scores)):
            if idx < 0 or idx >= len(self._manifest):
                continue
            row = self._manifest[idx]
            row_metadata = row.get("metadata", {})
            hits.append(
                CorpusHit(
                    chunk_id=row["id"],
                    text=row["text"],
                    source=row.get("source", ""),
                    score=float(score),
                    metadata={
                        **row_metadata,
                        "rank": rank,
                        "chunk_index": row.get("chunk_index", 0),
                        "n_chunks": row.get("n_chunks", 1),
                    },
                )
            )

        # Pos-filtro em memoria: mantem apenas hits cujo metadata bate com o filtro
        if filtro:
            hits = _aplicar_filtro(hits, filtro)

        return hits[:k]
