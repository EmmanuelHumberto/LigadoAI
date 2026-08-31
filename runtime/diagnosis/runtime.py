"""Runtime composition for COUS diagnosis routes and worker."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import APIRouter

from runtime.diagnosis.routes import create_diagnosis_router
from runtime.diagnosis.worker import DiagnosisWorker


@dataclass(frozen=True)
class DiagnosisRuntimeConfig:
    enabled: bool = True
    database_url: str | None = None
    auth_token: str | None = None
    worker_enabled: bool = True
    poll_interval: float = 5.0
    max_retries: int = 3
    diagnosis_timeout: float = 30.0

    @classmethod
    def from_env(cls) -> DiagnosisRuntimeConfig:
        enabled_raw = os.environ.get("OPENTRACY_DIAGNOSIS_ENABLED", "1").strip().lower()
        worker_raw = os.environ.get("OPENTRACY_DIAGNOSIS_WORKER_ENABLED", "1").strip().lower()
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
            database_url=database_url.strip() if database_url else None,
            auth_token=auth_token.strip() if auth_token else None,
            worker_enabled=worker_raw not in {"0", "false", "no", "off"},
            poll_interval=_float_env("OPENTRACY_DIAGNOSIS_POLL_INTERVAL", 5.0),
            max_retries=_int_env("OPENTRACY_DIAGNOSIS_MAX_RETRIES", 3),
            diagnosis_timeout=_float_env("OPENTRACY_DIAGNOSIS_TIMEOUT", 30.0),
        )


class LazyPostgresPool:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._pool: Any | None = None
        self._lock = asyncio.Lock()

    def acquire(self) -> LazyPoolAcquire:
        return LazyPoolAcquire(self)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _ensure(self) -> Any:
        if self._pool is not None:
            return self._pool
        async with self._lock:
            if self._pool is not None:
                return self._pool
            import asyncpg

            self._pool = await asyncpg.create_pool(dsn=self._dsn)
            return self._pool


class LazyPoolAcquire:
    def __init__(self, owner: LazyPostgresPool) -> None:
        self._owner = owner
        self._ctx: Any | None = None

    async def __aenter__(self) -> Any:
        pool = await self._owner._ensure()
        self._ctx = pool.acquire()
        return await self._ctx.__aenter__()

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self._ctx is None:
            return False
        return await self._ctx.__aexit__(exc_type, exc, tb)


class DiagnosisRepositoryProxy:
    def __init__(self, dsn: str) -> None:
        self._pool = LazyPostgresPool(dsn)

    async def close(self) -> None:
        await self._pool.close()


class DiagnosisRuntime:
    def __init__(self, config: DiagnosisRuntimeConfig) -> None:
        self.config = config
        self.repository: DiagnosisRepositoryProxy | None = (
            DiagnosisRepositoryProxy(config.database_url)
            if config.enabled and config.database_url
            else None
        )
        self.worker: DiagnosisWorker | None = None
        self._http: httpx.AsyncClient | None = None

    def router(self) -> APIRouter:
        router = APIRouter()
        if self.repository is None:
            @router.get("/v3/diagnosis/status")
            async def diagnosis_unavailable() -> dict[str, Any]:
                return {
                    "enabled": self.config.enabled,
                    "database_configured": bool(self.config.database_url),
                    "worker_enabled": False,
                    "status": "unavailable",
                }

            return router

        @router.get("/v3/diagnosis/status")
        async def diagnosis_available() -> dict[str, Any]:
            return {
                "enabled": self.config.enabled,
                "database_configured": True,
                "worker_enabled": self.config.worker_enabled,
                "worker_running": self.worker is not None,
                "status": "available",
            }

        router.include_router(
            create_diagnosis_router(
                repository=self.repository,
                auth_token=self.config.auth_token,
            )
        )

        return router

    async def start(self) -> None:
        if self.repository is None or not self.config.worker_enabled:
            return
        if self.worker is not None:
            return
        self._http = httpx.AsyncClient()
        self.worker = DiagnosisWorker(
            repository=self.repository,
            http_client=self._http,
            poll_interval=self.config.poll_interval,
            max_retries=self.config.max_retries,
            diagnosis_timeout=self.config.diagnosis_timeout,
        )
        await self.worker.start()

    async def stop(self) -> None:
        if self.worker is not None:
            await self.worker.stop()
            self.worker = None
        if self._http is not None:
            await self._http.aclose()
            self._http = None
        if self.repository is not None:
            await self.repository.close()


def create_diagnosis_runtime_from_env() -> DiagnosisRuntime:
    return DiagnosisRuntime(DiagnosisRuntimeConfig.from_env())


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default
