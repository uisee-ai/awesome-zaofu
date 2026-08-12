import {
  SharedSceneEntryService,
  type DemoDestination,
  type SharedSceneEntry,
} from "../../../../backend/studio/demo-linking/shared-scene-entry.js";
import {
  createCameraVisualization,
  createInferenceVisualization,
  createRunStatusVisualization,
  createTrajectoryVisualization,
  type CameraSequenceView,
  type RunStatus,
  type TrajectoryPointView,
} from "../../components/studio/index.js";
import { createResearchUseNotice } from "../../components/safety/index.js";

export interface SharedDemoScene {
  sceneVersionId: string;
  cameraFrames: readonly CameraSequenceView[];
  inference: {
    status: RunStatus;
    chainOfCausation: string;
    metaAction: string;
    trajectory: readonly TrajectoryPointView[];
  };
}

export interface DemoEntryVisualizations {
  camera: ReturnType<typeof createCameraVisualization>;
  runStatus: ReturnType<typeof createRunStatusVisualization>;
  inference: ReturnType<typeof createInferenceVisualization>;
  trajectory: ReturnType<typeof createTrajectoryVisualization>;
}

export interface DemoEntry extends SharedSceneEntry {
  demo: DemoDestination;
  researchUseNotice: string;
  visualizations: DemoEntryVisualizations;
}

/**
 * Presentation-level adapter shared by each demo entrance. It intentionally
 * holds no asset payload: every destination receives the same SceneVersion ID.
 */
export class DemoSwitcher {
  constructor(private readonly entries: SharedSceneEntryService = new SharedSceneEntryService()) {}

  createEntries(scene: SharedDemoScene): DemoEntry[] {
    return this.entries.createEntries(scene.sceneVersionId).map((entry) => ({
      ...entry,
      researchUseNotice: createResearchUseNotice(),
      visualizations: {
        camera: createCameraVisualization({ cameras: scene.cameraFrames, selectedFrameIndex: 0 }),
        runStatus: createRunStatusVisualization(scene.inference.status),
        inference: createInferenceVisualization({
          chainOfCausation: scene.inference.chainOfCausation,
          metaAction: scene.inference.metaAction,
        }),
        trajectory: createTrajectoryVisualization(scene.inference.trajectory),
      },
    }));
  }
}

export function createDemoSwitcher(): DemoSwitcher {
  return new DemoSwitcher();
}
