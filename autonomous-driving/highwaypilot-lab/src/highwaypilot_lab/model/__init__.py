"""Fail-closed runtime access to the single qualified ONNX model."""

from .runtime import ModelContractError, VerifiedOnnxModel

__all__ = ["ModelContractError", "VerifiedOnnxModel"]
