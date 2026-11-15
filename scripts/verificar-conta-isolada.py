#!/usr/bin/env python3
"""Proof performed inside the exact service sandbox, without reading secret contents."""
import argparse
import grp
import json
import os
from pathlib import Path
import socket


def denied_read(path):
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return True
    os.close(descriptor)
    return False


def denied_write(path):
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    except OSError:
        return True
    os.close(descriptor)
    return False


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--release',required=True)
    parser.add_argument('--work',required=True)
    parser.add_argument('--report',required=True)
    args=parser.parse_args()
    release=Path(args.release).resolve();work=Path(args.work).resolve();report=Path(args.report)
    assert release.is_relative_to('/opt/ligado-opentracy/releases')
    assert work.is_relative_to('/var/lib/ligado-opentracy')
    assert report.parent.resolve()==work and not report.is_symlink()
    assert os.getuid()!=0 and os.getuid()!=1000
    assert grp.getgrnam('docker').gr_gid not in os.getgroups()
    if os.environ.get('OPENTRACY_ISOLATION_CANDIDATE')=='1':
        assert not any('DATABASE_URL' in key for key in os.environ)
        assert not os.environ.get('OPENTRACY_SYSTEMOS_READ_KEY')
    status=Path('/proc/self/status').read_text()
    assert 'NoNewPrivs:\t1' in status
    assert 'CapEff:\t0000000000000000' in status
    assert denied_read('/home/hiatus/.ssh/id_ed25519_systemos')
    assert denied_read('/home/hiatus/Projetos/ligadotattoo/OpenTracy/.env')
    assert denied_write(release/'runtime/server.py')
    assert denied_write(release/'.venv/pyvenv.cfg')
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        sock.connect('/run/docker.sock')
    except OSError:
        pass
    else:
        raise RuntimeError('Docker socket is accessible')
    finally:
        sock.close()
    probe=work/'.write-probe'
    fd=os.open(probe,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    os.close(fd);probe.unlink()
    import ledger.writer,corpora.store
    assert Path(ledger.writer.__file__).resolve().is_relative_to(release/'storage_packages')
    assert Path(corpora.store.__file__).resolve().is_relative_to(release/'storage_packages')
    assert ledger.writer._PROJECT_ROOT.resolve()==work
    result={'result':'PASSOU','uid':os.getuid(),'noDockerGroup':True,'dockerSocketDenied':True,
            'personalFilesDenied':True,'codeWriteDenied':True,'dependenciesWriteDenied':True,
            'stateWriteAllowed':True,'noNewPrivileges':True,'effectiveCapabilitiesEmpty':True,
            'storageSourceFromRelease':True}
    report.write_text(json.dumps(result));report.chmod(0o600)
    print(json.dumps(result))


if __name__=='__main__':main()
