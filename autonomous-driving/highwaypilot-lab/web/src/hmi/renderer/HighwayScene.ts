import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";

import type { SceneRenderState, SceneRenderer } from "../../features/replay/replayController.js";
import { QUALITY_PROFILES, type CameraMode, type QualityLevel } from "../HmiState.js";
import { TrafficVehicleFleet, type TrafficInstanceState } from "./TrafficVehicleFleet.js";
import { VehicleAssetCatalog, type VehicleAssetInstance } from "./VehicleAssetCatalog.js";
import { createLoftGeometry } from "./VehicleGeometry.js";


export type Point2 = { x: number; y: number };
export type VehicleSnapshot = {
  vehicle_id: string;
  position_m: Point2;
  speed_mps: number;
  heading_rad: number;
  lane_index: number;
  target_lane_index: number;
  crashed: boolean;
  scenario_event: boolean;
};

export type HighwaySnapshot = {
  schema_version: "simulation-snapshot/v1";
  authority: "python";
  config_digest?: string;
  step?: number;
  time_s?: number;
  road: { lanes_count: number; lane_width_m: number; length_m: number; speed_limit_mps: number };
  construction: {
    side: "left" | "right";
    closed_lane_index: number;
    target_lane_index: number;
    zone_start_m: number;
    zone_end_m: number;
    authoritative_merge_action: "LANE_LEFT" | "LANE_RIGHT";
  };
  ego: VehicleSnapshot;
  vehicles: VehicleSnapshot[];
  objects: Array<{
    object_id: string;
    kind: string;
    position_m: Point2;
    lane_index: number;
    solid: boolean;
  }>;
  reward: { total: number; components: Record<string, number> };
  safety: { min_ttc_s: number | null; collision: boolean };
  status: { terminated: boolean; truncated: boolean; termination_reason: string | null };
  last_action: string | null;
  available_actions: string[];
};

export interface RendererAdapter {
  readonly domElement: HTMLCanvasElement;
  readonly capabilities: { isWebGL2: boolean };
  setSize(width: number, height: number, updateStyle?: boolean): void;
  setPixelRatio(value: number): void;
  setAnimationLoop(callback: ((time: number) => void) | null): void;
  render(scene: THREE.Scene, camera: THREE.Camera): void;
  dispose(): void;
}

type ControlsAdapter = { enabled: boolean; target: THREE.Vector3; update(): void; dispose(): void };
type EgoVisualData = {
  model: THREE.Group;
  source: "procedural" | "glb";
  bodyMaterials: THREE.MeshStandardMaterial[];
  rearLightMaterials: THREE.MeshStandardMaterial[];
  wheelNodes: THREE.Object3D[];
  wheelAxes: THREE.Vector3[];
  speedIndicator: THREE.Mesh;
  glbInstance: VehicleAssetInstance | null;
  displayColor: number;
};
type SceneOptions = {
  canvas: HTMLCanvasElement;
  width: number;
  height: number;
  quality?: QualityLevel;
  renderer?: RendererAdapter;
  controls?: ControlsAdapter;
  assetCatalog?: VehicleAssetCatalog | null;
  loadAssets?: boolean;
};

const EGO_COLOR = 0x168df0;
const EGO_BODY_COLOR = 0x168df0;
const COLLISION_COLOR = 0xef4444;
const DEFAULT_SNAPSHOT_INTERVAL_MS = 200;
const MIN_SNAPSHOT_INTERVAL_MS = 32;
const MAX_SNAPSHOT_INTERVAL_MS = 750;
const PROCEDURAL_WHEEL_AXLE_AXIS = new THREE.Vector3(0, 0, 1);
const GLB_WHEEL_AXLE_AXIS = new THREE.Vector3(0, 1, 0);

function disposeObjectResources(root: THREE.Object3D, disposeGeometry = true): void {
  const geometries = new Set<THREE.BufferGeometry>();
  const materials = new Set<THREE.Material>();
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    if (disposeGeometry) geometries.add(mesh.geometry);
    const values = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    values.filter(Boolean).forEach((value) => materials.add(value));
  });
  geometries.forEach((value) => value.dispose());
  materials.forEach((value) => value.dispose());
}

function roadTexture(): THREE.DataTexture {
  const size = 96;
  const data = new Uint8Array(size * size * 4);
  let state = 0x8f31a2c7;
  for (let index = 0; index < size * size; index += 1) {
    state ^= state << 13; state ^= state >>> 17; state ^= state << 5;
    // Keep a visible charcoal asphalt grain instead of multiplying the road
    // down to near-black on the unlit material.
    const grain = 172 + (state >>> 28);
    data.set([grain, grain + 2, grain + 5, 255], index * 4);
  }
  const texture = new THREE.DataTexture(data, size, size, THREE.RGBAFormat);
  texture.name = "procedural-asphalt";
  texture.wrapS = THREE.RepeatWrapping;
  texture.wrapT = THREE.RepeatWrapping;
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.needsUpdate = true;
  return texture;
}

function namedMesh(name: string, geometry: THREE.BufferGeometry, material: THREE.Material, position: [number, number, number]): THREE.Mesh {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.name = name;
  mesh.position.set(...position);
  return mesh;
}

function straightArrowGeometry(): THREE.ShapeGeometry {
  const shape = new THREE.Shape();
  shape.moveTo(-2.2, -0.18);
  shape.lineTo(0.75, -0.18);
  shape.lineTo(0.75, -0.58);
  shape.lineTo(2.2, 0);
  shape.lineTo(0.75, 0.58);
  shape.lineTo(0.75, 0.18);
  shape.lineTo(-2.2, 0.18);
  shape.closePath();
  const geometry = new THREE.ShapeGeometry(shape);
  geometry.rotateX(-Math.PI / 2);
  return geometry;
}

