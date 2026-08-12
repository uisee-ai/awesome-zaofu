#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --web-url URL --evidence PATH" >&2
}

web_url=""
evidence_path=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --web-url) web_url="$2"; shift 2 ;;
    --evidence) evidence_path="$2"; shift 2 ;;
    *) usage; exit 64 ;;
  esac
done

if [[ -z "$web_url" || -z "$evidence_path" ]]; then
  usage
  exit 64
fi

health_url="${web_url%/}/api/health"
health="$(curl --fail --silent --show-error "$health_url")"
node --input-type=module - "$health" "$evidence_path" <<'NODE'
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const [healthJson, evidencePath] = process.argv.slice(2);
const health = JSON.parse(healthJson);
const serialized = JSON.stringify(health);
if (health.status !== "ready" || health.services?.backend !== "ready" || health.services?.worker !== "ready") {
  throw new Error("Studio health is not ready");
}
if (/svc\.cluster\.local|authorization|secret|data:image\/.+base64/i.test(serialized)) {
  throw new Error("Public health response contains protected data");
}
const evidence = {
  schemaVersion: "local-studio-health.v1",
  status: health.status,
  services: health.services,
  redaction: "[REDACTED]",
};
mkdirSync(path.dirname(evidencePath), { recursive: true });
writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`, "utf8");
NODE
