#!/usr/bin/env python3
"""Add precisely one loopback API destination to the existing SSH tunnel key."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source-commit',required=True)
    parser.add_argument('--expected-script-sha256',required=True)
    args=parser.parse_args()
    assert os.geteuid()==0 and re.fullmatch('[a-f0-9]{40}',args.source_commit)
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest()==args.expected_script_sha256
    path=Path('/home/ligadoassist/.ssh/authorized_keys')
    assert path.is_file() and not path.is_symlink()
    before=path.read_bytes();text=before.decode()
    old='restrict,port-forwarding,permitlisten="127.0.0.1:18002",permitopen="127.0.0.1:11434",command="/usr/sbin/nologin" '
    new=old.replace(',command=',',permitopen="127.0.0.1:3001",command=')
    assert sum(line.startswith(old+'ssh-ed25519 ') for line in text.splitlines())==1
    changed=text.replace(old+'ssh-ed25519 ',new+'ssh-ed25519 ',1).encode()
    folder=Path('/var/lib/ligado-security/opentracy-api-forward')/args.source_commit
    folder.mkdir(parents=True,mode=0o700,exist_ok=False)
    backup=folder/'authorized_keys.before';backup.write_bytes(before);backup.chmod(0o600)
    state=path.stat();temp=path.with_name('authorized_keys.systemos-forward')
    assert not temp.exists()
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'wb') as output:output.write(changed);output.flush();os.fsync(output.fileno())
    os.chown(temp,state.st_uid,state.st_gid)
    try:
        subprocess.run(['ssh-keygen','-lf',str(temp)],check=True,capture_output=True)
        assert path.read_bytes()==before
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)
    result=dict(result='APPLIED',sourceCommit=args.source_commit,addedDestination='127.0.0.1:3001',
                sshRestarted=False,previousSha256=hashlib.sha256(before).hexdigest(),
                currentSha256=hashlib.sha256(changed).hexdigest(),executedAt=datetime.datetime.now(datetime.timezone.utc).isoformat())
    receipt=folder/'result.json';receipt.write_text(json.dumps(result,indent=2));receipt.chmod(0o600)
    print(json.dumps(result))


if __name__=='__main__':main()
