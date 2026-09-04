from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_replay_schema_is_valid_and_closed(replay_document):
    schema_path = Path("schemas/highwaypilot-replay/v1.schema.json")
    schema = json.loads(schema_path.read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(replay_document)
    assert schema["additionalProperties"] is False
