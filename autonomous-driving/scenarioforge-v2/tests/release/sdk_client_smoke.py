from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from scenarioforge.clients import ScenarioForgeClient, ScenarioForgeClientError


ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        required=True,
        choices=("health", "validate", "preflight", "comparison"),
    )
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    project_root = Path(os.environ.get("SCENARIOFORGE_PROJECT_ROOT", ROOT))
    workspace = Path(
        os.environ.get(
            "SCENARIOFORGE_WORKSPACE",
            project_root / ".scenarioforge-client-smoke",
        )
    )
    client = ScenarioForgeClient(
        project_root=project_root,
        workspace=workspace,
    )
    try:
        if arguments.operation == "health":
            response = client.health()
        elif arguments.operation == "validate":
            response = client.validate(project_root / "examples" / "p0c" / "brake_lead.json")
        elif arguments.operation == "preflight":
            response = client.preflight(project_root / "examples" / "p0c" / "brake_lead.json")
        else:
            response = client.comparison_contract()
    except ScenarioForgeClientError as error:
        print(json.dumps(error.to_dict(), sort_keys=True, separators=(",", ":")))
        return 2
    print(json.dumps(response.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
