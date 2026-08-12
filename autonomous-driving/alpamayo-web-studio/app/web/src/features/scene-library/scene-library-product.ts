import {
  createSceneLibraryController,
  type SceneLibraryLoader,
  type SceneLibrarySearch,
  type SceneLibrarySearchResult,
} from "./scene-library-controller.js";

interface CatalogResponse {
  items: SceneLibrarySearchResult[];
}

export interface SceneCatalogResponse {
  ok: boolean;
  json(): Promise<unknown>;
}

export type SceneCatalogRequest = (url: string) => Promise<SceneCatalogResponse>;

export function createSceneCatalogLoader(
  apiBaseUrl: string,
  request: SceneCatalogRequest = (url) => fetch(url),
): SceneLibraryLoader {
  return async (filters) => {
    const response = await request(catalogUrl(apiBaseUrl, filters));
    if (!response.ok) {
      throw new Error("场景库查询失败。");
    }
    const payload = await response.json() as CatalogResponse;
    return payload.items;
  };
}

export function createSceneLibraryPage(
  apiBaseUrl: string,
  request?: SceneCatalogRequest,
) {
  return createSceneLibraryController(createSceneCatalogLoader(apiBaseUrl, request));
}

function catalogUrl(apiBaseUrl: string, filters: SceneLibrarySearch): string {
  const url = new URL("/api/catalog/scenes", apiBaseUrl);
  if (filters.name) url.searchParams.set("name", filters.name);
  if (filters.cameraId !== undefined) url.searchParams.set("cameraId", String(filters.cameraId));
  for (const tag of filters.tags ?? []) url.searchParams.append("tags", tag);
  if (filters.source) url.searchParams.set("source", filters.source);
  if (filters.createdAfter) url.searchParams.set("createdAfter", filters.createdAfter);
  if (filters.createdBefore) url.searchParams.set("createdBefore", filters.createdBefore);
  return url.toString();
}
