"""Strict ONNX manifest and CPU-only inference boundary."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import onnxruntime as ort


class ModelContractError(RuntimeError):
    """The runtime model failed a qualification or inference invariant."""


_MANIFEST_KEYS = {
    "schema_version",
    "model_id",
    "version",
    "filename",
    "source",
    "training_code_commit",
    "dependencies",
    "input",
    "output",
    "action_mapping",
    "operators",
    "opset",
    "external_data",
    "custom_ops",
    "providers",
    "byte_length",
    "sha256",
    "resource_limits",
    "license",
}
_RUNTIME_FILES = {"manifest.json", "model.onnx"}
_ALLOWED_OPERATORS = {"Cast", "Flatten", "Gemm", "Relu"}


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelContractError(f"duplicate manifest key: {key}")
        result[key] = value
    return result


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_strict_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelContractError("invalid model manifest") from error
    if not isinstance(manifest, dict) or set(manifest) != _MANIFEST_KEYS:
        raise ModelContractError("model manifest fields do not match the frozen schema")
    return manifest


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while offset < len(data) and shift <= 63:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            return value, offset
        shift += 7
    raise ModelContractError("malformed ONNX protobuf varint")


def _protobuf_fields(data: bytes) -> Iterator[tuple[int, int, int | bytes]]:
    offset = 0
    while offset < len(data):
        key, offset = _varint(data, offset)
        field_number, wire_type = key >> 3, key & 7
        if field_number == 0:
            raise ModelContractError("malformed ONNX protobuf field")
        if wire_type == 0:
            value, offset = _varint(data, offset)
            yield field_number, wire_type, value
        elif wire_type == 1:
            if offset + 8 > len(data):
                raise ModelContractError("truncated ONNX protobuf field")
            yield field_number, wire_type, data[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _varint(data, offset)
            if offset + length > len(data):
                raise ModelContractError("truncated ONNX protobuf message")
            yield field_number, wire_type, data[offset : offset + length]
            offset += length
        elif wire_type == 5:
            if offset + 4 > len(data):
                raise ModelContractError("truncated ONNX protobuf field")
            yield field_number, wire_type, data[offset : offset + 4]
            offset += 4
        else:
            raise ModelContractError("unsupported ONNX protobuf wire type")


def _inspect_onnx(data: bytes) -> tuple[set[str], set[str], int, bool]:
    graph: bytes | None = None
    opset = None
    for number, wire, value in _protobuf_fields(data):
        if number == 7 and wire == 2:
            graph = bytes(value)
        elif number == 8 and wire == 2:
            domain = ""
            version = None
            for item_number, item_wire, item_value in _protobuf_fields(bytes(value)):
                if item_number == 1 and item_wire == 2:
                    domain = bytes(item_value).decode("utf-8")
                elif item_number == 2 and item_wire == 0:
                    version = int(item_value)
            if domain in {"", "ai.onnx"}:
                opset = version
    if graph is None or opset is None:
        raise ModelContractError("ONNX graph or default opset is missing")

    operators: set[str] = set()
    domains: set[str] = set()
    external_data = False
    for number, wire, value in _protobuf_fields(graph):
        if number == 1 and wire == 2:
            operator = None
            domain = ""
            for node_number, node_wire, node_value in _protobuf_fields(bytes(value)):
                if node_number == 4 and node_wire == 2:
                    operator = bytes(node_value).decode("utf-8")
                elif node_number == 7 and node_wire == 2:
                    domain = bytes(node_value).decode("utf-8")
            if not operator:
                raise ModelContractError("ONNX node has no operator")
            operators.add(operator)
            domains.add(domain)
        elif number == 5 and wire == 2:
            for tensor_number, tensor_wire, tensor_value in _protobuf_fields(bytes(value)):
                if tensor_number == 13 and tensor_wire == 2:
                    external_data = True
                elif tensor_number == 14 and tensor_wire == 0 and int(tensor_value) != 0:
                    external_data = True
    return operators, domains, opset, external_data


def _fixed_shape(value: Any, label: str) -> tuple[int, ...]:
    if not isinstance(value, list) or not value or any(type(item) is not int or item <= 0 for item in value):
        raise ModelContractError(f"{label} shape must be fixed positive integers")
    return tuple(value)


@dataclass(frozen=True)
class VerifiedOnnxModel:
    """A loaded model whose bytes, graph, I/O and provider are all qualified."""

    model_id: str
    version: str
    input_name: str
    input_shape: tuple[int, ...]
    output_name: str
    output_shape: tuple[int, ...]
    action_mapping: tuple[str, ...]
    operators: frozenset[str]
    providers: tuple[str, ...]
    sha256: str
    _session: ort.InferenceSession

    @classmethod
    def load(cls, model_dir: str | Path) -> "VerifiedOnnxModel":
        directory = Path(model_dir)
        if directory.is_symlink() or not directory.is_dir():
            raise ModelContractError("runtime model directory is invalid")
        actual_files = {
            path.name for path in directory.iterdir() if path.is_file() or path.is_symlink()
        }
        if actual_files != _RUNTIME_FILES or any(path.is_symlink() for path in directory.iterdir()):
            raise ModelContractError("runtime model directory contains non-whitelisted files")

        manifest = _read_manifest(directory / "manifest.json")
        if manifest["schema_version"] != "construction-dqn-model-manifest/v1":
            raise ModelContractError("unsupported model manifest version")
        if manifest["filename"] != "model.onnx":
            raise ModelContractError("model filename is not the fixed runtime path")
        model_path = directory / "model.onnx"
        model_bytes = model_path.read_bytes()
        if len(model_bytes) != manifest["byte_length"]:
            raise ModelContractError("model byte length mismatch")
        digest = hashlib.sha256(model_bytes).hexdigest()
        if digest != manifest["sha256"]:
            raise ModelContractError("model sha256 mismatch")
        maximum_bytes = manifest["resource_limits"].get("max_model_bytes")
        if type(maximum_bytes) is not int or len(model_bytes) > maximum_bytes:
            raise ModelContractError("model exceeds its frozen resource limit")

        operators, domains, opset, has_external_data = _inspect_onnx(model_bytes)
        if operators != set(manifest["operators"]) or not operators <= _ALLOWED_OPERATORS:
            raise ModelContractError("ONNX operator whitelist mismatch")
        if domains - {"", "ai.onnx"} or manifest["custom_ops"] is not False:
            raise ModelContractError("custom or contrib ONNX operators are forbidden")
        if has_external_data or manifest["external_data"] is not False:
            raise ModelContractError("external ONNX data is forbidden")
        if opset != manifest["opset"]:
            raise ModelContractError("ONNX opset mismatch")
        if manifest["providers"] != ["CPUExecutionProvider"]:
            raise ModelContractError("only CPUExecutionProvider is permitted")

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        try:
            session = ort.InferenceSession(
                model_bytes,
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
            session.disable_fallback()
        except Exception as error:
            raise ModelContractError("ONNX Runtime rejected the qualified model") from error
        if session.get_providers() != ["CPUExecutionProvider"]:
            raise ModelContractError("ONNX Runtime provider drift")
        inputs = session.get_inputs()
        outputs = session.get_outputs()
        if len(inputs) != 1 or len(outputs) != 1:
            raise ModelContractError("model must expose exactly one input and one output")
        input_contract = manifest["input"]
        output_contract = manifest["output"]
        input_shape = _fixed_shape(input_contract.get("shape"), "input")
        output_shape = _fixed_shape(output_contract.get("shape"), "output")
        if (
            inputs[0].name != input_contract.get("name")
            or inputs[0].type != "tensor(float)"
            or tuple(inputs[0].shape) != input_shape
        ):
            raise ModelContractError("ONNX input shape, name or dtype mismatch")
        if (
            outputs[0].name != output_contract.get("name")
            or outputs[0].type != "tensor(float)"
            or tuple(outputs[0].shape) != output_shape
        ):
            raise ModelContractError("ONNX output shape, name or dtype mismatch")
        if output_shape != (1, len(manifest["action_mapping"])):
            raise ModelContractError("output shape does not match the action mapping")

        return cls(
            model_id=manifest["model_id"],
            version=manifest["version"],
            input_name=inputs[0].name,
            input_shape=input_shape,
            output_name=outputs[0].name,
            output_shape=output_shape,
            action_mapping=tuple(manifest["action_mapping"]),
            operators=frozenset(operators),
            providers=tuple(session.get_providers()),
            sha256=digest,
            _session=session,
        )

    def infer(self, observation: np.ndarray) -> np.ndarray:
        value = np.asarray(observation, dtype=np.float32)
        if value.shape != self.input_shape or not np.isfinite(value).all():
            raise ModelContractError("inference input violates fixed shape or finiteness")
        try:
            output = self._session.run([self.output_name], {self.input_name: value})[0]
        except Exception as error:
            raise ModelContractError("ONNX inference failed") from error
        result = np.asarray(output, dtype=np.float32)
        if result.shape != self.output_shape or not np.isfinite(result).all():
            raise ModelContractError("inference output violates fixed shape or finiteness")
        return result
