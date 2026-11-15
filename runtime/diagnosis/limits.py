"""Bounded diagnosis admission and exact loopback callback destinations."""
import ipaddress
import json
import os
from urllib.parse import urlsplit

QUEUE_LOCK = 723091145


def positive_int(name, default, maximum):
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError:
        raise ValueError(name + ' must be an integer') from None
    if not 1 <= value <= maximum:
        raise ValueError(name + ' outside permitted range')
    return value


def canonical_callback(value):
    parsed = urlsplit(value)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Callback credentials, query and fragments are forbidden')
    if parsed.scheme != 'http' or parsed.path != '/cous/diagnosis/callback':
        raise ValueError('Unsupported callback destination')
    host = parsed.hostname
    if host == 'localhost':
        host = '127.0.0.1'
    try:
        address = ipaddress.ip_address(host)
        port = parsed.port
    except (ValueError, TypeError):
        raise ValueError('Callback must use an explicit loopback destination') from None
    if str(address) not in ('127.0.0.1', '::1') or port not in (8000, 8010):
        raise ValueError('Callback destination is not allowed')
    netloc = '[' + str(address) + ']' if address.version == 6 else str(address)
    return 'http://' + netloc + ':' + str(port) + parsed.path


def validate_request_budget(payload):
    if len(json.dumps(payload, ensure_ascii=False, default=str).encode()) > 160 * 1024:
        raise ValueError('Diagnosis payload exceeds 160 KiB')
