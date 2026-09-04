import * as THREE from "three";

import type { QualityLevel } from "../HmiState.js";
import { createSmoothSedanGeometries, type VehicleGeometryDetail } from "./VehicleGeometry.js";


export type TrafficInstanceState = {
  vehicleId: string;
  position: THREE.Vector3;
  headingRad: number;
  crashed: boolean;
  scenarioEvent: boolean;
};

type Pool = { body: THREE.InstancedMesh; all: THREE.InstancedMesh[] };

const MAX_TRAFFIC = 50;
const COLLISION_COLOR = new THREE.Color(0xef4444);
const TRAFFIC_PALETTE = [
  new THREE.Color(0xf3c746),
  new THREE.Color(0x11151b),
] as const;

function hashVehicleId(id: string): number {
  let value = 2166136261;
  for (const character of id) {
    value ^= character.charCodeAt(0);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

function colorForState(state: TrafficInstanceState): THREE.Color {
  if (state.crashed) return COLLISION_COLOR;
  return TRAFFIC_PALETTE[hashVehicleId(state.vehicleId) % TRAFFIC_PALETTE.length];
}

function createPool(detail: VehicleGeometryDetail, quality: QualityLevel): Pool {
  const geometry = createSmoothSedanGeometries(detail);
  const body = new THREE.InstancedMesh(
    geometry.body,
    new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness: 0.26, metalness: 0.48, clearcoat: 0.62, clearcoatRoughness: 0.22 }),
    MAX_TRAFFIC,
  );
  const cabin = new THREE.InstancedMesh(
    geometry.cabin,
    new THREE.MeshStandardMaterial({ color: 0x101b27, roughness: 0.15, metalness: 0.08 }),
    MAX_TRAFFIC,
  );
  const wheels = new THREE.InstancedMesh(
    geometry.wheels,
    new THREE.MeshStandardMaterial({ color: 0x080b10, roughness: 0.92 }),
    MAX_TRAFFIC,
  );
  const headlights = new THREE.InstancedMesh(
    geometry.headlights,
    new THREE.MeshStandardMaterial({ color: 0xdff5ff, emissive: 0xbcecff, emissiveIntensity: 1.3, roughness: 0.2 }),
    MAX_TRAFFIC,
  );
  const taillights = new THREE.InstancedMesh(
    geometry.taillights,
    new THREE.MeshStandardMaterial({ color: 0xff3048, emissive: 0xff102a, emissiveIntensity: 1.8, roughness: 0.2 }),
    MAX_TRAFFIC,
  );
  const all = [body, cabin, wheels, headlights, taillights];
  all.forEach((part, index) => {
    part.name = `traffic-${detail}-${["body", "cabin", "wheels", "headlights", "taillights"][index]}-instances`;
    part.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    part.count = 0;
    part.castShadow = quality === "high" && detail === "near";
    part.receiveShadow = part.castShadow;
    part.frustumCulled = false;
  });
  return { body, all };
}

/** One shared sedan silhouette, instanced into near/far LOD pools for up to 50 vehicles. */
export class TrafficVehicleFleet {
  readonly group = new THREE.Group();
  readonly #pools = new Map<VehicleGeometryDetail, Pool>();
  readonly #dummy = new THREE.Object3D();
  readonly #colors = new Map<string, number>();
  #quality: QualityLevel;

  constructor(quality: QualityLevel) {
    this.#quality = quality;
    this.group.name = "traffic-instanced-fleet";
    this.#buildPools();
  }

  update(states: TrafficInstanceState[], egoX: number): void {
    const buckets = new Map<VehicleGeometryDetail, TrafficInstanceState[]>();
    this.#colors.clear();
    for (const state of states) {
      const nearDistance = this.#quality === "high" ? 130 : this.#quality === "medium" ? 85 : 0;
      const detail: VehicleGeometryDetail = Math.abs(state.position.x - egoX) <= nearDistance ? "near" : "far";
      const bucket = buckets.get(detail) ?? [];
      bucket.push(state);
      buckets.set(detail, bucket);
    }
    for (const [detail, pool] of this.#pools) {
      const values = buckets.get(detail) ?? [];
      pool.all.forEach((part) => { part.count = values.length; });
      values.forEach((state, index) => {
        this.#dummy.position.copy(state.position);
        this.#dummy.rotation.set(0, -state.headingRad, 0);
        this.#dummy.scale.setScalar(1);
        this.#dummy.updateMatrix();
        pool.all.forEach((part) => part.setMatrixAt(index, this.#dummy.matrix));
        const color = colorForState(state);
        pool.body.setColorAt(index, color);
        this.#colors.set(state.vehicleId, color.getHex());
      });
      pool.all.forEach((part) => { part.instanceMatrix.needsUpdate = true; });
      if (pool.body.instanceColor) pool.body.instanceColor.needsUpdate = true;
    }
  }

  colorFor(vehicleId: string): number | undefined {
    return this.#colors.get(vehicleId);
  }

  setQuality(quality: QualityLevel): void {
    if (quality === this.#quality) return;
    this.dispose();
    this.#quality = quality;
    this.#buildPools();
  }

  dispose(): void {
    for (const pool of this.#pools.values()) {
      for (const part of pool.all) {
        part.removeFromParent();
        part.geometry.dispose();
        const materials = Array.isArray(part.material) ? part.material : [part.material];
        materials.forEach((value) => value.dispose());
      }
    }
    this.#pools.clear();
    this.#colors.clear();
  }

  #buildPools(): void {
    const details: readonly VehicleGeometryDetail[] = this.#quality === "low" ? ["far"] : ["near", "far"];
    for (const detail of details) {
      const pool = createPool(detail, this.#quality);
      this.#pools.set(detail, pool);
      this.group.add(...pool.all);
    }
  }
}
