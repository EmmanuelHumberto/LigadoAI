"""rag technique — retrieve documents for the generate stage.

Variants:

  - ``dense`` — queries the OpenTracy knowledge vertical. Cold-start safe:
    empty or unavailable corpus → returns 0 docs, no crash; the generate
    stage answers from the LLM's own knowledge.
  - ``sparse`` and ``hybrid`` — still stubs (BM25 + fusion lands in
    P1.10.x). Wired so the pipeline can opt into them when the index
    grows enough to make sparse worthwhile.

Both stub variants and the real dense variant carry the same Document
shape, so the rerank stage doesn't care which retriever produced a doc.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Any

from runtime.protocols import BaseTechnique, Context, Document, Stage

logger = logging.getLogger("techniques.rag")


class _StubRetriever:
    """Returns k canned docs whose content echoes the request.

    Kept for ``sparse`` and ``hybrid`` until those land. Marked
    ``stub=True`` so traces stay honest about what's real.
    """

    def __init__(self, knobs: dict[str, Any], variant: str) -> None:
        self.k: int = int(knobs.get("k", 8))
        self.chunk_size: int = int(knobs.get("chunk_size", 512))
        self.variant = variant

    def execute(self, context: Context) -> Context:
        context.documents = [
            Document(
                content=(
                    f"[stub doc {i}] (variant={self.variant}) "
                    f"relevant to: {context.request[:80]}"
                ),
                score=round(1.0 - 0.05 * i, 3),
                metadata={"variant": self.variant, "rank": i, "stub": True},
            )
            for i in range(self.k)
        ]
        return context


class _DenseRetriever:
    """Retrieve top-k chunks from the knowledge vertical."""

    def __init__(self, knobs: dict[str, Any]) -> None:
        self.k: int = int(knobs.get("k", 8))
        self.timeout_seconds: float = float(knobs.get("timeout_seconds", 5))
        self.catalog_limit: int = int(knobs.get("catalog_limit", 50))
        self._search: Any | None = None

    def execute(self, context: Context) -> Context:
        search = self._search or self._new_search()
        if search is None:
            context.documents = []
            return context

        try:
            hits, catalog = _run_async(
                _retrieve_and_close(
                    search,
                    context.request,
                    top_k=self.k,
                    include_catalog=_is_inventory_request(context.request),
                    catalog_limit=self.catalog_limit,
                    close_after=self._search is None,
                ),
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as e:
            logger.warning("knowledge search failed (%s) — returning 0 docs", e)
            context.documents = []
            return context

        context.documents = catalog + [
            Document(
                content=hit.text,
                score=hit.score,
                metadata={
                    "variant": "dense",
                    "chunk_id": str(hit.chunk_id),
                    "document_id": str(hit.document_id),
                    "source": hit.source_uri,
                    **hit.metadata,
                },
            )
            for hit in hits
        ]
        return context

    def _new_search(self):
        backend = os.environ.get("OPENTRACY_KNOWLEDGE_BACKEND", "memory").strip().lower()
        dsn = os.environ.get("OPENTRACY_KNOWLEDGE_DATABASE_URL", "").strip()
        if backend != "postgres" or not dsn:
            return None
        try:
            from knowledge.infrastructure.postgres import LazyPostgresKnowledgeRepository

            return LazyPostgresKnowledgeRepository(dsn)
        except Exception as e:
            logger.warning("knowledge search adapter load failed (%s)", e)
            return None


class RagTechnique(BaseTechnique):
    name = "rag"
    variants = ("dense", "sparse", "hybrid")

    def compile(self, variant: str, knobs: dict[str, Any]) -> Stage:
        if variant not in self.variants:
            raise ValueError(f"rag: unknown variant {variant!r}; expected one of {self.variants}")
        if variant == "dense":
            return _DenseRetriever(knobs)
        return _StubRetriever(knobs, variant)


def _run_async(awaitable, *, timeout_seconds: float):
    import asyncio

    async def _with_timeout():
        return await asyncio.wait_for(awaitable, timeout=timeout_seconds)

    result: list[Any] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(asyncio.run(_with_timeout()))
        except BaseException as exc:  # propagated on the caller thread
            errors.append(exc)

    thread = threading.Thread(target=run, name="rag-dense", daemon=True)
    thread.start()
    thread.join(timeout=timeout_seconds + 1.0)
    if thread.is_alive():
        raise TimeoutError("rag dense retriever timed out")
    if errors:
        raise errors[0]
    if not result:
        raise RuntimeError("rag dense retriever returned no result")
    return result[0]


async def _retrieve_and_close(
    search,
    query: str,
    *,
    top_k: int,
    include_catalog: bool,
    catalog_limit: int,
    close_after: bool,
):
    try:
        hits = await search.search(query, top_k=top_k)
        catalog = []
        if include_catalog and hasattr(search, "list_documents"):
            catalog = [_catalog_document(await search.list_documents())]
            catalog[0].content = _limit_catalog(catalog[0].content, catalog_limit)
        return hits, catalog
    finally:
        if close_after and hasattr(search, "close"):
            await search.close()


def _is_inventory_request(query: str) -> bool:
    if query.startswith("TAREFA_SYSTEMOS_ANALISE_TECNICA_"):
        return False
    normalized = query.lower()
    triggers = (
        "listar todos",
        "liste todos",
        "lista todos",
        "todos os",
        "todas as",
        "quais ",
        "catalogo",
        "catálogo",
        "inventario",
        "inventário",
    )
    return any(trigger in normalized for trigger in triggers)


def _catalog_document(documents: list[Any]) -> Document:
    lines = ["Catalogo de documentos indexados disponiveis no OpenTracy:"]
    for index, document in enumerate(documents, 1):
        if str(getattr(document, "status", "")).endswith("deleted"):
            continue
        metadata = getattr(document, "metadata", {}) or {}
        if metadata.get("retrieval_eligible") is False or metadata.get("extra", {}).get("retrieval_eligible") is False:
            continue
        title = getattr(document, "title", None) or "-"
        source = getattr(document, "source_uri", None) or "-"
        manufacturer = getattr(document, "manufacturer", None) or "-"
        model = getattr(document, "model", None) or "-"
        document_type = getattr(document, "document_type", None) or "-"
        lines.append(
            f"{index}. titulo={title}; fonte={source}; fabricante={manufacturer}; "
            f"modelo={model}; tipo={document_type}"
        )
    return Document(
        content="\n".join(lines),
        score=100.0,
        metadata={"variant": "catalog", "source": "knowledge_documents"},
    )


def _limit_catalog(content: str, limit: int) -> str:
    lines = content.splitlines()
    if len(lines) <= limit + 1:
        return content
    shown = lines[: limit + 1]
    remaining = len(lines) - len(shown)
    shown.append(f"... {remaining} documentos adicionais omitidos do catalogo.")
    return "\n".join(shown)
