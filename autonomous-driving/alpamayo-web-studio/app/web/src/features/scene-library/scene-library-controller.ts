export interface SceneLibrarySearch {
  name?: string;
  cameraId?: number;
  tags?: string[];
  source?: string;
  createdAfter?: string;
  createdBefore?: string;
}

export interface SceneIntegrityIssue {
  code: string;
  message: string;
}

export interface SceneLibrarySearchResult {
  sceneId: string;
  name: string;
  cameraIds: number[];
  tags: string[];
  source: string;
  createdAt: string;
  integrity: {
    state: "complete" | "needs_attention";
    issues: SceneIntegrityIssue[];
  };
}

export interface SceneLibraryRow {
  sceneId: string;
  name: string;
  cameraIds: number[];
  tags: string[];
  source: string;
  createdAt: string;
  integrityLabel: "数据完整" | "需要补充数据";
  integrityIssues: string[];
}

export type SceneLibraryLoader = (filters: SceneLibrarySearch) => Promise<SceneLibrarySearchResult[]>;

export type SceneLibraryState =
  | { phase: "idle"; rows: [] }
  | { phase: "loading"; rows: SceneLibraryRow[] }
  | { phase: "ready"; rows: SceneLibraryRow[] }
  | { phase: "failed"; rows: SceneLibraryRow[]; error: string };

export class SceneLibraryController {
  private state: SceneLibraryState = { phase: "idle", rows: [] };

  constructor(private readonly loader: SceneLibraryLoader) {}

  snapshot(): SceneLibraryState {
    return this.state;
  }

  async search(filters: SceneLibrarySearch = {}): Promise<SceneLibraryRow[]> {
    this.state = { phase: "loading", rows: this.state.rows };
    try {
      const results = await this.loader(copyFilters(filters));
      const rows = results.map(toRow);
      this.state = { phase: "ready", rows };
      return rows;
    } catch (error) {
      const message = error instanceof Error ? error.message : "场景库搜索失败。";
      this.state = { phase: "failed", rows: this.state.rows, error: message };
      throw error;
    }
  }
}

function copyFilters(filters: SceneLibrarySearch): SceneLibrarySearch {
  return { ...filters, tags: filters.tags ? [...filters.tags] : undefined };
}

function toRow(result: SceneLibrarySearchResult): SceneLibraryRow {
  return {
    sceneId: result.sceneId,
    name: result.name,
    cameraIds: [...result.cameraIds],
    tags: [...result.tags],
    source: result.source,
    createdAt: result.createdAt,
    integrityLabel: result.integrity.state === "complete" ? "数据完整" : "需要补充数据",
    integrityIssues: result.integrity.issues.map((issue) => issue.message),
  };
}

export function createSceneLibraryController(loader: SceneLibraryLoader): SceneLibraryController {
  return new SceneLibraryController(loader);
}
