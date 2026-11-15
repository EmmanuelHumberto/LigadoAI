#!/usr/bin/env python3
"""Prepare and test a dedicated application account; never switch live services."""
import argparse
import datetime
import grp
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shlex
import shutil
import socket
import subprocess
import tarfile
import time
import urllib.request

BASE=Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
ACCOUNT='ligado-opentracy'
TOP=Path('/var/lib/ligado-opentracy')
DATA=('agent','tenants','datasets','versions','evals/golden','evals/suites','evals/reports')
ALIASES={'agents':'tenants/_default/agents','ledger':'tenants/_default/ledger','corpora':'tenants/_default/corpora','traces':'tenants/_default/traces'}


def run(args,**kwargs):
    return subprocess.check_output(args,stderr=subprocess.DEVNULL,text=True,timeout=30,**kwargs).strip()


def git(*args,binary=False):
    args=['runuser','-u','hiatus','--','git','-C',str(BASE),*args]
    if binary:return subprocess.check_output(args,stderr=subprocess.DEVNULL,timeout=30)
    return run(args)


def user_systemctl(*args):
    return run(['runuser','-u','hiatus','--','env','XDG_RUNTIME_DIR=/run/user/1000','DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus','systemctl','--user',*args])


def private_file(path,data,gid=None):
    assert not path.exists() and not path.is_symlink()
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o750)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o640 if gid is not None else 0o600)
    with os.fdopen(fd,'wb') as handle:handle.write(data);handle.flush();os.fsync(handle.fileno())
    if gid is not None:os.chown(path,0,gid)


def parse_env(text):
    values={}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:continue
        key,value=line.split('=',1)
        key=key.strip();value=value.strip().strip('"').strip("'")
        assert re.fullmatch('[A-Za-z_][A-Za-z0-9_]*',key)
        assert key not in values or values[key]==value, "Conflicting duplicate configuration key"
        values[key]=value
    return values


def env_bytes(values):
    return ''.join(key+'='+json.dumps(value,ensure_ascii=False)+'\n' for key,value in sorted(values.items())).encode()


def copied_code(relative):
    parts=Path(relative).parts
    known={'ledger/__init__.py','ledger/types.py','ledger/writer.py','ledger/versioning.py',
           'corpora/__init__.py','corpora/memory_store.py','corpora/store.py','corpora/ingest.py',
           'corpora/tests/__init__.py','corpora/tests/test_ingest_and_store.py'}
    return len(parts)>2 and parts[0]=='_default' and '/'.join(parts[1:]) in known


