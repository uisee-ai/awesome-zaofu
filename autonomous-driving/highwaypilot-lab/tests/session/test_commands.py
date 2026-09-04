import asyncio
from pathlib import Path

from highwaypilot_lab.session import Session

from .conftest import command, session_config


def test_manual_five_actions_return_current_feedback_and_invalid_actions_do_not_mutate() -> None:
    async def scenario() -> None:
        created = Session.create(session_config())
        session = created.session

        initial_actions = session.snapshot()["available_actions"]
        assert initial_actions == ["LANE_LEFT", "IDLE", "FASTER", "SLOWER"]

        invalid = await session.submit(
            command(session, "invalid-action", "manual.action", {"action": "FLY"})
        )
        assert invalid["type"] == "command.error"
        assert invalid["error"] == {
            "code": "INVALID_ACTION",
            "message": "action is not currently available",
            "available_actions": initial_actions,
        }
        assert session.state_seq == 0

        session.drain_outbox()
        for index, action in enumerate(initial_actions, start=1):
            result = await session.submit(
                command(session, f"action-{index}", "manual.action", {"action": action})
            )
            assert result["type"] == "command.result"
            assert result["result"]["accepted_action"] == action
            assert result["result"]["available_actions"]
            session.drain_outbox()

        assert "SLOWER" in session.snapshot()["available_actions"]
        slower = await session.submit(
            command(session, "action-slower", "manual.action", {"action": "SLOWER"})
        )
        assert slower["result"]["accepted_action"] == "SLOWER"

        left_session = Session.create(session_config(side="left")).session
        assert "LANE_RIGHT" in left_session.snapshot()["available_actions"]
        lane_right = await left_session.submit(
            command(left_session, "action-lane-right", "manual.action", {"action": "LANE_RIGHT"})
        )
        assert lane_right["result"]["accepted_action"] == "LANE_RIGHT"

    asyncio.run(scenario())


def test_manual_actions_are_admitted_while_simulation_is_playing() -> None:
    async def scenario() -> None:
        session = Session.create(session_config()).session
        await session.submit(command(session, "play", "simulation.play"))
        session.drain_outbox()

        result = await session.submit(command(session, "lane-live", "manual.action", {"action": "LANE_LEFT"}))

        assert result["type"] == "command.result"
        assert result["result"]["accepted_action"] == "LANE_LEFT"
        assert result["result"]["queued"] is True
        assert session.simulation_status == "playing"
        assert await session.tick_playback() is True
        assert session.snapshot()["last_action"] == "LANE_LEFT"

    asyncio.run(scenario())


def test_live_lane_change_takes_priority_and_reversing_speed_cancels_stale_input() -> None:
    async def scenario() -> None:
        session = Session.create(session_config()).session
        await session.submit(command(session, "play-priority", "simulation.play"))
        session.drain_outbox()

        for index in range(3):
            result = await session.submit(
                command(session, f"slower-{index}", "manual.action", {"action": "SLOWER"})
            )
            assert result["type"] == "command.result"
        lane = await session.submit(
            command(session, "lane-priority", "manual.action", {"action": "LANE_LEFT"})
        )
        assert lane["type"] == "command.result"
        assert await session.tick_playback() is True
        assert session.snapshot()["last_action"] == "LANE_LEFT"
        assert session.snapshot()["ego"]["target_lane_index"] == 1

        faster = await session.submit(
            command(session, "reverse-speed", "manual.action", {"action": "FASTER"})
        )
        assert faster["type"] == "command.result"
        assert await session.tick_playback() is True
        assert session.snapshot()["last_action"] == "FASTER"

    asyncio.run(scenario())


