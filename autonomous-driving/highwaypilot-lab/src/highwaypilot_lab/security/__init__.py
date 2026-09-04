"""Fail-closed local HTTP and WebSocket boundary."""

from .loopback import LoopbackBoundaryError, LoopbackBoundaryMiddleware, validate_bind_address

__all__ = ["LoopbackBoundaryError", "LoopbackBoundaryMiddleware", "validate_bind_address"]
