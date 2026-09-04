import asyncio

from highwaypilot_lab.session import SessionRegistry

from .conftest import command, session_config


def test_cross_session_control_reference_is_rejected_without_existence_disclosure() -> None:
    async def scenario() -> None:
        registry = SessionRegistry()
        first = registry.create(session_config()).session
        second = registry.create(session_config()).session

        cross_session_command = command(first, "cross", "manual.action", {"action": "IDLE"})
        cross_session_command = cross_session_command.replace(session_id=second.session_id)
        result = await registry.submit(first.session_id, cross_session_command)
        missing = await registry.submit("missing-session", cross_session_command)

        assert result == missing == {
            "protocol_version": "highwaypilot-ws/v1",
            "type": "command.error",
            "error": {"code": "SESSION_NOT_FOUND", "message": "session is unavailable"},
        }
        assert first.state_seq == second.state_seq == 0

    asyncio.run(scenario())
