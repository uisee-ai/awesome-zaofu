from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from scenarioforge.application import (
    ApplicationError,
    P0A_DELIVERY_MANIFEST,
    ScenarioForgeApplication,
    application_error_payload,
)
from scenarioforge.clients import ScenarioForgeClient, ScenarioForgeClientError
from scenarioforge.core import strict_loads
from scenarioforge.web.server import DEFAULT_PORT, serve as serve_web


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scenarioforge")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--workspace", type=Path, default=Path.cwd() / ".scenarioforge-runs")
    commands = parser.add_subparsers(dest="command", required=True)

    compile_parser = commands.add_parser("compile", help="strictly load and exact-compile a scenario")
    compile_parser.add_argument("scenario", type=Path)

    run_parser = commands.add_parser("run", help="execute one isolated run")
    run_parser.add_argument("scenario", type=Path)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--attempt-id", required=True)
    run_parser.add_argument("--timeout-seconds", type=int, default=120)

    reproduce_parser = commands.add_parser("reproduce", help="execute and compare three runs")
    reproduce_parser.add_argument("scenario", type=Path)
    reproduce_parser.add_argument("--comparison-id", required=True)
    reproduce_parser.add_argument("--run-id-prefix", required=True)
    reproduce_parser.add_argument("--timeout-seconds", type=int, default=120)

    web_parser = commands.add_parser("web", help="serve the local immutable replay UI")
    web_parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    web_parser.add_argument("--timeout-seconds", type=int, default=120)

    validate_parser = commands.add_parser("validate", help="validate a scenario as stable JSON")
    validate_parser.add_argument("--json", dest="scenario", type=Path, required=True)

    preflight_parser = commands.add_parser("preflight", help="preflight a scenario as stable JSON")
    preflight_parser.add_argument("--json", dest="scenario", type=Path, required=True)

    commands.add_parser("health", help="report local client capabilities")

    submit_parser = commands.add_parser("experiment-submit", help="freeze a batch Experiment")
    submit_parser.add_argument("--json", dest="definition", type=Path, required=True)
    submit_parser.add_argument("--idempotency-key", required=True)

    query_parser = commands.add_parser("experiment-query", help="query persistent Experiments")
    query_parser.add_argument("--experiment-id")

    control_parser = commands.add_parser("experiment-control", help="control one Experiment")
    control_parser.add_argument("experiment_id")
    control_parser.add_argument("operation", choices=("start", "pause", "step", "resume", "stop", "reset"))
    control_parser.add_argument("--command-id", required=True)

    commands.add_parser("experiment-recover", help="recover and query persistent Experiments")
    commands.add_parser("comparison-contract", help="print the frozen paired comparison contract")

    candidate_parser = commands.add_parser(
        "candidate-contract",
        help="print the frozen P1 entrypoint and gate contract",
    )
    candidate_parser.add_argument("--candidate-commit", required=True)

    commands.add_parser("trace", help="print the frozen P0-A delivery manifest")
    return parser


def _write(payload: object, *, stream: object | None = None) -> None:
    destination = sys.stdout if stream is None else stream
    print(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        file=destination,
    )


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "trace":
        _write(P0A_DELIVERY_MANIFEST.to_dict())
        return 0
    if arguments.command == "web":
        serve_web(
            workspace=arguments.workspace,
            project_root=arguments.project_root,
            port=arguments.port,
            timeout_seconds=arguments.timeout_seconds,
        )
        return 0
    if arguments.command == "candidate-contract":
        application = ScenarioForgeApplication(
            workspace=arguments.workspace,
            project_root=arguments.project_root,
        )
        try:
            payload = application.candidate_contract(
                arguments.candidate_commit
            ).to_dict()
        except ApplicationError as error:
            _write(application_error_payload(error), stream=sys.stderr)
            return 2
        _write(payload)
        return 0

    client_commands = {
        "validate",
        "preflight",
        "health",
        "experiment-submit",
        "experiment-query",
        "experiment-control",
        "experiment-recover",
        "comparison-contract",
    }
    if arguments.command in client_commands:
        client = ScenarioForgeClient(
            workspace=arguments.workspace,
            project_root=arguments.project_root,
        )
        try:
            if arguments.command == "validate":
                response = client.validate(arguments.scenario)
            elif arguments.command == "preflight":
                response = client.preflight(arguments.scenario)
            elif arguments.command == "health":
                response = client.health()
            elif arguments.command == "experiment-submit":
                raw_definition = strict_loads(arguments.definition.read_bytes())
                if not isinstance(raw_definition, dict):
                    raise ScenarioForgeClientError(
                        operation="submit_experiment",
                        code="client_request_invalid",
                        message="submit_experiment request failed closed",
                    )
                response = client.submit_experiment(
                    raw_definition,
                    idempotency_key=arguments.idempotency_key,
                )
            elif arguments.command == "experiment-query":
                response = (
                    client.list_experiments()
                    if arguments.experiment_id is None
                    else client.get_experiment(arguments.experiment_id)
                )
            elif arguments.command == "experiment-control":
                response = client.control_experiment(
                    arguments.experiment_id,
                    arguments.operation,
                    command_id=arguments.command_id,
                )
            elif arguments.command == "experiment-recover":
                response = client.recover_experiments()
            else:
                response = client.comparison_contract()
        except ScenarioForgeClientError as error:
            _write(error.to_dict(), stream=sys.stderr)
            return 2
        _write(response.to_dict())
        return 0

    application = ScenarioForgeApplication(
        workspace=arguments.workspace,
        project_root=arguments.project_root,
    )
    try:
        if arguments.command == "compile":
            payload = application.prepare(arguments.scenario).to_dict()
        elif arguments.command == "run":
            outcome = application.run_single(
                arguments.scenario,
                run_id=arguments.run_id,
                attempt_id=arguments.attempt_id,
                timeout_seconds=arguments.timeout_seconds,
            )
            payload = {
                "schema_version": "scenarioforge.application-run/v1",
                "run_result": outcome.run_result.to_dict(),
                "artifact_index_digest": outcome.artifact_index.digest,
            }
        else:
            outcome = application.run_three(
                arguments.scenario,
                comparison_id=arguments.comparison_id,
                run_id_prefix=arguments.run_id_prefix,
                timeout_seconds=arguments.timeout_seconds,
            )
            payload = outcome.report.to_dict()
    except ApplicationError as error:
        _write(application_error_payload(error), stream=sys.stderr)
        return 2
    _write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
