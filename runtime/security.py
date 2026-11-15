"""Production runtime authentication and analysis concurrency limits."""
import hmac
import os
import re


def enabled():
    return os.environ.get("OPENTRACY_RUNTIME_SECURITY") == "required"


def validate_security_config():
    if os.environ.get("OPENTRACY_RUNTIME_SECURITY", "") not in ("", "required"):
        raise RuntimeError("Unknown runtime security mode")
    if enabled() and len(os.environ.get("OPENTRACY_RUNTIME_INTERNAL_TOKEN", "").strip()) < 32:
        raise RuntimeError("Runtime internal authentication is not configured")


def matches(actual, expected):
    return bool(expected) and hmac.compare_digest(actual.encode(), expected.encode())


def protected(path):
    if path == "/health" or path == "/billing/webhook":
        return False
    if any(path == root or path.startswith(root + "/") for root in
           ("/knowledge", "/measurements", "/v3", "/mcp", "/widget")):
        return False
    return re.fullmatch(r"/api/[^/]+/chat", path) is None


def expensive(path):
    return path in ("/run", "/introspect", "/onboarding/turn", "/v3/systemos/diagnosis") or bool(
        re.fullmatch(r"/api/[^/]+/(chat|internal-run)", path))


class RuntimeSecurityMiddleware:
    def __init__(self, app, max_concurrent=2):
        self.app = app
        self.max_concurrent = max_concurrent
        self.active = 0

    async def reject(self, send, status, message):
        headers = [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]
        if status == 429:
            headers.append((b"retry-after", b"5"))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": message})

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not enabled():
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        headers = {k.lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
        if protected(path):
            internal = os.environ.get("OPENTRACY_RUNTIME_INTERNAL_TOKEN", "").strip()
            if len(internal) < 32:
                return await self.reject(send, 503, b'{"error":"authentication_unavailable"}')
            authorized = matches(headers.get(b"x-opentracy-runtime-key", ""), internal)
            authorization = headers.get(b"authorization", "")
            bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
            authorized |= any(matches(bearer, key.strip()) for key in os.environ.get("BACKEND_API_KEYS", "").split(","))
            if scope.get("method") == "GET" and path == "/agent/config":
                authorized |= matches(bearer, os.environ.get("OPENTRACY_KNOWLEDGE_AUTH_TOKEN", ""))
            if not authorized:
                return await self.reject(send, 401, b'{"error":"unauthorized"}')
        limited = scope.get("method") == "POST" and expensive(path)
        if limited and self.active >= self.max_concurrent:
            return await self.reject(send, 429, b'{"error":"analysis_busy"}')
        if limited:
            self.active += 1
        try:
            return await self.app(scope, receive, send)
        finally:
            if limited:
                self.active -= 1
