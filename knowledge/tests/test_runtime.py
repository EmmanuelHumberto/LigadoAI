from fastapi import APIRouter

from knowledge.runtime import KnowledgeRuntimeConfig, create_default_knowledge_router


def test_runtime_config_reads_disabled_env(monkeypatch):
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_ENABLED", "false")
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_BACKEND", "memory")
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_DATABASE_URL", "postgresql://example/db")
    monkeypatch.setenv("OPENTRACY_KNOWLEDGE_AUTH_TOKEN", "secret-token")

    config = KnowledgeRuntimeConfig.from_env()

    assert config.enabled is False
    assert config.backend == "memory"
    assert config.database_url == "postgresql://example/db"
    assert config.auth_token == "secret-token"


def test_disabled_runtime_router_has_no_routes():
    router = create_default_knowledge_router(KnowledgeRuntimeConfig(enabled=False))

    assert isinstance(router, APIRouter)
    assert router.routes == []


def test_postgres_runtime_backend_requires_database_url():
    try:
        create_default_knowledge_router(KnowledgeRuntimeConfig(backend="postgres"))
    except RuntimeError as exc:
        assert "OPENTRACY_KNOWLEDGE_DATABASE_URL is required" in str(exc)
    else:
        raise AssertionError("expected postgres backend without URL to fail")


def test_postgres_runtime_backend_builds_router_without_connecting():
    router = create_default_knowledge_router(
        KnowledgeRuntimeConfig(
            backend="postgres",
            database_url="postgresql://user:pass@localhost/db",
        )
    )

    paths = {route.path for route in router.routes}
    assert "/knowledge/status" in paths


def test_unsupported_runtime_backend_fails_fast():
    try:
        create_default_knowledge_router(KnowledgeRuntimeConfig(backend="unknown"))
    except RuntimeError as exc:
        assert "unsupported knowledge backend" in str(exc)
    else:
        raise AssertionError("expected unsupported backend to fail")
