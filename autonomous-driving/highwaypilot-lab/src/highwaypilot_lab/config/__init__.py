"""Strict construction-v0 configuration boundary."""

from .parser import DEFAULT_CONFIG, UINT32_MAX, ConfigError, parse_config, parse_config_json

__all__ = ["DEFAULT_CONFIG", "UINT32_MAX", "ConfigError", "parse_config", "parse_config_json"]
