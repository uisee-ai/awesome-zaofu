from __future__ import annotations

import math
from dataclasses import replace
from collections.abc import Mapping
from typing import Any

from .canonical import canonical_digest, freeze_json
from .models import (
    CapabilityDescriptor,
    CapabilityMapping,
    CompilationDiagnostic,
    CompilationStatus,
    CompileBundle,
    CompileReport,
    ExecutionPlan,
    ScenarioInstance,
)


COMPILER_VERSION = "1.0.0"
COMPILER_VERSION_V2 = "2.0.0"
COMPILER_VERSION_AUTHORING = "3.0.0"
ADAPTER_ID = "scenarioforge.metadrive"
ADAPTER_VERSION = "1.0.0"
ADAPTER_VERSION_V2 = "2.0.0"
ADAPTER_VERSION_AUTHORING = "3.0.0"
METADRIVE_VERSION = "0.4.3"
METADRIVE_FIRST_BLOCK_ENTRANCE_LENGTH_M = 10.0

SUPPORTED_CAPABILITIES = (
    "constraints.horizon-collision",
    "coordinate.right-handed-x-forward-y-left",
    "event.tick-brake",
    "participant.ego",
    "participant.social-vehicle",
    "policy.constant-lane.v1",
    "road.lanes.2",
    "road.straight",
    "units.si-tick",
)

SUPPORTED_CAPABILITIES_V2 = (
    "actor.spawn.v2",
    "event.ordered.v2",
    "lane.stable-id.v2",
    "metric.definition.v2",
    "policy.deterministic.v2",
    "route.stable-id.v2",
    "terminal.dual-axis.v2",
    "topology.versioned.v2",
    "trigger.tick.v2",
)


