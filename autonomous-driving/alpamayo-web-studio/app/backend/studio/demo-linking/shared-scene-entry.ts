/** The six Studio surfaces that can operate on an existing SceneVersion. */
export const DEMO_DESTINATIONS = [
  "workbench",
  "navigation",
  "ablation",
  "vqa",
  "auto-label",
  "regression-judge",
] as const;

export type DemoDestination = typeof DEMO_DESTINATIONS[number];

export interface SharedSceneEntry {
  demo: DemoDestination;
  sceneVersionId: string;
  href: string;
  /** Demo entry always references the selected immutable version; it never uploads assets. */
  uploadRequired: false;
}

const demoPaths: Readonly<Record<DemoDestination, string>> = {
  workbench: "/workbench",
  navigation: "/navigation",
  ablation: "/ablation",
  vqa: "/vqa",
  "auto-label": "/auto-label",
  "regression-judge": "/regression-judge",
};

/** Creates stable links from the shared scene library into every Studio demo. */
export class SharedSceneEntryService {
  createEntries(sceneVersionId: string): SharedSceneEntry[] {
    const normalizedSceneVersionId = sceneVersionId.trim();
    if (normalizedSceneVersionId.length === 0) {
      throw new Error("A shared SceneVersion is required before entering a demo.");
    }

    return DEMO_DESTINATIONS.map((demo) => ({
      demo,
      sceneVersionId: normalizedSceneVersionId,
      href: `${demoPaths[demo]}?sceneVersionId=${encodeURIComponent(normalizedSceneVersionId)}`,
      uploadRequired: false,
    }));
  }
}