export class WebGLUnavailableError extends Error {
  readonly code = "WEBGL2_UNAVAILABLE";
}

export class HighwayScene implements SceneRenderer<HighwaySnapshot> {
  readonly threeScene = new THREE.Scene();
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: RendererAdapter;
  readonly #controls: ControlsAdapter;
  readonly #staticGroup = new THREE.Group();
  readonly #vehicleGroup = new THREE.Group();
  readonly #trajectoryGroup = new THREE.Group();
  readonly #starts = new Map<string, THREE.Vector3>();
  readonly #targets = new Map<string, THREE.Vector3>();
  readonly #vehicleStates = new Map<string, VehicleSnapshot>();
  readonly #history: THREE.Vector3[] = [];
  readonly #trafficFleet: TrafficVehicleFleet;
  readonly #roadTexture = roadTexture();
  readonly #assetCatalog: VehicleAssetCatalog | null;
  readonly #ownsAssetCatalog: boolean;
  #environmentTarget: THREE.WebGLRenderTarget | null = null;
  #egoAssetLoading = false;
  #cameraMode: CameraMode = "follow";
  #quality: QualityLevel;
  #roadSignature = "";
  #trajectoryGeometry: THREE.BufferGeometry | null = null;
  #trajectoryVisual: THREE.Line | THREE.Points | null = null;
  #snapshot: HighwaySnapshot | null = null;
  #lastSnapshotReceivedAt: number | null = null;
  #lastSnapshotStep: number | null = null;
  #snapshotIntervalMs = DEFAULT_SNAPSHOT_INTERVAL_MS;
  #motionStartedAt = 0;
  #motionDurationMs = DEFAULT_SNAPSHOT_INTERVAL_MS;
  #lastEgoVisualX: number | null = null;
  #lastAnimationRenderAt = Number.NEGATIVE_INFINITY;
  readonly #canvas: HTMLCanvasElement;
  readonly #resizeHandler: () => void;
  readonly #contextLostHandler: (event: Event) => void;
  readonly #contextRestoredHandler: () => void;
  #contextLost = false;
  #disposed = false;

