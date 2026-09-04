"""Mechanical implementation of ``highwaypilot-rng/v1``."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Mapping
from typing import Any

import numpy as np
import rfc8785

from highwaypilot_lab.config import parse_config


RNG_CONTRACT_VERSION = "highwaypilot-rng/v1"
STREAM_NAMES = ("env_core", "traffic", "scenario_events", "random_policy")
_PREFIX = RNG_CONTRACT_VERSION.encode("ascii")


class RNGContractError(RuntimeError):
    """Raised when a caller violates stream ownership or lifecycle."""


def canonical_config_bytes(config: Mapping[str, Any]) -> bytes:
    """Return RFC 8785 bytes for the complete effective configuration."""

    return rfc8785.dumps(parse_config(config))


def config_digest(config: Mapping[str, Any]) -> bytes:
    return hashlib.sha256(canonical_config_bytes(config)).digest()


def _stream_digest(seed: int, digest: bytes, stream_name: str) -> bytes:
    if stream_name not in STREAM_NAMES:
        raise RNGContractError(f"unknown RNG stream: {stream_name}")
    encoded_name = stream_name.encode("ascii")
    material = b"".join(
        (
            struct.pack(">H", len(_PREFIX)),
            _PREFIX,
            struct.pack(">I", seed),
            digest,
            struct.pack(">H", len(encoded_name)),
            encoded_name,
        )
    )
    return hashlib.sha256(material).digest()


def _generator(seed: int, digest: bytes, stream_name: str) -> np.random.Generator:
    stream_digest = _stream_digest(seed, digest, stream_name)
    entropy = [
        int.from_bytes(stream_digest[offset : offset + 4], "big", signed=False)
        for offset in range(0, len(stream_digest), 4)
    ]
    sequence = np.random.SeedSequence(entropy=entropy, spawn_key=(), pool_size=4)
    return np.random.Generator(np.random.PCG64(sequence))


def _class_identity(value: type[object]) -> str:
    return f"{value.__module__}.{value.__qualname__}"


class RNGStreams:
    """Own exactly one generator for each named v1 stream."""

    def __init__(self, config: Mapping[str, Any]) -> None:
        self.effective_config = parse_config(config)
        self._digest = config_digest(self.effective_config)
        seed = self.effective_config["seed"]
        self._generators = {
            name: _generator(seed, self._digest, name) for name in STREAM_NAMES
        }
        self._env_core_consumed = False
        self.metadata = {
            "contract_version": RNG_CONTRACT_VERSION,
            "user_seed": seed,
            "config_digest": self._digest.hex(),
            "stream_names": list(STREAM_NAMES),
            "numpy_version": np.__version__,
            "bit_generator": _class_identity(np.random.PCG64),
            "seed_sequence": _class_identity(np.random.SeedSequence),
        }

    @property
    def env_core_sealed(self) -> bool:
        return self._env_core_consumed

    def take_env_seed(self) -> int:
        """Perform the sole permitted ``env_core`` consumption, then seal it."""

        if self._env_core_consumed:
            raise RNGContractError("env_core already consumed")
        generator = self._generators["env_core"]
        scalar = generator.integers(
            low=0,
            high=np.iinfo(np.uint32).max,
            size=None,
            dtype=np.uint32,
            endpoint=True,
        )
        self._env_core_consumed = True
        return int(scalar)

    def generator(self, stream_name: str) -> np.random.Generator:
        """Return a domain-owned stream; ``env_core`` never escapes this object."""

        if stream_name == "env_core":
            raise RNGContractError("env_core is not directly accessible")
        if stream_name not in STREAM_NAMES:
            raise RNGContractError(f"unknown RNG stream: {stream_name}")
        return self._generators[stream_name]
