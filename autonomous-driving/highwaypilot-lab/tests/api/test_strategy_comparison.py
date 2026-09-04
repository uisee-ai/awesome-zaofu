from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from highwaypilot_lab.api import RuntimeService, create_app
from highwaypilot_lab.episodes import validate_replay


PROJECT_ROOT = Path(__file__).parents[2]
BASE_URL = "http://127.0.0.1:4317"
ORIGIN = BASE_URL


def test_strategy_comparison_returns_traceable_metrics_and_savable_failed_replays(
    tmp_path: Path,
) -> None:
    shutil.copytree(
        PROJECT_ROOT / "models" / "construction-dqn-v1",
        tmp_path / "models" / "construction-dqn-v1",
    )
    runtime = RuntimeService(project_root=tmp_path)
    client = TestClient(create_app(runtime=runtime), base_url=BASE_URL)
    config = json.loads(
        (PROJECT_ROOT / "configs" / "presets" / "normal-v1.json").read_text(
            encoding="utf-8"
        )
    )

    response = client.post(
        "/api/strategy-comparisons",
        json={"config": config, "manual_actions": ["IDLE", "IDLE"], "max_steps": 2},
        headers={"origin": ORIGIN},
    )

    assert response.status_code == 200
    comparison = response.json()
    assert comparison["schema_version"] == "strategy-comparison/v1"
    assert comparison["aggregation"] is None
    assert len(comparison["episodes"]) == 4
    for episode in comparison["episodes"]:
        metrics = episode["metrics"]
        assert metrics["collision"] is (episode["result"] == "collision")
        assert metrics["success"] is (episode["result"] == "merge_success")
        assert metrics["timeout"] is (episode["result"] in {"timeout", "step_limit"})
        assert validate_replay(episode["replay"]) == episode["replay"]

    failed = next(episode for episode in comparison["episodes"] if not episode["metrics"]["success"])
    saved = client.post(
        "/api/episodes",
        json={"replay": failed["replay"], "name": "comparison failure"},
        headers={"origin": ORIGIN},
    )
    assert saved.status_code == 201
    episode_id = saved.json()["episode_id"]
    loaded = client.get(f"/api/episodes/{episode_id}")
    assert loaded.status_code == 200
    assert loaded.json()["termination_reason"] == failed["result"]
