"""Optional fail-closed network guard used by the clean offline release proof."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any


if os.environ.get("SCENARIOFORGE_NETWORK_GUARD") == "1":
    _attempt_log = Path(os.environ["SCENARIOFORGE_NETWORK_ATTEMPT_LOG"])
    _original_connect = socket.socket.connect
    _original_connect_ex = socket.socket.connect_ex
    _original_getaddrinfo = socket.getaddrinfo

    def _hostname(address: object) -> str:
        if isinstance(address, tuple) and address:
            return str(address[0])
        return str(address)

    def _loopback(host: str) -> bool:
        return host in {"127.0.0.1", "::1", "localhost"}

    def _deny(operation: str, host: str) -> None:
        _attempt_log.parent.mkdir(parents=True, exist_ok=True)
        with _attempt_log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"operation": operation, "host": host}, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        raise OSError("external network is denied by the ScenarioForge offline release guard")

    def _guarded_connect(instance: socket.socket, address: Any) -> Any:
        host = _hostname(address)
        if not _loopback(host):
            _deny("connect", host)
        return _original_connect(instance, address)

    def _guarded_connect_ex(instance: socket.socket, address: Any) -> int:
        host = _hostname(address)
        if not _loopback(host):
            _deny("connect_ex", host)
        return _original_connect_ex(instance, address)

    def _guarded_getaddrinfo(host: str | bytes | None, *args: Any, **kwargs: Any) -> Any:
        candidate = host.decode("ascii", errors="replace") if isinstance(host, bytes) else str(host)
        if not _loopback(candidate):
            _deny("getaddrinfo", candidate)
        return _original_getaddrinfo(host, *args, **kwargs)

    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    socket.getaddrinfo = _guarded_getaddrinfo
