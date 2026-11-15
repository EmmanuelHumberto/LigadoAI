import importlib.util
from pathlib import Path
import pytest

@pytest.fixture
def prep(monkeypatch,tmp_path):
    source=Path(__file__).resolve().parents[2]/"scripts/preparar-conta-opentracy.py"
    spec=importlib.util.spec_from_file_location("host_preparation",source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,"BASE",tmp_path)
    return module


def test_manifest_preserves_python_documents_but_excludes_legacy_storage_source(prep,tmp_path):
    source=tmp_path/'tenants/_default/corpora'
    (source/'ingested').mkdir(parents=True)
    (source/'store.py').write_text('# canonical implementation')
    (source/'ingested/calibration.py').write_text('# document supplied by operator')
    result=prep.state_manifest(tmp_path)
    assert 'tenants/_default/corpora/store.py' not in result
    assert 'tenants/_default/corpora/ingested/calibration.py' in result


def test_state_symlink_cannot_import_files_outside_application(prep,tmp_path):
    source=tmp_path/'agent';source.mkdir()
    (source/'escape').symlink_to('/etc/passwd')
    with pytest.raises(RuntimeError):prep.state_manifest(tmp_path)


def test_configuration_duplicates_cannot_silently_change_credentials(prep):
    assert prep.parse_env('KEY=value\nKEY=value\n')=={'KEY':'value'}
    with pytest.raises(AssertionError):prep.parse_env('KEY=first\nKEY=second\n')


def test_internal_dataset_pointer_is_preserved_in_manifest(prep,tmp_path):
    source=tmp_path/'datasets';source.mkdir()
    (source/'v1.json').write_text('{"version":1}')
    (source/'current').symlink_to('v1.json')
    result=prep.state_manifest(tmp_path)
    assert result['datasets/current']['link']=='v1.json'
    assert result['datasets/current']['targetSha256']==result['datasets/v1.json']
