export interface LibraryItem {
  episode_id: string;
  name: string;
  canonical_bytes: number;
  created_at: string;
}

export interface EpisodeLibraryTransport {
  list(): Promise<LibraryItem[]>;
  saveTemporary(episodeId: string, name: string): Promise<LibraryItem>;
  rename(episodeId: string, name: string): Promise<LibraryItem>;
  delete(episodeId: string): Promise<void>;
  importReplay(payload: Uint8Array): Promise<LibraryItem>;
  exportReplay(episodeId: string, gzipTransport: boolean): Promise<Uint8Array>;
}

export type ConfirmDeletion = (item: LibraryItem) => boolean | Promise<boolean>;

/** UI state for the project-shared permanent Library. */
export class EpisodeLibraryController {
  readonly #transport: EpisodeLibraryTransport;
  readonly #confirmDeletion: ConfirmDeletion;
  #items: LibraryItem[] = [];

  constructor(transport: EpisodeLibraryTransport, confirmDeletion: ConfirmDeletion) {
    this.#transport = transport;
    this.#confirmDeletion = confirmDeletion;
  }

  items(): LibraryItem[] {
    return this.#items.map((item) => ({ ...item }));
  }

  async refresh(): Promise<LibraryItem[]> {
    this.#items = this.#sort(await this.#transport.list());
    return this.items();
  }

  async saveTemporary(episodeId: string, name: string): Promise<LibraryItem> {
    const saved = await this.#transport.saveTemporary(episodeId, name);
    this.#upsert(saved);
    return { ...saved };
  }

  async rename(episodeId: string, name: string): Promise<LibraryItem> {
    const renamed = await this.#transport.rename(episodeId, name);
    this.#upsert(renamed);
    return { ...renamed };
  }

  async delete(episodeId: string): Promise<boolean> {
    const item = this.#items.find((candidate) => candidate.episode_id === episodeId);
    if (item === undefined) {
      return false;
    }
    if (!(await this.#confirmDeletion({ ...item }))) {
      return false;
    }
    await this.#transport.delete(episodeId);
    this.#items = this.#items.filter((candidate) => candidate.episode_id !== episodeId);
    return true;
  }

  async importReplay(payload: Uint8Array): Promise<LibraryItem> {
    const imported = await this.#transport.importReplay(payload);
    this.#upsert(imported);
    return { ...imported };
  }

  exportReplay(episodeId: string, gzipTransport = false): Promise<Uint8Array> {
    return this.#transport.exportReplay(episodeId, gzipTransport);
  }

  #upsert(item: LibraryItem): void {
    this.#items = this.#sort([
      ...this.#items.filter((candidate) => candidate.episode_id !== item.episode_id),
      { ...item },
    ]);
  }

  #sort(items: LibraryItem[]): LibraryItem[] {
    return items.map((item) => ({ ...item })).sort((left, right) =>
      left.created_at.localeCompare(right.created_at) || left.episode_id.localeCompare(right.episode_id),
    );
  }
}
