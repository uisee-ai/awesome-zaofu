export interface NuScenesSearchSource {
  readonly stableId: string;
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly sourceText: string;
}

export interface DerivedSceneMetadata {
  readonly weather: "rain" | "clear" | "unknown";
  readonly daylight: "night" | "day" | "unknown";
}

export interface NuScenesSearchQuery {
  readonly text: string;
  readonly derivedFilters: Readonly<Partial<DerivedSceneMetadata>>;
}

export interface NuScenesSearchResult {
  readonly stableId: string;
  readonly sceneRef: string;
  readonly frameRef: string;
  readonly sourceText: string;
  readonly derived: true;
  readonly derivationSource: "scene.description";
  readonly ruleVersion: string;
  readonly derivedFilters: DerivedSceneMetadata;
}

interface IndexedScene extends NuScenesSearchSource {
  readonly derivedFilters: DerivedSceneMetadata;
}

function deriveSceneMetadata(sourceText: string): DerivedSceneMetadata {
  const text = sourceText.toLowerCase();
  const weather = text.includes("rain") ? "rain" : text.includes("sunny") || text.includes("clear") ? "clear" : "unknown";
  const daylight = text.includes("night") ? "night" : text.includes("daytime") || text.includes("sunny") ? "day" : "unknown";
  return { weather, daylight };
}

export class NuScenesSearchIndex {
  readonly #records: readonly IndexedScene[];

  constructor(
    readonly ruleVersion: string,
    sources: readonly NuScenesSearchSource[],
  ) {
    if (ruleVersion.length === 0) throw new TypeError("ruleVersion is required");
    const ids = new Set<string>();
    this.#records = sources.map((source) => {
      if (ids.has(source.stableId)) throw new TypeError(`duplicate search stableId: ${source.stableId}`);
      ids.add(source.stableId);
      return { ...source, derivedFilters: deriveSceneMetadata(source.sourceText) };
    });
  }

  search(query: NuScenesSearchQuery): readonly NuScenesSearchResult[] {
    const text = query.text.trim().toLowerCase();
    return this.#records
      .filter((record) => text.length === 0 || record.sourceText.toLowerCase().includes(text))
      .filter((record) =>
        Object.entries(query.derivedFilters).every(
          ([key, value]) => value === undefined || record.derivedFilters[key as keyof DerivedSceneMetadata] === value,
        ),
      )
      .map((record) => ({
        stableId: record.stableId,
        sceneRef: record.sceneRef,
        frameRef: record.frameRef,
        sourceText: record.sourceText,
        derived: true,
        derivationSource: "scene.description",
        ruleVersion: this.ruleVersion,
        derivedFilters: record.derivedFilters,
      }));
  }

  snapshot() {
    return this.#records.map((record) => ({
      stableId: record.stableId,
      sourceText: record.sourceText,
      derivedFilters: record.derivedFilters,
      derivationSource: "scene.description" as const,
      ruleVersion: this.ruleVersion,
    }));
  }
}
