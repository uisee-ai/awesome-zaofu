import { realpath } from "node:fs/promises";
import { isAbsolute, relative, resolve } from "node:path";

export type BoundaryViolationCode =
  | "path_traversal"
  | "encoded_path_traversal"
  | "symlink_escape"
  | "invalid_host"
  | "invalid_origin"
  | "csrf_rejected"
  | "non_loopback_request";

export interface RedactedBoundaryReceipt {
  readonly code: BoundaryViolationCode;
  readonly target: "[redacted]";
  readonly absolutePathsIncluded: false;
}

export class BoundaryViolation extends Error {
  readonly name = "BoundaryViolation";
  readonly receipt: RedactedBoundaryReceipt;

  constructor(readonly code: BoundaryViolationCode) {
    super(`data boundary rejected request: ${code}`);
    this.receipt = { code, target: "[redacted]", absolutePathsIncluded: false };
  }
}

function isContained(parent: string, candidate: string): boolean {
  const offset = relative(parent, candidate);
  return offset === "" || (!offset.startsWith("..") && !isAbsolute(offset));
}

function decodedAssetPath(rawPath: string): string {
  let decoded: string;
  try {
    decoded = decodeURIComponent(rawPath);
  } catch {
    throw new BoundaryViolation("encoded_path_traversal");
  }

  const segments = decoded.split(/[\\/]/);
  if (decoded !== rawPath && (segments.includes("..") || isAbsolute(decoded))) {
    throw new BoundaryViolation("encoded_path_traversal");
  }
  if (segments.includes("..") || isAbsolute(decoded)) throw new BoundaryViolation("path_traversal");
  return decoded;
}

export async function resolveDataAsset(dataRoot: string, rawPath: string): Promise<string> {
  const decoded = decodedAssetPath(rawPath);
  const canonicalRoot = await realpath(dataRoot);
  const lexicalTarget = resolve(canonicalRoot, decoded);
  if (!isContained(canonicalRoot, lexicalTarget)) throw new BoundaryViolation("path_traversal");

  const canonicalTarget = await realpath(lexicalTarget);
  if (!isContained(canonicalRoot, canonicalTarget)) throw new BoundaryViolation("symlink_escape");
  return canonicalTarget;
}

function hostName(host: string): string {
  if (host.startsWith("[")) return host.slice(1, host.indexOf("]"));
  return host.split(":", 1)[0] ?? "";
}

function isLoopbackHost(host: string): boolean {
  const normalized = host.replace(/^\[|\]$/g, "").toLowerCase();
  return normalized === "localhost" || normalized === "127.0.0.1" || normalized === "::1";
}

export interface LocalRequest {
  readonly host: string;
  readonly origin?: string;
  readonly method: string;
  readonly csrfToken?: string;
  readonly expectedCsrfToken?: string;
}

export interface LocalRequestAuthorization {
  readonly loopbackOnly: true;
  readonly sameOrigin: boolean;
  readonly writeAuthorized: boolean;
}

export function authorizeLocalRequest(request: LocalRequest): LocalRequestAuthorization {
  const requestHost = hostName(request.host);
  if (!isLoopbackHost(requestHost)) throw new BoundaryViolation("invalid_host");

  let sameOrigin = true;
  if (request.origin !== undefined) {
    let origin: URL;
    try {
      origin = new URL(request.origin);
    } catch {
      throw new BoundaryViolation("invalid_origin");
    }
    if (!isLoopbackHost(origin.hostname)) throw new BoundaryViolation("invalid_origin");
    sameOrigin = origin.host === request.host;
    if (!sameOrigin) throw new BoundaryViolation("invalid_origin");
  }

  const write = !["GET", "HEAD", "OPTIONS"].includes(request.method.toUpperCase());
  if (
    write &&
    (!sameOrigin ||
      request.csrfToken === undefined ||
      request.expectedCsrfToken === undefined ||
      request.csrfToken !== request.expectedCsrfToken)
  ) {
    throw new BoundaryViolation("csrf_rejected");
  }
  return { loopbackOnly: true, sameOrigin, writeAuthorized: write };
}

export function assertLoopbackUrl(input: string): string {
  let url: URL;
  try {
    url = new URL(input);
  } catch {
    throw new BoundaryViolation("non_loopback_request");
  }
  if (!isLoopbackHost(url.hostname)) throw new BoundaryViolation("non_loopback_request");
  return input;
}
