"""Strict, closed client-to-server messages for highwaypilot-ws/v1."""

from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
from typing import Any, Literal, Mapping


PROTOCOL_VERSION = "highwaypilot-ws/v1"
COMMAND_NAMES = {
    "manual.action",
    "control.action",
    "control.set_mode",
    "simulation.play",
    "simulation.pause",
    "simulation.step",
    "simulation.reset",
    "simulation.set_rate",
    "session.close",
}


class ProtocolMessageError(ValueError):
    """The wire object is not an exact highwaypilot-ws/v1 message."""


def _closed_object(
    value: object,
    *,
    required: tuple[str, ...],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProtocolMessageError(f"{label} must be an object")
    data = dict(value)
    if set(data) != set(required):
        missing = sorted(set(required) - set(data))
        unknown = sorted(set(data) - set(required))
        raise ProtocolMessageError(f"{label} fields mismatch: missing={missing}, unknown={unknown}")
    if list(data) != list(required):
        # Wire ordering is not semantic. This branch deliberately does nothing;
        # fixtures assert canonical field order independently.
        pass
    return data


def _string(data: Mapping[str, Any], key: str) -> str:
    value = data[key]
    if not isinstance(value, str) or not value:
        raise ProtocolMessageError(f"{key} must be a non-empty string")
    return value


def _integer(data: Mapping[str, Any], key: str) -> int:
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProtocolMessageError(f"{key} must be a non-negative integer")
    return value


def _version(data: Mapping[str, Any]) -> None:
    if data["protocol_version"] != PROTOCOL_VERSION:
        raise ProtocolMessageError("unsupported protocol_version")


@dataclass(frozen=True)
class SessionCommand:
    protocol_version: str
    session_id: str
    command_id: str
    attachment_epoch: int
    simulation_generation: int
    expected_state_seq: int
    name: str
    payload: dict[str, Any]
    type: Literal["command"] = "command"

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "session_id": self.session_id,
            "command_id": self.command_id,
            "attachment_epoch": self.attachment_epoch,
            "simulation_generation": self.simulation_generation,
            "expected_state_seq": self.expected_state_seq,
            "name": self.name,
            "payload": dict(self.payload),
        }

    def replace(self, **changes: Any) -> "SessionCommand":
        return dataclass_replace(self, **changes)


@dataclass(frozen=True)
class ResumeOffer:
    protocol_version: str
    session_id: str
    resume_token: str
    resume_attempt_id: str
    type: Literal["resume.offer"] = "resume.offer"

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "session_id": self.session_id,
            "resume_token": self.resume_token,
            "resume_attempt_id": self.resume_attempt_id,
        }


@dataclass(frozen=True)
class ResumeCommit:
    protocol_version: str
    session_id: str
    resume_attempt_id: str
    offer_id: str
    type: Literal["resume.commit"] = "resume.commit"

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "type": self.type,
            "session_id": self.session_id,
            "resume_attempt_id": self.resume_attempt_id,
            "offer_id": self.offer_id,
        }


ClientMessage = SessionCommand | ResumeOffer | ResumeCommit


def parse_client_message(value: object) -> ClientMessage:
    if not isinstance(value, Mapping):
        raise ProtocolMessageError("message must be an object")
    message_type = value.get("type")
    if message_type == "command":
        required = (
            "protocol_version",
            "type",
            "session_id",
            "command_id",
            "attachment_epoch",
            "simulation_generation",
            "expected_state_seq",
            "name",
            "payload",
        )
        data = _closed_object(value, required=required, label="command")
        _version(data)
        name = _string(data, "name")
        if name not in COMMAND_NAMES:
            raise ProtocolMessageError("unknown command name")
        if not isinstance(data["payload"], Mapping):
            raise ProtocolMessageError("payload must be an object")
        return SessionCommand(
            protocol_version=PROTOCOL_VERSION,
            session_id=_string(data, "session_id"),
            command_id=_string(data, "command_id"),
            attachment_epoch=_integer(data, "attachment_epoch"),
            simulation_generation=_integer(data, "simulation_generation"),
            expected_state_seq=_integer(data, "expected_state_seq"),
            name=name,
            payload=dict(data["payload"]),
        )
    if message_type == "resume.offer":
        required = (
            "protocol_version",
            "type",
            "session_id",
            "resume_token",
            "resume_attempt_id",
        )
        data = _closed_object(value, required=required, label="resume.offer")
        _version(data)
        token = _string(data, "resume_token")
        attempt = _string(data, "resume_attempt_id")
        if len(token) != 43 or "=" in token:
            raise ProtocolMessageError("resume_token must be 32-byte unpadded base64url")
        if len(attempt) != 22 or "=" in attempt:
            raise ProtocolMessageError("resume_attempt_id must be 16-byte unpadded base64url")
        return ResumeOffer(PROTOCOL_VERSION, _string(data, "session_id"), token, attempt)
    if message_type == "resume.commit":
        required = (
            "protocol_version",
            "type",
            "session_id",
            "resume_attempt_id",
            "offer_id",
        )
        data = _closed_object(value, required=required, label="resume.commit")
        _version(data)
        attempt = _string(data, "resume_attempt_id")
        if len(attempt) != 22 or "=" in attempt:
            raise ProtocolMessageError("resume_attempt_id must be 16-byte unpadded base64url")
        return ResumeCommit(
            PROTOCOL_VERSION,
            _string(data, "session_id"),
            attempt,
            _string(data, "offer_id"),
        )
    raise ProtocolMessageError("unknown message type")
