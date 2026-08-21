export interface NuScenesAnnotationRef {
  readonly annotationRef: string;
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly instanceRef: string;
  readonly cameraRef: string;
  readonly lidarRef: string;
  readonly bevRef: string;
  readonly previousAnnotationRef: string | null;
  readonly nextAnnotationRef: string | null;
}

export interface InstanceSelectionV1 {
  readonly stableInstanceRef: string;
  readonly sceneRef: string;
  readonly camera: { readonly stableInstanceRef: string; readonly refs: readonly string[] };
  readonly lidar: { readonly stableInstanceRef: string; readonly refs: readonly string[] };
  readonly bev: { readonly stableInstanceRef: string; readonly refs: readonly string[] };
  readonly annotationChain: readonly {
    readonly annotationRef: string;
    readonly frameRef: string;
    readonly previousAnnotationRef: string | null;
    readonly nextAnnotationRef: string | null;
  }[];
}

export function createInstanceSelection(
  sceneRef: string,
  stableInstanceRef: string,
  annotations: readonly NuScenesAnnotationRef[],
): InstanceSelectionV1 {
  const chain = annotations.filter(
    (annotation) => annotation.sceneRef === sceneRef && annotation.instanceRef === stableInstanceRef,
  );
  if (chain.length === 0) throw new RangeError("instance has no annotations in the selected scene");
  const annotationIds = new Set(chain.map((annotation) => annotation.annotationRef));
  for (const annotation of chain) {
    if (annotation.previousAnnotationRef !== null && !annotationIds.has(annotation.previousAnnotationRef)) {
      throw new TypeError("annotation chain contains an external previous reference");
    }
    if (annotation.nextAnnotationRef !== null && !annotationIds.has(annotation.nextAnnotationRef)) {
      throw new TypeError("annotation chain contains an external next reference");
    }
  }
  return {
    stableInstanceRef,
    sceneRef,
    camera: { stableInstanceRef, refs: chain.map((annotation) => annotation.cameraRef) },
    lidar: { stableInstanceRef, refs: chain.map((annotation) => annotation.lidarRef) },
    bev: { stableInstanceRef, refs: chain.map((annotation) => annotation.bevRef) },
    annotationChain: chain.map((annotation) => ({
      annotationRef: annotation.annotationRef,
      frameRef: annotation.frameRef,
      previousAnnotationRef: annotation.previousAnnotationRef,
      nextAnnotationRef: annotation.nextAnnotationRef,
    })),
  };
}
