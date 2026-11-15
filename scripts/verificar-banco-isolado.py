#!/usr/bin/env python3
"""Read-only database proof, run by ExecStartPre inside the production sandbox."""
import asyncio
import json
import os
import socket
import errno


async def main():
    import asyncpg
    assert os.getuid() not in (0, 1000)
    dsn = os.environ.get('OPENTRACY_COUS_V3_DATABASE_URL') or os.environ.get('OPENTRACY_KNOWLEDGE_DATABASE_URL')
    assert dsn
    connection = await asyncpg.connect(dsn, timeout=5)
    try:
        async with connection.transaction(readonly=True):
            assert await connection.fetchval('SELECT 1') == 1
            assert await connection.fetchval("SELECT current_setting('transaction_read_only')") == 'on'
            await connection.fetchval('SELECT count(*) FROM diagnosis_queue')
            required = os.environ.get('OPENTRACY_DATABASE_ROLE_REQUIRED')
            if required:
                row = await connection.fetchrow("SELECT current_user AS role,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
                assert row['role'] == required
                assert not any(row[key] for key in ('rolsuper','rolcreatedb','rolcreaterole','rolreplication','rolbypassrls'))
                assert await connection.fetchval("SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user)") == 0
                assert not await connection.fetchval("SELECT has_schema_privilege('public','CREATE')")
                for privilege in ('SELECT','INSERT','UPDATE','DELETE'):
                    assert await connection.fetchval("SELECT has_table_privilege('diagnosis_queue',$1)", privilege)
    finally:
        await connection.close()
    if os.environ.get('OPENTRACY_DATABASE_ROLE_REQUIRED'):
        connection = await asyncpg.connect(dsn, timeout=5)
        try:
            transaction = connection.transaction()
            await transaction.start()
            try:
                assert await connection.execute("UPDATE diagnosis_queue SET priority=priority WHERE false") == 'UPDATE 0'
                for statement in ("CREATE TABLE public.__ligado_forbidden_probe(id integer)", "SET ROLE ligadoai"):
                    denied = False
                    try:
                        async with connection.transaction():
                            await connection.execute(statement)
                    except asyncpg.InsufficientPrivilegeError:
                        denied = True
                    assert denied, 'Unexpected database administrative privilege'
            finally:
                await transaction.rollback()
        finally:
            await connection.close()
    if os.environ.get('OPENTRACY_EGRESS_REQUIRED') == '1':
        for destination in (('127.0.0.1',22),('179.66.130.52',22)):
            try:
                with socket.create_connection(destination,timeout=3):pass
            except OSError as error:
                assert error.errno in (errno.EACCES,errno.EPERM,errno.EHOSTUNREACH,errno.ENETUNREACH)
            else:
                raise AssertionError('Unexpected management egress was accepted')
        # Boot must not depend on the continued existence of any customer OS.
        # The publisher performs the authenticated read once; startup proves only
        # connectivity to its exact private transport destination.
        with socket.create_connection(('127.0.0.1',13301),timeout=4):pass
    print(json.dumps({'databaseReadOnlyProbe': 'PASSOU', 'leastPrivilegeVerified': bool(os.environ.get('OPENTRACY_DATABASE_ROLE_REQUIRED')), 'uid': os.getuid()}))


if __name__ == '__main__':
    asyncio.run(main())
