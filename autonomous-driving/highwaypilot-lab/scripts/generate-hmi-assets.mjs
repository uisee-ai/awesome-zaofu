import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import * as THREE from "three";
import { GLTFExporter } from "three/addons/exporters/GLTFExporter.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";


// GLTFExporter uses FileReader for binary output. This adapter keeps the
// asset build reproducible under Node without introducing a runtime package.
globalThis.FileReader = class FileReader {
  result = null;
  onloadend = null;
  onerror = null;

  readAsArrayBuffer(blob) {
    blob.arrayBuffer()
      .then((value) => {
        this.result = value;
        this.onloadend?.({ target: this });
      })
      .catch((error) => this.onerror?.(error));
  }

  readAsDataURL(blob) {
    blob.arrayBuffer()
      .then((value) => {
        this.result = `data:${blob.type};base64,${Buffer.from(value).toString("base64")}`;
        this.onloadend?.({ target: this });
      })
      .catch((error) => this.onerror?.(error));
  }
};

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUTPUT = path.join(ROOT, "web", "public", "assets", "hmi", "vehicles");

function physicalMaterial(name, parameters) {
  const value = new THREE.MeshPhysicalMaterial(parameters);
  value.name = name;
  return value;
}

function roundedMesh(name, size, radius, material, position) {
  const mesh = new THREE.Mesh(new RoundedBoxGeometry(size[0], size[1], size[2], 3, radius), material);
  mesh.name = name;
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function signedPower(value, power) {
  return Math.sign(value) * Math.abs(value) ** power;
}

function loftGeometry(sections, radialSegments, roundness) {
  const positions = [];
  const indices = [];
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
      const ring = section * radialSegments;
      const nextRing = (section + 1) * radialSegments;
      const a = ring + segment;
      const b = ring + next;
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
  return geometry;
}

function loftMesh(name, sections, radialSegments, roundness, material) {
  const mesh = new THREE.Mesh(loftGeometry(sections, radialSegments, roundness), material);
  mesh.name = name;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  return mesh;
}

function createGenericEgo() {
  const root = new THREE.Group();
  root.name = "generic_ego_sedan";
  const body = physicalMaterial("body", {
    color: 0x168df0,
    metalness: 0.62,
    roughness: 0.24,
    clearcoat: 0.82,
    clearcoatRoughness: 0.18,
  });
  const trim = physicalMaterial("trim", { color: 0x11151b, metalness: 0.22, roughness: 0.5 });
  const glass = physicalMaterial("glass", {
    color: 0x172331,
    metalness: 0.08,
    roughness: 0.12,
    transparent: true,
    opacity: 0.76,
  });
  const tire = physicalMaterial("tire", { color: 0x090b0f, metalness: 0.02, roughness: 0.9 });
  const rim = physicalMaterial("rim", { color: 0x68717d, metalness: 0.82, roughness: 0.28 });
  const headlight = physicalMaterial("head_light", {
    color: 0xeaf7ff,
    emissive: 0xc6efff,
    emissiveIntensity: 2.4,
    roughness: 0.16,
  });
  const tailLight = physicalMaterial("tail_light", {
    color: 0xff243b,
    emissive: 0xff102a,
    emissiveIntensity: 2.8,
    roughness: 0.2,
  });

  root.add(
    loftMesh("body_shell", [
      { x: -2.38, centerY: 0.63, radiusY: 0.1, radiusZ: 0.28 },
      { x: -2.25, centerY: 0.65, radiusY: 0.26, radiusZ: 0.76 },
      { x: -1.68, centerY: 0.68, radiusY: 0.37, radiusZ: 0.96 },
      { x: 0.82, centerY: 0.68, radiusY: 0.37, radiusZ: 0.96 },
      { x: 1.72, centerY: 0.65, radiusY: 0.31, radiusZ: 0.86 },
      { x: 2.25, centerY: 0.62, radiusY: 0.2, radiusZ: 0.58 },
      { x: 2.38, centerY: 0.61, radiusY: 0.08, radiusZ: 0.25 },
    ], 24, 3.1, body),
    loftMesh("glass_canopy", [
      { x: -1.38, centerY: 1.02, radiusY: 0.04, radiusZ: 0.42 },
      { x: -1.08, centerY: 1.1, radiusY: 0.28, radiusZ: 0.65 },
      { x: -0.56, centerY: 1.16, radiusY: 0.46, radiusZ: 0.76 },
      { x: 0.5, centerY: 1.15, radiusY: 0.45, radiusZ: 0.75 },
      { x: 1.12, centerY: 1.05, radiusY: 0.24, radiusZ: 0.62 },
      { x: 1.42, centerY: 0.97, radiusY: 0.04, radiusZ: 0.4 },
    ], 24, 2.25, glass),
    roundedMesh("lower_trim", [4.28, 0.08, 1.72], 0.035, trim, [-0.04, 0.31, 0]),
  );

  for (const x of [-1.46, 1.46]) {
    for (const z of [-0.98, 0.98]) {
      const side = z < 0 ? "left" : "right";
      const axle = x < 0 ? "rear" : "front";
      const wheel = new THREE.Mesh(new THREE.CylinderGeometry(0.38, 0.38, 0.2, 20), tire);
      wheel.name = `wheel_${axle}_${side}`;
      wheel.rotation.x = Math.PI / 2;
      wheel.position.set(x, 0.38, z);
      wheel.castShadow = true;
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.21, 0.21, 0.215, 12), rim);
      hub.name = `wheel_${axle}_${side}_rim`;
      hub.rotation.x = Math.PI / 2;
      hub.position.copy(wheel.position);
      root.add(wheel, hub);
    }
  }
  for (const z of [-0.61, 0.61]) {
    const side = z < 0 ? "left" : "right";
    root.add(
      roundedMesh(`head_light_${side}`, [0.09, 0.16, 0.42], 0.025, headlight, [2.39, 0.76, z]),
    );
  }
  root.add(roundedMesh("tail_light_bar", [0.09, 0.105, 1.5], 0.03, tailLight, [-2.39, 0.72, 0]));
  root.updateMatrixWorld(true);
  return root;
}

async function exportBinary(object, target) {
  const result = await new GLTFExporter().parseAsync(object, { binary: true, onlyVisible: true });
  if (!(result instanceof ArrayBuffer)) throw new Error("expected binary GLB output");
  await fs.writeFile(target, Buffer.from(result));
}

await fs.mkdir(OUTPUT, { recursive: true });
await exportBinary(createGenericEgo(), path.join(OUTPUT, "generic-ego-sedan.glb"));
await fs.writeFile(path.join(OUTPUT, "README.md"), `# HighwayPilot HMI vehicle asset\n\n\`generic-ego-sedan.glb\` is generated by \`scripts/generate-hmi-assets.mjs\`. It contains no third-party model, trademark, logo, or texture.\n`);
console.log(`Generated ${path.relative(ROOT, path.join(OUTPUT, "generic-ego-sedan.glb"))}`);