def state_manifest(source):
    result={}
    for part in DATA:
        folder=source/part
        if not folder.exists():continue
        assert folder.resolve().is_relative_to(BASE)
        for file in sorted(folder.rglob('*')):
            if '__pycache__' in file.parts:continue
            if part=='tenants' and copied_code(file.relative_to(folder).as_posix()):continue
            if file.is_symlink():
                target=file.readlink()
                if target.is_absolute() or not file.resolve().is_relative_to(folder.resolve()) or not file.resolve().is_file():
                    raise RuntimeError('Unsafe state symlink; inspect before migration')
                result[part+'/'+file.relative_to(folder).as_posix()]={'link':str(target),'targetSha256':hashlib.sha256(file.read_bytes()).hexdigest()}
            elif file.is_file():result[part+'/'+file.relative_to(folder).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit',required=True)
    args=parser.parse_args();sha=args.expected_commit
    if os.geteuid()!=0:raise SystemExit('Execute com sudo no terminal Linux; nao envie a senha pelo chat.')
    assert re.fullmatch('[0-9a-f]{40}',sha)
    assert git('rev-parse','HEAD')==sha and not git('status','--porcelain')
    assert git('ls-remote','origin','refs/heads/main').split()[0]==sha
    assert git('show',sha+':scripts/preparar-conta-opentracy.py')==Path(__file__).read_text().strip()
    assert shutil.disk_usage('/var/lib').free>512*1024*1024,'Insufficient free disk space'
    original_pids={unit:user_systemctl('show',unit,'-p','MainPID','--value') for unit in ('opentracy-systemos','opentracy-systemos-gateway')}
    assert all(int(value)>0 for value in original_pids.values())
    for port in (18011,18012):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',port))
    # Positive controls prevent mistaking nonexistent paths for successful isolation.
    for path in (BASE/'.env',Path('/home/hiatus/.config/ligado-vps-tunnel/id_ed25519')):
        assert path.is_file()
        descriptor=os.open(path,os.O_RDONLY);os.close(descriptor)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as docker_control:
        docker_control.connect('/run/docker.sock')
    source_before=state_manifest(BASE)
    release=Path('/opt/ligado-opentracy/releases')/sha
    deployment=TOP/'deployments'/sha
    work=TOP/('work-'+sha[:12])
    home=TOP/('home-'+sha[:12]);cache=Path('/var/cache/ligado-opentracy')/sha[:12]
    assert not any(path.exists() or path.is_symlink() for path in (release,deployment,work,home,cache))
    try:pwd.getpwnam(ACCOUNT)
    except KeyError:
        subprocess.run(['useradd','--system','--user-group','--home-dir',str(TOP),'--no-create-home','--shell','/usr/sbin/nologin',ACCOUNT],check=True,capture_output=True)
    identity=pwd.getpwnam(ACCOUNT)
    assert identity.pw_shell=='/usr/sbin/nologin' and identity.pw_uid not in (0,1000) and identity.pw_dir==str(TOP)
    assert set(os.getgrouplist(ACCOUNT,identity.pw_gid))=={identity.pw_gid}
    assert grp.getgrnam('docker').gr_gid!=identity.pw_gid
    assert grp.getgrgid(identity.pw_gid).gr_name==ACCOUNT
    for parent in (Path('/opt/ligado-opentracy'),TOP,Path('/var/cache/ligado-opentracy')):
        if parent.exists():assert not parent.is_symlink() and parent.stat().st_uid==0
    for directory in [release,deployment,work,home,cache]:directory.mkdir(parents=True,mode=0o750)
    release.chmod(0o755);release.parent.chmod(0o755);release.parent.parent.chmod(0o755);TOP.chmod(0o755)
    with tarfile.open(fileobj=io.BytesIO(git('archive',sha,binary=True))) as archive:
        archive.extractall(release,filter='data')
    for folder in (work,home,cache):os.chown(folder,identity.pw_uid,identity.pw_gid);folder.chmod(0o700)
    for part in DATA:
        source=BASE/part;target=work/part
        if source.exists():
            def ignore(directory,names):
                skipped=[name for name in names if name=='__pycache__']
                if part=='tenants':
                    skipped += [name for name in names if copied_code((Path(directory)/name).relative_to(source).as_posix())]
                return skipped
            shutil.copytree(source,target,ignore=ignore,dirs_exist_ok=True,symlinks=True)
        else:target.mkdir(parents=True,exist_ok=True)
    for name,target in ALIASES.items():(work/name).symlink_to(target,target_is_directory=True)
    for name in ('agent','tenants','datasets','versions'):
        dest=release/name
        if dest.is_symlink():dest.unlink()
        elif dest.is_dir():shutil.rmtree(dest)
        dest.symlink_to(work/name,target_is_directory=True)
    for part in ('evals/golden','evals/suites','evals/reports'):
        dest=release/part
        if dest.exists():shutil.rmtree(dest)
        dest.symlink_to(work/part,target_is_directory=True)
    for entry in release.iterdir():
        if entry.name.startswith('.') or (work/entry.name).exists() or (work/entry.name).is_symlink():continue
        (work/entry.name).symlink_to(entry,target_is_directory=entry.is_dir())
    # Source-only directories remain root-owned; only state/home/cache are writable.
    for root in (work,home,cache):
        for path in [root,*root.rglob('*')]:
            if path.is_symlink():continue
            os.chown(path,identity.pw_uid,identity.pw_gid);path.chmod(0o700 if path.is_dir() else 0o600)
    for name in ('.venv','.hf/hub','backend/node_modules'):
        target=release/name
        if target.is_symlink():target.unlink()
        target.mkdir(parents=True,exist_ok=True)
    source_after=state_manifest(BASE)
    assert source_before==source_after,'Live state changed during snapshot; preparation deferred'
    for relative,digest in source_before.items():
        destination=work/relative
        if isinstance(digest,dict):
            assert destination.is_symlink() and str(destination.readlink())==digest['link']
            assert hashlib.sha256(destination.read_bytes()).hexdigest()==digest['targetSha256']
        else:
            assert not destination.is_symlink() and hashlib.sha256(destination.read_bytes()).hexdigest()==digest
    # Keep a fresh private copy for later activation, never load these secrets in the candidate.
    runtime=parse_env((BASE/'.env').read_text())
    overrides=dict(value.split('=',1) for value in shlex.split(user_systemctl('show','opentracy-systemos','-p','Environment','--value')) if '=' in value)
    runtime.update(overrides)
    runtime.update(OPENTRACY_STATE_ROOT=str(work),OPENTRACY_RUNTIME_HOST='127.0.0.1',OPENTRACY_RUNTIME_PORT='8001',OPENTRACY_RUNTIME_SECURITY='required',OPENTRACY_SOURCE_COMMIT=sha)
    gateway={key:runtime[key] for key in ('BACKEND_API_KEYS','SYSTEMOS_COGNITIVE_TOKEN','OPENTRACY_RUNTIME_INTERNAL_TOKEN','OPENTRACY_RUNTIME_SECURITY','OPENTRACY_KNOWLEDGE_AUTH_TOKEN','OPENTRACY_COUS_V3_AUTH_TOKEN') if key in runtime}
    gateway.update(RUNTIME_URL='http://127.0.0.1:8001',PORT='8002',OPENTRACY_AGENTS_ROOT=str(work/'agents'),OPENTRACY_SOURCE_COMMIT=sha)
    private_file(deployment/'runtime.env',env_bytes(runtime),identity.pw_gid)
    private_file(deployment/'gateway.env',env_bytes(gateway),identity.pw_gid)
    # EnvironmentFile is read by the root manager; Node needs a separate readable copy.
    candidate_env=Path('/etc/ligado-opentracy')/('candidate-'+sha[:12]+'.env')
    candidate_env.parent.mkdir(mode=0o750,parents=True,exist_ok=True);os.chown(candidate_env.parent,0,identity.pw_gid)
    token=secrets.token_hex(32)
    candidate={'OPENTRACY_ISOLATION_CANDIDATE':'1','OPENTRACY_STATE_ROOT':str(work),'OPENTRACY_RUNTIME_SECURITY':'required','OPENTRACY_RUNTIME_INTERNAL_TOKEN':token,'BACKEND_API_KEYS':token,
               'SYSTEMOS_COGNITIVE_TOKEN':token,'OPENTRACY_KNOWLEDGE_AUTH_TOKEN':token,'OPENTRACY_MEASUREMENTS_AUTH_TOKEN':token,
               'OPENTRACY_KNOWLEDGE_BACKEND':'memory','OPENTRACY_MEASUREMENTS_BACKEND':'memory','OPENTRACY_COUS_V3_ENABLED':'0',
               'OPENTRACY_DIAGNOSIS_ENABLED':'0','OPENTRACY_DIAGNOSIS_WORKER_ENABLED':'0','OPENTRACY_RUNTIME_PORT':'18011','OPENTRACY_RUNTIME_HOST':'127.0.0.1',
               'PORT':'18012','RUNTIME_URL':'http://127.0.0.1:18011','OPENTRACY_AGENTS_ROOT':str(work/'agents')}
    private_file(candidate_env,env_bytes(candidate),identity.pw_gid)
    template=(release/'infra/systemos/opentracy-isolated.service.in').read_text()
    units=[];reports={}
    try:
        for component in ('runtime','gateway'):
            unit='ligado-opentracy-candidate-'+component+'.service'
            target=Path('/run/systemd/system')/unit;assert not target.exists()
            execution=str(release/'.venv/bin/python')+' -m runtime.server' if component=='runtime' else '/usr/bin/node --env-file='+str(candidate_env)+' --import tsx api/server.ts'
            values={'DESCRIPTION':'OpenTracy isolated candidate '+component,'RELEASE':str(release),'WORK':str(work),'WORKDIR':str(work if component=='runtime' else release/'backend'),
                    'ENVFILE':str(candidate_env),'HOME':str(home),'CACHE':str(cache),'REPORT':component+'-isolation.json','EXEC':execution,
                    'EXTRA_DENY':'InaccessiblePaths='+str(deployment)}
            text=template
            for key,value in values.items():text=text.replace('@'+key+'@',value)
            assert not re.search(r'@[A-Z_]+@',text)
            text=text.replace('Restart=on-failure','Restart=no')
            private_file(target,text.encode());units.append(unit)
        run(['systemctl','daemon-reload'])
        for component,port in [('runtime',18011),('gateway',18012)]:
            unit='ligado-opentracy-candidate-'+component+'.service'
            run(['systemctl','start',unit])
            for attempt in range(30):
                try:
                    with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/health',timeout=2) as response:
                        if response.status==200:break
                except Exception:time.sleep(0.5)
            else:raise RuntimeError('Candidate health unavailable')
            reports[component]=json.loads((work/(component+'-isolation.json')).read_text())
            assert reports[component]['result']=='PASSOU'
        for port,path in [(18011,'/agent/config'),(18012,'/v1/agent/config')]:
            request=urllib.request.Request('http://127.0.0.1:'+str(port)+path,headers={'authorization':'Bearer '+token})
            with urllib.request.urlopen(request,timeout=5) as response:assert response.status==200
        assert original_pids=={unit:user_systemctl('show',unit,'-p','MainPID','--value') for unit in original_pids}
        result={'result':'READY_NOT_ACTIVATED','sourceCommit':sha,'executedAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'account':ACCOUNT,'componentIsolationProofs':reports,'candidateRuntimeHealth':200,'candidateGatewayHealth':200,
                'stateFilesVerified':len(source_before),'productionServicesUnchanged':True,'candidateDatabaseCredentialsProvided':False,
                'dependenciesCopied':False,'sharedApplicationAccount':True,'hostPositiveControlsVerified':True}
        private_file(deployment/'result.json',json.dumps(result,indent=2).encode())
        private_file(deployment/'manifest.json',json.dumps({'sourceCommit':sha,'release':str(release),'work':str(work),'home':str(home),'cache':str(cache),'account':ACCOUNT,'stateSha256':source_before},indent=2).encode())
        print(json.dumps(result,indent=2))
    except Exception:
        # Candidate logs contain synthetic credentials only; keep them private for diagnostics.
        logs=subprocess.run(['journalctl','-u','ligado-opentracy-candidate-runtime','-u','ligado-opentracy-candidate-gateway','--no-pager','-n','40'],capture_output=True,text=True)
        private_file(deployment/'candidate-errors.log',logs.stdout.encode())
        print(json.dumps({'result':'PREPARATION_INCOMPLETE','sourceCommit':sha,'productionServicesChanged':False,'diagnosticFile':str(deployment/'candidate-errors.log')}))
        raise
    finally:
        for unit in reversed(units):
            subprocess.run(['systemctl','stop',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
            path=Path('/run/systemd/system')/unit
            if path.exists():path.unlink()
        subprocess.run(['systemctl','daemon-reload'],capture_output=True,timeout=20)


if __name__=='__main__':main()
