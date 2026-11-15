#!/usr/bin/env python3
"""Explicit owner-only schema provisioning. Never called by request handlers.

Supply OPENTRACY_MIGRATION_DATABASE_URL outside the runtime environment.
Existing installations must baseline only after verifying their schema.
"""
import argparse
import asyncio
import hashlib
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def migrate(dsn, *, baseline=False):
    import asyncpg
    connection = await asyncpg.connect(dsn)
    try:
        async with connection.transaction():
            await connection.execute('SELECT pg_advisory_xact_lock(723091146)')
            if not await connection.fetchval("SELECT has_schema_privilege('public','CREATE')"):
                raise PermissionError('Schema owner credentials required; never grant DDL to runtime')
            await connection.execute("CREATE TABLE IF NOT EXISTS public.opentracy_schema_migrations (name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())")
            await connection.execute('REVOKE ALL ON public.opentracy_schema_migrations FROM PUBLIC')
            if await connection.fetchval("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='opentracy_runtime')"):
                await connection.execute('REVOKE ALL ON public.opentracy_schema_migrations FROM opentracy_runtime')
            for vertical in ('knowledge', 'measurements'):
                directory = ROOT / vertical / 'infrastructure/postgres/migrations'
                for path in sorted(directory.glob('*.sql')):
                    name = vertical + '/' + path.name
                    sql = path.read_text(encoding='utf-8')
                    digest = hashlib.sha256(sql.encode()).hexdigest()
                    previous = await connection.fetchval('SELECT sha256 FROM public.opentracy_schema_migrations WHERE name=$1', name)
                    if previous is not None:
                        if previous != digest:
                            raise RuntimeError('Previously applied migration was changed: ' + name)
                        continue
                    if not baseline:
                        await connection.execute(sql)
                    await connection.execute('INSERT INTO public.opentracy_schema_migrations(name,sha256) VALUES($1,$2)', name, digest)
    finally:
        await connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-existing', action='store_true', help='Record verified existing migrations without executing them')
    args = parser.parse_args()
    dsn = os.environ.get('OPENTRACY_MIGRATION_DATABASE_URL')
    if not dsn:
        parser.error('OPENTRACY_MIGRATION_DATABASE_URL is required; runtime credentials are not used')
    asyncio.run(migrate(dsn, baseline=args.baseline_existing))
