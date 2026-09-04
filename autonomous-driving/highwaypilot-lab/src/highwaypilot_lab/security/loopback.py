"""Exact IPv4-loopback Host/Origin enforcement for the single-port service."""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send


_HOST = re.compile(r"^127\.0\.0\.1:([1-9][0-9]{0,4})$")
_PROXY_HEADERS = {
    b"forwarded",
    b"x-forwarded-for",
    b"x-forwarded-host",
    b"x-forwarded-port",
    b"x-forwarded-proto",
}


class LoopbackBoundaryError(ValueError):
    """The configured listener escapes the product's local trust boundary."""


def validate_bind_address(host: str, port: int) -> tuple[str, int]:
    if host != "127.0.0.1":
        raise LoopbackBoundaryError("service host must be exactly 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise LoopbackBoundaryError("service port must be an integer from 1 to 65535")
    return host, port


def _headers(scope: Scope, name: bytes) -> list[str]:
    return [value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == name]


def _host_error(message: str) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": "HOST_REJECTED", "message": message}},
        status_code=400,
    )


def _origin_error() -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "ORIGIN_REJECTED",
                "message": "request origin is not the exact loopback service origin",
            }
        },
        status_code=403,
    )


class LoopbackBoundaryMiddleware:
    """Validate connection metadata before any application route can mutate state."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        raw_headers = scope.get("headers", [])
        if any(key.lower() in _PROXY_HEADERS for key, _ in raw_headers):
            await self._reject(scope, receive, send, _host_error("proxy headers are not accepted"))
            return

        hosts = _headers(scope, b"host")
        if len(hosts) != 1:
            await self._reject(scope, receive, send, _host_error("exactly one Host header is required"))
            return
        match = _HOST.fullmatch(hosts[0])
        server = scope.get("server")
        if (
            match is None
            or int(match.group(1)) > 65535
            or not server
            or server[0] != "127.0.0.1"
            or int(match.group(1)) != int(server[1])
        ):
            await self._reject(scope, receive, send, _host_error("Host must match 127.0.0.1 and the listener port"))
            return

        origins = _headers(scope, b"origin")
        origin_required = scope["type"] == "websocket" or scope.get("method") not in {"GET", "HEAD"}
        exact_origin = f"http://{hosts[0]}"
        if len(origins) > 1 or (origin_required and len(origins) != 1):
            await self._reject(scope, receive, send, _origin_error())
            return
        if origins and origins[0] != exact_origin:
            await self._reject(scope, receive, send, _origin_error())
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _reject(
        scope: Scope,
        receive: Receive,
        send: Send,
        response: JSONResponse,
    ) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4403, "reason": "loopback boundary rejected"})
            return
        await response(scope, receive, send)
