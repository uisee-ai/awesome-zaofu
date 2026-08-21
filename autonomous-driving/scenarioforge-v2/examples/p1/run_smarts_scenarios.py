from __future__ import annotations

import argparse
from pathlib import Path

from scenarioforge.runtime.smarts_worker import (
    CANONICAL_SMARTS_SCENARIOS,
    publish_smarts_evidence,
    run_canonical_smarts_scenario,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run one content-bound ScenarioForge P1 scenario on SMARTS 2.0.1."
    )
    parser.add_argument("scenario_id", choices=CANONICAL_SMARTS_SCENARIOS)
    parser.add_argument("--run-id", default="p1-smarts-demo")
    parser.add_argument("--max-episode-steps", type=int, default=80)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/p1/smarts"))
    arguments = parser.parse_args(argv)

    evidence = run_canonical_smarts_scenario(
        arguments.scenario_id,
        run_id=arguments.run_id,
        max_episode_steps=arguments.max_episode_steps,
    )
    output = publish_smarts_evidence(evidence, arguments.output_dir)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
