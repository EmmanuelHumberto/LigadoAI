#!/usr/bin/env python3
"""Publish Git-bound queue, least-privilege DB and UID egress guards.

Uses the existing writable state and restores original source links on failure;
never returns to the obsolete pre-isolation state in the user's home directory.
"""
import argparse
import datetime
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import re
import secrets
import shutil
import signal
import socket
import subprocess
import tarfile
import urllib.parse
import urllib.request

BASE=Path('/home/hiatus/Projetos/ligadotattoo/OpenTracy')
TOP=Path('/var/lib/ligado-opentracy')
OLD='ff858d329c66049f97186f29ef621de12329e3ca'
ROLE='opentracy_runtime'
MARKER=Path('/etc/ligado-opentracy-production-active')
UNITS=('ligado-opentracy-runtime','ligado-opentracy-gateway')
TUNNEL_DROP=Path('/home/hiatus/.config/systemd/user/opentracy-vps-tunnel.service.d/80-private-systemos-api.conf')
RULES=Path('/etc/ligado-security/opentracy-egress.nft')
FIREWALL=Path('/etc/systemd/system/ligado-opentracy-egress.service')


def load(name,relative):
    spec=importlib.util.spec_from_file_location(name,BASE/relative)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def run(args,**kwargs):
    result=subprocess.run(args,capture_output=True,text=True,timeout=45,**kwargs)
    if result.returncode:
        raise RuntimeError('Command failed: '+args[0])
    return result.stdout.strip()


def sql(text):
    return run(['runuser','-u','postgres','--','psql','-X','-v','ON_ERROR_STOP=1','-At','-d','ligadoai'],input=text)


def replace(path,data,mode=0o600):
    assert not path.is_symlink()
    temporary=path.with_name(path.name+'.'+secrets.token_hex(6))
    try:
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,mode)
        with os.fdopen(fd,'wb') as output:output.write(data);output.flush();os.fsync(output.fileno())
        temporary.replace(path)
    finally:temporary.unlink(missing_ok=True)


def role_policy(password):
    assert re.fullmatch('[a-f0-9]{64}',password)
    existing=sql("SELECT COALESCE(shobj_description(oid,'pg_authid'),'') FROM pg_roles WHERE rolname='opentracy_runtime'")
    exists=sql("SELECT count(*) FROM pg_roles WHERE rolname='opentracy_runtime'")=='1'
    assert not exists or existing=='Ligado isolated runtime policy v1', 'Unmanaged role; inspect first'
    create=('ALTER' if exists else 'CREATE')+" ROLE opentracy_runtime LOGIN PASSWORD '"+password+"' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT CONNECTION LIMIT 24;"
    sql("BEGIN; "+create+"""
        COMMENT ON ROLE opentracy_runtime IS 'Ligado isolated runtime policy v1';
        GRANT CONNECT ON DATABASE ligadoai TO opentracy_runtime;
        REVOKE CREATE ON SCHEMA public FROM PUBLIC, opentracy_runtime;
        GRANT USAGE ON SCHEMA public TO opentracy_runtime;
        GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO opentracy_runtime;
        GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO opentracy_runtime;
        ALTER DEFAULT PRIVILEGES FOR ROLE ligadoai IN SCHEMA public GRANT SELECT,INSERT,UPDATE,DELETE ON TABLES TO opentracy_runtime;
        ALTER DEFAULT PRIVILEGES FOR ROLE ligadoai IN SCHEMA public GRANT USAGE,SELECT ON SEQUENCES TO opentracy_runtime;
        ALTER ROLE opentracy_runtime SET statement_timeout='30s';
        ALTER ROLE opentracy_runtime SET lock_timeout='5s';
        ALTER ROLE opentracy_runtime SET idle_in_transaction_session_timeout='30s';
        ALTER ROLE ligadoai NOCREATEDB;
        COMMIT;
    """)
    assert sql("SELECT count(*) FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='opentracy_runtime')")=='0'
    assert sql("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND p.prosecdef AND has_function_privilege('opentracy_runtime',p.oid,'EXECUTE')")=='0'


