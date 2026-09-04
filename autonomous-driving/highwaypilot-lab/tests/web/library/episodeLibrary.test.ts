import { describe, expect, it, vi } from "vitest";

import {
  EpisodeLibraryController,
  type EpisodeLibraryTransport,
  type LibraryItem,
} from "../../../web/src/features/library/episodeLibrary.ts";


function item(episode_id: string, name = episode_id): LibraryItem {
  return { episode_id, name, canonical_bytes: 100, created_at: `2026-08-25T00:00:0${episode_id.at(-1)}Z` };
}

function transport(): EpisodeLibraryTransport {
  return {
    list: vi.fn(async () => [item("episode-2"), item("episode-1")]),
    saveTemporary: vi.fn(async (episodeId, name) => item(episodeId, name)),
    rename: vi.fn(async (episodeId, name) => item(episodeId, name)),
    delete: vi.fn(async () => undefined),
    importReplay: vi.fn(async () => item("episode-3", "Imported")),
    exportReplay: vi.fn(async () => new Uint8Array([1, 2, 3])),
  };
}


describe("EpisodeLibraryController", () => {
  it("lists, explicitly saves, renames, imports, and exports permanent Episodes", async () => {
    const api = transport();
    const library = new EpisodeLibraryController(api, () => true);

    expect((await library.refresh()).map(({ episode_id }) => episode_id)).toEqual(["episode-1", "episode-2"]);
    await library.saveTemporary("episode-4", "Saved from this session");
    expect(library.items().find((entry) => entry.episode_id === "episode-4")?.name).toBe("Saved from this session");
    await library.rename("episode-4", "Renamed");
    expect(library.items().find((entry) => entry.episode_id === "episode-4")?.name).toBe("Renamed");
    await library.importReplay(new Uint8Array([123, 125]));
    expect(library.items().some((entry) => entry.episode_id === "episode-3")).toBe(true);
    await expect(library.exportReplay("episode-3", true)).resolves.toEqual(new Uint8Array([1, 2, 3]));
  });

  it("requires ordinary confirmation before issuing delete", async () => {
    const api = transport();
    const confirm = vi.fn(() => false);
    const library = new EpisodeLibraryController(api, confirm);
    await library.refresh();

    await expect(library.delete("episode-1")).resolves.toBe(false);
    expect(api.delete).not.toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledWith(item("episode-1"));
  });
});
