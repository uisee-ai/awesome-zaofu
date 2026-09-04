import * as THREE from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";


export type VehicleGeometryDetail = "near" | "far";
export type VehicleGeometrySet = Record<
  "body" | "cabin" | "wheels" | "headlights" | "taillights",
  THREE.BufferGeometry
>;

type LoftSection = {
  x: number;
  centerY: number;
  radiusY: number;
  radiusZ: number;
};

const VEHICLE_LENGTH = 4.76;
const VEHICLE_WIDTH = 1.92;
const WHEEL_RADIUS = 0.38;

function signedPower(value: number, power: number): number {
  return Math.sign(value) * Math.abs(value) ** power;
}

/** Builds one watertight, continuously shaded longitudinal vehicle surface. */
export function createLoftGeometry(
  sections: readonly LoftSection[],
  radialSegments: number,
  roundness = 2.4,
): THREE.BufferGeometry {
  if (sections.length < 2) throw new RangeError("vehicle loft requires at least two sections");
  const positions: number[] = [];
  const indices: number[] = [];
  const power = 2 / roundness;
  for (const section of sections) {
    for (let segment = 0; segment < radialSegments; segment += 1) {
      const angle = segment / radialSegments * Math.PI * 2;
      positions.push(
        section.x,
        section.centerY + section.radiusY * signedPower(Math.cos(angle), power),
        section.radiusZ * signedPower(Math.sin(angle), power),
      );
    }
  }
  for (let section = 0; section < sections.length - 1; section += 1) {
    for (let segment = 0; segment < radialSegments; segment += 1) {
      const next = (segment + 1) % radialSegments;
      const currentRing = section * radialSegments;
      const nextRing = (section + 1) * radialSegments;
      const a = currentRing + segment;
      const b = currentRing + next;
      const c = nextRing + segment;
      const d = nextRing + next;
      indices.push(a, b, c, b, d, c);
    }
  }
  const startCenter = positions.length / 3;
  positions.push(sections[0].x, sections[0].centerY, 0);
  const endCenter = positions.length / 3;
  const last = sections.length - 1;
  positions.push(sections[last].x, sections[last].centerY, 0);
  for (let segment = 0; segment < radialSegments; segment += 1) {
    const next = (segment + 1) % radialSegments;
    indices.push(startCenter, segment, next);
    indices.push(endCenter, last * radialSegments + next, last * radialSegments + segment);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

function baked(
  geometry: THREE.BufferGeometry,
  position: readonly [number, number, number],
  rotationX = 0,
): THREE.BufferGeometry {
  if (rotationX) geometry.rotateX(rotationX);
  geometry.translate(...position);
  return geometry;
}

function merge(parts: THREE.BufferGeometry[]): THREE.BufferGeometry {
  const geometry = mergeGeometries(parts, false);
  parts.forEach((part) => part.dispose());
  if (!geometry) throw new Error("unable to merge vehicle geometry");
  geometry.computeBoundingSphere();
  return geometry;
}

/** Shared silhouette for the ego and every social vehicle; LOD changes tessellation only. */
export function createSmoothSedanGeometries(detail: VehicleGeometryDetail): VehicleGeometrySet {
  // Keep the same smooth silhouette for every vehicle and quality profile.
  // Low quality reduces lighting/shadows and draw cost through instancing;
  // it must not turn social cars into visibly faceted blocks.
  const radialSegments = 24;
  const body = createLoftGeometry([
    { x: -VEHICLE_LENGTH / 2, centerY: 0.63, radiusY: 0.1, radiusZ: 0.28 },
    { x: -2.25, centerY: 0.65, radiusY: 0.26, radiusZ: 0.76 },
    { x: -1.68, centerY: 0.68, radiusY: 0.37, radiusZ: VEHICLE_WIDTH / 2 },
    { x: 0.82, centerY: 0.68, radiusY: 0.37, radiusZ: VEHICLE_WIDTH / 2 },
    { x: 1.72, centerY: 0.65, radiusY: 0.31, radiusZ: 0.86 },
    { x: 2.25, centerY: 0.62, radiusY: 0.2, radiusZ: 0.58 },
    { x: VEHICLE_LENGTH / 2, centerY: 0.61, radiusY: 0.08, radiusZ: 0.25 },
  ], radialSegments, 3.1);
  const cabin = createLoftGeometry([
    { x: -1.38, centerY: 1.02, radiusY: 0.04, radiusZ: 0.42 },
    { x: -1.08, centerY: 1.1, radiusY: 0.28, radiusZ: 0.65 },
    { x: -0.56, centerY: 1.16, radiusY: 0.46, radiusZ: 0.76 },
    { x: 0.5, centerY: 1.15, radiusY: 0.45, radiusZ: 0.75 },
    { x: 1.12, centerY: 1.05, radiusY: 0.24, radiusZ: 0.62 },
    { x: 1.42, centerY: 0.97, radiusY: 0.04, radiusZ: 0.4 },
  ], radialSegments, 2.25);
  const wheels: THREE.BufferGeometry[] = [];
  for (const x of [-1.48, 1.48]) {
    for (const z of [-VEHICLE_WIDTH * 0.505, VEHICLE_WIDTH * 0.505]) {
      wheels.push(baked(
        new THREE.CylinderGeometry(WHEEL_RADIUS, WHEEL_RADIUS, 0.2, detail === "near" ? 20 : 10),
        [x, WHEEL_RADIUS, z],
        Math.PI / 2,
      ));
    }
  }
  const headlights = [-0.61, 0.61].map((z) => baked(
    new RoundedBoxGeometry(0.09, 0.13, 0.42, 2, 0.025),
    [2.385, 0.72, z],
  ));
  const tailBar = baked(
    new RoundedBoxGeometry(0.09, 0.105, 1.5, 2, 0.03),
    [-2.385, 0.72, 0],
  );
  return {
    body,
    cabin,
    wheels: merge(wheels),
    headlights: merge(headlights),
    taillights: tailBar,
  };
}
