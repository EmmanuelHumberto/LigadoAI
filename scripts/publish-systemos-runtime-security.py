#!/usr/bin/env python3
"""Publish a pushed Git revision with idle checks, private config backup and rollback."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
import urllib.error
import urllib.request

BASE = Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
UNIT = Path.home() / '.config/systemd/user/opentracy-systemos.service.d/70-systemos-runtime-security.conf'


def run(args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs).strip()


def queue_idle():
    code = """import asyncio,os,json
from runtime.dotenv import load_env
load_env()
async def main():
 import asyncpg
 dsn=os.environ.get('OPENTRACY_COUS_V3_DATABASE_URL') or os.environ.get('OPENTRACY_KNOWLEDGE_DATABASE_URL')
 assert dsn
 c=await asyncpg.connect(dsn,timeout=5)
 try:
  async with c.transaction(readonly=True):
   row=await c.fetchrow("SELECT count(*) FILTER(WHERE status IN ('pending','processing')) AS active, count(*) FILTER(WHERE callback_status='processing') AS callbacks FROM diagnosis_queue")
   print(json.dumps(dict(row)))
 finally:await c.close()
asyncio.run(main())"""
    counts = json.loads(run([str(BASE / '.venv/bin/python'), '-c', code], cwd=BASE))
    if counts != {'active': 0, 'callbacks': 0}:
        raise RuntimeError('Diagnosis queue is not idle; publication deferred')
    return counts


def atomic(path, data):
    assert not path.is_symlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + secrets.token_hex(6))
    fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def health(port):
    for attempt in range(40):
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError('Service health unavailable')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    sha = args.expected_commit
    assert len(sha) == 40 and all(c in '0123456789abcdef' for c in sha)
    assert os.getuid() == BASE.stat().st_uid
    assert not run(['git', 'status', '--porcelain'], cwd=BASE)
    assert run(['git', 'ls-remote', 'origin', 'refs/heads/main'], cwd=BASE).split()[0] == sha
    subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=BASE, check=True, capture_output=True)
    own = run(['git', 'show', sha + ':scripts/publish-systemos-runtime-security.py'], cwd=BASE)
    assert own == Path(__file__).read_text().strip()
    previous = run(['git', 'rev-parse', 'HEAD'], cwd=BASE)
    subprocess.run(['git', 'merge-base', '--is-ancestor', previous, sha], cwd=BASE, check=True)
    for port in (8001, 8002):
        assert not run(['ss', '-Hnt', 'state', 'established', 'sport', '=', ':' + str(port)]), 'Active HTTP connections; publication deferred'
    before = queue_idle()
    env = BASE / '.env'
    assert not env.is_symlink() and env.stat().st_mode & 0o077 == 0
    old_env = env.read_bytes()
    assert b'OPENTRACY_RUNTIME_INTERNAL_TOKEN=' not in old_env
    assert b'OPENTRACY_RUNTIME_SECURITY=' not in old_env
    old_unit = UNIT.read_bytes() if UNIT.exists() else None
    folder = Path.home() / '.local/state/opentracy-systemos' / ('runtime-security-' + sha[:12])
    folder.mkdir(mode=0o700, exist_ok=False)
    atomic(folder / 'environment-before.env', old_env)
    if old_unit is not None:
        atomic(folder / 'unit-before.conf', old_unit)
    service = ['systemctl', '--user']
    changed = False
    try:
        subprocess.run(service + ['stop', 'opentracy-systemos-gateway'], check=True)
        queue_idle()
        subprocess.run(['git', 'merge', '--ff-only', sha], cwd=BASE, check=True, capture_output=True)
        changed = True
        token = secrets.token_hex(32)
        atomic(env, old_env.rstrip() + b'\nOPENTRACY_RUNTIME_SECURITY=required\nOPENTRACY_RUNTIME_INTERNAL_TOKEN=' + token.encode() + b'\n')
        atomic(UNIT, (BASE / 'runtime/systemd/70-systemos-runtime-security.conf').read_bytes())
        subprocess.run(service + ['daemon-reload'], check=True)
        subprocess.run(service + ['restart', 'opentracy-systemos'], check=True)
        health(8001)
        subprocess.run(service + ['start', 'opentracy-systemos-gateway'], check=True)
        health(8002)
        for path in ['/agent/config', '/policy', '/agents', '/docs']:
            try:
                urllib.request.urlopen('http://127.0.0.1:8001' + path, timeout=4)
                raise RuntimeError('Anonymous runtime administration was accepted')
            except urllib.error.HTTPError as error:
                assert error.code == 401
        request = urllib.request.Request('http://127.0.0.1:8001/policy', headers={'x-opentracy-runtime-key': token})
        with urllib.request.urlopen(request, timeout=5) as response:
            assert response.status == 200
        pid = run(service + ['show', 'opentracy-systemos', '-p', 'MainPID', '--value'])
        assert 'NoNewPrivs:\t1' in Path('/proc/' + pid + '/status').read_text()
        result = {'result': 'PUBLISHED', 'sourceCommit': sha, 'previousCommit': previous,
                  'executedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'queueBefore': before, 'runtimeAnonymousDenied': True,
                  'runtimeAuthenticatedRead': True, 'noNewPrivileges': True,
                  'maxConcurrentHttpAnalyses': 2, 'cousRestarted': False,
                  'financialOperationExecuted': False,
                  'unitSha256': hashlib.sha256(UNIT.read_bytes()).hexdigest()}
    except Exception:
        subprocess.run(service + ['stop', 'opentracy-systemos-gateway'], capture_output=True)
        atomic(env, old_env)
        if old_unit is None:
            UNIT.unlink(missing_ok=True)
        else:
            atomic(UNIT, old_unit)
        if changed:
            subprocess.run(['git', 'switch', '--detach', previous], cwd=BASE, check=True, capture_output=True)
        subprocess.run(service + ['daemon-reload'], check=True)
        subprocess.run(service + ['restart', 'opentracy-systemos'], check=True)
        subprocess.run(service + ['start', 'opentracy-systemos-gateway'], check=True)
        atomic(folder / 'result.json', json.dumps({'result': 'ROLLED_BACK', 'sourceCommit': previous}).encode())
        raise
    atomic(folder / 'result.json', json.dumps(result, indent=2).encode())
    print(json.dumps(result))


if __name__ == '__main__':
    main()
