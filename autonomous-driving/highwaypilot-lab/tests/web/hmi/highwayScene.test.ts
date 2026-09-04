import * as THREE from "three";
import { describe, expect, it, vi } from "vitest";

import {
  HighwayScene,
  type HighwaySnapshot,
  type RendererAdapter,
} from "../../../web/src/hmi/renderer/HighwayScene.js";


class TestRenderer implements RendererAdapter {
  readonly domElement = { width: 800, height: 450 } as HTMLCanvasElement;
  readonly capabilities = { isWebGL2: true };
  readonly render = vi.fn();
  readonly setSize = vi.fn();
  readonly setPixelRatio = vi.fn();
  readonly dispose = vi.fn();
  animationLoop: ((time: number) => void) | null = null;

  setAnimationLoop(callback: ((time: number) => void) | null): void {
    this.animationLoop = callback;
  }
}


const snapshot = (egoX: number): HighwaySnapshot => ({
  schema_version: "simulation-snapshot/v1",
  authority: "python",
  road: { lanes_count: 3, lane_width_m: 4, length_m: 1000, speed_limit_mps: 30 },
  construction: {
    side: "right",
    closed_lane_index: 2,
    target_lane_index: 1,
    zone_start_m: 260,
    zone_end_m: 340,
    authoritative_merge_action: "LANE_LEFT",
  },
  ego: {
    vehicle_id: "ego",
    position_m: { x: egoX, y: 8 },
    speed_mps: 22,
    heading_rad: 0,
    lane_index: 2,
    target_lane_index: 1,
    crashed: false,
    scenario_event: false,
  },
  vehicles: [
    {
      vehicle_id: "traffic-1",
      position_m: { x: egoX + 28, y: 4 },
      speed_mps: 19,
      heading_rad: 0,
      lane_index: 1,
      target_lane_index: 1,
      crashed: false,
      scenario_event: false,
    },
  ],
  objects: [
    {
      object_id: "cone-1",
      kind: "cone",
      position_m: { x: 280, y: 8 },
      lane_index: 2,
      solid: true,
    },
  ],
  reward: { total: 0.3, components: { speed: 0.4, comfort: -0.1 } },
  safety: { min_ttc_s: 3.4, collision: false },
  status: { terminated: false, truncated: false, termination_reason: null },
  last_action: "IDLE",
  available_actions: ["LANE_LEFT", "IDLE", "FASTER", "SLOWER"],
});

