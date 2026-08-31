"""Runtime composition for COUS v3 Knowledge Units vertical.

Segue o padrão de measurements/runtime.py e knowledge/runtime.py.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from fastapi import APIRouter

from knowledge.api.cous_routes import create_cous_v3_router
from knowledge.infrastructure.postgres.cous_repository import CousKnowledgeRepository


@dataclass(frozen=True)
class CousV3RuntimeConfig:
    enabled: bool = True
    backend: str = "postgres"
    database_url: str | None = None
    auth_token: str | None = None

    @classmethod
    def from_env(cls) -> CousV3RuntimeConfig:
        enabled_raw = os.environ.get("OPENTRACY_COUS_V3_ENABLED", "1").strip().lower()
        backend = os.environ.get("OPENTRACY_COUS_V3_BACKEND", "postgres").strip().lower()
        database_url = (
            os.environ.get("OPENTRACY_COUS_V3_DATABASE_URL")
            or os.environ.get("OPENTRACY_KNOWLEDGE_DATABASE_URL")
        )
        auth_token = (
            os.environ.get("OPENTRACY_COUS_V3_AUTH_TOKEN")
            or os.environ.get("OPENTRACY_KNOWLEDGE_AUTH_TOKEN")
        )
        return cls(
            enabled=enabled_raw not in {"0", "false", "no", "off"},
            backend=backend or "postgres",
            database_url=database_url.strip() if database_url else None,
            auth_token=auth_token.strip() if auth_token else None,
        )


class LazyCousRepository:
    """Proxy lazy que inicializa o CousKnowledgeRepository na primeira chamada."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._repo: CousKnowledgeRepository | None = None
        self._lock = asyncio.Lock()

    async def _ensure(self) -> CousKnowledgeRepository:
        if self._repo is not None:
            return self._repo
        async with self._lock:
            if self._repo is not None:
                return self._repo
            self._repo = await CousKnowledgeRepository.connect(self._dsn)
            return self._repo

    async def close(self) -> None:
        if self._repo:
            await self._repo.close()

    async def get_pool(self):
        """Retorna o pool asyncpg inicializado (para acesso direto)."""
        repo = await self._ensure()
        return repo._pool

    # ── Proxy methods ─────────────────────────────────────────────────

    async def create_ku(self, *args, **kwargs):
        return await (await self._ensure()).create_ku(*args, **kwargs)

    async def get_ku(self, *args, **kwargs):
        return await (await self._ensure()).get_ku(*args, **kwargs)

    async def list_kus(self, *args, **kwargs):
        return await (await self._ensure()).list_kus(*args, **kwargs)

    async def count_kus(self, *args, **kwargs):
        return await (await self._ensure()).count_kus(*args, **kwargs)

    async def update_ku(self, *args, **kwargs):
        return await (await self._ensure()).update_ku(*args, **kwargs)

    async def create_relation(self, *args, **kwargs):
        return await (await self._ensure()).create_relation(*args, **kwargs)

    async def list_relations(self, *args, **kwargs):
        return await (await self._ensure()).list_relations(*args, **kwargs)

    async def delete_relation(self, *args, **kwargs):
        return await (await self._ensure()).delete_relation(*args, **kwargs)

    async def create_contradiction(self, *args, **kwargs):
        return await (await self._ensure()).create_contradiction(*args, **kwargs)

    async def list_contradictions(self, *args, **kwargs):
        return await (await self._ensure()).list_contradictions(*args, **kwargs)

    async def count_open_contradictions(self, *args, **kwargs):
        return await (await self._ensure()).count_open_contradictions(*args, **kwargs)

    async def get_graph_nodes(self, *args, **kwargs):
        return await (await self._ensure()).get_graph_nodes(*args, **kwargs)

    async def get_graph_edges(self, *args, **kwargs):
        return await (await self._ensure()).get_graph_edges(*args, **kwargs)

    async def find_paths(self, *args, **kwargs):
        return await (await self._ensure()).find_paths(*args, **kwargs)

    async def add_ku_source(self, *args, **kwargs):
        return await (await self._ensure()).add_ku_source(*args, **kwargs)

    async def count_sources(self, *args, **kwargs):
        return await (await self._ensure()).count_sources(*args, **kwargs)

    async def increment_chunk_usage(self, *args, **kwargs):
        return await (await self._ensure()).increment_chunk_usage(*args, **kwargs)

    async def resolve_capture_identity(self, *args, **kwargs):
        return await (await self._ensure()).resolve_capture_identity(*args, **kwargs)


def create_cous_v3_router_with_config(
    config: CousV3RuntimeConfig | None = None,
) -> APIRouter:
    """Cria router COUS v3 com configuração de ambiente."""
    config = config or CousV3RuntimeConfig.from_env()
    router = APIRouter()

    if not config.enabled or not config.database_url:
        @router.get("/v3/status")
        async def v3_status():
            return {
                "enabled": config.enabled,
                "backend": config.backend,
                "database_configured": bool(config.database_url),
                "status": "unavailable" if not config.database_url else "disabled",
            }
        return router

    repo = LazyCousRepository(config.database_url)

    v3_router = create_cous_v3_router(
        repository=repo,
        auth_token=config.auth_token,
    )
    router.include_router(v3_router)

    # Cadeias causais (extraídas de OS)
    from knowledge.api.causal_chains_routes import create_causal_chains_router
    cc_router = create_causal_chains_router(
        repository=repo,
        auth_token=config.auth_token,
    )
    router.include_router(cc_router)

    # Diagnóstico local (motor offline, sem LLM)
    from knowledge.api.local_diagnosis import create_local_diagnosis_router
    ld_router = create_local_diagnosis_router(repository=repo)
    router.include_router(ld_router)

    @router.get("/v3/status")
    async def v3_status():
        return {
            "enabled": config.enabled,
            "backend": config.backend,
            "database_configured": True,
            "auth_configured": bool(config.auth_token),
            "status": "available",
        }

    return router
