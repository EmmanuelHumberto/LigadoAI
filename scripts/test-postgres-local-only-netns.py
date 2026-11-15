#!/usr/bin/env python3
"""Real TCP firewall test inside disposable user/network namespaces only."""
import json
import os
from pathlib import Path
import socket
import socketserver
import subprocess
import sys
import threading
import time


def run(args):
    return subprocess.check_output(args, text=True).strip()


class Sink(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b"ok")


class V6Server(socketserver.ThreadingTCPServer):
    address_family = socket.AF_INET6
    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


def main():
    assert os.geteuid() == 0
    assert Path('/proc/self/uid_map').read_text().split()[2] == '1', 'Run only with unshare --user --map-root-user --net'
    assert len(sys.argv) == 2 and sys.argv[1].startswith('net:['), 'Pass original network namespace identity'
    assert os.readlink('/proc/self/ns/net') != sys.argv[1], 'Host network forbidden'
    policy = Path(__file__).resolve().parent.parent / 'infra/systemos/postgres-local-only.nft'
    run(['ip', 'link', 'set', 'lo', 'up'])
    child = subprocess.Popen(['unshare', '--net', 'sleep', '60'])
    servers = []
    try:
        for attempt in range(100):
            if os.readlink('/proc/' + str(child.pid) + '/ns/net') != os.readlink('/proc/self/ns/net'):
                break
            time.sleep(0.01)
        else:
            raise RuntimeError('Client network namespace not ready')
        run(['ip', 'link', 'add', 'pg-host', 'type', 'veth', 'peer', 'name', 'pg-client'])
        run(['ip', 'link', 'set', 'pg-client', 'netns', str(child.pid)])
        run(['ip', 'addr', 'add', '10.231.90.1/30', 'dev', 'pg-host'])
        run(['ip', '-6', 'addr', 'add', 'fd42:231:90::1/64', 'dev', 'pg-host', 'nodad'])
        run(['ip', 'link', 'set', 'pg-host', 'up'])
        ns = ['nsenter', '--target', str(child.pid), '--net']
        run(ns + ['ip', 'link', 'set', 'lo', 'up'])
        run(ns + ['ip', 'addr', 'add', '10.231.90.2/30', 'dev', 'pg-client'])
        run(ns + ['ip', '-6', 'addr', 'add', 'fd42:231:90::2/64', 'dev', 'pg-client', 'nodad'])
        run(ns + ['ip', 'link', 'set', 'pg-client', 'up'])
        for server_type, address in [(socketserver.ThreadingTCPServer, ('0.0.0.0', 5432)), (socketserver.ThreadingTCPServer, ('0.0.0.0', 8080)), (V6Server, ('::', 5432))]:
            server = server_type(address, Sink)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            servers.append(server)
        def remote(address, port):
            code = 'import socket; s=socket.create_connection((' + repr(address) + ',' + str(port) + '),timeout=2); assert s.recv(2)==b"ok"; s.close()'
            return subprocess.run(ns + [sys.executable, '-c', code], capture_output=True).returncode == 0
        def local(address):
            with socket.create_connection((address, 5432), timeout=2) as connection:
                assert connection.recv(2) == b'ok'
        assert remote('10.231.90.1', 5432)
        assert remote('fd42:231:90::1', 5432)
        assert remote('10.231.90.1', 8080)
        local('127.0.0.1'); local('::1')
        run(['/usr/sbin/nft', '-c', '-f', str(policy)])
        run(['/usr/sbin/nft', '-f', str(policy)])
        assert not remote('10.231.90.1', 5432)
        assert not remote('fd42:231:90::1', 5432)
        local('127.0.0.1'); local('::1')
        assert remote('10.231.90.1', 8080), 'Unrelated port must remain available'
        run(['/usr/sbin/nft', 'delete', 'table', 'inet', 'ligado_opentracy_postgres'])
        assert remote('10.231.90.1', 5432), 'Rollback must restore namespace baseline'
        print(json.dumps({'result': 'PASSOU', 'isolatedNamespaces': True, 'ipv4RemoteDenied': True, 'ipv6RemoteDenied': True, 'loopbackPositiveControls': True, 'unrelatedPortPreserved': True, 'rollbackVerified': True, 'hostFirewallChanged': False}))
    finally:
        child.terminate(); child.wait(timeout=5)
        for server in servers:
            server.shutdown(); server.server_close()


if __name__ == '__main__':
    main()
