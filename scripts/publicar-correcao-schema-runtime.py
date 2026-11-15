#!/usr/bin/env python3
"""Git-bound source-only correction; preserves role, firewall, queue and state."""
import argparse
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
TOP = Path('/var/lib/ligado-opentracy')
PREVIOUS = '1831c2f162bf2cfb0a4faeb10104b827f4d61033'
MARKER = Path('/etc/ligado-opentracy-production-active')
UNITS = ('ligado-opentracy-runtime', 'ligado-opentracy-gateway')
STATE_VERSION = 'ff858d329c66'


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, BASE / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_knowledge_reads(activation, runtime_values, gateway_values):
    """The gateway integration token and runtime knowledge token have distinct scopes."""
    path = '/knowledge/jobs/7385f41d-acee-4f0d-a0e7-b7f358210b41'
    knowledge = runtime_values['OPENTRACY_KNOWLEDGE_AUTH_TOKEN']
    integration = gateway_values['SYSTEMOS_COGNITIVE_TOKEN']
    assert knowledge and integration
    assert activation.http_status(8001, path, knowledge) == 200
    assert activation.http_status(8002, path, integration) == 200
    assert activation.http_status(8002, path) == 401


def verify_live_dispatch(activation, values):
    """A synthetic real inference must coexist with health and protected reads."""
    knowledge = values[0]['OPENTRACY_KNOWLEDGE_AUTH_TOKEN']
    integration = values[1]['SYSTEMOS_COGNITIVE_TOKEN']
    def inference():
        request = urllib.request.Request('http://127.0.0.1:8001/run',
            data=json.dumps({'request': 'Teste sintetico de disponibilidade. Responda somente OK. Nao ha dados de cliente.',
                             'session_id': 'synthetic-availability-probe'}).encode(),
            headers={'content-type': 'application/json',
                     'x-opentracy-runtime-key': values[0]['OPENTRACY_RUNTIME_INTERNAL_TOKEN']})
        with urllib.request.urlopen(request, timeout=905) as response:
            return json.load(response)
    # On a probe failure, wait for accepted work before a rollback can stop it.
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(inference)
        probes = 0
        for _ in range(3):
            if pending.done(): break
            started = time.monotonic()
            assert activation.http_status(8001, '/health') == 200
            path = '/knowledge/jobs/7385f41d-acee-4f0d-a0e7-b7f358210b41'
            assert activation.http_status(8001, path, knowledge) == 200
            assert activation.http_status(8002, path, integration) == 200
            assert time.monotonic() - started < 5, 'Reads blocked during inference'
            probes += 1
            time.sleep(.25)
        result = pending.result(timeout=910)
    assert result.get('success') is True
    assert not str(result.get('response', '')).startswith(('[error]', '[offline]'))
    assert probes > 0, 'No overlapping availability observation'
    return {'syntheticInferenceSucceeded': True, 'overlappingReadRounds': probes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit', required=True)
    sha = parser.parse_args().expected_commit
    assert os.geteuid() == 0 and re.fullmatch('[a-f0-9]{40}', sha)
    prep = load('preparation', 'scripts/preparar-conta-opentracy.py')
    activation = load('activation', 'scripts/ativar-conta-opentracy.py')
    resources = load('resources', 'scripts/publicar-recursos-opentracy.py')
    run, replace = resources.run, resources.replace
    assert prep.git('rev-parse', 'HEAD') == sha and not prep.git('status', '--porcelain')
    assert prep.git('ls-remote', 'origin', 'refs/heads/main').split()[0] == sha
    assert prep.git('show', sha + ':scripts/publicar-correcao-schema-runtime.py') == Path(__file__).read_text().strip()
    assert MARKER.read_text().strip() == PREVIOUS
    for unit in UNITS:
        assert run(['systemctl', 'is-active', unit]) == 'active'
        assert run(['systemctl', 'show', unit, '-p', 'User', '--value']) == 'ligado-opentracy'
    assert run(['systemctl', 'is-active', 'ligado-opentracy-egress']) == 'active'
    # Do not interrupt inference or a customer request, including a still-running webhook.
    for port in (8001, 8002):
        assert not run(['ss', '-Hnt', 'state', 'established', 'sport', '=', ':' + str(port)]), 'Active requests; retry after they finish'
    current_envs = [Path('/etc/ligado-opentracy/schema-' + component + '-' + PREVIOUS[:12] + '.env') for component in ('runtime', 'gateway')]
    values = [prep.parse_env(path.read_text()) for path in current_envs]
    assert values[0]['OPENTRACY_DATABASE_ROLE_REQUIRED'] == 'opentracy_runtime'
    assert values[0]['OPENTRACY_EGRESS_REQUIRED'] == '1'
    activation.queue_idle(values[0])
    work = TOP / ('work-' + STATE_VERSION)
    home = TOP / ('home-' + STATE_VERSION)
    cache = Path('/var/cache/ligado-opentracy') / STATE_VERSION
    previous_release = Path('/opt/ligado-opentracy/releases') / PREVIOUS
    release = previous_release.parent / sha
    operation = TOP / 'pipeline-corrections' / sha
    assert not release.exists() and not operation.exists()
    assert shutil.disk_usage(TOP).free > 512 * 1024 * 1024
    identity = pwd.getpwnam('ligado-opentracy')
    operation.mkdir(parents=True, mode=0o700)
    units = [Path('/etc/systemd/system') / (unit + '.service') for unit in UNITS]
    originals = {path: path.read_bytes() for path in units}
    for index, path in enumerate(units):
        prep.private_file(operation / ('unit-' + str(index) + '.before'), originals[path])
    release.mkdir(mode=0o755)
    with tarfile.open(fileobj=io.BytesIO(prep.git('archive', sha, binary=True))) as archive:
        archive.extractall(release, filter='data')
    for name in ('agent', 'tenants', 'datasets', 'versions', 'evals/golden', 'evals/suites', 'evals/reports'):
        target = release / name
        if target.is_symlink(): target.unlink()
        elif target.exists(): shutil.rmtree(target)
        target.symlink_to(work / name, target_is_directory=True)
    for name in ('.venv', '.hf/hub', 'backend/node_modules'):
        target = release / name
        if target.is_symlink(): target.unlink()
        target.mkdir(parents=True, exist_ok=True)
    envs = [Path('/etc/ligado-opentracy/schema-' + component + '-' + sha[:12] + '.env') for component in ('runtime', 'gateway')]
    for path, environment in zip(envs, values):
        environment['OPENTRACY_SOURCE_COMMIT'] = sha
        prep.private_file(path, prep.env_bytes(environment), identity.pw_gid)
    aliases = {path: path.readlink() for path in work.iterdir() if path.is_symlink() and path.readlink().is_absolute() and path.readlink().is_relative_to(previous_release)}
    assert work / 'runtime' in aliases and work / 'knowledge' in aliases and work / 'measurements' in aliases
    started = False
    def interrupted(signum, frame): raise KeyboardInterrupt('Publication interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        started = True
        run(['systemctl', 'stop', UNITS[1]])
        activation.queue_idle(values[0])
        run(['systemctl', 'stop', UNITS[0]])
        activation.queue_idle(values[0])
        for path, old in aliases.items():
            path.unlink()
            path.symlink_to(release / old.relative_to(previous_release), target_is_directory=True)
        template = (release / 'infra/systemos/opentracy-isolated.service.in').read_text()
        for path, component, env in zip(units, ('runtime', 'gateway'), envs):
            text = activation.unit_text(template, release, work, home, cache, env, component, operation, release / 'scripts/verificar-banco-isolado.py')
            guard = (release / 'infra/systemos/opentracy-egress-require.conf').read_text().split('[Unit]\n', 1)[1]
            replace(path, text.replace('[Unit]\n', '[Unit]\n' + guard, 1).encode())
        run(['systemctl', 'daemon-reload'])
        # ExecStartPre now initializes both real adapters as the restricted UID/role.
        run(['systemctl', 'start', UNITS[0]])
        activation.health(8001)
        token = values[0]['BACKEND_API_KEYS'].split(',')[0].strip()
        knowledge = values[0]['OPENTRACY_KNOWLEDGE_AUTH_TOKEN']
        known_job = '/knowledge/jobs/7385f41d-acee-4f0d-a0e7-b7f358210b41'
        assert activation.http_status(8001, known_job, knowledge) == 200
        run(['systemctl', 'start', UNITS[1]])
        activation.health(8002)
        activation.verify_gateway_contract(8002, token, knowledge)
        verify_knowledge_reads(activation, values[0], values[1])
        availability = verify_live_dispatch(activation, values)
        assert run(['systemctl', 'is-active', 'ligado-opentracy-egress']) == 'active'
        replace(MARKER, (sha + '\n').encode(), 0o644)
        result = dict(result='PUBLISHED', sourceCommit=sha, previousSource=PREVIOUS,
                      realKnowledgeJobRead=200, lazyAdaptersRestrictedRoleVerified=True,
                      inferenceAvailability=availability,
                      databasePrivilegesUnchanged=True, firewallUnchanged=True, stateDirectoryUnchanged=True,
                      migrationsExecuted=False, cousRestarted=False, financialOperationExecuted=False,
                      executedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException:
        if started:
            for unit in reversed(UNITS): subprocess.run(['systemctl', 'stop', unit], capture_output=True, timeout=30)
            for path, old in aliases.items():
                if path.is_symlink(): path.unlink()
                path.symlink_to(old, target_is_directory=True)
            for path, data in originals.items(): replace(path, data)
            run(['systemctl', 'daemon-reload'])
            run(['systemctl', 'start', UNITS[0]]); activation.health(8001)
            run(['systemctl', 'start', UNITS[1]]); activation.health(8002)
        logs = subprocess.run(['journalctl', '-u', UNITS[0], '-u', UNITS[1], '--no-pager', '-n', '100'], capture_output=True)
        prep.private_file(operation / 'errors.log', logs.stdout)
        result = dict(result='ROLLED_BACK', sourceCommit=PREVIOUS, stateDirectoryUnchanged=True,
                      diagnosticFile=str(operation / 'errors.log'))
        prep.private_file(operation / 'result.json', json.dumps(result, indent=2).encode())
        print(json.dumps(result)); raise
    prep.private_file(operation / 'result.json', json.dumps(result, indent=2).encode())
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
