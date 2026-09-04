import asyncio
import hashlib

from highwaypilot_lab.session import ResumeError, Session

from .conftest import FakeClock, FixedEntropy, attempt_id, command, session_config


def test_resume_is_two_phase_single_winner_with_immutable_replay_and_atomic_play_restore() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        created = Session.create(
            session_config(),
            clock=clock,
            entropy=FixedEntropy(),
            outbox_capacity=16,
        )
        session = created.session
        old_token = created.resume_token.reveal()
        session.drain_outbox()
        await session.submit(command(session, "play", "simulation.play"))
        session.drain_outbox()
        await session.detach()

        assert session.socket_status == "detached"
        assert session.simulation_status == "paused"
        assert session.restore_playing_intent is True
        assert session.playback_task_running is False

        current_attempt = attempt_id(9)
        first_offer = await session.resume_offer(old_token, current_attempt, "socket-a")
        new_token = first_offer["new_resume_token"]
        assert first_offer["candidate_attachment_epoch"] == 1
        assert session.attachment_epoch == 0
        assert session.session_status == "resume_pending"
        session.drain_outbox()

        replay = await session.resume_offer(old_token, current_attempt, "socket-b")
        assert {key: value for key, value in replay.items() if key != "server_seq"} == {
            key: value for key, value in first_offer.items() if key != "server_seq"
        }
        assert replay["server_seq"] > first_offer["server_seq"]
        session.drain_outbox()

        with pytest_raises_resume("RESUME_INVALID"):
            await session.resume_commit(current_attempt, first_offer["offer_id"], "socket-a")

        committed = await session.resume_commit(
            current_attempt,
            first_offer["offer_id"],
            "socket-b",
        )
        assert committed["type"] == "resume.commit_result"
        assert committed["attachment_epoch"] == 1
        assert committed["playing_restored"] is True
        assert session.attachment_epoch == 1
        assert session.socket_status == "attached"
        assert session.session_status == "active"
        assert session.simulation_status == "playing"
        assert session.playback_task_running is True
        assert session.credential_digest == hashlib.sha256(new_token.encode("ascii")).hexdigest()
        assert new_token not in repr(session)
        assert session.pending_plaintext_token is None

        session.drain_outbox()
        retry = await session.resume_commit(
            current_attempt,
            first_offer["offer_id"],
            "socket-b",
        )
        assert retry["playing_restored"] is True
        assert retry["server_seq"] > committed["server_seq"]

    asyncio.run(scenario())


def test_resume_reservation_failure_does_not_consume_token_or_advance_epoch() -> None:
    async def scenario() -> None:
        created = Session.create(
            session_config(),
            entropy=FixedEntropy(),
            outbox_capacity=2,
        )
        session = created.session
        token = created.resume_token.reveal()
        session.drain_outbox()
        await session.detach()
        session.publish_snapshot(lossy_playing=False, reason="required-a")
        session.publish_snapshot(lossy_playing=False, reason="required-b")

        with pytest_raises_resume("BACKPRESSURE"):
            await session.resume_offer(token, attempt_id(7), "socket-a")

        assert session.attachment_epoch == 0
        assert session.credential_matches(token)
        assert session.session_status == "active"
        session.drain_outbox()

        offer = await session.resume_offer(token, attempt_id(7), "socket-a")
        assert offer["candidate_attachment_epoch"] == 1

    asyncio.run(scenario())


def test_resume_deadline_is_anchored_to_disconnect_and_retries_do_not_extend_it() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        created = Session.create(session_config(), clock=clock, entropy=FixedEntropy())
        session = created.session
        token = created.resume_token.reveal()
        session.drain_outbox()
        await session.detach()
        clock.advance(59)
        await session.resume_offer(token, attempt_id(8), "socket-a")
        session.drain_outbox()
        clock.advance(2)

        with pytest_raises_resume("RESUME_INVALID"):
            await session.resume_offer(token, attempt_id(8), "socket-b")

        assert session.session_status == "closed"
        assert session.credential_digest is None

    asyncio.run(scenario())


def test_duplicate_disconnect_notification_does_not_restart_the_resume_window() -> None:
    async def scenario() -> None:
        clock = FakeClock()
        created = Session.create(session_config(), clock=clock, entropy=FixedEntropy())
        session = created.session
        token = created.resume_token.reveal()
        await session.detach()
        clock.advance(50)
        await session.detach()
        clock.advance(11)

        with pytest_raises_resume("RESUME_INVALID"):
            await session.resume_offer(token, attempt_id(6), "socket-a")

        assert session.session_status == "closed"

    asyncio.run(scenario())


def test_concurrent_resume_commits_have_exactly_one_winner() -> None:
    async def scenario() -> None:
        created = Session.create(session_config(), entropy=FixedEntropy(), outbox_capacity=16)
        session = created.session
        token = created.resume_token.reveal()
        await session.detach()
        offer = await session.resume_offer(token, attempt_id(5), "socket-a")
        session.drain_outbox()
        await session.resume_offer(token, attempt_id(5), "socket-b")
        session.drain_outbox()

        outcomes = await asyncio.gather(
            session.resume_commit(attempt_id(5), offer["offer_id"], "socket-b"),
            session.resume_commit(attempt_id(5), offer["offer_id"], "socket-a"),
            return_exceptions=True,
        )

        winners = [outcome for outcome in outcomes if isinstance(outcome, dict)]
        losers = [outcome for outcome in outcomes if isinstance(outcome, ResumeError)]
        assert len(winners) == len(losers) == 1
        assert winners[0]["committed"] is True
        assert losers[0].code == "RESUME_INVALID"
        assert session.attachment_epoch == 1

    asyncio.run(scenario())


def test_resume_token_is_csprng_base64url_redacted_and_not_serialized() -> None:
    created = Session.create(session_config(), entropy=FixedEntropy())
    token = created.resume_token.reveal()

    assert len(token) == 43
    assert "=" not in token
    assert token not in repr(created)
    assert token not in repr(created.session)
    assert created.session.export_diagnostics() == {
        "session_id": created.session.session_id,
        "socket_status": "attached",
        "session_status": "active",
        "simulation_status": "paused",
        "simulation_generation": 0,
        "attachment_epoch": 0,
        "server_seq": 0,
        "state_seq": 0,
    }
    assert token not in str(created.session.export_diagnostics())


class pytest_raises_resume:
    def __init__(self, code: str) -> None:
        self.code = code

    def __enter__(self):
        return self

    def __exit__(self, exception_type, exception, traceback) -> bool:
        assert exception_type is ResumeError
        assert exception.code == self.code
        return True
