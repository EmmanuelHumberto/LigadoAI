#!/usr/bin/env python3
"""Read-only database proof, run by ExecStartPre inside the production sandbox."""
import asyncio
import json
import os


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
    finally:
        await connection.close()
    print(json.dumps({'databaseReadOnlyProbe': 'PASSOU', 'uid': os.getuid()}))


if __name__ == '__main__':
    asyncio.run(main())
