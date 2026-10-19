import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


EXEMPT_PATHS = {"/health", "/ui", "/ui/", "/docs", "/openapi.json", "/redoc"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_is_local(origin: str, request_host: str) -> bool:
    try:
        parsed = urlsplit(origin)
        origin_host = parsed.hostname
        request_name = request_host.split(":", 1)[0].strip("[]").lower()
        if not parsed.scheme or not origin_host or parsed.username or parsed.password:
            return False
        # Accept only same-host local origins. Browser ports may be omitted by the host parser,
        # so compare the hostname; the API has no cross-origin CORS allowance.
        return _is_loopback(origin_host) and _is_loopback(request_name)
    except (TypeError, ValueError):
        return False


class LocalAPIProtection:
    """Protect API routes with a shared token and reject cross-origin mutations.

    Health and static UI are intentionally public so the UI can load and report status.
    When no token is configured, API calls are restricted to loopback clients as a
    development fallback. Configure AETHER_API_TOKEN for an explicit bearer token.
    """

    def __init__(self, app):
        self.app = app
        self.token = os.getenv("AETHER_API_TOKEN", "").strip()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        exempt = path in EXEMPT_PATHS or path.startswith("/ui/")
        if not exempt:
            if method in UNSAFE_METHODS and "origin" in headers:
                origin = headers["origin"]
                host = headers.get("host", "")
                if not _origin_is_local(origin, host):
                    response = JSONResponse({"detail": "Cross-origin API mutations are not allowed"}, status_code=403)
                    await response(scope, receive, send)
                    return

            client = scope.get("client")
            client_host = client[0] if client else None
            if self.token:
                auth = headers.get("authorization", "")
                bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                supplied = headers.get("x-aether-token", "") or bearer
                if not supplied or not hmac.compare_digest(supplied, self.token):
                    response = JSONResponse({"detail": "Valid Aether API token required"}, status_code=401,
                                             headers={"WWW-Authenticate": "Bearer"})
                    await response(scope, receive, send)
                    return
            elif not _is_loopback(client_host):
                response = JSONResponse({"detail": "Configure AETHER_API_TOKEN for non-loopback access"}, status_code=403)
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)