class ScenarioCompiler:
    """Pure compiler: this module deliberately has no MetaDrive import."""

    def capabilities(
        self,
        schema_version: str = "scenarioforge.scenario/v1",
    ) -> CapabilityDescriptor:
        if schema_version == "scenarioforge.scenario/v2":
            return CapabilityDescriptor(
                schema_version="scenarioforge.capability-descriptor/v2",
                backend_id="metadrive",
                backend_version=METADRIVE_VERSION,
                adapter_id=ADAPTER_ID,
                adapter_version=ADAPTER_VERSION_V2,
                compiler_version=COMPILER_VERSION_V2,
                supported_capabilities=SUPPORTED_CAPABILITIES_V2,
                extension_contracts=freeze_json(
                    {
                        "metadrive": {
                            "schema_version": "scenarioforge.metadrive-extension/v2",
                            "allowed_fields": [],
                        }
                    }
                ),
            )
        return CapabilityDescriptor(
            schema_version="scenarioforge.capability-descriptor/v1",
            backend_id="metadrive",
            backend_version=METADRIVE_VERSION,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION,
            compiler_version=COMPILER_VERSION,
            supported_capabilities=SUPPORTED_CAPABILITIES,
            extension_contracts=freeze_json(
                {
                    "metadrive": {
                        "schema_version": "scenarioforge.metadrive-extension/v1",
                        "allowed_fields": [],
                    }
                }
            ),
        )

    def compile(self, scenario: ScenarioInstance) -> CompileBundle:
        if scenario.source_schema_version == "scenarioforge.scenario/v2":
            return self._compile_v2(scenario)
        descriptor = self.capabilities()
        mappings: list[CapabilityMapping] = []
        diagnostics: list[CompilationDiagnostic] = []
        supported = set(descriptor.supported_capabilities)

        for index, capability in enumerate(scenario.required_capabilities):
            status = CompilationStatus.EXACT if capability in supported else CompilationStatus.UNSUPPORTED
            mapping = CapabilityMapping(
                path=f"$.required_capabilities[{index}]",
                capability=capability,
                status=status,
                reason=(
                    "supported without semantic loss"
                    if status is CompilationStatus.EXACT
                    else "required capability is not supported by the MetaDrive P0-A adapter"
                ),
                alternative=(
                    None
                    if status is CompilationStatus.EXACT
                    else "remove the capability or select a backend that declares exact support"
                ),
            )
            mappings.append(mapping)
            if status is not CompilationStatus.EXACT:
                diagnostics.append(
                    CompilationDiagnostic(
                        path=mapping.path,
                        capability=mapping.capability,
                        status=mapping.status,
                        reason=mapping.reason,
                        alternative=mapping.alternative,
                    )
                )

        lane_count = int(scenario.road["lane_count"])
        if lane_count != 2:
            diagnostics.append(
                CompilationDiagnostic(
                    path="$.road.lane_count",
                    capability="road.lanes.2",
                    status=CompilationStatus.UNSUPPORTED,
                    reason="MetaDrive P0-A is frozen to an exact two-lane road",
                    alternative="set road.lane_count to 2",
                )
            )
        lane_width = float(scenario.road["lane_width_m"])
        if lane_width != 3.5:
            diagnostics.append(
                CompilationDiagnostic(
                    path="$.road.lane_width_m",
                    capability="road.lane-width.3.5m",
                    status=CompilationStatus.LOSSY,
                    reason="MetaDrive P0-A is frozen to a 3.5 m lane width",
                    alternative="set road.lane_width_m to 3.5",
                )
            )

        extensions = scenario.backend_extensions["extensions"]
        assert isinstance(extensions, dict | type(freeze_json({})))
        for namespace, extension in extensions.items():
            if namespace != "metadrive":
                diagnostics.append(
                    CompilationDiagnostic(
                        path=f"$.backend_extensions.extensions.{namespace}",
                        capability=f"backend-extension.{namespace}",
                        status=CompilationStatus.UNSUPPORTED,
                        reason="extension namespace is not supported by the MetaDrive adapter",
                        alternative="remove the extension and express the scenario with the P0-A core",
                    )
                )
            elif extension["options"]:
                diagnostics.append(
                    CompilationDiagnostic(
                        path="$.backend_extensions.extensions.metadrive.options",
                        capability="backend-extension.metadrive",
                        status=CompilationStatus.UNSUPPORTED,
                        reason="MetaDrive P0-A does not define extension options",
                        alternative="use an empty options object",
                    )
                )

        statuses = {diagnostic.status for diagnostic in diagnostics}
        if CompilationStatus.UNSUPPORTED in statuses:
            overall_status = CompilationStatus.UNSUPPORTED
        elif CompilationStatus.LOSSY in statuses:
            overall_status = CompilationStatus.LOSSY
        else:
            overall_status = CompilationStatus.EXACT

        report = CompileReport(
            schema_version="scenarioforge.compile-report/v1",
            compiler_version=COMPILER_VERSION,
            capability_descriptor_digest=descriptor.digest,
            scenario_instance_digest=scenario.digest,
            overall_status=overall_status,
            executable=overall_status is CompilationStatus.EXACT,
            mappings=tuple(mappings),
            diagnostics=tuple(diagnostics),
        )
        plan = self._execution_plan(scenario) if report.executable else None
        return CompileBundle(scenario_instance=scenario, report=report, execution_plan=plan)

    def compile_revision(self, revision: Any) -> tuple[CapabilityDescriptor, CompileBundle]:
        """Compile only an immutable library revision and retain its server identity."""
        content = revision.content
        if not isinstance(content, Mapping):
            raise ValueError("scenario revision content must be an object")
        source_schema = str(revision.schema_version)
        if source_schema in {"scenarioforge.scenario/v1", "scenarioforge.scenario/v2"}:
            instance = replace(
                ScenarioInstance.from_spec(content, revision.canonical_digest),
                schema_version="scenarioforge.scenario-instance/v3",
                scenario_id=str(revision.scenario_id),
                revision_id=str(revision.revision_id),
                revision_digest=str(revision.canonical_digest),
                revision_schema_version=source_schema,
            )
            descriptor = self.capabilities(source_schema)
            legacy = self.compile(instance)
            adapter = {"id": descriptor.adapter_id, "version": descriptor.adapter_version}
            report = replace(
                legacy.report,
                schema_version="scenarioforge.compile-report/v3",
                adapter_id=descriptor.adapter_id,
                adapter_version=descriptor.adapter_version,
                adapter_digest=canonical_digest(adapter),
            )
            plan = legacy.execution_plan
            if report.overall_status is CompilationStatus.LOSSY and plan is None:
                plan = self._execution_plan(instance)
            return descriptor, CompileBundle(instance, report, plan)
        if source_schema == "scenarioforge.authoring/v1":
            return self._compile_authoring_revision(revision)
        raise ValueError(f"unsupported revision schema: {source_schema}")

    def _compile_authoring_revision(
        self, revision: Any
    ) -> tuple[CapabilityDescriptor, CompileBundle]:
        content = revision.content
        descriptor = CapabilityDescriptor(
            schema_version="scenarioforge.capability-descriptor/v3",
            backend_id="metadrive",
            backend_version=METADRIVE_VERSION,
            adapter_id=ADAPTER_ID,
            adapter_version=ADAPTER_VERSION_AUTHORING,
            compiler_version=COMPILER_VERSION_AUTHORING,
            supported_capabilities=(
                "actor.vehicle",
                "coordinate.right-handed-x-forward-y-left",
                "policy.deterministic.v2",
                "road.straight",
                "route.stable-id",
                "units.si",
            ),
            extension_contracts=freeze_json({}),
        )
        instance = ScenarioInstance(
            schema_version="scenarioforge.scenario-instance/v3",
            scenario_id=str(revision.scenario_id),
            source_schema_version=str(revision.schema_version),
            source_spec_digest=str(revision.canonical_digest),
            seed=int(content["seed"]),
            road=freeze_json(content["road"]),
            participants=freeze_json(content["actors"]),
            parameters=freeze_json({"definitions": content["parameters"]}),
            events=freeze_json(content["events"]),
            constraints=freeze_json(content["constraints"]),
            policy=freeze_json(content["policy"]),
            required_capabilities=tuple(str(item) for item in content["required_capabilities"]),
            backend_extensions=freeze_json({"extensions": {}}),
            revision_id=str(revision.revision_id),
            revision_digest=str(revision.canonical_digest),
            revision_schema_version=str(revision.schema_version),
        )
        top_level = (
            "title", "description", "seed", "road", "routes", "actors",
            "static_obstacles", "environment", "events", "constraints",
            "parameters", "policy", "required_capabilities",
        )
        unsupported_fields: dict[str, str] = {}
        if content["road"]["topology_kind"] not in {"straight", "corridor"}:
            unsupported_fields["road"] = "authoring topology is not exactly supported"
        if any(actor["kind"] != "vehicle" for actor in content["actors"]):
            unsupported_fields["actors"] = "non-vehicle actors are unsupported"
        if content["static_obstacles"]:
            unsupported_fields["static_obstacles"] = "static obstacles are unsupported"
        mappings: list[CapabilityMapping] = []
        diagnostics: list[CompilationDiagnostic] = []
        for field in top_level:
            status = (
                CompilationStatus.UNSUPPORTED
                if field in unsupported_fields
                else CompilationStatus.EXACT
            )
            reason = unsupported_fields.get(field, "field is retained without semantic loss")
            mapping = CapabilityMapping(
                path=f"$.{field}",
                capability=f"authoring.{field}",
                status=status,
                reason=reason,
                alternative=None if status is CompilationStatus.EXACT else "use supported core primitives",
            )
            mappings.append(mapping)
            if status is not CompilationStatus.EXACT:
                diagnostics.append(
                    CompilationDiagnostic(
                        mapping.path, mapping.capability, mapping.status,
                        mapping.reason, mapping.alternative,
                    )
                )
        for index, actor in enumerate(content["actors"]):
            if actor["kind"] != "vehicle":
                diagnostics.append(
                    CompilationDiagnostic(
                        path=f"$.actors[{index}].kind",
                        capability=f"actor.{actor['kind']}",
                        status=CompilationStatus.UNSUPPORTED,
                        reason="MetaDrive authoring adapter supports vehicle actors only",
                        alternative="select an adapter with exact actor support",
                    )
                )
        supported = set(descriptor.supported_capabilities)
        for index, capability in enumerate(instance.required_capabilities):
            if capability not in supported:
                diagnostics.append(
                    CompilationDiagnostic(
                        path=f"$.required_capabilities[{index}]",
                        capability=capability,
                        status=CompilationStatus.UNSUPPORTED,
                        reason="required authoring capability is not supported",
                        alternative="select an adapter declaring exact support",
                    )
                )
        overall = (
            CompilationStatus.UNSUPPORTED if diagnostics else CompilationStatus.EXACT
        )
        adapter = {"id": descriptor.adapter_id, "version": descriptor.adapter_version}
        report = CompileReport(
            schema_version="scenarioforge.compile-report/v3",
            compiler_version=COMPILER_VERSION_AUTHORING,
            capability_descriptor_digest=descriptor.digest,
            scenario_instance_digest=instance.digest,
            overall_status=overall,
            executable=False,
            mappings=tuple(mappings),
            diagnostics=tuple(diagnostics),
            adapter_id=descriptor.adapter_id,
            adapter_version=descriptor.adapter_version,
            adapter_digest=canonical_digest(adapter),
        )
        return descriptor, CompileBundle(instance, report, None)

    def _execution_plan(self, scenario: ScenarioInstance) -> ExecutionPlan:
        return ExecutionPlan(
            schema_version="scenarioforge.execution-plan/v1",
            scenario_instance_digest=scenario.digest,
            backend=freeze_json(
                {
                    "id": "metadrive",
                    "version": METADRIVE_VERSION,
                    "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION},
                }
            ),
            seed=scenario.seed,
            simulation=freeze_json(
                {
                    "map_block_sequence": "S",
                    "lane_count": int(scenario.road["lane_count"]),
                    "lane_width_m": float(scenario.road["lane_width_m"]),
                    "length_m": float(scenario.road["length_m"]),
                    "physics_world_step_size_s": 0.02,
                    "decision_repeat": 5,
                    "max_steps": int(scenario.constraints["max_steps"]),
                    "headless": True,
                    "gpu_required": False,
                }
            ),
            participants=scenario.participants,
            events=scenario.events,
            constraints=scenario.constraints,
            policy=scenario.policy,
            tick_contract=freeze_json(
                {
                    "schema_version": "scenarioforge.tick-contract/v1",
                    "state_indexing": "S_N_at_tick_start",
                    "trigger_evaluation": "S_N_and_tick_N",
                    "action_application": "S_N_to_S_N_plus_1",
                    "event_effect_offset": 1,
                    "priority_order": ["scenario_override", "policy"],
                    "same_tick_events": "preserve_input_order",
                }
            ),
            artifact_contract=freeze_json(
                {
                    "schema_version": "scenarioforge.artifact-contract/v1",
                    "required": [
                        "actions.json",
                        "events.json",
                        "metrics.json",
                        "trajectory.json",
                        "worker_result.json",
                    ],
                    "max_file_bytes": 10_485_760,
                }
            ),
            resource_config=freeze_json(
                {
                    "schema_version": "scenarioforge.resource-config/v1",
                    "wall_clock_timeout_s": 120,
                    "memory_limit_mb": 4096,
                    "pid_limit": 32,
                    "log_limit_bytes": 1_048_576,
                    "artifact_limit_bytes": 10_485_760,
                }
            ),
            tolerances_version="scenarioforge.p0a-tolerances/v1",
        )

    def _compile_v2(self, scenario: ScenarioInstance) -> CompileBundle:
        descriptor = self.capabilities(scenario.source_schema_version)
        supported = set(descriptor.supported_capabilities)
        mappings: list[CapabilityMapping] = []
        diagnostics: list[CompilationDiagnostic] = []

        def reject(path: str, capability: str, reason: str, alternative: str) -> None:
            diagnostics.append(
                CompilationDiagnostic(
                    path=path,
                    capability=capability,
                    status=CompilationStatus.UNSUPPORTED,
                    reason=reason,
                    alternative=alternative,
                )
            )

        for index, capability in enumerate(scenario.required_capabilities):
            status = (
                CompilationStatus.EXACT
                if capability in supported
                else CompilationStatus.UNSUPPORTED
            )
            mapping = CapabilityMapping(
                path=f"$.required_capabilities[{index}]",
                capability=capability,
                status=status,
                reason=(
                    "supported by the versioned P0-C contract"
                    if status is CompilationStatus.EXACT
                    else "required capability is not supported by the MetaDrive P0-C adapter"
                ),
                alternative=(
                    None
                    if status is CompilationStatus.EXACT
                    else "remove the capability or select a backend that declares exact v2 support"
                ),
            )
            mappings.append(mapping)
            if status is not CompilationStatus.EXACT:
                diagnostics.append(
                    CompilationDiagnostic(
                        path=mapping.path,
                        capability=mapping.capability,
                        status=mapping.status,
                        reason=mapping.reason,
                        alternative=mapping.alternative,
                    )
                )

        lanes = tuple(scenario.road["lanes"])
        lane_ids = [str(lane["id"]) for lane in lanes]
        lane_id_set = set(lane_ids)
        lane_by_id = {str(lane["id"]): lane for lane in lanes}
        engine_lane_indexes = [
            (
                str(lane["engine_lane_index"]["start_node"]),
                str(lane["engine_lane_index"]["end_node"]),
                int(lane["engine_lane_index"]["lane_index"]),
            )
            for lane in lanes
        ]
        lane_count = max(index[2] for index in engine_lane_indexes) + 1
        if len(lane_ids) != len(lane_id_set):
            reject(
                "$.road.lanes",
                "lane.stable-id.v2",
                "v2 lane IDs must be unique",
                "assign a stable unique ID to every lane",
            )
        if len(engine_lane_indexes) != len(set(engine_lane_indexes)):
            reject(
                "$.road.lanes",
                "topology.versioned.v2",
                "MetaDrive engine lane indexes must be unique within the topology projection",
                "assign one start_node/end_node/lane_index tuple per stable lane",
            )
        for index, lane in enumerate(lanes):
            engine_lane = engine_lane_indexes[index]
            if engine_lane[0] == engine_lane[1]:
                reject(
                    f"$.road.lanes[{index}].engine_lane_index",
                    "topology.versioned.v2",
                    "MetaDrive engine road endpoints must be distinct",
                    "bind the stable lane to a directed MetaDrive road",
                )
            references = tuple(lane["predecessor_lane_ids"]) + tuple(
                lane["successor_lane_ids"]
            )
            unknown = sorted(str(item) for item in references if item not in lane_id_set)
            if unknown:
                reject(
                    f"$.road.lanes[{index}]",
                    "lane.stable-id.v2",
                    f"lane graph references unknown stable IDs: {', '.join(unknown)}",
                    "reference only IDs declared in road.lanes",
                )
        for index, zone in enumerate(scenario.road["conflict_zones"]):
            unknown = sorted(
                str(item) for item in zone["lane_ids"] if item not in lane_id_set
            )
            if unknown:
                reject(
                    f"$.road.conflict_zones[{index}].lane_ids",
                    "topology.versioned.v2",
                    f"conflict zone references unknown lanes: {', '.join(unknown)}",
                    "bind conflict zones to declared stable lane IDs",
                )
            if float(zone["end_m"]) <= float(zone["start_m"]):
                reject(
                    f"$.road.conflict_zones[{index}]",
                    "topology.versioned.v2",
                    "conflict zone end must follow its start",
                    "increase end_m above start_m",
                )

        route_ids: set[str] = set()
        declared_participant_ids = [
            str(item["id"]) for item in scenario.participants
        ]
        participant_ids = set(declared_participant_ids)
        if len(declared_participant_ids) != len(participant_ids):
            reject(
                "$.participants",
                "actor.spawn.v2",
                "participant IDs must be unique",
                "assign one stable ID to every participant",
            )
        if sum(item["role"] == "ego" for item in scenario.participants) != 1:
            reject(
                "$.participants",
                "actor.spawn.v2",
                "v2 execution requires exactly one ego participant",
                "mark exactly one participant as ego",
            )
        for index, participant in enumerate(scenario.participants):
            spawn_lane = str(participant["spawn"]["lane_id"])
            route = participant["route"]
            route_id = str(route["id"])
            route_lanes = tuple(str(item) for item in route["lane_ids"])
            goal_lane = str(route["goal"]["lane_id"])
            if route_id in route_ids:
                reject(
                    f"$.participants[{index}].route.id",
                    "route.stable-id.v2",
                    "route IDs must be unique",
                    "assign a stable unique route ID to every participant",
                )
            route_ids.add(route_id)
            unknown = [
                item
                for item in (spawn_lane, *route_lanes, goal_lane)
                if item not in lane_id_set
            ]
            if unknown:
                reject(
                    f"$.participants[{index}]",
                    "route.stable-id.v2",
                    f"spawn or route references unknown lanes: {', '.join(sorted(set(unknown)))}",
                    "bind spawn and route fields to declared stable lane IDs",
                )
            if not route_lanes or spawn_lane != route_lanes[0] or goal_lane != route_lanes[-1]:
                reject(
                    f"$.participants[{index}].route",
                    "route.stable-id.v2",
                    "route endpoints must match the actor spawn and goal lane",
                    "make route.lane_ids start at spawn.lane_id and end at goal.lane_id",
                )
            if not unknown:
                if float(participant["spawn"]["longitudinal_m"]) > float(
                    lane_by_id[spawn_lane]["length_m"]
                ):
                    reject(
                        f"$.participants[{index}].spawn.longitudinal_m",
                        "actor.spawn.v2",
                        "spawn longitude exceeds the declared stable lane length",
                        "move the spawn within its bound lane",
                    )
                if float(route["goal"]["longitudinal_m"]) > float(
                    lane_by_id[goal_lane]["length_m"]
                ):
                    reject(
                        f"$.participants[{index}].route.goal.longitudinal_m",
                        "route.stable-id.v2",
                        "route goal exceeds the declared stable lane length",
                        "move the goal within its bound lane",
                    )
                engine_route = [
                    (
                        str(lane_by_id[item]["engine_lane_index"]["start_node"]),
                        str(lane_by_id[item]["engine_lane_index"]["end_node"]),
                        int(lane_by_id[item]["engine_lane_index"]["lane_index"]),
                    )
                    for item in route_lanes
                ]
                for route_index, (current, following) in enumerate(
                    zip(engine_route, engine_route[1:])
                ):
                    same_road = current[:2] == following[:2]
                    connected_road = current[1] == following[0]
                    if not same_road and not connected_road:
                        reject(
                            f"$.participants[{index}].route.lane_ids[{route_index + 1}]",
                            "route.stable-id.v2",
                            "declared stable route is disconnected in the MetaDrive road graph",
                            "bind consecutive route lanes to the same or connected engine roads",
                        )
                if engine_route[-1][2] != lane_count - 1:
                    reject(
                        f"$.participants[{index}].route.goal.lane_id",
                        "route.stable-id.v2",
                        "MetaDrive 0.4.3 navigation resolves the final road to its rightmost lane",
                        "bind the declared goal to the final engine road's rightmost lane",
                    )

        event_ids = [str(item["id"]) for item in scenario.events]
        sequences = [int(item["sequence"]) for item in scenario.events]
        if len(event_ids) != len(set(event_ids)) or sequences != list(range(len(sequences))):
            reject(
                "$.events",
                "event.ordered.v2",
                "events require unique IDs and contiguous input-order sequence numbers",
                "assign unique IDs and sequence values 0..N-1 in expected order",
            )
        for index, event in enumerate(scenario.events):
            if str(event["participant_id"]) not in participant_ids:
                reject(
                    f"$.events[{index}].participant_id",
                    "trigger.tick.v2",
                    "event participant does not exist",
                    "bind the event to a declared participant ID",
                )
            trigger_tick = int(event["trigger"]["tick"])
            max_steps = int(scenario.constraints["max_steps"])
            if trigger_tick >= max_steps:
                reject(
                    f"$.events[{index}].trigger.tick",
                    "trigger.tick.v2",
                    "event trigger must occur before the execution horizon",
                    "move the trigger before max_steps",
                )
            elif trigger_tick + int(event.get("duration_ticks", 1)) > max_steps:
                reject(
                    f"$.events[{index}].duration_ticks",
                    "trigger.tick.v2",
                    "event effect interval must end within the execution horizon",
                    "shorten the duration or move the trigger before max_steps",
                )
        if tuple(scenario.constraints["expected_events"]) != tuple(event_ids):
            reject(
                "$.constraints.expected_events",
                "event.ordered.v2",
                "expected event IDs must exactly match declared event order",
                "copy the ordered event IDs without omission or reordering",
            )

        expected_duration_s = (
            int(scenario.constraints["max_steps"])
            * 0.02
            * 5
        )
        if not math.isclose(
            float(scenario.constraints["duration_s"]),
            expected_duration_s,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            reject(
                "$.constraints.duration_s",
                "units.si-tick",
                "duration_s must equal max_steps times the frozen 0.1 second decision interval",
                "align duration_s and max_steps",
            )

        for axis in ("success_predicates", "failure_predicates"):
            for index, predicate in enumerate(scenario.constraints[axis]):
                unknown_participants = sorted(
                    str(item)
                    for item in predicate["participant_ids"]
                    if str(item) not in participant_ids
                )
                unknown_lanes = sorted(
                    str(item)
                    for item in predicate["lane_ids"]
                    if str(item) not in lane_id_set
                )
                if unknown_participants or unknown_lanes:
                    reject(
                        f"$.constraints.{axis}[{index}]",
                        "terminal.dual-axis.v2",
                        "predicate applicability references unknown participants or lanes",
                        "bind predicates only to declared participant and stable lane IDs",
                    )

        metric_definitions = tuple(scenario.constraints["metric_definitions"])
        definition_ids = [str(item["definition_id"]) for item in metric_definitions]
        metric_name_list = [str(item["metric"]) for item in metric_definitions]
        metric_names = set(metric_name_list)
        required_metric_names = {
            "collision",
            "hard_braking",
            "minimum_ttc",
            "completion_time",
            "termination_reason",
        }
        if len(definition_ids) != len(set(definition_ids)):
            reject(
                "$.constraints.metric_definitions",
                "metric.definition.v2",
                "metric definition IDs must be unique",
                "assign one stable definition_id per metric",
            )
        if len(metric_name_list) != len(metric_names):
            reject(
                "$.constraints.metric_definitions",
                "metric.definition.v2",
                "v2 requires exactly one definition for each metric name",
                "remove duplicate metric definitions",
            )
        if not required_metric_names.issubset(metric_names):
            reject(
                "$.constraints.metric_definitions",
                "metric.definition.v2",
                "v2 omits a required shared metric definition",
                "define collision, hard_braking, minimum_ttc, completion_time and termination_reason",
            )
        topology_kind = str(scenario.road["topology_kind"])
        for index, definition in enumerate(metric_definitions):
            unknown_participants = sorted(
                str(item)
                for item in definition["applies_to"]["participant_ids"]
                if str(item) not in participant_ids
            )
            if unknown_participants:
                reject(
                    f"$.constraints.metric_definitions[{index}].applies_to.participant_ids",
                    "metric.definition.v2",
                    "metric applicability references unknown participants",
                    "bind metric definitions only to declared participant IDs",
                )
            if topology_kind not in {
                str(item) for item in definition["applies_to"]["topology_kinds"]
            }:
                reject(
                    f"$.constraints.metric_definitions[{index}].applies_to.topology_kinds",
                    "metric.definition.v2",
                    "required metric does not apply to the scenario topology",
                    "include the current topology kind in metric applicability",
                )

        configured_participant_ids = [
            str(item["participant_id"])
            for item in scenario.policy["config"]["participant_actions"]
        ]
        if len(configured_participant_ids) != len(set(configured_participant_ids)):
            reject(
                "$.policy.config.participant_actions",
                "policy.deterministic.v2",
                "deterministic policy contains duplicate participant actions",
                "configure each participant at most once",
            )
        unknown_policy_participants = sorted(
            item for item in configured_participant_ids if item not in participant_ids
        )
        if unknown_policy_participants:
            reject(
                "$.policy.config.participant_actions",
                "policy.deterministic.v2",
                "deterministic policy references unknown participants",
                "configure only declared participant IDs",
            )

        extensions = scenario.backend_extensions["extensions"]
        for namespace, extension in extensions.items():
            if namespace != "metadrive" or extension["options"]:
                reject(
                    f"$.backend_extensions.extensions.{namespace}",
                    f"backend-extension.{namespace}",
                    "P0-C does not define non-empty backend extension options",
                    "use an empty metadrive extension or core v2 primitives",
                )

        overall_status = (
            CompilationStatus.UNSUPPORTED
            if diagnostics
            else CompilationStatus.EXACT
        )
        report = CompileReport(
            schema_version="scenarioforge.compile-report/v2",
            compiler_version=COMPILER_VERSION_V2,
            capability_descriptor_digest=descriptor.digest,
            scenario_instance_digest=scenario.digest,
            overall_status=overall_status,
            executable=overall_status is CompilationStatus.EXACT,
            mappings=tuple(mappings),
            diagnostics=tuple(diagnostics),
        )
        plan = self._execution_plan_v2(scenario) if report.executable else None
        return CompileBundle(
            scenario_instance=scenario,
            report=report,
            execution_plan=plan,
        )

    def _execution_plan_v2(self, scenario: ScenarioInstance) -> ExecutionPlan:
        lanes = tuple(scenario.road["lanes"])
        lane_count = (
            max(int(lane["engine_lane_index"]["lane_index"]) for lane in lanes)
            + 1
        )
        length_m = (
            max(float(lane["length_m"]) for lane in lanes)
            + METADRIVE_FIRST_BLOCK_ENTRANCE_LENGTH_M
        )
        return ExecutionPlan(
            schema_version="scenarioforge.execution-plan/v2",
            scenario_instance_digest=scenario.digest,
            backend=freeze_json(
                {
                    "id": "metadrive",
                    "version": METADRIVE_VERSION,
                    "adapter": {"id": ADAPTER_ID, "version": ADAPTER_VERSION_V2},
                }
            ),
            seed=scenario.seed,
            simulation=freeze_json(
                {
                    "topology": scenario.road,
                    "map_block_sequence": scenario.road["map_block_sequence"],
                    "lane_count": lane_count,
                    "lane_width_m": float(scenario.road["lane_width_m"]),
                    "length_m": length_m,
                    "physics_world_step_size_s": 0.02,
                    "decision_repeat": 5,
                    "max_steps": int(scenario.constraints["max_steps"]),
                    "duration_s": float(scenario.constraints["duration_s"]),
                    "headless": True,
                    "gpu_required": False,
                }
            ),
            participants=scenario.participants,
            events=scenario.events,
            constraints=scenario.constraints,
            policy=scenario.policy,
            tick_contract=freeze_json(
                {
                    "schema_version": "scenarioforge.tick-contract/v2",
                    "state_indexing": "S_N_at_tick_start",
                    "trigger_evaluation": "S_N_and_tick_N",
                    "action_application": "S_N_to_S_N_plus_1",
                    "event_effect_offset": 1,
                    "priority_order": ["scenario_override", "policy"],
                    "participant_order": [
                        str(participant["id"]) for participant in scenario.participants
                    ],
                    "same_tick_events": "preserve_sequence_order",
                }
            ),
            artifact_contract=freeze_json(
                {
                    "schema_version": "scenarioforge.artifact-contract/v2",
                    "required": [
                        "actions.json",
                        "events.json",
                        "metrics.json",
                        "trajectory.json",
                        "worker_result.json",
                    ],
                    "fully_verified_required": True,
                    "max_file_bytes": 10_485_760,
                }
            ),
            resource_config=freeze_json(
                {
                    "schema_version": "scenarioforge.resource-config/v2",
                    "wall_clock_timeout_s": 120,
                    "memory_limit_mb": 4096,
                    "pid_limit": 32,
                    "log_limit_bytes": 1_048_576,
                    "artifact_limit_bytes": 10_485_760,
                }
            ),
            tolerances_version="scenarioforge.p0c-calibration-pending/v2",
        )