def test_onnx_mode_runs_the_qualified_model_in_the_live_session() -> None:
    async def scenario() -> None:
        model_dir = Path(__file__).resolve().parents[2] / "models" / "construction-dqn-v1"
        session = Session.create(session_config(), model_dir=model_dir).session

        selected = await session.submit(command(session, "mode-onnx", "control.set_mode", {"mode": "onnx"}))
        assert selected["type"] == "command.result"
        assert selected["result"]["control_mode"] == "onnx"
        assert session.temporary_episode()["strategy"] == {
            "id": "construction_dqn_onnx",
            "version": "onnx-learning-policy/v1",
            "model_version": "1.0.0",
        }
        session.drain_outbox()

        await session.submit(command(session, "play-onnx", "simulation.play"))
        session.drain_outbox()
        assert await session.tick_playback() is True
        snapshots = [event for event in session.drain_outbox() if event["type"] == "simulation.snapshot"]
        assert snapshots[-1]["decision"]["strategy_id"] == "construction_dqn_onnx"
        assert snapshots[-1]["decision"]["reason"] == "maximum_q_value"
        await session.close()

    asyncio.run(scenario())


def test_command_ledger_orders_epoch_generation_id_state_and_business_checks() -> None:
    async def scenario() -> None:
        session = Session.create(session_config()).session

        first_command = command(session, "stable-id", "manual.action", {"action": "IDLE"})
        first = await session.submit(first_command)
        session.drain_outbox()
        replay = await session.submit(first_command)
        assert replay["result"] == first["result"]
        assert replay["server_seq"] > first["server_seq"]
        session.drain_outbox()

        reused = await session.submit(
            command(session, "stable-id", "manual.action", {"action": "FASTER"})
        )
        assert reused["error"]["code"] == "COMMAND_ID_REUSE"
        session.drain_outbox()

        stale_epoch = await session.submit(
            command(
                session,
                "not-consumed-by-epoch",
                "manual.action",
                {"action": "IDLE"},
                attachment_epoch=session.attachment_epoch - 1,
            )
        )
        assert stale_epoch["error"]["code"] == "STALE_ATTACHMENT_EPOCH"
        session.drain_outbox()
        accepted_after_epoch_rejection = await session.submit(
            command(session, "not-consumed-by-epoch", "manual.action", {"action": "IDLE"})
        )
        assert accepted_after_epoch_rejection["type"] == "command.result"
        session.drain_outbox()

        stale_state_command = command(
            session,
            "cached-stale-state",
            "manual.action",
            {"action": "IDLE"},
            expected_state_seq=session.state_seq + 100,
        )
        stale_state = await session.submit(stale_state_command)
        session.drain_outbox()
        stale_state_replay = await session.submit(stale_state_command)
        assert stale_state["error"]["code"] == "STALE_STATE"
        assert stale_state_replay["error"] == stale_state["error"]
        session.drain_outbox()

        old_generation = session.simulation_generation
        reset = await session.submit(command(session, "reset", "simulation.reset"))
        assert reset["result"]["simulation_generation"] == old_generation + 1
        assert session.state_seq == 0
        session.drain_outbox()

        stale_generation = await session.submit(
            command(
                session,
                "not-consumed-by-generation",
                "manual.action",
                {"action": "IDLE"},
                simulation_generation=old_generation,
            )
        )
        assert stale_generation["error"]["code"] == "STALE_SIMULATION_GENERATION"
        session.drain_outbox()
        accepted_after_generation_rejection = await session.submit(
            command(
                session,
                "not-consumed-by-generation",
                "manual.action",
                {"action": "IDLE"},
            )
        )
        assert accepted_after_generation_rejection["type"] == "command.result"
        session.drain_outbox()

        old_id_after_reset = await session.submit(
            command(session, "stable-id", "manual.action", {"action": "IDLE"})
        )
        assert old_id_after_reset["error"]["code"] == "COMMAND_ID_REUSE"

    asyncio.run(scenario())


def test_server_and_state_sequences_have_independent_frozen_semantics() -> None:
    async def scenario() -> None:
        session = Session.create(session_config()).session

        session.publish_snapshot(lossy_playing=True)
        await session.submit(command(session, "step-1", "manual.action", {"action": "IDLE"}))
        session.publish_snapshot(lossy_playing=True)
        session.publish_snapshot(lossy_playing=True)
        messages = session.drain_outbox()

        assert [message["server_seq"] for message in messages] == list(
            range(1, len(messages) + 1)
        )
        snapshots = [message for message in messages if message["type"] == "simulation.snapshot"]
        assert len(snapshots) == 1
        assert snapshots[0]["snapshot"]["step"] == session.snapshot()["step"]
        assert session.state_seq == 1

    asyncio.run(scenario())
