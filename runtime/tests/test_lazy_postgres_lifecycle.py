"""Runtime must never migrate, and failed initialization must release its pool."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from knowledge.infrastructure.postgres import lazy as knowledge
from measurements.infrastructure.postgres import lazy as measurements


class Context:
    def __init__(self, value): self.value = value
    async def __aenter__(self): return self.value
    async def __aexit__(self, *args): return False


@pytest.mark.parametrize('module,repo_class,lazy_class', [
    (knowledge, knowledge.PostgresKnowledgeRepository, knowledge.LazyPostgresKnowledgeRepository),
    (measurements, measurements.PostgresMeasurementRepository, measurements.LazyPostgresMeasurementRepository),
])
@pytest.mark.parametrize('failure', [None, RuntimeError('missing schema'), asyncio.CancelledError()])
def test_runtime_schema_is_readonly_and_closes_failed_pool(monkeypatch, module, repo_class, lazy_class, failure):
    async def exercise():
        statements = []
        def transaction(*, readonly):
            assert readonly is True
            return Context(None)
        async def execute(query):
            assert query.startswith('SELECT ') and query.endswith('LIMIT 0')
            statements.append(query)
            if failure is not None: raise failure
        conn = SimpleNamespace(transaction=transaction, execute=execute)
        repo = SimpleNamespace(_pool=SimpleNamespace(acquire=lambda: Context(conn)), close=AsyncMock())
        connect = AsyncMock(return_value=repo)
        monkeypatch.setattr(repo_class, 'connect', connect)
        lazy = lazy_class('unused-test-dsn')
        if failure is not None:
            with pytest.raises(type(failure)):
                await lazy._ensure_repo()
            repo.close.assert_awaited_once()
            assert lazy._repo is None
        else:
            first, second = await asyncio.gather(lazy._ensure_repo(), lazy._ensure_repo())
            assert first is second is repo
            assert len(statements) >= 4
            connect.assert_awaited_once()
            repo.close.assert_not_awaited()
            await lazy.close()
            repo.close.assert_awaited_once()
        assert statements
    asyncio.run(exercise())


def test_explicit_migrator_rejects_runtime_and_detects_changed_migration(monkeypatch, tmp_path):
    import importlib.util
    import asyncpg
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / 'scripts/migrate-postgres.py'
    spec = importlib.util.spec_from_file_location('schema_migrator_test', script)
    migrator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migrator)
    monkeypatch.setattr(migrator, 'ROOT', tmp_path)
    directory = tmp_path / 'knowledge/infrastructure/postgres/migrations'
    directory.mkdir(parents=True)
    migration = directory / '001_test.sql'
    migration.write_text('CREATE TABLE synthetic_test(id integer)')
    ledger = {}
    statements = []
    is_owner = False
    class Connection:
        def transaction(self): return Context(None)
        async def fetchval(self, query, *args):
            if 'has_schema_privilege' in query: return is_owner
            if 'pg_roles' in query: return True
            return ledger.get(args[0])
        async def execute(self, query, *args):
            statements.append(query)
            if query.startswith('INSERT INTO public.opentracy_schema_migrations'):
                ledger[args[0]] = args[1]
        close = AsyncMock()
    connection = Connection()
    monkeypatch.setattr(asyncpg, 'connect', AsyncMock(return_value=connection))
    async def exercise():
        nonlocal is_owner
        with pytest.raises(PermissionError): await migrator.migrate('synthetic')
        assert not any(statement.startswith('CREATE') for statement in statements)
        connection.close.assert_awaited_once()
        is_owner = True
        await migrator.migrate('synthetic')
        await migrator.migrate('synthetic')
        assert statements.count('CREATE TABLE synthetic_test(id integer)') == 1
        migration.write_text('CREATE TABLE changed(id integer)')
        with pytest.raises(RuntimeError, match='Previously applied migration was changed'):
            await migrator.migrate('synthetic')
        assert 'CREATE TABLE changed(id integer)' not in statements
    asyncio.run(exercise())


def test_publication_respects_gateway_and_runtime_credential_scopes():
    import importlib.util
    from pathlib import Path
    script = Path(__file__).resolve().parents[2] / 'scripts/publicar-correcao-schema-runtime.py'
    spec = importlib.util.spec_from_file_location('schema_publisher_test', script)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    calls = []
    def status(port, path, token=None):
        calls.append((port, token))
        assert path.startswith('/knowledge/jobs/')
        expected = 'synthetic-knowledge' if port == 8001 else 'synthetic-integration'
        return 200 if token == expected else 401
    activation = SimpleNamespace(http_status=status)
    publisher.verify_knowledge_reads(activation,
        {'OPENTRACY_KNOWLEDGE_AUTH_TOKEN': 'synthetic-knowledge'},
        {'SYSTEMOS_COGNITIVE_TOKEN': 'synthetic-integration'})
    assert calls == [(8001, 'synthetic-knowledge'), (8002, 'synthetic-integration'), (8002, None)]
