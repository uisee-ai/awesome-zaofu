from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
MODULE = ROOT / "src/scenarioforge/web/static/p1_replay.js"


def test_browser_module_has_four_camera_modes_role_parity_and_finite_inputs() -> None:
    script = f"""
      import {{
        P1_CAMERA_MODES,
        applyCameraInput,
        buildParticipantLegend,
        createCameraState,
        switchCameraMode,
      }} from {json.dumps(MODULE.as_uri())};
      const target = {{position_m: [10, 2], heading_deg: 0}};
      const bounds = {{center_m: [0, 0], half_extents_m: [30, 12]}};
      let state = createCameraState("follow", {{targetPose: target, bounds}});
      state = switchCameraMode(state, "free", {{targetPose: target, bounds}});
      state = applyCameraInput(state, {{kind: "pointer", action: "rotate", delta_x: 30, delta_y: -12, trusted: true}});
      state = applyCameraInput(state, {{kind: "pointer", action: "pan", delta_x: 8, delta_y: 4, trusted: true}});
      state = applyCameraInput(state, {{kind: "wheel", delta_y: -120, trusted: true}});
      state = applyCameraInput(state, {{kind: "keyboard", key: "w", trusted: true}});
      const legend = buildParticipantLegend(
        [
          {{id: "ego", role: "ego"}},
          {{id: "challenger", role: "controlled"}},
          {{id: "traffic-1", role: "social_vehicle"}},
          {{id: "walker", role: "pedestrian"}},
        ],
        [
          {{tick: 2, participant_id: "ego", speed_mps: 7.5, brake: 0.4}},
          {{tick: 2, participant_id: "challenger", speed_mps: 8, brake: 0}},
          {{tick: 2, participant_id: "traffic-1", speed_mps: 6.25, brake: 0}},
          {{tick: 2, participant_id: "walker", speed_mps: 1.4, brake: 0}},
        ],
        [{{event_id: "ego-brakes", participant_id: "ego", trigger_tick: 2, end_tick: 4}}],
        2,
      );
      console.log(JSON.stringify({{modes: P1_CAMERA_MODES, state, legend}}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["modes"] == ["follow", "overview", "fixed", "free"]
    assert result["state"]["mode"] == "free"
    assert result["state"]["initialized"] is True
    assert [item["role"] for item in result["legend"]] == [
        "ego",
        "controlled_agent",
        "social_vehicle",
        "pedestrian",
    ]
    assert result["legend"][0]["accessibleLabel"] == (
        "ego · ego · 7.5 m/s · braking · event ego-brakes"
    )


def test_browser_module_registers_real_pointer_keyboard_and_wheel_handlers() -> None:
    source = MODULE.read_text(encoding="utf-8")

    for event_name in ("pointerdown", "pointermove", "pointerup", "keydown", "wheel"):
        assert f'addEventListener("{event_name}"' in source
    for forbidden in ("innerHTML", "eval(", "new Function", "http://", "https://"):
        assert forbidden not in source


def test_browser_module_calculates_follow_position_and_view_direction_errors() -> None:
    script = f"""
      import {{followCameraQuality}} from {json.dumps(MODULE.as_uri())};
      const exact = followCameraQuality({{
        cameraPosition: [0, 4, 0],
        lookAt: [12, 0, 0],
        desiredPosition: [0, 4, 0],
        desiredLookAt: [12, 0, 0],
      }});
      const displaced = followCameraQuality({{
        cameraPosition: [1, 4, 0],
        lookAt: [2, 4, 0],
        desiredPosition: [0, 4, 0],
        desiredLookAt: [0, 4, 1],
      }});
      console.log(JSON.stringify({{exact, displaced}}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["exact"] == {
        "followErrorM": 0,
        "viewDirectionErrorDeg": 0,
        "withinTolerance": True,
    }
    assert result["displaced"] == {
        "followErrorM": 1,
        "viewDirectionErrorDeg": 90,
        "withinTolerance": False,
    }


def test_browser_view_model_preserves_samples_and_rejects_wrong_heading() -> None:
    script = f"""
      import {{createP1ReplayViewModel}} from {json.dumps(MODULE.as_uri())};
      const scene = {{
        schema_version: "scenarioforge.replay-scene/v1",
        camera: {{available_modes: ["follow", "overview", "fixed", "free"]}},
        tracks: [{{
          participant_id: "ego",
          role: "ego",
          samples: [
            {{tick: 0, position_m: [0, 0], heading_deg: 0, speed_mps: 8, brake: 0.4, signals: [{{signal_id: "s1", state: "green"}}]}},
            {{tick: 1, position_m: [1, 0], heading_deg: 0, speed_mps: 7, brake: 0.4, signals: [{{signal_id: "s1", state: "green"}}]}},
          ],
        }}],
        events: [{{event_id: "brake", participant_id: "ego", trigger_tick: 0, end_tick: 1}}],
        p1_replay: {{
          schema_version: "scenarioforge.p1-replay/v1",
          road_legend: ["Right-hand travel uses the legal right carriageway."],
          signal_legend: [{{signal_id: "s1", state: "green", accessible_label: "s1 · green"}}],
        }},
      }};
      const view = createP1ReplayViewModel(scene, 0);
      scene.tracks[0].samples[0].heading_deg = 180;
      let rejected = false;
      try {{ createP1ReplayViewModel(scene, 0); }} catch (error) {{ rejected = error.message.includes("heading"); }}
      console.log(JSON.stringify({{view, rejected}}));
    """
    completed = subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["view"]["cameraModes"] == ["follow", "overview", "fixed", "free"]
    assert result["view"]["tracks"][0]["samples"][0] == {
        "tick": 0,
        "positionM": [0, 0],
        "headingDeg": 0,
        "speedMps": 8,
        "brake": 0.4,
        "signals": [{"signalId": "s1", "state": "green"}],
        "headingTangentErrorDeg": 0,
    }
    assert result["view"]["participantLegend"][0]["keyEventState"] == "brake"
    assert result["view"]["roadLegend"] == [
        "Right-hand travel uses the legal right carriageway."
    ]
    assert result["rejected"] is True