describe("HighwayScene", () => {
  it("uses a real Three.js scene/camera seam and materializes every v1 visual", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({
      canvas: renderer.domElement,
      width: 800,
      height: 450,
      renderer,
    });

    scene.render(snapshot(40), { mode: "live", index: 0, length: 0 });

    expect(scene.threeScene).toBeInstanceOf(THREE.Scene);
    expect(scene.camera).toBeInstanceOf(THREE.PerspectiveCamera);
    expect(scene.objectNames()).toEqual(expect.arrayContaining([
      "road-surface",
      "lane-line-1",
      "road-shoulder-left",
      "lane-direction-arrows",
      "construction-closed-zone",
      "construction-zone-hatches",
      "construction-cone-1",
      "warning-sign-0",
      "traffic-instanced-fleet",
      "vehicle-ego",
      "vehicle-traffic-1",
      "vehicle-body",
      "vehicle-cabin",
      "vehicle-wheel-front-left",
      "vehicle-tail-light-bar",
      "vehicle-speed-indicator",
      "ego-history",
    ]));
    expect(renderer.animationLoop).not.toBeNull();
    expect(renderer.render).toHaveBeenCalled();
  });

  it("interpolates authoritative positions and exposes observable camera differences", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({
      canvas: renderer.domElement,
      width: 800,
      height: 450,
      renderer,
    });
    scene.render(snapshot(40), { mode: "live", index: 0, length: 0 });
    scene.render(snapshot(60), { mode: "live", index: 0, length: 0 });

    const before = scene.vehiclePosition("ego");
    scene.advanceFrame(0.5);
    const after = scene.vehiclePosition("ego");
    expect(before.x).toBe(40);
    expect(after.x).toBeGreaterThan(40);
    expect(after.x).toBeLessThan(60);

    scene.setCameraMode("follow");
    const follow = scene.camera.position.clone();
    scene.setCameraMode("top");
    const top = scene.camera.position.clone();
    scene.setCameraMode("free");
    const free = scene.camera.position.clone();
    expect(follow.equals(top)).toBe(false);
    expect(top.equals(free)).toBe(false);
  });

  it("spreads authoritative movement across the full snapshot interval", () => {
    const renderer = new TestRenderer();
    const now = vi.spyOn(performance, "now").mockReturnValue(1_000);
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    const first = snapshot(40);
    first.step = 1;
    scene.render(first, { mode: "live", index: 0, length: 0 });
    renderer.animationLoop?.(1_200);

    now.mockReturnValue(1_200);
    const second = snapshot(60);
    second.step = 2;
    scene.render(second, { mode: "live", index: 0, length: 0 });
    renderer.animationLoop?.(1_300);
    expect(scene.vehiclePosition("ego").x).toBeCloseTo(50, 4);

    renderer.animationLoop?.(1_400);
    expect(scene.vehiclePosition("ego").x).toBeCloseTo(60, 4);
    now.mockRestore();
    scene.dispose();
  });

  it("rolls wheels around their axle in the direction of travel", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    scene.render(snapshot(40), { mode: "live", index: 0, length: 0 });
    const wheel = scene.threeScene.getObjectByName("vehicle-wheel-front-left") as THREE.Object3D;
    const before = wheel.quaternion.clone();
    scene.render(snapshot(41), { mode: "live", index: 0, length: 0 });
    scene.advanceFrame(1);
    expect(wheel.quaternion.equals(before)).toBe(false);
    // The local +Z axle receives a positive roll for +X travel.
    expect(wheel.getWorldDirection(new THREE.Vector3()).length()).toBeCloseTo(1);
  });

  it("reuses a vehicle visual by id and maps authoritative heading", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    const first = snapshot(40);
    scene.render(first, { mode: "live", index: 0, length: 0 });
    const traffic = scene.threeScene.getObjectByName("vehicle-traffic-1");
    first.vehicles[0].heading_rad = Math.PI / 2;
    first.vehicles[0].position_m.x += 10;
    scene.render(first, { mode: "live", index: 0, length: 0 });
    const reused = scene.threeScene.getObjectByName("vehicle-traffic-1");
    expect(reused).toBe(traffic);
    expect(reused?.rotation.y).toBeCloseTo(-Math.PI / 2);

    first.vehicles = [];
    scene.render(first, { mode: "live", index: 0, length: 0 });
    expect(scene.threeScene.getObjectByName("vehicle-traffic-1")).toBeUndefined();
  });

  it("marks collision state and stops the animation loop on disposal", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({
      canvas: renderer.domElement,
      width: 800,
      height: 450,
      renderer,
    });
    const collision = snapshot(40);
    collision.ego.crashed = true;
    collision.safety.collision = true;

    scene.render(collision, { mode: "live", index: 0, length: 0 });
    expect(scene.vehicleColor("ego")).toBe(0xef4444);

    scene.dispose();
    expect(renderer.animationLoop).toBeNull();
    expect(renderer.dispose).toHaveBeenCalledOnce();
  });

  it("uses role overlays and server speed for vehicle visuals", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    const frame = snapshot(40);
    frame.ego.speed_mps = 30;
    frame.vehicles[0].scenario_event = true;
    scene.render(frame, { mode: "live", index: 0, length: 0 });

    const ego = scene.threeScene.getObjectByName("vehicle-ego") as THREE.Group;
    expect(ego.getObjectByName("vehicle-ego-glow")).toBeUndefined();
    expect((ego.getObjectByName("vehicle-speed-indicator") as THREE.Mesh).scale.x).toBeGreaterThan(0.9);
    expect(scene.threeScene.getObjectByName("vehicle-traffic-1")).toBeInstanceOf(THREE.Group);
    expect([0x11151b, 0xf3c746]).toContain(scene.vehicleColor("traffic-1"));
  });

  it("uses a bounded lightweight mesh count for dense traffic", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    scene.render(snapshot(40), { mode: "live", index: 0, length: 0 });

    const traffic = scene.threeScene.getObjectByName("vehicle-traffic-1") as THREE.Group;
    expect(traffic.children).toHaveLength(0);
    expect(scene.trafficDrawMeshCount()).toBe(10);
    expect(scene.threeScene.getObjectByName("traffic-near-body-instances")).toBeInstanceOf(THREE.InstancedMesh);

    scene.setQuality("low");
    expect(scene.trafficDrawMeshCount()).toBe(5);
    expect(scene.threeScene.getObjectByName("traffic-near-body-instances")).toBeUndefined();
    expect(scene.threeScene.getObjectByName("traffic-far-body-instances")).toBeInstanceOf(THREE.InstancedMesh);
  });

  it("centers sparse 500-meter arrows in every lane and keeps the live trajectory", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    scene.render(snapshot(40), { mode: "live", index: 0, length: 0 });

    const arrows = scene.threeScene.getObjectByName("lane-direction-arrows") as THREE.InstancedMesh;
    expect(arrows.count).toBe(6);
    const matrix = new THREE.Matrix4();
    const position = new THREE.Vector3();
    const placements: Array<[number, number]> = [];
    for (let index = 0; index < arrows.count; index += 1) {
      arrows.getMatrixAt(index, matrix);
      position.setFromMatrixPosition(matrix);
      placements.push([position.x, position.z]);
    }
    expect(placements).toEqual([
      [100, 0], [100, 4], [100, 8],
      [600, 0], [600, 4], [600, 8],
    ]);

    const trajectory = scene.threeScene.getObjectByName("ego-history") as THREE.Line | THREE.Points;
    expect(trajectory).toBeInstanceOf(THREE.Points);
    expect(trajectory.frustumCulled).toBe(false);
    const initialMaterial = trajectory.material as THREE.PointsMaterial;
    expect(initialMaterial.color.getHex()).toBe(0x168df0);

    const next = snapshot(55);
    next.step = 2;
    scene.render(next, { mode: "live", index: 0, length: 0 });
    const updated = scene.threeScene.getObjectByName("ego-history") as THREE.Line;
    expect(updated).toBeInstanceOf(THREE.Line);
    expect((updated.geometry as THREE.BufferGeometry).drawRange.count).toBe(2);
    expect((updated.material as THREE.LineBasicMaterial).color.getHex()).toBe(0x168df0);
    expect(scene.threeScene.getObjectByName("ego-guidance-ribbon")).toBeUndefined();
  });

  it("draws lane lines for the supported 2–5 lane range", () => {
    const renderer = new TestRenderer();
    const scene = new HighwayScene({ canvas: renderer.domElement, width: 800, height: 450, renderer });
    for (const lanes of [2, 3, 4, 5]) {
      const frame = snapshot(40);
      frame.road.lanes_count = lanes;
      frame.ego.lane_index = Math.min(frame.ego.lane_index, lanes - 1);
      frame.ego.target_lane_index = Math.min(frame.ego.target_lane_index, lanes - 1);
      scene.render(frame, { mode: "live", index: 0, length: 0 });
      expect(scene.objectNames()).toContain(`lane-line-${lanes - 1}`);
    }
  });
});