def runtime_environment(values,work,sha,password):
    result=dict(values)
    for key,value in list(result.items()):
        if 'DATABASE_URL' not in key or not value:continue
        parsed=urllib.parse.urlsplit(value)
        assert parsed.hostname in ('127.0.0.1','localhost','::1') and parsed.path=='/ligadoai'
        assert not any(key.lower() in ('user','password','dbname','database','host','port') for key,value in urllib.parse.parse_qsl(parsed.query))
        host='['+parsed.hostname+']' if ':' in parsed.hostname else parsed.hostname
        result[key]=urllib.parse.urlunsplit((parsed.scheme,ROLE+':'+password+'@'+host+':'+str(parsed.port or 5432),parsed.path,parsed.query,''))
    result.update(OPENTRACY_STATE_ROOT=str(work),OPENTRACY_SOURCE_COMMIT=sha,OPENTRACY_DATABASE_ROLE_REQUIRED=ROLE,
        OPENTRACY_SYSTEMOS_URL='http://127.0.0.1:13301/api/v1',OPENTRACY_DIAGNOSIS_MAX_CONCURRENT='2',
        OPENTRACY_DIAGNOSIS_QUEUE_CAPACITY='100',OPENTRACY_DIAGNOSIS_CALLBACK_ATTEMPTS='8',OPENTRACY_EGRESS_REQUIRED='1')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-commit',required=True)
    args=parser.parse_args();sha=args.expected_commit
    assert os.geteuid()==0 and re.fullmatch('[a-f0-9]{40}',sha)
    prep=load('preparation','scripts/preparar-conta-opentracy.py')
    activation=load('activation','scripts/ativar-conta-opentracy.py')
    assert prep.git('rev-parse','HEAD')==sha and not prep.git('status','--porcelain')
    assert prep.git('ls-remote','origin','refs/heads/main').split()[0]==sha
    assert prep.git('show',sha+':scripts/publicar-recursos-opentracy.py')==Path(__file__).read_text().strip()
    assert MARKER.read_text().strip()==OLD
    assert all(run(['systemctl','is-active',unit])=='active' for unit in UNITS)
    assert all(run(['systemctl','show',unit,'-p','User','--value'])=='ligado-opentracy' for unit in UNITS)
    assert not TUNNEL_DROP.exists() and not RULES.exists() and not FIREWALL.exists()
    assert shutil.disk_usage(TOP).free>512*1024*1024
    oldrelease=Path('/opt/ligado-opentracy/releases')/OLD
    work=TOP/('work-'+OLD[:12]);home=TOP/('home-'+OLD[:12]);cache=Path('/var/cache/ligado-opentracy')/OLD[:12]
    identity=pwd.getpwnam('ligado-opentracy')
    assert identity.pw_uid not in (0,1000)
    operation=TOP/'resource-publications'/sha;operation.mkdir(parents=True,mode=0o700,exist_ok=False)
    unitpaths=[Path('/etc/systemd/system')/(unit+'.service') for unit in UNITS]
    originals={path:path.read_bytes() for path in unitpaths}
    for i,path in enumerate(unitpaths):prep.private_file(operation/('unit-'+str(i)+'.before'),originals[path])
    # Existing effective credentials stay private and are replaced only in new files.
    envpaths=[Path('/etc/ligado-opentracy/production-'+component+'-afb14357d732.env') for component in ('runtime','gateway')]
    values=prep.parse_env(envpaths[0].read_text())
    activation.queue_idle(values)
    # Host positive controls distinguish enforced denial from an unavailable service.
    for destination in (('127.0.0.1',22),('179.66.130.52',22)):
        with socket.create_connection(destination,timeout=4):pass
    password=secrets.token_hex(32)
    role_policy(password)
    release=Path('/opt/ligado-opentracy/releases')/sha
    assert not release.exists();release.mkdir(mode=0o755)
    with tarfile.open(fileobj=io.BytesIO(prep.git('archive',sha,binary=True))) as archive:archive.extractall(release,filter='data')
    for name in ('agent','tenants','datasets','versions','evals/golden','evals/suites','evals/reports'):
        target=release/name
        if target.is_symlink():target.unlink()
        elif target.exists():shutil.rmtree(target)
        target.symlink_to(work/name,target_is_directory=True)
    for name in ('.venv','.hf/hub','backend/node_modules'):
        target=release/name
        if target.is_symlink():target.unlink()
        target.mkdir(parents=True,exist_ok=True)
    envs=[Path('/etc/ligado-opentracy')/('resources-'+component+'-'+sha[:12]+'.env') for component in ('runtime','gateway')]
    runtime=runtime_environment(values,work,sha,password)
    gateway=activation.gateway_environment(runtime,work);gateway.update(PORT='8002',OPENTRACY_SOURCE_COMMIT=sha)
    for path,env in zip(envs,(runtime,gateway)):prep.private_file(path,prep.env_bytes(env),identity.pw_gid)
    aliases={path:path.readlink() for path in work.iterdir() if path.is_symlink() and path.readlink().is_absolute() and path.readlink().is_relative_to(oldrelease)}
    assert work/'runtime' in aliases
    started=False;network_installed=False;tunnel_installed=False
    def interrupted(signum,frame):raise KeyboardInterrupt('Publication interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        started=True
        run(['systemctl','stop',UNITS[1]]);activation.queue_idle(values)
        run(['systemctl','stop',UNITS[0]]);activation.queue_idle(values)
        # All runtime state remains in the same directory, including rollback writes.
        for path,old in aliases.items():path.unlink();path.symlink_to(release/old.relative_to(oldrelease),target_is_directory=True)
        TUNNEL_DROP.parent.mkdir(parents=True,exist_ok=True,mode=0o755);TUNNEL_DROP.parent.chmod(0o755)
        prep.private_file(TUNNEL_DROP,(release/'infra/systemos/opentracy-tunnel-systemos.conf').read_bytes());TUNNEL_DROP.chmod(0o644)
        tunnel_installed=True
        prep.user_systemctl('daemon-reload');prep.user_systemctl('restart','opentracy-vps-tunnel')
        for attempt in range(30):
            try:
                request=urllib.request.Request('http://127.0.0.1:13301/api/v1/integracoes/cognicao/ordens/1156',headers={'x-cognitive-read-key':runtime['OPENTRACY_SYSTEMOS_READ_KEY']})
                with urllib.request.urlopen(request,timeout=3) as response:
                    assert response.status==200
                break
            except Exception:
                __import__('time').sleep(0.5)
        else:raise RuntimeError('Private SystemOS read unavailable')
        RULES.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
        prep.private_file(RULES,(release/'infra/systemos/opentracy-egress.nft.in').read_text().replace('@UID@',str(identity.pw_uid)).encode())
        prep.private_file(FIREWALL,(release/'infra/systemos/opentracy-egress.service').read_bytes())
        network_installed=True
        run(['/usr/sbin/nft','-c','-f',str(RULES)])
        template=(release/'infra/systemos/opentracy-isolated.service.in').read_text()
        for path,component,envfile in zip(unitpaths,('runtime','gateway'),envs):
            text=activation.unit_text(template,release,work,home,cache,envfile,component,operation,release/'scripts/verificar-banco-isolado.py')
            guard=(release/'infra/systemos/opentracy-egress-require.conf').read_text().split('[Unit]\n',1)[1]
            text=text.replace('[Unit]\n','[Unit]\n'+guard,1)
            replace(path,text.encode())
        run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','ligado-opentracy-egress'])
        run(['systemctl','start',UNITS[0]]);activation.health(8001)
        token=runtime['BACKEND_API_KEYS'].split(',')[0].strip();knowledge=runtime['OPENTRACY_KNOWLEDGE_AUTH_TOKEN']
        assert activation.http_status(8001,'/agent/config',token)==200
        assert activation.http_status(8001,'/agent/config',knowledge)==200
        run(['systemctl','start',UNITS[1]]);activation.health(8002)
        activation.verify_gateway_contract(8002,token,knowledge)
        # Actual UID policy and least-privilege database proof already ran at ExecStartPre.
        assert run(['systemctl','is-active','ligado-opentracy-egress'])=='active'
        replace(MARKER,(sha+'\n').encode(),0o644)
        result=dict(result='PUBLISHED',sourceCommit=sha,previousSource=OLD,account=identity.pw_name,
            databaseRole=ROLE,ownerCreatedbRemoved=True,egressRestricted=True,privateSystemosRead=True,
            maxConcurrentDiagnoses=2,queueCapacity=100,maxCallbackAttempts=8,
            stateDirectoryUnchanged=True,cousRestarted=False,financialOperationExecuted=False,
            executedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException:
        if started:
            for unit in reversed(UNITS):subprocess.run(['systemctl','stop',unit],capture_output=True,timeout=30)
            for path,old in aliases.items():
                if path.is_symlink():path.unlink()
                path.symlink_to(old,target_is_directory=True)
            for path,data in originals.items():replace(path,data)
            if network_installed:
                subprocess.run(['systemctl','disable','--now','ligado-opentracy-egress'],capture_output=True,timeout=20)
                RULES.unlink(missing_ok=True);FIREWALL.unlink(missing_ok=True)
            if tunnel_installed:
                TUNNEL_DROP.unlink();prep.user_systemctl('daemon-reload');prep.user_systemctl('restart','opentracy-vps-tunnel')
            run(['systemctl','daemon-reload'])
            run(['systemctl','start',UNITS[0]]);activation.health(8001)
            run(['systemctl','start',UNITS[1]]);activation.health(8002)
        logs=subprocess.run(['journalctl','-u',UNITS[0],'-u',UNITS[1],'-u','ligado-opentracy-egress','--no-pager','-n','80'],capture_output=True)
        prep.private_file(operation/'errors.log',logs.stdout)
        result=dict(result='ROLLED_BACK',sourceCommit=OLD,stateDirectoryUnchanged=True,diagnosticFile=str(operation/'errors.log'))
        prep.private_file(operation/'result.json',json.dumps(result,indent=2).encode())
        print(json.dumps(result));raise
    prep.private_file(operation/'result.json',json.dumps(result,indent=2).encode())
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
