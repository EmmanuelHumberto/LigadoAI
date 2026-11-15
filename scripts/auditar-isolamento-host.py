#!/usr/bin/env python3
"""Read-only privileged inventory for the next Linux isolation migration."""
import argparse
import datetime
import json
import os
import pathlib
import pwd
import shutil
import stat
import subprocess


def read_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {"available": result.returncode == 0, "output": result.stdout.strip()}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "output": ""}


def postgres(query):
    args = ['runuser', '-u', 'postgres', '--', 'psql', '-X', '-A', '-t', '-d', 'postgres', '-c', query]
    result = read_command(args)
    if not result['available']:
        return {"available": False}
    try:
        return json.loads(result['output'])
    except ValueError:
        return {"available": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Execute com sudo. Nenhuma senha deve ser enviada pelo chat.')
    operator = pwd.getpwnam('hiatus')
    base = pathlib.Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
    assert base.is_dir() and not base.is_symlink() and base.stat().st_uid == operator.pw_uid
    rules = read_command(['nft', '-j', 'list', 'ruleset'])
    # Do not export arbitrary firewall strings, processes, env, database rows or secrets.
    try:
        nft = json.loads(rules['output']) if rules['available'] else {}
        firewall = {"available": rules['available'], "objects": len(nft.get('nftables', []))}
    except ValueError:
        firewall = {"available": False}
    result = {
        'result': 'INVENTORY_ONLY',
        'executedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'sourceCommit': read_command(['git', '-c', 'safe.directory=' + str(base), '-C', str(base), 'rev-parse', 'HEAD'])['output'],
        'operatorGroups': read_command(['id', '-Gn', 'hiatus'])['output'].split(),
        'firewall': firewall,
        'postgresSettings': postgres("SELECT json_build_object('listenAddresses',current_setting('listen_addresses'),'ssl',current_setting('ssl'),'port',current_setting('port'))"),
        'postgresRoles': postgres("SELECT coalesce(json_agg(json_build_object('role',rolname,'superuser',rolsuper,'createRole',rolcreaterole,'createDatabase',rolcreatedb,'login',rolcanlogin,'bypassRls',rolbypassrls)), '[]') FROM pg_roles WHERE rolname NOT LIKE 'pg_%'"),
        'postgresClientOrigins': postgres("SELECT coalesce(json_agg(row_to_json(x)),'[]') FROM (SELECT coalesce(client_addr::text,'local-socket') AS origin,count(*) AS connections FROM pg_stat_activity WHERE backend_type='client backend' GROUP BY client_addr) x"),
        'postgresHba': postgres("SELECT coalesce(json_agg(json_build_object('type',type,'address',address,'netmask',netmask,'method',auth_method,'error',error)),'[]') FROM pg_hba_file_rules"),
        'postgresServiceActive': read_command(['systemctl', 'is-active', 'postgresql'])['output'],
        'dockerSocket': {},
        'paths': {},
        'servicesChanged': False,
        'databaseModified': False,
        'credentialsExported': False,
    }
    for name in ['/var/run/docker.sock', '/run/docker.sock']:
        path = pathlib.Path(name)
        if path.exists():
            info = path.stat()
            result['dockerSocket'][name] = {'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(stat.S_IMODE(info.st_mode))}
    for name in ['.env', '.venv', 'agents', 'ledger', 'traces', 'corpora', 'tenants', 'uploads']:
        path = base / name
        if path.exists():
            info = path.stat()
            result['paths'][name] = {'uid': info.st_uid, 'gid': info.st_gid, 'mode': oct(stat.S_IMODE(info.st_mode)), 'symlink': path.is_symlink()}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
