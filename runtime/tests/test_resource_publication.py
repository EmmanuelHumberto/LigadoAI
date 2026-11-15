import importlib.util
from pathlib import Path
from urllib.parse import urlsplit
import pytest


def load():
    path=Path(__file__).resolve().parents[2]/'scripts/publicar-recursos-opentracy.py'
    spec=importlib.util.spec_from_file_location('resource_publication',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_runtime_credentials_become_non_owner_and_systemos_uses_private_forward():
    policy=load();original=dict(OPENTRACY_COUS_V3_DATABASE_URL='postgresql://ligadoai:old@127.0.0.1/ligadoai',
        OPENTRACY_MEASUREMENTS_DATABASE_URL='postgresql://ligadoai:old@localhost/ligadoai',BACKEND_API_KEYS='operator')
    updated=policy.runtime_environment(original,Path('/var/lib/state'),'a'*40,'b'*64)
    for key in ('OPENTRACY_COUS_V3_DATABASE_URL','OPENTRACY_MEASUREMENTS_DATABASE_URL'):
        parsed=urlsplit(updated[key]);assert parsed.username=='opentracy_runtime' and parsed.password=='b'*64
    assert updated['OPENTRACY_STATE_ROOT']=='/var/lib/state'
    assert updated['OPENTRACY_SOURCE_COMMIT']=='a'*40
    assert updated['OPENTRACY_SYSTEMOS_URL']=='http://127.0.0.1:13301/api/v1'
    assert updated['OPENTRACY_EGRESS_REQUIRED']=='1'
    assert updated['OPENTRACY_DIAGNOSIS_MAX_CONCURRENT']=='2'
    assert original['OPENTRACY_COUS_V3_DATABASE_URL'].startswith('postgresql://ligadoai:old')


@pytest.mark.parametrize('dsn',['postgresql://owner:old@remote.example/ligadoai',
    'postgresql://owner:old@127.0.0.1/another_database',
    'postgresql://owner:old@127.0.0.1/ligadoai?user=ligadoai'])
def test_unknown_database_destination_or_credential_override_is_refused(dsn):
    with pytest.raises(AssertionError):load().runtime_environment({'DATABASE_URL':dsn},Path('/state'),'a'*40,'b'*64)


def test_partial_atomic_write_preserves_active_configuration(tmp_path,monkeypatch):
    policy=load();target=tmp_path/'active';target.write_bytes(b'previous')
    actual_fsync=policy.os.fsync
    def fail(fd):raise OSError('injected filesystem failure')
    monkeypatch.setattr(policy.os,'fsync',fail)
    with pytest.raises(OSError):policy.replace(target,b'new')
    assert target.read_bytes()==b'previous'
