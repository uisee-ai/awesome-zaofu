function normalize(value: unknown): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("cannot digest a non-finite number");
    return value;
  }
  if (Array.isArray(value)) return value.map(normalize);
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return Object.fromEntries(
      Object.keys(record)
        .sort()
        .map((key) => {
          if (record[key] === undefined) throw new TypeError(`cannot digest undefined field ${key}`);
          return [key, normalize(record[key])];
        }),
    );
  }
  throw new TypeError(`cannot digest ${typeof value}`);
}

export function stableJson(value: unknown): string {
  return JSON.stringify(normalize(value));
}

export async function sha256(value: unknown): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new Error("Web Crypto SHA-256 is unavailable");
  const bytes = new TextEncoder().encode(typeof value === "string" ? value : stableJson(value));
  const result = await subtle.digest("SHA-256", bytes);
  const hexadecimal = [...new Uint8Array(result)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  return `sha256:${hexadecimal}`;
}