  constructor(options: SceneOptions) {
    this.#canvas = options.canvas;
    this.#quality = options.quality ?? "medium";
    this.camera = new THREE.PerspectiveCamera(52, options.width / options.height, 0.1, 2200);
    this.renderer = options.renderer ?? this.#createRenderer(options.canvas);
    this.renderer.setSize(options.width, options.height, false);
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio ?? 1, QUALITY_PROFILES[this.#quality].pixelRatioCap));
    this.#controls = options.controls ?? (
      options.renderer
        ? { enabled: false, target: new THREE.Vector3(), update() {}, dispose() {} }
        : new OrbitControls(this.camera, this.renderer.domElement)
    );
    this.#controls.enabled = false;
    this.#trafficFleet = new TrafficVehicleFleet(this.#quality);
    this.#vehicleGroup.add(this.#trafficFleet.group);
    const shouldLoadAssets = options.loadAssets ?? !options.renderer;
    this.#ownsAssetCatalog = options.assetCatalog === undefined && shouldLoadAssets;
    this.#assetCatalog = options.assetCatalog === undefined
      ? shouldLoadAssets ? new VehicleAssetCatalog() : null
      : options.assetCatalog;

    this.threeScene.background = new THREE.Color(0x05090f);
    this.threeScene.fog = new THREE.FogExp2(0x05090f, 0.00215);
    const hemisphere = new THREE.HemisphereLight(0x9eb8d5, 0x05070b, 1.35);
    hemisphere.name = "hmi-hemisphere-light";
    const sun = new THREE.DirectionalLight(0xdcecff, 3.15);
    sun.name = "hmi-key-light";
    sun.position.set(24, 54, -18);
    sun.castShadow = this.#quality === "high";
    sun.shadow.mapSize.set(1024, 1024);
    sun.shadow.camera.left = -55; sun.shadow.camera.right = 55;
    sun.shadow.camera.top = 55; sun.shadow.camera.bottom = -55;
    sun.shadow.camera.near = 1; sun.shadow.camera.far = 170;
    sun.shadow.bias = -0.00035;
    const rim = new THREE.DirectionalLight(0x2b7fff, 0.75);
    rim.name = "hmi-rim-light";
    rim.position.set(-30, 12, 28);
    this.threeScene.add(hemisphere, sun, rim, this.#staticGroup, this.#vehicleGroup, this.#trajectoryGroup);
    this.#installEnvironment();
    // Preview framing: keep the ego vehicle prominent in the lower third while
    // retaining enough road ahead to show traffic, arrows, and construction.
    this.camera.position.set(-12, 6.8, 7.1);
    // Authoritative snapshots arrive at policy frequency (normally 5 Hz),
    // and dense scenes can take longer to compute.  Spread each correction
    // over the observed snapshot cadence instead of catching up early and
    // visibly stopping before the next snapshot arrives.
    this.renderer.setAnimationLoop((time) => this.#advanceTimedFrame(time));
    this.#resizeHandler = () => {
      const rect = this.#canvas.getBoundingClientRect();
      const width = Math.max(1, Math.round(rect.width || options.width));
      const height = Math.max(1, Math.round(rect.height || options.height));
      this.renderer.setSize(width, height, false);
      this.camera.aspect = width / height;
      this.camera.updateProjectionMatrix();
    };
    this.#contextLostHandler = (event) => {
      event.preventDefault();
      this.#contextLost = true;
      this.#canvas.dataset.webglState = "context-lost";
      this.#canvas.dispatchEvent(new CustomEvent("highwaypilot:webgl-lost"));
    };
    this.#contextRestoredHandler = () => {
      this.#contextLost = false;
      delete this.#canvas.dataset.webglState;
      this.#resizeHandler();
      this.#canvas.dispatchEvent(new CustomEvent("highwaypilot:webgl-restored"));
      if (this.#snapshot) this.render(this.#snapshot, { mode: "live", index: 0, length: 0 });
    };
    this.#canvas.addEventListener?.("webglcontextlost", this.#contextLostHandler);
    this.#canvas.addEventListener?.("webglcontextrestored", this.#contextRestoredHandler);
    globalThis.addEventListener?.("resize", this.#resizeHandler);
  }

  #createRenderer(canvas: HTMLCanvasElement): THREE.WebGLRenderer {
    const context = canvas.getContext("webgl2", {
      alpha: false,
      antialias: QUALITY_PROFILES[this.#quality].antialias,
      powerPreference: "high-performance",
    });
    if (context === null) {
      throw new WebGLUnavailableError("WebGL 2 is unavailable");
    }
    const renderer = new THREE.WebGLRenderer({ canvas, context, antialias: QUALITY_PROFILES[this.#quality].antialias, powerPreference: "high-performance" });
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.92;
    renderer.shadowMap.enabled = QUALITY_PROFILES[this.#quality].shadows;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.setClearColor(0x05090f, 1);
    return renderer;
  }

  #installEnvironment(): void {
    // PMREM generation is useful for the clear-coat/glass response, but on
    // SwiftShader/llvmpipe the one-time shader work can block the UI for tens
    // of seconds. App.ts already maps those renderers to the low profile, so
    // keep direct lights and skip the environment prefilter there.
    if (this.#quality === "low" || !(this.renderer instanceof THREE.WebGLRenderer)) return;
    const pmrem = new THREE.PMREMGenerator(this.renderer);
    const environment = new RoomEnvironment();
    this.#environmentTarget = pmrem.fromScene(environment, 0.035);
    this.threeScene.environment = this.#environmentTarget.texture;
    environment.dispose();
    pmrem.dispose();
  }

  render(snapshot: HighwaySnapshot, _state: SceneRenderState): void {
    if (this.#contextLost || this.#disposed) return;
    if (snapshot.schema_version !== "simulation-snapshot/v1" || snapshot.authority !== "python") {
      throw new Error("renderer accepts only Python-authoritative simulation-snapshot/v1 frames");
    }
    const receivedAt = globalThis.performance?.now() ?? Date.now();
    const step = snapshot.step ?? null;
    if (
      this.#lastSnapshotReceivedAt !== null
      && this.#lastSnapshotStep !== null
      && step !== null
      && step > this.#lastSnapshotStep
      && this.#lastSnapshotStep > 0
    ) {
      const observedInterval = receivedAt - this.#lastSnapshotReceivedAt;
      if (observedInterval >= MIN_SNAPSHOT_INTERVAL_MS && observedInterval <= MAX_SNAPSHOT_INTERVAL_MS) {
        this.#snapshotIntervalMs = THREE.MathUtils.lerp(
          this.#snapshotIntervalMs,
          observedInterval,
          0.75,
        );
      }
    }
    this.#lastSnapshotReceivedAt = receivedAt;
    this.#lastSnapshotStep = step;
    this.#motionStartedAt = receivedAt;
    this.#motionDurationMs = THREE.MathUtils.clamp(
      this.#snapshotIntervalMs,
      MIN_SNAPSHOT_INTERVAL_MS,
      MAX_SNAPSHOT_INTERVAL_MS,
    );
    this.#snapshot = snapshot;
    this.#materializeStaticWorld(snapshot);
    this.#materializeVehicles(snapshot);
    this.#history.push(new THREE.Vector3(snapshot.ego.position_m.x, 0.16, snapshot.ego.position_m.y));
    const maxPoints = QUALITY_PROFILES[this.#quality].trajectoryPoints;
    this.#history.splice(0, Math.max(0, this.#history.length - maxPoints));
    this.#materializeTrajectory();
    this.#syncAnimatedVisuals();
    this.#updateCamera();
    this.renderer.render(this.threeScene, this.camera);
  }

  #materializeStaticWorld(snapshot: HighwaySnapshot): void {
    const road = snapshot.road;
    const signature = `${road.lanes_count}:${road.lane_width_m}:${road.length_m}:${snapshot.construction.side}:${snapshot.construction.closed_lane_index}:${snapshot.construction.zone_start_m}:${snapshot.construction.zone_end_m}:${snapshot.objects.map((item) => `${item.object_id}:${item.kind}:${item.position_m.x}:${item.position_m.y}`).join(",")}:${this.#quality}`;
    if (signature === this.#roadSignature) return;
    this.#roadSignature = signature;
    this.#clear(this.#staticGroup);
    const roadWidth = road.lanes_count * road.lane_width_m;
    const centerZ = (road.lanes_count - 1) * road.lane_width_m / 2;
    this.#roadTexture.repeat.set(Math.max(1, road.length_m / 28), Math.max(1, roadWidth / 7));
    const surface = new THREE.Mesh(
      new THREE.PlaneGeometry(road.length_m, roadWidth),
      // Dark, high-contrast asphalt keeps lane markings and the blue route
      // visible like the approved preview.
      // Unlit asphalt keeps the approved near-black appearance consistent
      // across real GPU drivers and SwiftShader (which apply different HDR
      // light responses to a StandardMaterial).
      new THREE.MeshBasicMaterial({ color: 0x555555, map: this.#roadTexture, toneMapped: false }),
    );
    surface.name = "road-surface";
    surface.rotation.x = -Math.PI / 2;
    surface.position.set(road.length_m / 2, 0, centerZ);
    surface.receiveShadow = this.#quality === "high";
    this.#staticGroup.add(surface);

    const shoulderMaterial = new THREE.MeshStandardMaterial({ color: 0xd7dbe0, roughness: 0.58, emissive: 0x30343a, emissiveIntensity: 0.12 });
    for (const [name, z] of [["left", -road.lane_width_m / 2], ["right", roadWidth - road.lane_width_m / 2]] as const) {
      this.#staticGroup.add(namedMesh(`road-shoulder-${name}`, new THREE.BoxGeometry(road.length_m, 0.035, 0.14), shoulderMaterial, [road.length_m / 2, 0.028, z]));
    }
    const laneMaterial = new THREE.MeshBasicMaterial({ color: 0xc9ced4, toneMapped: false });
    const dashLength = 3.2;
    const dashPeriod = 8.8;
    const dashCount = Math.ceil(road.length_m / dashPeriod);
    for (let lane = 1; lane < road.lanes_count; lane += 1) {
      const line = new THREE.InstancedMesh(new THREE.BoxGeometry(dashLength, 0.025, 0.105), laneMaterial, dashCount);
      line.name = `lane-line-${lane}`;
      const dummy = new THREE.Object3D();
      for (let index = 0; index < dashCount; index += 1) {
        dummy.position.set(index * dashPeriod + dashLength / 2, 0.032, lane * road.lane_width_m - road.lane_width_m / 2);
        dummy.updateMatrix();
        line.setMatrixAt(index, dummy.matrix);
      }
      line.instanceMatrix.needsUpdate = true;
      line.frustumCulled = false;
      this.#staticGroup.add(line);
    }

    const arrowXs: number[] = [];
    for (let x = 100; x < road.length_m; x += 500) arrowXs.push(x);
    const arrows = new THREE.InstancedMesh(
      straightArrowGeometry(),
      new THREE.MeshBasicMaterial({ color: 0xe7ebef, transparent: true, opacity: 0.92, toneMapped: false, side: THREE.DoubleSide }),
      arrowXs.length * road.lanes_count,
    );
    arrows.name = "lane-direction-arrows";
    const arrowDummy = new THREE.Object3D();
    let arrowIndex = 0;
    for (const x of arrowXs) {
      for (let lane = 0; lane < road.lanes_count; lane += 1) {
        // Lane centers are lane_index * lane_width_m; boundaries are offset
        // by half a lane, so arrows can never overlap a divider.
        arrowDummy.position.set(x, 0.046, lane * road.lane_width_m);
        arrowDummy.updateMatrix();
        arrows.setMatrixAt(arrowIndex, arrowDummy.matrix);
        arrowIndex += 1;
      }
    }
    arrows.instanceMatrix.needsUpdate = true;
    arrows.frustumCulled = false;
    this.#staticGroup.add(arrows);

    const construction = snapshot.construction;
    const laneZ = construction.closed_lane_index * road.lane_width_m;
    const zoneLength = construction.zone_end_m - construction.zone_start_m;
    const closed = namedMesh(
      "construction-closed-zone",
      new THREE.BoxGeometry(construction.zone_end_m - construction.zone_start_m, 0.04, road.lane_width_m * 0.84),
      new THREE.MeshStandardMaterial({ color: 0x5c3524, roughness: 0.88, transparent: true, opacity: 0.58 }),
      [(construction.zone_start_m + construction.zone_end_m) / 2, 0.04, laneZ],
    );
    this.#staticGroup.add(closed);

    const hatchCount = Math.max(1, Math.floor(zoneLength / 7));
    const hatches = new THREE.InstancedMesh(new THREE.BoxGeometry(3.2, 0.025, 0.16), new THREE.MeshBasicMaterial({ color: 0xd88621, transparent: true, opacity: 0.76, toneMapped: false }), hatchCount);
    hatches.name = "construction-zone-hatches";
    const hatchDummy = new THREE.Object3D();
    for (let index = 0; index < hatchCount; index += 1) {
      hatchDummy.position.set(construction.zone_start_m + 3.5 + index * 7, 0.068, laneZ);
      hatchDummy.rotation.y = index % 2 === 0 ? 0.65 : -0.65;
      hatchDummy.updateMatrix();
      hatches.setMatrixAt(index, hatchDummy.matrix);
    }
    hatches.instanceMatrix.needsUpdate = true;
    this.#staticGroup.add(hatches);

    [120, 80, 40].forEach((offset, index) => {
      const sign = new THREE.Group();
      sign.name = `warning-sign-${index}`;
      sign.add(
        namedMesh(`warning-sign-${index}-pole`, new THREE.CylinderGeometry(0.055, 0.065, 1.55, 8), new THREE.MeshStandardMaterial({ color: 0x68717d, metalness: 0.58, roughness: 0.42 }), [0, 0.78, 0]),
        namedMesh(`warning-sign-${index}-board`, new RoundedBoxGeometry(0.12, 0.92, 0.92, 2, 0.08), new THREE.MeshStandardMaterial({ color: 0xf5a524, emissive: 0x6b3200, emissiveIntensity: 0.28, roughness: 0.5 }), [0, 1.66, 0]),
      );
      sign.position.set(construction.zone_start_m - offset, 0, laneZ);
      this.#staticGroup.add(sign);
    });
    this.#addConstructionObjects(snapshot);
  }

  #addConstructionObjects(snapshot: HighwaySnapshot): void {
    const cones = snapshot.objects.filter((object) => object.kind === "cone");
    const barriers = snapshot.objects.filter((object) => object.kind === "barrier");
    const signs = snapshot.objects.filter((object) => object.kind !== "cone" && object.kind !== "barrier");
    const dummy = new THREE.Object3D();
    if (cones.length) {
      const coneBodies = new THREE.InstancedMesh(new THREE.ConeGeometry(0.33, 0.82, this.#quality === "low" ? 8 : 16), new THREE.MeshStandardMaterial({ color: 0xf47b20, roughness: 0.62 }), cones.length);
      const coneBases = new THREE.InstancedMesh(new RoundedBoxGeometry(0.62, 0.09, 0.62, 1, 0.035), new THREE.MeshStandardMaterial({ color: 0x171a1e, roughness: 0.9 }), cones.length);
      coneBodies.name = "construction-cones";
      coneBases.name = "construction-cone-bases";
      cones.forEach((object, index) => {
        dummy.position.set(object.position_m.x, 0.46, object.position_m.y); dummy.rotation.set(0, 0, 0); dummy.updateMatrix(); coneBodies.setMatrixAt(index, dummy.matrix);
        dummy.position.y = 0.045; dummy.updateMatrix(); coneBases.setMatrixAt(index, dummy.matrix);
        const anchor = new THREE.Object3D(); anchor.name = `construction-${object.object_id}`; anchor.position.set(object.position_m.x, 0, object.position_m.y); this.#staticGroup.add(anchor);
      });
      coneBodies.instanceMatrix.needsUpdate = true; coneBases.instanceMatrix.needsUpdate = true;
      this.#staticGroup.add(coneBodies, coneBases);
    }
    if (barriers.length) {
      const bodies = new THREE.InstancedMesh(new RoundedBoxGeometry(1.65, 0.64, 0.58, 2, 0.09), new THREE.MeshStandardMaterial({ color: 0xe69a24, roughness: 0.67 }), barriers.length);
      bodies.name = "construction-barriers";
      barriers.forEach((object, index) => {
        dummy.position.set(object.position_m.x, 0.34, object.position_m.y); dummy.rotation.set(0, 0, 0); dummy.updateMatrix(); bodies.setMatrixAt(index, dummy.matrix);
        const anchor = new THREE.Object3D(); anchor.name = `construction-${object.object_id}`; anchor.position.set(object.position_m.x, 0, object.position_m.y); this.#staticGroup.add(anchor);
      });
      bodies.instanceMatrix.needsUpdate = true;
      this.#staticGroup.add(bodies);
    }
    signs.forEach((object) => this.#staticGroup.add(namedMesh(`construction-${object.object_id}`, new RoundedBoxGeometry(0.3, 2.1, 1.55, 2, 0.08), new THREE.MeshStandardMaterial({ color: 0xe9a22b, roughness: 0.58 }), [object.position_m.x, 1.05, object.position_m.y])));
  }

  #materializeVehicles(snapshot: HighwaySnapshot): void {
    const incoming = new Set<string>();
    for (const vehicle of [snapshot.ego, ...snapshot.vehicles]) {
      incoming.add(vehicle.vehicle_id);
      this.#vehicleStates.set(vehicle.vehicle_id, vehicle);
      const name = `vehicle-${vehicle.vehicle_id}`;
      let anchor = this.#vehicleGroup.getObjectByName(name) as THREE.Group | undefined;
      if (!anchor) {
        anchor = vehicle.vehicle_id === "ego" ? this.#createEgoAnchor() : new THREE.Group();
        anchor.name = name;
        anchor.position.set(vehicle.position_m.x, 0, vehicle.position_m.y);
        this.#vehicleGroup.add(anchor);
      }
      this.#starts.set(vehicle.vehicle_id, anchor.position.clone());
      anchor.rotation.y = -vehicle.heading_rad;
      this.#targets.set(vehicle.vehicle_id, new THREE.Vector3(vehicle.position_m.x, 0, vehicle.position_m.y));
      if (vehicle.vehicle_id === "ego") this.#updateEgoState(anchor, vehicle, snapshot.road.speed_limit_mps);
    }
    for (const child of [...this.#vehicleGroup.children]) {
      if (child === this.#trafficFleet.group || !child.name.startsWith("vehicle-")) continue;
      const id = child.name.slice("vehicle-".length);
      if (!incoming.has(id)) {
        if (id === "ego") this.#disposeEgoAnchor(child as THREE.Group);
        this.#vehicleGroup.remove(child);
        this.#starts.delete(id);
        this.#targets.delete(id);
        this.#vehicleStates.delete(id);
      }
    }
    this.#syncTrafficFleet();
  }

  #createEgoAnchor(): THREE.Group {
    const anchor = new THREE.Group();
    const fallback = this.#createProceduralEgoModel();
    const speedIndicator = namedMesh("vehicle-speed-indicator", new RoundedBoxGeometry(2.15, 0.045, 0.13, 2, 0.035), new THREE.MeshBasicMaterial({ color: EGO_COLOR, transparent: true, opacity: 0.88, toneMapped: false }), [3.15, 0.095, 0]);
    anchor.add(speedIndicator, fallback.model);
    anchor.userData = {
      ...fallback,
      wheelAxes: fallback.wheelNodes.map(() => PROCEDURAL_WHEEL_AXLE_AXIS),
      speedIndicator,
      glbInstance: null,
      displayColor: EGO_BODY_COLOR,
    } satisfies EgoVisualData;
    this.#beginEgoAssetLoad(anchor);
    return anchor;
  }

  #createProceduralEgoModel(): Pick<EgoVisualData, "model" | "source" | "bodyMaterials" | "rearLightMaterials" | "wheelNodes"> {
    const model = new THREE.Group();
    model.name = "ego-visual-model-procedural";
    const body = new THREE.MeshPhysicalMaterial({ name: "body", color: EGO_BODY_COLOR, roughness: 0.24, metalness: 0.62, clearcoat: 0.82, clearcoatRoughness: 0.18 });
    const trim = new THREE.MeshStandardMaterial({ color: 0x11151b, roughness: 0.55, metalness: 0.25 });
    const glass = new THREE.MeshStandardMaterial({ color: 0x152230, roughness: 0.14, metalness: 0.12, transparent: true, opacity: 0.78 });
    const tire = new THREE.MeshStandardMaterial({ color: 0x07090c, roughness: 0.94 });
    const rim = new THREE.MeshStandardMaterial({ color: 0x6c7783, roughness: 0.27, metalness: 0.8 });
    const tail = new THREE.MeshStandardMaterial({ color: 0xff233b, emissive: 0xff102a, emissiveIntensity: 2.4, roughness: 0.2 });
    const head = new THREE.MeshStandardMaterial({ color: 0xe8f8ff, emissive: 0xc9f0ff, emissiveIntensity: 2, roughness: 0.16 });
    model.add(
      namedMesh("vehicle-body", createLoftGeometry([
        { x: -2.38, centerY: 0.63, radiusY: 0.1, radiusZ: 0.28 },
        { x: -2.25, centerY: 0.65, radiusY: 0.26, radiusZ: 0.76 },
        { x: -1.68, centerY: 0.68, radiusY: 0.37, radiusZ: 0.96 },
        { x: 0.82, centerY: 0.68, radiusY: 0.37, radiusZ: 0.96 },
        { x: 1.72, centerY: 0.65, radiusY: 0.31, radiusZ: 0.86 },
        { x: 2.25, centerY: 0.62, radiusY: 0.2, radiusZ: 0.58 },
        { x: 2.38, centerY: 0.61, radiusY: 0.08, radiusZ: 0.25 },
      ], 24, 3.1), body, [0, 0, 0]),
      namedMesh("vehicle-lower-trim", new RoundedBoxGeometry(4.28, 0.08, 1.72, 2, 0.035), trim, [-0.04, 0.31, 0]),
      namedMesh("vehicle-cabin", createLoftGeometry([
        { x: -1.38, centerY: 1.02, radiusY: 0.04, radiusZ: 0.42 },
        { x: -1.08, centerY: 1.1, radiusY: 0.28, radiusZ: 0.65 },
        { x: -0.56, centerY: 1.16, radiusY: 0.46, radiusZ: 0.76 },
        { x: 0.5, centerY: 1.15, radiusY: 0.45, radiusZ: 0.75 },
        { x: 1.12, centerY: 1.05, radiusY: 0.24, radiusZ: 0.62 },
        { x: 1.42, centerY: 0.97, radiusY: 0.04, radiusZ: 0.4 },
      ], 24, 2.25), glass, [0, 0, 0]),
    );
    const wheelNodes: THREE.Object3D[] = [];
    for (const x of [-1.46, 1.46]) for (const z of [-0.98, 0.98]) {
      const pivot = new THREE.Group();
      pivot.name = `vehicle-wheel-${x < 0 ? "rear" : "front"}-${z < 0 ? "left" : "right"}`;
      pivot.position.set(x, 0.38, z);
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.2, 20), tire); wheel.rotation.x = Math.PI / 2;
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.21, 0.21, 0.215, 12), rim); hub.rotation.x = Math.PI / 2;
      pivot.add(wheel, hub); model.add(pivot); wheelNodes.push(pivot);
    }
    for (const z of [-0.61, 0.61]) model.add(
      namedMesh(`vehicle-head-light-${z < 0 ? "left" : "right"}`, new RoundedBoxGeometry(0.09, 0.16, 0.42, 2, 0.025), head, [2.39, 0.76, z]),
    );
    model.add(namedMesh("vehicle-tail-light-bar", new RoundedBoxGeometry(0.09, 0.105, 1.5, 2, 0.03), tail, [-2.39, 0.72, 0]));
    model.traverse((object) => { const mesh = object as THREE.Mesh; if (mesh.isMesh) { mesh.castShadow = this.#quality === "high"; mesh.receiveShadow = mesh.castShadow; } });
    return { model, source: "procedural", bodyMaterials: [body], rearLightMaterials: [tail], wheelNodes };
  }

  #beginEgoAssetLoad(anchor: THREE.Group): void {
    if (!this.#assetCatalog || this.#egoAssetLoading) return;
    this.#egoAssetLoading = true;
    this.#canvas.dataset.vehicleAsset = "loading";
    void this.#assetCatalog.createEgoInstance().then((instance) => {
      if (this.#disposed || !anchor.parent) { this.#assetCatalog?.disposeInstance(instance); return; }
      const previous = anchor.userData as EgoVisualData;
      previous.model.removeFromParent();
      disposeObjectResources(previous.model);
      instance.root.traverse((object) => { const mesh = object as THREE.Mesh; if (mesh.isMesh) { mesh.castShadow = this.#quality === "high"; mesh.receiveShadow = mesh.castShadow; } });
      anchor.add(instance.root);
      anchor.userData = {
        ...previous,
        model: instance.root,
        source: "glb",
        bodyMaterials: instance.bodyMaterials,
        rearLightMaterials: instance.rearLightMaterials,
        wheelNodes: instance.wheelNodes,
        wheelAxes: instance.wheelNodes.map(() => GLB_WHEEL_AXLE_AXIS),
        glbInstance: instance,
      } satisfies EgoVisualData;
      this.#canvas.dataset.vehicleAsset = "ready";
      if (this.#snapshot) this.#updateEgoState(anchor, this.#snapshot.ego, this.#snapshot.road.speed_limit_mps);
      if (this.renderer instanceof THREE.WebGLRenderer) void this.renderer.compileAsync(this.threeScene, this.camera).catch(() => undefined);
    }).catch(() => { if (!this.#disposed) this.#canvas.dataset.vehicleAsset = "fallback"; }).finally(() => { this.#egoAssetLoading = false; });
  }

  #updateEgoState(anchor: THREE.Group, vehicle: VehicleSnapshot, speedLimit: number): void {
    const visual = anchor.userData as EgoVisualData;
    const color = vehicle.crashed ? COLLISION_COLOR : EGO_BODY_COLOR;
    visual.displayColor = color;
    visual.bodyMaterials.forEach((material) => material.color.setHex(color));
    visual.rearLightMaterials.forEach((material) => { material.emissive.setHex(0xff102a); material.emissiveIntensity = vehicle.crashed ? 4.2 : 2.4; });
    visual.speedIndicator.scale.x = THREE.MathUtils.clamp(vehicle.speed_mps / Math.max(speedLimit, 1), 0.22, 1.5);
  }

  #disposeEgoAnchor(anchor: THREE.Group): void {
    const visual = anchor.userData as EgoVisualData;
    if (visual.glbInstance) this.#assetCatalog?.disposeInstance(visual.glbInstance); else disposeObjectResources(visual.model);
    disposeObjectResources(visual.speedIndicator);
  }

  #syncTrafficFleet(): void {
    const ego = this.#vehicleGroup.getObjectByName("vehicle-ego");
    if (!ego) return;
    const states: TrafficInstanceState[] = [];
    for (const [id, state] of this.#vehicleStates) {
      if (id === "ego") continue;
      const anchor = this.#vehicleGroup.getObjectByName(`vehicle-${id}`);
      if (anchor) states.push({ vehicleId: id, position: anchor.position, headingRad: state.heading_rad, crashed: state.crashed, scenarioEvent: state.scenario_event });
    }
    this.#trafficFleet.update(states, ego.position.x);
  }

  #materializeTrajectory(): void {
    if (this.#history.length === 0) return;
    const shouldBePoints = this.#history.length === 1;
    if (!this.#trajectoryVisual || (shouldBePoints && !(this.#trajectoryVisual instanceof THREE.Points)) || (!shouldBePoints && !(this.#trajectoryVisual instanceof THREE.Line))) {
      this.#clear(this.#trajectoryGroup);
      this.#trajectoryGeometry = new THREE.BufferGeometry();
      const capacity = QUALITY_PROFILES[this.#quality].trajectoryPoints;
      this.#trajectoryGeometry.setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(capacity * 3), 3));
      this.#trajectoryVisual = shouldBePoints
        ? new THREE.Points(this.#trajectoryGeometry, new THREE.PointsMaterial({ color: EGO_COLOR, size: 0.3, transparent: true, opacity: 0.95, depthTest: false, depthWrite: false }))
        : new THREE.Line(this.#trajectoryGeometry, new THREE.LineBasicMaterial({ color: EGO_COLOR, transparent: true, opacity: 0.95, depthTest: false, depthWrite: false }));
      this.#trajectoryVisual.name = "ego-history";
      // The position buffer is updated continuously during interpolation. Its
      // bounding sphere would otherwise remain stale and Three.js could cull
      // the whole trail after the ego vehicle moves away from the first point.
      this.#trajectoryVisual.frustumCulled = false;
      this.#trajectoryGroup.add(this.#trajectoryVisual);
    }
    const positions = this.#trajectoryGeometry?.getAttribute("position") as THREE.BufferAttribute | undefined;
    if (!positions) return;
    this.#history.forEach((point, index) => positions.setXYZ(index, point.x, point.y, point.z));
    positions.needsUpdate = true;
    this.#trajectoryGeometry?.setDrawRange(0, this.#history.length);
  }

  setCameraMode(mode: CameraMode): void {
    this.#cameraMode = mode;
    this.#controls.enabled = mode === "free";
    this.#updateCamera(true);
    this.renderer.render(this.threeScene, this.camera);
  }

  setQuality(quality: QualityLevel): void {
    this.#quality = quality;
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio ?? 1, QUALITY_PROFILES[quality].pixelRatioCap));
    if (this.renderer instanceof THREE.WebGLRenderer) this.renderer.shadowMap.enabled = QUALITY_PROFILES[quality].shadows;
    const keyLight = this.threeScene.getObjectByName("hmi-key-light") as THREE.DirectionalLight | undefined;
    if (keyLight) keyLight.castShadow = quality === "high";
    this.#trafficFleet.setQuality(quality);
    this.#vehicleGroup.getObjectByName("vehicle-ego")?.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (mesh.isMesh) { mesh.castShadow = quality === "high"; mesh.receiveShadow = mesh.castShadow; }
    });
    this.#roadSignature = "";
    this.#trajectoryVisual = null;
    this.#trajectoryGeometry = null;
    if (this.#snapshot) this.render(this.#snapshot, { mode: "live", index: 0, length: 0 });
  }

  advanceFrame(alpha = 0.28): void {
    const blend = THREE.MathUtils.clamp(alpha, 0, 1);
    for (const [id, target] of this.#targets) {
      this.#vehicleGroup.getObjectByName(`vehicle-${id}`)?.position.lerp(target, blend);
    }
    this.#syncAnimatedVisuals();
    this.#materializeTrajectory();
    this.#updateCamera();
    if (this.#cameraMode === "free") this.#controls.update();
    this.renderer.render(this.threeScene, this.camera);
  }

  #advanceTimedFrame(time: number): void {
    const progress = THREE.MathUtils.clamp(
      (time - this.#motionStartedAt) / Math.max(this.#motionDurationMs, 1),
      0,
      1,
    );
    for (const [id, target] of this.#targets) {
      const vehicle = this.#vehicleGroup.getObjectByName(`vehicle-${id}`);
      const start = this.#starts.get(id);
      if (vehicle && start) vehicle.position.lerpVectors(start, target, progress);
    }
    this.#syncAnimatedVisuals();
    this.#materializeTrajectory();
    this.#updateCamera();
    if (this.#cameraMode === "free") this.#controls.update();
    // Software renderers are detected before construction and use the low
    // profile. Capping only that fallback path keeps the UI responsive while
    // preserving full-rate interpolation on a real GPU.
    if (this.#quality === "low" && time - this.#lastAnimationRenderAt < 1000 / 30) return;
    this.#lastAnimationRenderAt = time;
    this.renderer.render(this.threeScene, this.camera);
  }

  #syncAnimatedVisuals(): void {
    const ego = this.#vehicleGroup.getObjectByName("vehicle-ego") as THREE.Group | undefined;
    if (!ego) return;
    this.#syncTrafficFleet();
    const visual = ego.userData as EgoVisualData;
    if (this.#lastEgoVisualX !== null) {
      // Rotate around each model's actual local axle using Object3D's
      // quaternion path.  GLB wheel nodes use local +Y; procedural wheel
      // pivots use local +Z. Positive travel along +X rolls forward.
      const rotation = (ego.position.x - this.#lastEgoVisualX) / 0.38;
      visual.wheelNodes.forEach((wheel, index) => {
        wheel.rotateOnAxis(visual.wheelAxes[index] ?? PROCEDURAL_WHEEL_AXLE_AXIS, rotation);
      });
    }
    this.#lastEgoVisualX = ego.position.x;
    const tail = this.#history[this.#history.length - 1];
    if (tail) tail.set(ego.position.x, 0.16, ego.position.z);
  }

  #updateCamera(force = false): void {
    const ego = this.#vehicleGroup.getObjectByName("vehicle-ego");
    if (!ego) return;
    const target = ego.position;
    if (this.#cameraMode === "follow") {
      this.camera.position.set(target.x - 12, 6.8, target.z + 7.1);
      this.camera.lookAt(target.x + 9.5, 0.55, target.z);
    } else if (this.#cameraMode === "top") {
      this.camera.position.set(target.x, 48, target.z + 0.001);
      this.camera.lookAt(target);
    } else if (force) {
      this.camera.position.set(target.x - 24, 18, target.z + 24);
      this.#controls.target.copy(target);
      this.#controls.update();
    }
  }

  objectNames(): string[] {
    const names: string[] = [];
    this.threeScene.traverse((object) => { if (object.name) names.push(object.name); });
    return names;
  }

  vehiclePosition(id: string): THREE.Vector3 {
    const vehicle = this.#vehicleGroup.getObjectByName(`vehicle-${id}`);
    if (!vehicle) throw new Error(`vehicle ${id} is unavailable`);
    return vehicle.position.clone();
  }

  vehicleColor(id: string): number {
    if (id !== "ego") {
      const color = this.#trafficFleet.colorFor(id);
      if (color === undefined) throw new Error(`vehicle ${id} is unavailable`);
      return color;
    }
    const vehicle = this.#vehicleGroup.getObjectByName("vehicle-ego") as THREE.Group | undefined;
    if (!vehicle) throw new Error("vehicle ego is unavailable");
    return (vehicle.userData as EgoVisualData).displayColor;
  }

  trafficDrawMeshCount(): number {
    let count = 0;
    this.#trafficFleet.group.traverse((object) => { if ((object as THREE.Mesh).isMesh) count += 1; });
    return count;
  }

  dispose(): void {
    if (this.#disposed) return;
    this.#disposed = true;
    this.#canvas.removeEventListener?.("webglcontextlost", this.#contextLostHandler);
    this.#canvas.removeEventListener?.("webglcontextrestored", this.#contextRestoredHandler);
    globalThis.removeEventListener?.("resize", this.#resizeHandler);
    this.renderer.setAnimationLoop(null);
    this.#controls.dispose();
    this.#trafficFleet.dispose();
    const ego = this.#vehicleGroup.getObjectByName("vehicle-ego") as THREE.Group | undefined;
    if (ego) this.#disposeEgoAnchor(ego);
    this.#clear(this.#staticGroup);
    this.#clear(this.#trajectoryGroup);
    for (const child of [...this.#vehicleGroup.children]) child.removeFromParent();
    this.#environmentTarget?.dispose();
    this.#roadTexture.dispose();
    if (this.#ownsAssetCatalog) this.#assetCatalog?.dispose();
    this.#starts.clear();
    this.#targets.clear();
    this.#vehicleStates.clear();
    this.renderer.dispose();
  }

  #clear(group: THREE.Group): void {
    for (const child of [...group.children]) {
      disposeObjectResources(child);
      group.remove(child);
    }
  }
}
