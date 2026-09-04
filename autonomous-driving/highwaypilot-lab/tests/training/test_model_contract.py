from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from highwaypilot_lab.model import ModelContractError, VerifiedOnnxModel


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models/construction-dqn-v1"


def test_runtime_model_is_hash_bound_fixed_shape_cpu_only_and_runnable() -> None:
    model = VerifiedOnnxModel.load(MODEL_DIR)

    assert model.input_name == "observation"
    assert model.input_shape == (1, 10)
    assert model.output_name == "q_values"
    assert model.output_shape == (1, 5)
    assert model.providers == ("CPUExecutionProvider",)
    assert model.operators == {"Cast", "Flatten", "Gemm", "Relu"}
    q_values = model.infer(np.zeros((1, 10), dtype=np.float32))
    assert q_values.shape == (1, 5)
    assert np.isfinite(q_values).all()


def test_model_loader_fails_closed_on_hash_shape_and_operator_drift(tmp_path: Path) -> None:
    manifest = json.loads((MODEL_DIR / "manifest.json").read_text())
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    model_bytes = (MODEL_DIR / "model.onnx").read_bytes()
    (tmp_path / "model.onnx").write_bytes(model_bytes + b"tampered")

    with pytest.raises(ModelContractError, match="sha256|byte length"):
        VerifiedOnnxModel.load(tmp_path)

    (tmp_path / "model.onnx").write_bytes(model_bytes)
    manifest["input"]["shape"] = [1, 9]
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ModelContractError, match="input shape"):
        VerifiedOnnxModel.load(tmp_path)


def test_runtime_model_directory_rejects_training_artifacts(tmp_path: Path) -> None:
    for name in ("manifest.json", "model.onnx"):
        (tmp_path / name).write_bytes((MODEL_DIR / name).read_bytes())
    (tmp_path / "checkpoint.zip").write_bytes(b"forbidden")

    with pytest.raises(ModelContractError, match="runtime model directory"):
        VerifiedOnnxModel.load(tmp_path)
