#!/usr/bin/env python3
"""Functional IPv4/IPv6 egress proof in a disposable network namespace only."""
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading


class Sink(socketserver.BaseRequestHandler):
    def handle(self):self.request.sendall(b'ok')


class V6Server(socketserver.ThreadingTCPServer):
    address_family=socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,1)
        super().server_bind()


def run(*args,input=None):
    return subprocess.run(args,input=input,text=True,check=True,capture_output=True)


def connects(host,port):
    try:
        with socket.create_connection((host,port),timeout=1) as conn:return conn.recv(2)==b'ok'
    except OSError:return False


def main():
    assert os.geteuid()==0
    assert Path('/proc/self/uid_map').read_text().split()[2]=='1'
    assert len(sys.argv)==2 and sys.argv[1].startswith('net:[')
    assert os.readlink('/proc/self/ns/net')!=sys.argv[1], 'Host namespace forbidden'
    run('ip','link','set','lo','up')
    run('ip','addr','add','10.231.92.1/32','dev','lo')
    run('ip','-6','addr','add','fd42:231:92::1/128','dev','lo','nodad')
    servers=[]
    try:
        for cls,address in [(socketserver.ThreadingTCPServer,('0.0.0.0',5432)),
            (socketserver.ThreadingTCPServer,('0.0.0.0',8080)),(V6Server,('::',5432)),(V6Server,('::',8080))]:
            server=cls(address,Sink);servers.append(server)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        assert connects('10.231.92.1',8080) and connects('fd42:231:92::1',8080)
        assert connects('127.0.0.1',5432) and connects('::1',5432)
        template=(Path(__file__).resolve().parents[1]/'infra/systemos/opentracy-egress.nft.in').read_text()
        # A policy for another UID must not affect this client's connections.
        run('/usr/sbin/nft','-f','-',input=template.replace('@UID@','424242'))
        assert connects('10.231.92.1',8080)
        run('/usr/sbin/nft','delete','table','inet','ligado_opentracy_egress')
        policy=template.replace('@UID@','0')
        run('/usr/sbin/nft','-c','-f','-',input=policy);run('/usr/sbin/nft','-f','-',input=policy)
        assert not connects('10.231.92.1',8080)
        assert not connects('fd42:231:92::1',8080)
        assert not connects('127.0.0.1',8080)
        assert not connects('::1',8080)
        assert connects('127.0.0.1',5432) and connects('::1',5432)
        run('/usr/sbin/nft','delete','table','inet','ligado_opentracy_egress')
        assert connects('10.231.92.1',8080) and connects('fd42:231:92::1',8080)
        print(json.dumps(dict(result='PASSOU',hostFirewallChanged=False,ipv4Denied=True,ipv6Denied=True,
            unexpectedLoopbackPortDenied=True,allowedLoopbackVerified=True,otherUidPreserved=True,rollbackVerified=True)))
    finally:
        for server in servers:server.shutdown();server.server_close()


if __name__=='__main__':main()
