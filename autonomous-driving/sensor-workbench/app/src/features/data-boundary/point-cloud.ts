export interface PointCloudReadOptions {
  readonly byteLength: number;
  readonly maxChunkBytes: number;
  readonly lod: number;
}

export interface PointCloudReadPlan {
  readonly byteLength: number;
  readonly maxChunkBytes: number;
  readonly lod: number;
  readonly worker: true;
  readonly chunks: readonly { readonly offset: number; readonly length: number }[];
  readonly metrics: {
    readonly chunkCount: number;
    readonly largestChunkBytes: number;
    readonly transferredToWorker: true;
  };
}

export function planPointCloudRead(options: PointCloudReadOptions): PointCloudReadPlan {
  if (!Number.isSafeInteger(options.byteLength) || options.byteLength < 0) throw new RangeError("byteLength is invalid");
  if (!Number.isSafeInteger(options.maxChunkBytes) || options.maxChunkBytes < 1) {
    throw new RangeError("maxChunkBytes is invalid");
  }
  if (!Number.isSafeInteger(options.lod) || options.lod < 0) throw new RangeError("lod is invalid");
  const chunks: { offset: number; length: number }[] = [];
  for (let offset = 0; offset < options.byteLength; offset += options.maxChunkBytes) {
    chunks.push({ offset, length: Math.min(options.maxChunkBytes, options.byteLength - offset) });
  }
  return {
    byteLength: options.byteLength,
    maxChunkBytes: options.maxChunkBytes,
    lod: options.lod,
    worker: true,
    chunks,
    metrics: {
      chunkCount: chunks.length,
      largestChunkBytes: chunks.reduce((largest, chunk) => Math.max(largest, chunk.length), 0),
      transferredToWorker: true,
    },
  };
}

export interface CacheEviction {
  readonly key: string;
  readonly bytes: number;
  readonly reason: "capacity";
}

interface CacheEntry<T> {
  readonly value: T;
  readonly bytes: number;
}

export class DeterministicByteCache<T> {
  readonly #entries = new Map<string, CacheEntry<T>>();
  readonly #evictions: CacheEviction[] = [];
  #usedBytes = 0;

  constructor(readonly maxBytes: number) {
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1) throw new RangeError("maxBytes must be a positive safe integer");
  }

  set(key: string, value: T, bytes: number): void {
    if (!Number.isSafeInteger(bytes) || bytes < 0 || bytes > this.maxBytes) throw new RangeError("entry bytes exceed cache limit");
    const previous = this.#entries.get(key);
    if (previous !== undefined) {
      this.#usedBytes -= previous.bytes;
      this.#entries.delete(key);
    }
    this.#entries.set(key, { value, bytes });
    this.#usedBytes += bytes;
    while (this.#usedBytes > this.maxBytes) {
      const oldest = this.#entries.entries().next().value as [string, CacheEntry<T>] | undefined;
      if (oldest === undefined) break;
      const [evictedKey, entry] = oldest;
      this.#entries.delete(evictedKey);
      this.#usedBytes -= entry.bytes;
      this.#evictions.push({ key: evictedKey, bytes: entry.bytes, reason: "capacity" });
    }
  }

  get(key: string): T | undefined {
    const entry = this.#entries.get(key);
    if (entry === undefined) return undefined;
    this.#entries.delete(key);
    this.#entries.set(key, entry);
    return entry.value;
  }

  snapshot() {
    return {
      maxBytes: this.maxBytes,
      usedBytes: this.#usedBytes,
      keys: [...this.#entries.keys()],
      evictions: this.#evictions.map((eviction) => ({ ...eviction })),
    };
  }
}
