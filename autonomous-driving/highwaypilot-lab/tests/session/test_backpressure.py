import asyncio

from highwaypilot_lab.session import Session

from .conftest import command, session_config


def test_failed_result_reservation_does_not_mutate_consume_id_or_write_ledger() -> None:
    async def scenario() -> None:
        session = Session.create(session_config(), outbox_capacity=1, emergency_capacity=1).session

        await session.submit(command(session, "fills-outbox", "simulation.pause"))
        before = session.snapshot()
        rejected = await session.submit(
            command(session, "retryable", "manual.action", {"action": "IDLE"})
        )

        assert rejected["type"] == "command.error"
        assert rejected["error"]["code"] == "BACKPRESSURE"
        assert session.snapshot() == before
        assert "retryable" not in session.command_ids

        session.drain_outbox()
        accepted = await session.submit(
            command(session, "retryable", "manual.action", {"action": "IDLE"})
        )
        assert accepted["type"] == "command.result"

    asyncio.run(scenario())


def test_undeliverable_backpressure_atomically_detaches_pauses_and_closes_socket() -> None:
    async def scenario() -> None:
        session = Session.create(session_config(), outbox_capacity=1, emergency_capacity=0).session

        await session.submit(command(session, "play", "simulation.play"))
        rejected = await session.submit(
            command(session, "cannot-deliver", "manual.action", {"action": "IDLE"})
        )

        assert rejected is None
        assert session.socket_status == "detached"
        assert session.simulation_status == "paused"
        assert session.socket_open is False
        assert "cannot-deliver" not in session.command_ids
        assert session.playback_task_running is False

    asyncio.run(scenario())


def test_lossy_playing_snapshots_never_mask_required_lifecycle_or_command_messages() -> None:
    async def scenario() -> None:
        session = Session.create(session_config(), outbox_capacity=4).session

        session.publish_snapshot(lossy_playing=True)
        session.publish_snapshot(lossy_playing=True)
        result = await session.submit(command(session, "pause", "simulation.pause"))
        session.publish_snapshot(lossy_playing=False, reason="paused")
        messages = session.drain_outbox()

        assert result in messages
        assert [message["type"] for message in messages].count("simulation.snapshot") == 2
        assert any(message.get("reason") == "paused" for message in messages)

    asyncio.run(scenario())


def test_required_command_admission_evicts_a_pending_lossy_snapshot() -> None:
    async def scenario() -> None:
        session = Session.create(session_config(), outbox_capacity=1).session
        assert session.publish_snapshot(lossy_playing=True) is True

        result = await session.submit(command(session, "required", "simulation.pause"))

        assert result["type"] == "command.result"
        assert session.drain_outbox() == [result]

    asyncio.run(scenario())
