import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";


export type VehicleAssetInstance = {
  root: THREE.Group;
  bodyMaterials: THREE.MeshStandardMaterial[];
  rearLightMaterials: THREE.MeshStandardMaterial[];
  wheelNodes: THREE.Object3D[];
};

const EGO_ASSET_URL = "/assets/hmi/vehicles/generic-ego-sedan.glb";

function isStandardMaterial(material: THREE.Material): material is THREE.MeshStandardMaterial {
  return (
    ("isMeshStandardMaterial" in material && Boolean(material.isMeshStandardMaterial))
    || ("isMeshPhysicalMaterial" in material && Boolean(material.isMeshPhysicalMaterial))
  );
}

function materialList(material: THREE.Material | THREE.Material[]): THREE.Material[] {
  return Array.isArray(material) ? material : [material];
}

/** Loads, caches, clones and disposes the project-owned vehicle GLB. */
export class VehicleAssetCatalog {
  readonly #loader: GLTFLoader;
  #egoSource: Promise<THREE.Group> | null = null;
  #sourceRoot: THREE.Group | null = null;
  #disposed = false;

  constructor(loader = new GLTFLoader()) {
    this.#loader = loader;
  }

  preload(): Promise<void> {
    return this.#loadEgoSource().then(() => undefined);
  }

  async createEgoInstance(): Promise<VehicleAssetInstance> {
    const source = await this.#loadEgoSource();
    if (this.#disposed) throw new Error("vehicle asset catalog is disposed");
    const root = source.clone(true);
    root.name = "ego-visual-model-glb";
    const bodyMaterials: THREE.MeshStandardMaterial[] = [];
    const rearLightMaterials: THREE.MeshStandardMaterial[] = [];
    const wheelNodes: THREE.Object3D[] = [];
    const clonedMaterials = new Map<THREE.Material, THREE.Material>();

    root.traverse((object) => {
      if (/^wheel_/i.test(object.name) && !/_rim$/i.test(object.name)) wheelNodes.push(object);
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      const cloned = materialList(mesh.material).map((value) => {
        const existing = clonedMaterials.get(value);
        if (existing) return existing;
        const copy = value.clone();
        clonedMaterials.set(value, copy);
        return copy;
      });
      mesh.material = Array.isArray(mesh.material) ? cloned : cloned[0];
      for (const value of cloned) {
        if (!isStandardMaterial(value)) continue;
        const semantic = `${object.name}:${value.name}`.toLowerCase();
        if (semantic.includes("body") || semantic.includes("roof")) {
          value.metalness = 0.22;
          value.roughness = 0.36;
          value.envMapIntensity = 0.28;
          bodyMaterials.push(value);
        }
        if (semantic.includes("tail_light")) rearLightMaterials.push(value);
      }
    });
    return {
      root,
      bodyMaterials: [...new Set(bodyMaterials)],
      rearLightMaterials: [...new Set(rearLightMaterials)],
      wheelNodes,
    };
  }

  disposeInstance(instance: VehicleAssetInstance): void {
    const materials = new Set<THREE.Material>();
    instance.root.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      materialList(mesh.material).forEach((value) => materials.add(value));
    });
    materials.forEach((value) => value.dispose());
    instance.root.removeFromParent();
  }

  dispose(): void {
    this.#disposed = true;
    if (!this.#sourceRoot) return;
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();
    const textures = new Set<THREE.Texture>();
    this.#sourceRoot.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      geometries.add(mesh.geometry);
      for (const value of materialList(mesh.material)) {
        materials.add(value);
        Object.values(value).forEach((property) => {
          if (property instanceof THREE.Texture) textures.add(property);
        });
      }
    });
    geometries.forEach((value) => value.dispose());
    materials.forEach((value) => value.dispose());
    textures.forEach((value) => value.dispose());
    this.#sourceRoot = null;
    this.#egoSource = null;
  }

  #loadEgoSource(): Promise<THREE.Group> {
    if (!this.#egoSource) {
      this.#egoSource = this.#loader.loadAsync(EGO_ASSET_URL).then((gltf) => {
        if (this.#disposed) throw new Error("vehicle asset catalog is disposed");
        gltf.scene.updateMatrixWorld(true);
        this.#sourceRoot = gltf.scene;
        return gltf.scene;
      });
    }
    return this.#egoSource;
  }
}
