"""Shared request and result schema definitions for the Studio backend."""

from .scene import InferenceResult, SceneInput, SceneWarning, validate_scene_input

__all__ = ["InferenceResult", "SceneInput", "SceneWarning", "validate_scene_input"]
