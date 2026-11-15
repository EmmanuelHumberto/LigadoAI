import json
import os
from pathlib import Path
import subprocess
import sys


def test_storage_code_is_recoverable_without_legacy_tenant_python_files(tmp_path):
    root=Path(__file__).resolve().parents[2]
    work=tmp_path/'work';work.mkdir()
    (work/'ledger').mkdir();(work/'corpora').mkdir()
    env=os.environ.copy()
    env['PYTHONPATH']=str(root/'storage_packages')+os.pathsep+str(root)
    env['OPENTRACY_STATE_ROOT']=str(work)
    code="import json,ledger.writer,corpora.store; print(json.dumps({'ledger':ledger.writer.__file__,'corpora':corpora.store.__file__,'state':str(ledger.writer._PROJECT_ROOT)}))"
    r=subprocess.run([sys.executable,'-c',code],cwd=work,env=env,capture_output=True,text=True,check=True)
    data=json.loads(r.stdout)
    assert Path(data['ledger']).is_relative_to(root/'storage_packages')
    assert Path(data['corpora']).is_relative_to(root/'storage_packages')
    assert Path(data['state'])==work
