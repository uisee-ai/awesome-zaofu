"""Train and qualify the sole construction-v0 DQN model and evidence asset."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import shutil
import stat
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import gymnasium as gym
import numpy as np
import onnx
import onnxruntime
import stable_baselines3
import torch
from gymnasium import spaces
from stable_baselines3 import DQN
from stable_baselines3.common.callbacks import BaseCallback

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Project imports intentionally follow the direct-script path bootstrap above.
from highwaypilot_lab.simulation import ConstructionSimulation  # noqa: E402
from highwaypilot_lab.simulation.observation import observation_vector  # noqa: E402
from highwaypilot_lab.strategies.policy import ACTIONS  # noqa: E402

TRAINING_CONFIG = ROOT / "configs/training/dqn-v1.json"
RUNTIME_DIR = ROOT / "models/construction-dqn-v1"
ASSET_DIR = ROOT / "training/assets/construction-dqn-v1"


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _write_json(path: Path, value: Any) -> None:
    path.write_bytes(_canonical_json(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class SnapshotTrainingEnv(gym.Env[np.ndarray, int]):
    """A Gymnasium view of the locked Python-authoritative construction-v0."""

    metadata = {"render_modes": []}

    def __init__(self, preset: dict[str, Any], training_seed: int, max_steps: int) -> None:
        super().__init__()
        self._preset = preset
        self._training_seed = training_seed
        self._max_steps = max_steps
        self._episode_index = 0
        self._simulation: ConstructionSimulation | None = None
        self.action_space = spaces.Discrete(len(ACTIONS), seed=training_seed)
        self.observation_space = spaces.Box(
            low=np.array([-1.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=np.float32),
            high=np.array([1.0, 1.0, 1.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0], dtype=np.float32),
            dtype=np.float32,
        )
        self._step_count = 0

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if self._simulation is not None:
            self._simulation.close()
        config = json.loads(json.dumps(self._preset))
        config["seed"] = (self._training_seed + self._episode_index) % (2**32)
        self._episode_index += 1
        self._simulation = ConstructionSimulation(config)
        self._step_count = 0
        snapshot = self._simulation.snapshot()
        return observation_vector(snapshot), {"config_digest": snapshot["config_digest"]}

    def step(self, action: int):
        if self._simulation is None:
            raise RuntimeError("training environment must be reset before step")
        snapshot = self._simulation.step(int(action))
        self._step_count += 1
        terminated = bool(snapshot["status"]["terminated"])
        truncated = bool(snapshot["status"]["truncated"] or self._step_count >= self._max_steps)
        return (
            observation_vector(snapshot),
            float(snapshot["reward"]["total"]),
            terminated,
            truncated,
            {"termination_reason": snapshot["status"]["termination_reason"]},
        )

    def close(self) -> None:
        if self._simulation is not None:
            self._simulation.close()
            self._simulation = None


class CurveCallback(BaseCallback):
    def __init__(self) -> None:
        super().__init__()
        self.points: list[dict[str, float | int]] = []

    def _on_step(self) -> bool:
        if self.num_timesteps % 16 == 0:
            rewards = np.asarray(self.locals.get("rewards", []), dtype=float)
            self.points.append(
                {
                    "timesteps": self.num_timesteps,
                    "mean_step_reward": round(float(rewards.mean()) if rewards.size else 0.0, 12),
                }
            )
        return True


def _evaluate(model: DQN, preset: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    results = []
    env = SnapshotTrainingEnv(
        preset,
        config["training_seed"] + 10000,
        config["maximum_episode_steps"],
    )
    try:
        for episode_index in range(config["evaluation_episodes"]):
            observation, info = env.reset()
            reward_sum = 0.0
            terminated = truncated = False
            steps = 0
            reason = None
            while not (terminated or truncated):
                action, _ = model.predict(observation, deterministic=True)
                observation, reward, terminated, truncated, step_info = env.step(int(action))
                reward_sum += reward
                steps += 1
                reason = step_info["termination_reason"]
            results.append(
                {
                    "episode": episode_index,
                    "config_digest": info["config_digest"],
                    "steps": steps,
                    "reward": round(reward_sum, 12),
                    "result": reason or "training_step_limit",
                }
            )
    finally:
        env.close()
    return results


def _package_metadata() -> list[dict[str, str]]:
    license_overrides = {
        "gymnasium": "MIT",
        "highway-env": "MIT",
        "numpy": "BSD-3-Clause",
        "onnx": "Apache-2.0",
        "onnxruntime": "MIT",
        "stable-baselines3": "MIT",
        "torch": "BSD-3-Clause",
    }
    packages = []
    for name in sorted(license_overrides):
        packages.append(
            {
                "name": name,
                "version": importlib.metadata.version(name),
                "license": license_overrides[name],
            }
        )
    return packages


def _checkpoint_member_manifest(checkpoint_path: Path) -> dict[str, Any]:
    archive_bytes = checkpoint_path.read_bytes()
    eocd_offset = archive_bytes.rfind(b"PK\x05\x06")
    if eocd_offset < 0 or eocd_offset + 22 > len(archive_bytes):
        raise RuntimeError("checkpoint has no canonical ZIP end record")
    comment_length = int.from_bytes(archive_bytes[eocd_offset + 20 : eocd_offset + 22], "little")
    if eocd_offset + 22 + comment_length != len(archive_bytes):
        raise RuntimeError("checkpoint has trailing data")

    members: list[dict[str, Any]] = []
    names: set[str] = set()
    folded_names: set[str] = set()
    with zipfile.ZipFile(checkpoint_path, "r") as archive:
        for info in archive.infolist():
            path = PurePosixPath(info.filename)
            canonical_path = path.as_posix()
            if (
                info.is_dir()
                or canonical_path != info.filename
                or path.is_absolute()
                or ".." in path.parts
                or canonical_path in names
                or canonical_path.casefold() in folded_names
                or Path(canonical_path).suffix.lower() in {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z"}
            ):
                raise RuntimeError(f"unsafe checkpoint member: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode) or stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
                raise RuntimeError(f"non-regular checkpoint member: {info.filename}")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise RuntimeError(f"unsupported checkpoint compression: {info.compress_type}")
            content = archive.read(info)
            if len(content) != info.file_size:
                raise RuntimeError(f"checkpoint member length mismatch: {info.filename}")
            names.add(canonical_path)
            folded_names.add(canonical_path.casefold())
            members.append(
                {
                    "path": canonical_path,
                    "byte_length": info.file_size,
                    "compressed_length": info.compress_size,
                    "compression": "stored" if info.compress_type == zipfile.ZIP_STORED else "deflated",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return {
        "schema_version": "sb3-checkpoint-members/v1",
        "checkpoint": "checkpoint.zip",
        "checkpoint_byte_length": checkpoint_path.stat().st_size,
        "checkpoint_sha256": _sha256(checkpoint_path),
        "trailing_data": False,
        "members": sorted(members, key=lambda member: member["path"]),
    }


def main() -> None:
    config = json.loads(TRAINING_CONFIG.read_text(encoding="utf-8"))
    preset = json.loads((ROOT / config["preset"]).read_text(encoding="utf-8"))
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for path in (RUNTIME_DIR / "model.onnx", RUNTIME_DIR / "manifest.json"):
        path.unlink(missing_ok=True)
    for path in ASSET_DIR.iterdir():
        if path.is_file():
            path.unlink()

    np.random.seed(config["training_seed"])
    torch.manual_seed(config["training_seed"])
    torch.use_deterministic_algorithms(True)
    env = SnapshotTrainingEnv(preset, config["training_seed"], config["maximum_episode_steps"])
    callback = CurveCallback()
    started = time.time()
    model = DQN(
        "MlpPolicy",
        env,
        learning_rate=config["learning_rate"],
        buffer_size=config["buffer_size"],
        learning_starts=config["learning_starts"],
        batch_size=config["batch_size"],
        gamma=config["gamma"],
        train_freq=config["train_frequency"],
        gradient_steps=config["gradient_steps"],
        target_update_interval=config["target_update_interval"],
        exploration_fraction=config["exploration_fraction"],
        exploration_final_eps=config["exploration_final_epsilon"],
        policy_kwargs={"net_arch": config["network_architecture"]},
        seed=config["training_seed"],
        device="cpu",
        verbose=0,
    )
    model.learn(total_timesteps=config["total_timesteps"], callback=callback)
    elapsed = time.time() - started
    checkpoint_stem = ASSET_DIR / "checkpoint"
    model.save(checkpoint_stem)
    checkpoint_path = ASSET_DIR / "checkpoint.zip"
    _write_json(
        ASSET_DIR / "checkpoint-members.json",
        _checkpoint_member_manifest(checkpoint_path),
    )

    q_network = model.policy.q_net.eval().cpu()
    dummy = torch.zeros((1, 10), dtype=torch.float32)
    torch.onnx.export(
        q_network,
        dummy,
        RUNTIME_DIR / "model.onnx",
        input_names=["observation"],
        output_names=["q_values"],
        opset_version=config["onnx_opset"],
        dynamic_axes=None,
        dynamo=False,
    )
    onnx_model = onnx.load(RUNTIME_DIR / "model.onnx", load_external_data=False)
    onnx.checker.check_model(onnx_model, full_check=True)
    operators = sorted({node.op_type for node in onnx_model.graph.node})
    if set(operators) - {"Cast", "Flatten", "Gemm", "Relu"}:
        raise RuntimeError(f"exported model contains forbidden operators: {operators}")
    if any(tensor.data_location == onnx.TensorProto.EXTERNAL for tensor in onnx_model.graph.initializer):
        raise RuntimeError("exported model contains external data")

    evaluation = _evaluate(model, preset, config)
    env.close()
    commit = _git_head()
    packages = _package_metadata()
    model_path = RUNTIME_DIR / "model.onnx"
    model_manifest = {
        "schema_version": "construction-dqn-model-manifest/v1",
        "model_id": "construction-dqn-v1",
        "version": "1.0.0",
        "filename": "model.onnx",
        "source": "project-trained synthetic construction-v0 interactions",
        "training_code_commit": commit,
        "dependencies": [
            package for package in packages if package["name"] in {"numpy", "onnxruntime"}
        ],
        "input": {"name": "observation", "dtype": "float32", "shape": [1, 10]},
        "output": {"name": "q_values", "dtype": "float32", "shape": [1, 5]},
        "action_mapping": list(ACTIONS),
        "operators": operators,
        "opset": config["onnx_opset"],
        "external_data": False,
        "custom_ops": False,
        "providers": ["CPUExecutionProvider"],
        "byte_length": model_path.stat().st_size,
        "sha256": _sha256(model_path),
        "resource_limits": config["resource_limits"],
        "license": {
            "decision": "approved",
            "license_id": "LicenseRef-Zaofu-HPL-Model-v1",
            "decision_ref": "licenses/training/model-onnx.json",
        },
    }
    _write_json(RUNTIME_DIR / "manifest.json", model_manifest)

    shutil.copy2(TRAINING_CONFIG, ASSET_DIR / "training-config.json")
    shutil.copy2(ROOT / "training/requirements.lock", ASSET_DIR / "requirements.lock")
    _write_json(ASSET_DIR / "training-curve.json", {"schema_version": "training-curve/v1", "points": callback.points})
    _write_json(ASSET_DIR / "evaluation.json", {"schema_version": "model-evaluation/v1", "episodes": evaluation})
    _write_json(
        ASSET_DIR / "rights.json",
        {
            "schema_version": "training-rights/v1",
            "owner": "Zaofu HighwayPilot Lab contributors",
            "license_id": "LicenseRef-Zaofu-HPL-Training-Asset-v1",
            "synthetic_data_only": True,
            "external_weights": False,
            "external_checkpoints": False,
            "external_datasets": False,
        },
    )
    _write_json(
        ASSET_DIR / "receipt.json",
        {
            "schema_version": "dqn-training-receipt/v1",
            "training_code_commit": commit,
            "training_config_sha256": _sha256(TRAINING_CONFIG),
            "checkpoint_sha256": _sha256(checkpoint_path),
            "model_onnx_sha256": model_manifest["sha256"],
            "training_seed": config["training_seed"],
            "total_timesteps": config["total_timesteps"],
            "elapsed_seconds": round(elapsed, 6),
            "synthetic_source": "Python-authoritative construction-v0",
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "numpy_version": np.__version__,
            "torch_version": torch.__version__,
            "stable_baselines3_version": stable_baselines3.__version__,
            "onnx_version": onnx.__version__,
            "onnxruntime_version": onnxruntime.__version__,
        },
    )
    files = []
    for path in sorted(ASSET_DIR.iterdir(), key=lambda item: item.name):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files.append(
            {
                "path": path.name,
                "byte_length": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    asset_manifest = {
        "schema_version": "training-asset-manifest/v1",
        "asset_id": "construction-dqn-v1-training-evidence",
        "training_code_commit": commit,
        "checkpoint_path": "checkpoint.zip",
        "files": files,
    }
    _write_json(ASSET_DIR / "manifest.json", asset_manifest)
    asset_manifest_digest = _sha256(ASSET_DIR / "manifest.json")

    (ROOT / "sbom/training").mkdir(parents=True, exist_ok=True)
    _write_json(
        ROOT / "sbom/training/index.json",
        {
            "schema_version": "training-sbom/v1",
            "scope": "training_only",
            "runtime_included": False,
            "packages": packages,
            "training_asset_manifest": "training/assets/construction-dqn-v1/manifest.json",
            "training_asset_manifest_sha256": asset_manifest_digest,
        },
    )
    (ROOT / "licenses/training").mkdir(parents=True, exist_ok=True)
    _write_json(
        ROOT / "licenses/training/construction-dqn-v1.json",
        {
            "schema_version": "asset-license-decision/v1",
            "scope": "training_asset",
            "decision": "approved",
            "license_id": "LicenseRef-Zaofu-HPL-Training-Asset-v1",
            "owner": "Zaofu HighwayPilot Lab contributors",
            "training_asset_manifest_sha256": asset_manifest_digest,
            "model_onnx_sha256": model_manifest["sha256"],
            "model_decision": "separate",
        },
    )
    _write_json(
        ROOT / "licenses/training/model-onnx.json",
        {
            "schema_version": "asset-license-decision/v1",
            "scope": "runtime_model",
            "decision": "approved",
            "license_id": "LicenseRef-Zaofu-HPL-Model-v1",
            "owner": "Zaofu HighwayPilot Lab contributors",
            "model_onnx_sha256": model_manifest["sha256"],
            "training_asset_decision": "separate",
        },
    )
    (ROOT / "licenses/training/ASSET-LICENSE.txt").write_text(
        "Copyright 2026 Zaofu HighwayPilot Lab contributors.\n"
        "Permission is granted to use, copy, modify, and redistribute the project-trained "
        "construction-dqn-v1 model and its training evidence, with this notice preserved.\n",
        encoding="utf-8",
    )
    _write_json(
        ROOT / "evidence/model/training-run.json",
        {
            "schema_version": "model-training-index/v1",
            "status": "produced_unverified",
            "training_code_commit": commit,
            "model_manifest": "models/construction-dqn-v1/manifest.json",
            "model_sha256": model_manifest["sha256"],
            "training_asset_manifest": "training/assets/construction-dqn-v1/manifest.json",
            "training_asset_manifest_sha256": asset_manifest_digest,
            "verification_command": "python -m pytest tests/strategies tests/training -q",
        },
    )


if __name__ == "__main__":
    main()
