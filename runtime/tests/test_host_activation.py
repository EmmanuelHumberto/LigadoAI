import copy
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[2] / 'scripts' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def activation():
    return module('host_activation', 'ativar-conta-opentracy.py')


@pytest.fixture
def proof(activation):
    checks = {name: True for name in ('noDockerGroup', 'dockerSocketDenied', 'personalFilesDenied',
        'codeWriteDenied', 'dependenciesWriteDenied', 'stateWriteAllowed', 'noNewPrivileges',
        'effectiveCapabilitiesEmpty', 'storageSourceFromRelease')}
    checks.update(result='PASSOU', uid=997)
    return dict(result='READY_NOT_ACTIVATED', sourceCommit=activation.TESTED,
                productionServicesUnchanged=True, candidateDatabaseCredentialsProvided=False,
                componentIsolationProofs={name: copy.deepcopy(checks) for name in ('runtime', 'gateway')})


@pytest.mark.parametrize('component', ['runtime', 'gateway'])
def test_preflight_refuses_proof_with_docker_access(activation, proof, component):
    manifest = dict(sourceCommit=activation.TESTED, account='ligado-opentracy')
    activation.verify_prepared(proof, manifest)
    proof['componentIsolationProofs'][component]['dockerSocketDenied'] = False
    with pytest.raises(AssertionError):
        activation.verify_prepared(proof, manifest)


def test_preflight_rejects_proof_from_another_release(activation, proof):
    proof['sourceCommit'] = 'a' * 40
    with pytest.raises(AssertionError):
        activation.verify_prepared(proof, dict(sourceCommit=activation.TESTED, account='ligado-opentracy'))


def state_fixture(activation, tmp_path, monkeypatch):
    prep = module('preparation_for_activation', 'preparar-conta-opentracy.py')
    source = tmp_path / 'legacy'
    top = tmp_path / 'isolated'
    source.mkdir(); top.mkdir()
    work = top / ('work-' + activation.TESTED[:12]); work.mkdir()
    for part in prep.DATA:
        (source / part).mkdir(parents=True, exist_ok=True)
        (work / part).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(activation, 'BASE', source)
    monkeypatch.setattr(activation, 'TOP', top)
    monkeypatch.setattr(prep, 'BASE', source)
    identity = SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())
    return prep, source, work, identity


def test_cutover_uses_fresh_state_and_preserves_legacy(activation, tmp_path, monkeypatch):
    prep, source, work, identity = state_fixture(activation, tmp_path, monkeypatch)
    (work / 'agent/current.json').write_text('{"version":"stale candidate"}')
    (work / 'agent/deleted-after-preparation.txt').write_text('Stale')
    (source / 'agent/current.json').write_text('{"version":"new live state"}')
    (source / 'datasets/v1.json').write_text('{"version":1}')
    (source / 'datasets/current').symlink_to('v1.json')
    before = prep.state_manifest(source)
    result = activation.replace_state(prep, work, identity)
    assert result == before == prep.state_manifest(source)
    assert (work / 'agent/current.json').read_bytes() == (source / 'agent/current.json').read_bytes()
    assert not (work / 'agent/deleted-after-preparation.txt').exists()
    assert (work / 'datasets/current').readlink() == Path('v1.json')


def test_cutover_defers_if_legacy_state_changes_during_copy(activation, tmp_path, monkeypatch):
    prep, source, work, identity = state_fixture(activation, tmp_path, monkeypatch)
    path = source / 'agent/current.json'; path.write_text('before')
    actual_copy = activation.shutil.copytree
    changed = False
    def concurrent_copy(*args, **kwargs):
        nonlocal changed
        result = actual_copy(*args, **kwargs)
        if not changed:
            path.write_text('concurrent update')
            changed = True
        return result
    monkeypatch.setattr(activation.shutil, 'copytree', concurrent_copy)
    with pytest.raises(AssertionError, match='Legacy state changed'):
        activation.replace_state(prep, work, identity)
    assert path.read_text() == 'concurrent update'


def test_atomic_config_failure_keeps_previous_credentials(activation, tmp_path):
    target = tmp_path / 'runtime.env'; target.write_text('original')
    def fail_write(path, data, gid):
        path.write_text('partial')
        raise OSError('injected disk failure')
    prep = SimpleNamespace(private_file=fail_write, env_bytes=lambda v: b'replacement')
    with pytest.raises(OSError):
        activation.replace_configuration(prep, target, {}, os.getgid())
    assert target.read_text() == 'original'
    assert list(tmp_path.iterdir()) == [target]


def test_runtime_unit_requires_database_probe_inside_same_sandbox(activation):
    root = Path(__file__).resolve().parents[2]
    template = (root / 'infra/systemos/opentracy-isolated.service.in').read_text()
    text = activation.unit_text(template, Path('/opt/release'), Path('/var/lib/work'), Path('/var/lib/home'),
        Path('/var/cache/app'), Path('/etc/runtime.env'), 'runtime', Path('/var/lib/deployment'), Path('/opt/tools/db.py'))
    assert 'ExecStartPre=/opt/release/.venv/bin/python /opt/tools/db.py' in text
    assert 'User=ligado-opentracy' in text
    assert 'ProtectHome=yes' in text and 'ProtectSystem=strict' in text
    assert '@' not in text
