import base64
from collections.abc import Iterator

from highwaypilot_lab.config import parse_config
from highwaypilot_lab.protocol import SessionCommand


def session_config(*, side: str = "right") -> dict[str, object]:
    return parse_config(
        {
            "schema_version": "construction-config/v1",
            "scenario_id": "construction-v0",
            "seed": 314,
            "construction": {"side": side},
            "traffic": {"vehicles_count": 0},
        }
    )


def command(
    session,
    command_id: str,
    name: str,
    payload: dict[str, object] | None = None,
    *,
    attachment_epoch: int | None = None,
    simulation_generation: int | None = None,
    expected_state_seq: int | None = None,
) -> SessionCommand:
    return SessionCommand(
        protocol_version="highwaypilot-ws/v1",
        session_id=session.session_id,
        command_id=command_id,
        attachment_epoch=(
            session.attachment_epoch if attachment_epoch is None else attachment_epoch
        ),
        simulation_generation=(
            session.simulation_generation
            if simulation_generation is None
            else simulation_generation
        ),
        expected_state_seq=(session.state_seq if expected_state_seq is None else expected_state_seq),
        name=name,
        payload={} if payload is None else payload,
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FixedEntropy:
    def __init__(self) -> None:
        self._chunks: Iterator[bytes] = iter(
            bytes([value]) * size
            for value, size in [
                (1, 32),
                (2, 32),
                (3, 32),
                (4, 32),
                (5, 32),
            ]
        )

    def __call__(self, size: int) -> bytes:
        chunk = next(self._chunks)
        assert len(chunk) == size
        return chunk


def attempt_id(value: int) -> str:
    return base64.urlsafe_b64encode(bytes([value]) * 16).rstrip(b"=").decode("ascii")
