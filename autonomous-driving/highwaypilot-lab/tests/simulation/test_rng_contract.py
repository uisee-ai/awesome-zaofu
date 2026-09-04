import json
from pathlib import Path

import numpy as np
import pytest

from highwaypilot_lab.config import parse_config
from highwaypilot_lab.rng import (
    RNG_CONTRACT_VERSION,
    STREAM_NAMES,
    RNGContractError,
    RNGStreams,
    canonical_config_bytes,
    config_digest,
)


def normal_config() -> dict[str, object]:
    raw = json.loads(Path("configs/presets/normal-v1.json").read_text(encoding="utf-8"))
    return parse_config(raw)


def test_rfc8785_config_digest_matches_the_frozen_golden_vector() -> None:
    effective = normal_config()

    assert canonical_config_bytes(effective).startswith(b'{"construction":')
    assert config_digest(effective).hex() == (
        "6a021197a9241735b7345edc16e9f4cf31f52a03ea8ecb7442d01968cfa4c6d1"
    )


def test_all_four_streams_match_the_highwaypilot_rng_v1_golden_vectors() -> None:
    streams = RNGStreams(normal_config())

    assert streams.take_env_seed() == 261_116_608
    assert streams.generator("traffic").integers(0, 2**32, size=4, dtype=np.uint32).tolist() == [
        1826491679,
        169037833,
        297772211,
        3851409116,
    ]
    assert streams.generator("scenario_events").integers(
        0, 2**32, size=4, dtype=np.uint32
    ).tolist() == [690240376, 1477070332, 3182693965, 1244604242]
    assert streams.generator("random_policy").integers(
        0, 2**32, size=4, dtype=np.uint32
    ).tolist() == [2258829221, 4177531577, 1870821361, 2061106409]


def test_env_core_can_be_consumed_exactly_once_and_is_never_exposed() -> None:
    streams = RNGStreams(normal_config())

    assert streams.take_env_seed() == 261_116_608
    assert streams.env_core_sealed is True
    with pytest.raises(RNGContractError, match="already consumed"):
        streams.take_env_seed()
    with pytest.raises(RNGContractError, match="not directly accessible"):
        streams.generator("env_core")


def test_named_stream_consumption_is_isolated() -> None:
    first = RNGStreams(normal_config())
    second = RNGStreams(normal_config())

    first.generator("traffic").random(100)
    first_scenario = first.generator("scenario_events").integers(0, 2**32, dtype=np.uint32)
    second_scenario = second.generator("scenario_events").integers(0, 2**32, dtype=np.uint32)
    assert int(first_scenario) == int(second_scenario)


def test_cross_run_sequences_and_runtime_metadata_are_reproducible() -> None:
    first = RNGStreams(normal_config())
    second = RNGStreams(normal_config())

    assert first.take_env_seed() == second.take_env_seed()
    assert first.generator("random_policy").random(16).tolist() == second.generator(
        "random_policy"
    ).random(16).tolist()
    assert first.metadata == second.metadata
    assert first.metadata == {
        "contract_version": RNG_CONTRACT_VERSION,
        "user_seed": 101,
        "config_digest": "6a021197a9241735b7345edc16e9f4cf31f52a03ea8ecb7442d01968cfa4c6d1",
        "stream_names": list(STREAM_NAMES),
        "numpy_version": np.__version__,
        "bit_generator": "numpy.random._pcg64.PCG64",
        "seed_sequence": "numpy.random.bit_generator.SeedSequence",
    }


def test_unknown_stream_names_fail_closed() -> None:
    streams = RNGStreams(normal_config())

    with pytest.raises(RNGContractError, match="unknown RNG stream"):
        streams.generator("events")
