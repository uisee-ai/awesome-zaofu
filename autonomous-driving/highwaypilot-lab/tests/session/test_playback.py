import asyncio

from highwaypilot_lab.session import Session

from .conftest import command, session_config


def test_real_play_pause_tick_and_reset_cancel_and_await_stale_tasks() -> None:
    async def scenario() -> None:
        session = Session.create(session_config(), outbox_capacity=16).session

        play = await session.submit(command(session, "play", "simulation.play"))
        assert play["result"]["simulation_status"] == "playing"
        assert session.playback_task_running is True
        old_task = session.playback_task
        session.drain_outbox()

        assert await session.tick_playback() is True
        assert session.state_seq == 1
        assert session.snapshot()["step"] == 1
        session.drain_outbox()

        paused = await session.submit(command(session, "pause", "simulation.pause"))
        assert paused["result"]["simulation_status"] == "paused"
        assert old_task.done()
        assert session.playback_task_running is False
        assert await session.tick_playback() is False
        session.drain_outbox()

        await session.submit(command(session, "play-again", "simulation.play"))
        second_task = session.playback_task
        session.drain_outbox()
        reset = await session.submit(command(session, "reset", "simulation.reset"))
        assert reset["result"]["simulation_generation"] == 1
        assert reset["result"]["simulation_status"] == "paused"
        assert second_task.done()
        assert session.playback_task_running is False

    asyncio.run(scenario())
