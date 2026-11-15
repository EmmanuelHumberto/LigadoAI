#!/usr/bin/env python3
"""Install the Git-bound PostgreSQL LAN guard without restarting the database."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import socket
import subprocess

BASE = Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
RULE = Path('/etc/ligado-security/opentracy-postgres-local-only.nft')
UNIT = Path('/etc/systemd/system/ligado-opentracy-postgres-local-only.service')
STATE = Path('/var/lib/ligado-security/postgres-local-only')
SERVICE = UNIT.name
NFT = '/usr/sbin/nft'
TABLE = ['inet', 'ligado_opentracy_postgres']


def command(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.DEVNULL, timeout=20).strip()


def git(*args):
    # User-owned Git config must never run as root.
    return command(['runuser', '-u', 'hiatus', '--', 'git', '-C', str(BASE), *args])


def atomic(path, data, mode=0o600):
    assert not path.is_symlink()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = path.parent.stat()
    assert parent.st_uid == 0 and not parent.st_mode & 0o022
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(descriptor, 'wb') as out:
        out.write(data); out.flush(); os.fsync(out.fileno())
    temporary.replace(path)


def database_query(query):
    return command(['runuser', '-u', 'postgres', '--', 'psql', '-X', '-A', '-t', '-d', 'postgres', '-c', query])


def table_exists():
    return subprocess.run([NFT, 'list', 'table', *TABLE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Execute com sudo no terminal Linux. Nao envie a senha pelo chat.')
    sha = args.expected_commit
    assert re.fullmatch('[a-f0-9]{40}', sha)
    assert BASE.stat().st_uid == pwd.getpwnam('hiatus').pw_uid
    assert not git('status', '--porcelain')
    assert git('rev-parse', 'HEAD') == sha
    assert git('ls-remote', 'origin', 'refs/heads/main').split()[0] == sha
    source = git('show', sha + ':scripts/aplicar-protecao-postgres-linux.py')
    assert source == Path(__file__).read_text().strip()
    assert not RULE.exists() and not RULE.is_symlink() and not UNIT.exists() and not UNIT.is_symlink()
    assert not table_exists(), 'Existing guard requires an explicit reviewed update'
    assert not STATE.exists(), 'Prior operation exists; inspect its receipt before retrying'
    assert database_query('SELECT 1') == '1'
    assert database_query("SELECT count(*) FROM pg_stat_activity WHERE client_addr IS NOT NULL AND client_addr NOT IN ('127.0.0.1'::inet,'::1'::inet)") == '0', 'External database clients exist; installation deferred'
    instances = [line.split()[0] for line in command(['systemctl', 'list-units', '--type=service', '--all', '--plain', '--no-legend', 'postgresql@*']).splitlines()]
    assert instances and all(re.fullmatch(r'postgresql@[0-9]+-[A-Za-z0-9_-]+\.service', value) for value in instances)
    pids = {name: command(['systemctl', 'show', name, '-p', 'MainPID', '--value']) for name in instances}
    assert all(int(value) > 0 for value in pids.values())
    rules = (git('show', sha + ':infra/systemos/postgres-local-only.nft') + '\n').encode()
    unit = (git('show', sha + ':infra/systemos/ligado-opentracy-postgres-local-only.service').replace('@PG_INSTANCES@', ' '.join(instances)) + '\n').encode()
    STATE.mkdir(parents=True, mode=0o700)
    atomic(STATE / 'candidate.nft', rules)
    command([NFT, '-c', '-f', str(STATE / 'candidate.nft')])
    created_rule = created_unit = False
    try:
        atomic(RULE, rules); created_rule = True
        atomic(UNIT, unit, 0o644); created_unit = True
        command(['systemctl', 'daemon-reload'])
        command(['systemctl', 'enable', '--now', SERVICE])
        assert command(['systemctl', 'is-active', SERVICE]) == 'active'
        assert command(['systemctl', 'is-enabled', SERVICE]) == 'enabled'
        assert table_exists()
        for address in ['127.0.0.1', '::1']:
            with socket.create_connection((address, 5432), timeout=3): pass
        assert database_query('SELECT 1') == '1'
        assert pids == {name: command(['systemctl', 'show', name, '-p', 'MainPID', '--value']) for name in instances}
        result = {'result': 'APPLIED', 'sourceCommit': sha,
                  'executedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'loopbackPreserved': True, 'postgresRestarted': False,
                  'otherFirewallTablesModified': False, 'databaseDataModified': False,
                  'rolePrivilegesChanged': False, 'serviceEnabled': True,
                  'rulesSha256': hashlib.sha256(rules).hexdigest(), 'unitSha256': hashlib.sha256(unit).hexdigest()}
        atomic(STATE / 'result.json', json.dumps(result, indent=2).encode())
        print(json.dumps(result, indent=2))
    except Exception:
        if created_unit:
            subprocess.run(['systemctl', 'disable', '--now', SERVICE], capture_output=True, timeout=20)
        if table_exists():
            subprocess.run([NFT, 'delete', 'table', *TABLE], check=True, capture_output=True, timeout=10)
        if created_unit: UNIT.unlink()
        if created_rule: RULE.unlink()
        command(['systemctl', 'daemon-reload'])
        atomic(STATE / 'result.json', json.dumps({'result': 'ROLLED_BACK', 'sourceCommit': sha}).encode())
        raise


if __name__ == '__main__':
    main()
