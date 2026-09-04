import json
from pathlib import Path

import pytest

from highwaypilot_lab.protocol import ProtocolMessageError, SessionCommand, parse_client_message


SCHEMA_PATH = Path("schemas/websocket/v1.schema.json")


def command_fixture() -> dict[str, object]:
    return {
        "protocol_version": "highwaypilot-ws/v1",
        "type": "command",
        "session_id": "session-01",
        "command_id": "command-01",
        "attachment_epoch": 0,
        "simulation_generation": 0,
        "expected_state_seq": 0,
        "name": "manual.action",
        "payload": {"action": "LANE_LEFT"},
    }


def test_command_fixture_is_exact_and_parses_to_the_public_contract() -> None:
    message = command_fixture()

    parsed = parse_client_message(message)

    assert parsed == SessionCommand(
        protocol_version="highwaypilot-ws/v1",
        session_id="session-01",
        command_id="command-01",
        attachment_epoch=0,
        simulation_generation=0,
        expected_state_seq=0,
        name="manual.action",
        payload={"action": "LANE_LEFT"},
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"commandId": "camel-case"},
        {"unexpected": True},
        {"protocol_version": "highwaypilot-ws/v2"},
        {"expected_state_seq": -1},
        {"attachment_epoch": True},
    ],
)
def test_protocol_rejects_unknown_camel_case_version_and_invalid_integer_fields(
    mutation: dict[str, object],
) -> None:
    message = command_fixture()
    message.update(mutation)

    with pytest.raises(ProtocolMessageError):
        parse_client_message(message)


@pytest.mark.parametrize(
    ("message_type", "extra"),
    [
        (
            "resume.offer",
            {
                "session_id": "session-01",
                "resume_token": "A" * 43,
                "resume_attempt_id": "B" * 22,
            },
        ),
        (
            "resume.commit",
            {
                "session_id": "session-01",
                "resume_attempt_id": "B" * 22,
                "offer_id": "offer-01",
            },
        ),
    ],
)
def test_resume_client_messages_preserve_the_complete_snake_case_shape(
    message_type: str,
    extra: dict[str, object],
) -> None:
    parsed = parse_client_message(
        {
            "protocol_version": "highwaypilot-ws/v1",
            "type": message_type,
            **extra,
        }
    )

    assert parsed.type == message_type
    assert parsed.to_wire() == {
        "protocol_version": "highwaypilot-ws/v1",
        "type": message_type,
        **extra,
    }


def test_json_schema_is_an_exact_closed_union_for_all_client_messages() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert list(schema) == [
        "$schema",
        "$id",
        "title",
        "oneOf",
        "$defs",
    ]
    assert schema["$id"] == "https://highwaypilot.local/schemas/websocket/v1.schema.json"
    assert schema["oneOf"] == [
        {"$ref": "#/$defs/command"},
        {"$ref": "#/$defs/resume_offer"},
        {"$ref": "#/$defs/resume_commit"},
    ]
    assert list(schema["$defs"]) == ["command", "resume_offer", "resume_commit"]
    assert schema["$defs"]["command"]["required"] == [
        "protocol_version",
        "type",
        "session_id",
        "command_id",
        "attachment_epoch",
        "simulation_generation",
        "expected_state_seq",
        "name",
        "payload",
    ]
    assert all(definition["additionalProperties"] is False for definition in schema["$defs"].values())
