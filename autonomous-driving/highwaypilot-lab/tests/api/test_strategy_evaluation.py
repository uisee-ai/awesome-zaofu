from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

import highwaypilot_lab.api.server as server
from highwaypilot_lab.api import RuntimeService, create_app


ROOT = Path(__file__).parents[2]
BASE_URL = "http://127.0.0.1:4317"


def test_strategy_evaluation_runs_as_a_progress_job_with_paired_seed_range(monkeypatch) -> None:
    captured: dict = {}

    def fake_evaluation(config, *, seeds, strategy_ids, progress, **_kwargs):
        captured.update(seeds=seeds, strategy_ids=strategy_ids, base_seed=config["seed"])
        total = len(seeds) * len(strategy_ids)
        progress(total, total)
        return {
            "schema_version": "strategy-evaluation/v1",
            "seeds": seeds,
            "episodes_per_strategy": len(seeds),
            "strategy_order": strategy_ids,
            "total_episodes": total,
            "episodes": [],
            "strategies": [],
        }

    monkeypatch.setattr(server, "run_paired_strategy_evaluation", fake_evaluation)
    config = json.loads((ROOT / "configs/presets/normal-v1.json").read_text(encoding="utf-8"))
    runtime = RuntimeService(project_root=ROOT)
    with TestClient(create_app(runtime=runtime), base_url=BASE_URL) as client:
        created = client.post(
            "/api/strategy-evaluations",
            json={
                "config": config,
                "episodes_per_strategy": 3,
                "seed_start": 700,
                "strategies": ["random", "qualified_rule"],
            },
            headers={"origin": BASE_URL},
        )
        assert created.status_code == 202
        evaluation_id = created.json()["evaluation_id"]
        for _ in range(50):
            current = client.get(
                f"/api/strategy-evaluations/{evaluation_id}",
                headers={"origin": BASE_URL},
            )
            if current.json()["status"] == "completed":
                break
            time.sleep(0.01)

        assert current.status_code == 200
        assert current.json()["progress"] == {"completed": 6, "total": 6}
        assert current.json()["result"]["seeds"] == [700, 701, 702]
        assert captured == {
            "seeds": [700, 701, 702],
            "strategy_ids": ["random", "qualified_rule"],
            "base_seed": config["seed"],
        }


def test_strategy_evaluation_rejects_seed_overflow() -> None:
    config = json.loads((ROOT / "configs/presets/normal-v1.json").read_text(encoding="utf-8"))
    runtime = RuntimeService(project_root=ROOT)
    with TestClient(create_app(runtime=runtime), base_url=BASE_URL) as client:
        response = client.post(
            "/api/strategy-evaluations",
            json={"config": config, "episodes_per_strategy": 2, "seed_start": 4_294_967_295},
            headers={"origin": BASE_URL},
        )
    assert response.status_code == 422
    assert "Seed range" in response.json()["error"]["message"]
