#!/usr/bin/env python3
"""Activate the proven isolated release with fresh state and a closed verification gate.

Rollback is automatic only while external access and the worker are gated. Once the
commit marker is written, preserve isolated state and do not restart legacy writers.
"""
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request

BASE = Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
TOP = Path('/var/lib/ligado-opentracy')
TESTED = 'ff858d329c66049f97186f29ef621de12329e3ca'
OLD = ('opentracy-systemos', 'opentracy-systemos-gateway')
NEW = ('ligado-opentracy-runtime', 'ligado-opentracy-gateway')
MARKER = Path('/etc/ligado-opentracy-production-active')


def load_preparation():
    spec = importlib.util.spec_from_file_location('host_preparation', BASE / 'scripts/preparar-conta-opentracy.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def command(args, **kwargs):
    return subprocess.check_output(args, stderr=subprocess.DEVNULL, text=True, timeout=45, **kwargs).strip()


def system(*args):
    return command(['systemctl', *args])


def effective_environment(prep):
    values = prep.parse_env((BASE / '.env').read_text())
    overrides = dict(part.split('=', 1) for part in shlex.split(prep.user_systemctl('show', OLD[0], '-p', 'Environment', '--value')) if '=' in part)
    values.update(overrides)
    return values


def queue_idle(values):
    # Only SELECT inside a read-only transaction; no queue consumption or inference.
    code = """import asyncio,os,json
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
    counts = json.loads(command([str(BASE / '.venv/bin/python'), '-c', code], env={**os.environ, **values}, cwd='/tmp'))
    if counts != {'active': 0, 'callbacks': 0}:
        raise RuntimeError('Diagnosis queue not idle; activation deferred')
    return counts


def verify_prepared(proof, manifest):
    assert proof['result'] == 'READY_NOT_ACTIVATED' and proof['sourceCommit'] == TESTED
    assert manifest['sourceCommit'] == TESTED and manifest['account'] == 'ligado-opentracy'
    assert proof['productionServicesUnchanged'] is True
    assert proof['candidateDatabaseCredentialsProvided'] is False
    for component in ('runtime', 'gateway'):
        checks = proof['componentIsolationProofs'][component]
        assert checks['result'] == 'PASSOU' and checks['uid'] not in (0, 1000)
        for name in ('noDockerGroup', 'dockerSocketDenied', 'personalFilesDenied', 'codeWriteDenied',
                     'dependenciesWriteDenied', 'stateWriteAllowed', 'noNewPrivileges',
                     'effectiveCapabilitiesEmpty', 'storageSourceFromRelease'):
            assert checks[name] is True


def replace_state(prep, work, identity):
    assert work == TOP / ('work-' + TESTED[:12]) and not work.is_symlink()
    before = prep.state_manifest(BASE)
    for part in prep.DATA:
        source = BASE / part
        target = work / part
        assert not target.is_symlink() and target.parent.resolve().is_relative_to(work)
        if target.exists():
            shutil.rmtree(target)
        if source.exists():
            def ignore(directory, names):
                return [name for name in names if name == '__pycache__' or
                        (part == 'tenants' and prep.copied_code((Path(directory) / name).relative_to(source).as_posix()))]
            shutil.copytree(source, target, symlinks=True, ignore=ignore)
        else:
            target.mkdir(parents=True)
        for path in (target, *target.rglob('*')):
            if path.is_symlink():
                continue
            os.chown(path, identity.pw_uid, identity.pw_gid)
            path.chmod(0o700 if path.is_dir() else 0o600)
    assert before == prep.state_manifest(BASE), 'Legacy state changed while writers were stopped'
    for relative, digest in before.items():
        destination = work / relative
        if isinstance(digest, dict):
            assert destination.is_symlink() and str(destination.readlink()) == digest['link']
            assert hashlib.sha256(destination.read_bytes()).hexdigest() == digest['targetSha256']
        else:
            assert not destination.is_symlink() and hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    return before


def replace_configuration(prep, path, values, gid):
    assert path.is_file() and not path.is_symlink()
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8))
    try:
        prep.private_file(temporary, prep.env_bytes(values), gid)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def http_status(port, path, token=None):
    headers = {'authorization': 'Bearer ' + token} if token else {}
    request = urllib.request.Request('http://127.0.0.1:' + str(port) + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def health(port):
    for _ in range(40):
        try:
            if http_status(port, '/health') == 200:
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    raise RuntimeError('Isolated service health unavailable')


def unit_text(template, release, work, home, cache, envfile, component, deployment, database_probe):
    execution = str(release / '.venv/bin/python') + ' -m runtime.server' if component == 'runtime' else '/usr/bin/node --env-file=' + str(envfile) + ' --import tsx api/server.ts'
    values = {'DESCRIPTION': 'Isolated OpenTracy ' + component, 'RELEASE': str(release), 'WORK': str(work),
              'WORKDIR': str(work if component == 'runtime' else release / 'backend'), 'ENVFILE': str(envfile),
              'HOME': str(home), 'CACHE': str(cache), 'REPORT': 'production-' + component + '-isolation.json',
              'EXEC': execution, 'EXTRA_DENY': 'InaccessiblePaths=' + str(deployment)}
    text = template
    for key, value in values.items():
        text = text.replace('@' + key + '@', value)
    assert not re.search(r'@[A-Z_]+@', text)
    # Gateway is deliberately closed until authenticated runtime reads pass.
    if component == 'runtime':
        text = text.replace('ExecStart=', 'ExecStartPre=' + str(release / '.venv/bin/python') + ' ' + str(database_probe) + '\nExecStart=', 1)
    if component == 'gateway':
        text = text.replace('After=network-online.target', 'After=network-online.target ligado-opentracy-runtime.service\nRequires=ligado-opentracy-runtime.service')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    sha = args.expected_commit
    assert os.geteuid() == 0, 'Execute com sudo no terminal Linux.'
    assert re.fullmatch('[0-9a-f]{40}', sha)
    prep = load_preparation()
    assert prep.git('rev-parse', 'HEAD') == sha and not prep.git('status', '--porcelain')
    assert prep.git('ls-remote', 'origin', 'refs/heads/main').split()[0] == sha
    assert prep.git('show', sha + ':scripts/ativar-conta-opentracy.py') == Path(__file__).read_text().strip()
    # Source already passed the privileged sandbox proof. Only this publisher,
    # its tests and documentation may differ from that proven release.
    changed = prep.git('diff', '--name-only', TESTED, sha).splitlines()
    assert all(path.startswith('docs/') or path in ('scripts/ativar-conta-opentracy.py', 'runtime/tests/test_host_activation.py', 'scripts/verificar-banco-isolado.py') for path in changed)
    deployment = TOP / 'deployments' / TESTED
    proof = json.loads((deployment / 'result.json').read_text())
    manifest = json.loads((deployment / 'manifest.json').read_text())
    verify_prepared(proof, manifest)
    release = Path(manifest['release']); work = Path(manifest['work'])
    home = Path(manifest['home']); cache = Path(manifest['cache'])
    assert release == Path('/opt/ligado-opentracy/releases') / TESTED
    assert work == TOP / ('work-' + TESTED[:12])
    assert home == TOP / ('home-' + TESTED[:12])
    assert cache == Path('/var/cache/ligado-opentracy') / TESTED[:12]
    assert not MARKER.exists() and not MARKER.is_symlink()
    for path in (release, work, home, cache, deployment):
        assert path.is_dir() and not path.is_symlink()
    identity = pwd.getpwnam('ligado-opentracy')
    assert identity.pw_uid == proof['componentIsolationProofs']['runtime']['uid']
    assert set(os.getgrouplist(identity.pw_name, identity.pw_gid)) == {identity.pw_gid}
    assert shutil.disk_usage(TOP).free > 512 * 1024 * 1024
    assert all(prep.user_systemctl('is-active', unit) == 'active' for unit in OLD)
    assert all(not command(['ss', '-Hnt', 'state', 'established', 'sport', '=', ':' + str(port)]) for port in (8001, 8002)), 'Active requests; retry later'
    values = effective_environment(prep)
    queue_before = queue_idle(values)
    token = values['BACKEND_API_KEYS'].split(',')[0].strip()
    knowledge = values['OPENTRACY_KNOWLEDGE_AUTH_TOKEN']
    assert token and knowledge and values['OPENTRACY_RUNTIME_INTERNAL_TOKEN']
    enabled = {unit: prep.user_systemctl('is-enabled', unit) for unit in OLD}
    assert all(value == 'enabled' for value in enabled.values())
    units = [Path('/etc/systemd/system') / (unit + '.service') for unit in NEW]
    drops = [Path('/home/hiatus/.config/systemd/user') / (unit + '.service.d/90-exclusive-isolated.conf') for unit in OLD]
    assert not any(path.exists() or path.is_symlink() for path in (*units, *drops))
    operation = TOP / 'activations' / sha
    operation.mkdir(parents=True, mode=0o700, exist_ok=False)
    tools = Path('/opt/ligado-opentracy/operations') / sha
    tools.mkdir(parents=True, mode=0o755, exist_ok=False)
    tools.parent.chmod(0o755)
    database_probe = tools / 'verificar-banco-isolado.py'
    probe_source = prep.git('show', sha + ':scripts/verificar-banco-isolado.py')
    prep.private_file(database_probe, (probe_source + '\n').encode())
    database_probe.chmod(0o644)
    envs = [Path('/etc/ligado-opentracy') / ('production-' + component + '-' + sha[:12] + '.env') for component in ('runtime', 'gateway')]
    assert not any(path.exists() or path.is_symlink() for path in envs)
    committed = False
    changed_live = False
    installed_units = []
    installed_drops = []
    try:
        changed_live = True
        prep.user_systemctl('stop', OLD[1])
        queue_idle(values)
        prep.user_systemctl('stop', OLD[0])
        queue_idle(values)
        fresh = replace_state(prep, work, identity)
        prep.private_file(operation / 'fresh-state-manifest.json', json.dumps(fresh, indent=2).encode())
        runtime = dict(values)
        runtime.update(OPENTRACY_STATE_ROOT=str(work), OPENTRACY_RUNTIME_HOST='127.0.0.1', OPENTRACY_RUNTIME_PORT='8001',
                       OPENTRACY_RUNTIME_SECURITY='required', OPENTRACY_SOURCE_COMMIT=TESTED, OPENTRACY_DIAGNOSIS_WORKER_ENABLED='0')
        gateway = {key: runtime[key] for key in ('BACKEND_API_KEYS', 'SYSTEMOS_COGNITIVE_TOKEN', 'OPENTRACY_RUNTIME_INTERNAL_TOKEN',
                    'OPENTRACY_RUNTIME_SECURITY', 'OPENTRACY_KNOWLEDGE_AUTH_TOKEN', 'OPENTRACY_COUS_V3_AUTH_TOKEN') if key in runtime}
        gateway.update(RUNTIME_URL='http://127.0.0.1:8001', PORT='18012', OPENTRACY_AGENTS_ROOT=str(work / 'agents'), OPENTRACY_SOURCE_COMMIT=TESTED)
        for path, env in zip(envs, (runtime, gateway)):
            prep.private_file(path, prep.env_bytes(env), identity.pw_gid)
        template = (release / 'infra/systemos/opentracy-isolated.service.in').read_text()
        for path, component, envfile in zip(units, ('runtime', 'gateway'), envs):
            prep.private_file(path, unit_text(template, release, work, home, cache, envfile, component, deployment, database_probe).encode())
            installed_units.append(path)
        system('daemon-reload')
        system('start', NEW[0]); health(8001)
        assert http_status(8001, '/agent/config') == 401
        assert http_status(8001, '/agent/config', token) == 200
        assert http_status(8001, '/agent/config', knowledge) == 200
        assert http_status(8001, '/policy', knowledge) == 401
        # System manager owns credentials. The new process cannot read old secrets
        # or Docker, as demonstrated again by ExecStartPre in the actual unit.
        system('start', NEW[1]); health(18012)
        assert http_status(18012, '/v1/agent/config') == 401
        assert http_status(18012, '/v1/agent/config', token) == 200
        assert http_status(18012, '/v1/agent/config', knowledge) == 200
        system('stop', NEW[1])
        for component in ('runtime', 'gateway'):
            report = json.loads((work / ('production-' + component + '-isolation.json')).read_text())
            assert report['result'] == 'PASSOU' and report['uid'] == identity.pw_uid
        queue_idle(values)
        # Commit the handover before reopening writers. From this point a failure
        # must preserve the isolated state; never silently start stale legacy data.
        prep.private_file(MARKER, (TESTED + '\n').encode())
        committed = True
        MARKER.chmod(0o644)
        for path in drops:
            prep.private_file(path, ('[Unit]\nConditionPathExists=!' + str(MARKER) + '\n').encode())
            path.chmod(0o644)
            installed_drops.append(path)
        prep.user_systemctl('daemon-reload')
        prep.user_systemctl('disable', *OLD)
        system('enable', *NEW)
        # Restore the explicitly configured worker policy only after ownership commits.
        system('stop', NEW[0])
        runtime['OPENTRACY_DIAGNOSIS_WORKER_ENABLED'] = values.get('OPENTRACY_DIAGNOSIS_WORKER_ENABLED', '1')
        replace_configuration(prep, envs[0], runtime, identity.pw_gid)
        system('start', NEW[0]); health(8001)
        gateway['PORT'] = '8002'
        replace_configuration(prep, envs[1], gateway, identity.pw_gid)
        system('start', NEW[1]); health(8002)
        assert http_status(8002, '/v1/agent/config') == 401
        assert http_status(8002, '/v1/agent/config', token) == 200
        assert http_status(8002, '/v1/agent/config', knowledge) == 200
        assert all(system('is-active', unit) == 'active' for unit in NEW)
        assert all(prep.user_systemctl('show', unit, '-p', 'MainPID', '--value') == '0' for unit in OLD)
        result = {'result': 'ACTIVATED', 'sourceCommit': TESTED, 'publisherCommit': sha, 'account': identity.pw_name,
                  'uid': identity.pw_uid, 'stateFilesVerified': len(fresh), 'queueBefore': queue_before,
                  'authenticatedRuntimeRead': True, 'authenticatedGatewayRead': True, 'anonymousDenied': True,
                  'legacyWritersDisabled': True, 'cousRestarted': False, 'financialOperationExecuted': False,
                  'executedAt': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    except Exception:
        if not committed:
            for unit in reversed(NEW):
                subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=30)
            for path in installed_units:
                path.unlink()
            system('daemon-reload')
            if changed_live:
                prep.user_systemctl('start', OLD[0]); health(8001)
                prep.user_systemctl('start', OLD[1]); health(8002)
            outcome = 'ROLLED_BACK_BEFORE_HANDOVER'
        else:
            outcome = 'HANDOVER_COMMITTED_NEEDS_ATTENTION'
        # Keep all state and configuration for diagnosis; never erase new writes.
        logs = subprocess.run(['journalctl', '-u', NEW[0], '-u', NEW[1], '--no-pager', '-n', '60'], capture_output=True)
        prep.private_file(operation / 'errors.log', logs.stdout)
        result = {'result': outcome, 'sourceCommit': TESTED, 'publisherCommit': sha,
                  'productionStatePreserved': True, 'diagnosticFile': str(operation / 'errors.log')}
        prep.private_file(operation / 'result.json', json.dumps(result, indent=2).encode())
        print(json.dumps(result))
        raise
    prep.private_file(operation / 'result.json', json.dumps(result, indent=2).encode())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
