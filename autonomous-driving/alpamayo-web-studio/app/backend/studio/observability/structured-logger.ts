export interface CorrelationFields {
  requestId: string;
  sceneId: string;
  runId: string;
}

export interface StructuredLogInput extends CorrelationFields {
  actor: "backend" | "worker";
  event: string;
  modelResponseDurationMs?: number;
  data?: Record<string, unknown>;
}

export interface StructuredLogEntry extends StructuredLogInput {
  timestamp: string;
}

const sensitiveKey = /authorization|secret|password|token|api.?key/i;
const imageKey = /image|img|photo|frame|camera|base64/i;
const imageDataUrl = /^data:image\/[^;]+;base64,/i;
const bareBase64 = /^[A-Za-z0-9+/_-]+={0,2}$/;

function isBase64Image(value: string, key?: string): boolean {
  return imageDataUrl.test(value) || (key !== undefined && imageKey.test(key) && bareBase64.test(value));
}

function redact(value: unknown, key?: string): unknown {
  if (key !== undefined && sensitiveKey.test(key)) return "[REDACTED]";
  if (typeof value === "string") {
    if (isBase64Image(value, key)) {
      return "[REDACTED_BASE64]";
    }
    return value;
  }
  if (Array.isArray(value)) return value.map((item) => redact(item, key));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [childKey, redact(childValue, childKey)]));
  }
  return value;
}

/** Stores safe, correlated records that can be forwarded to any JSON logger. */
export class InMemoryStructuredLogger {
  private readonly records: StructuredLogEntry[] = [];

  constructor(private readonly now: () => string = () => new Date().toISOString()) {}

  info(input: StructuredLogInput): void {
    this.records.push({
      ...input,
      ...(input.data === undefined ? {} : { data: redact(input.data) as Record<string, unknown> }),
      timestamp: this.now(),
    });
  }

  entries(): StructuredLogEntry[] {
    return structuredClone(this.records);
  }
}
