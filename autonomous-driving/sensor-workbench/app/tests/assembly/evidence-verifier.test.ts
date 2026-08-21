import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { afterEach, describe, expect, it } from "vitest";

const temporaryDirectories: string[] = [];
const appRoot = fileURLToPath(new URL("../..", import.meta.url));

afterEach(async () => {
  await Promise.all(temporaryDirectories.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

describe("browser evidence verifier", () => {
  it("rejects a source-like fixed receipt that has no captured browser artifacts", async () => {
    const evidenceRoot = await mkdtemp(join(tmpdir(), "swb-forged-evidence-"));
    temporaryDirectories.push(evidenceRoot);
    await writeFile(join(evidenceRoot, "SWB-ASSEMBLY-005-R3-CMD-02.receipt.json"), JSON.stringify({
      schema_version: "browser-evidence-receipt.v1",
      receipt_id: "receipt-fixed-in-source",
      command_id: "SWB-ASSEMBLY-005-R3-CMD-02",
      canonical_command: "npm --prefix app run e2e:synthetic",
      contract_revision: "contract-r89699449158a",
      source_commit: "0000000000000000000000000000000000000000",
      production_build_digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      runner: { name: "@playwright/test", version: "1.62.1" },
      browser: { name: "chromium", version: "pinned" },
      fixture: {
        kind: "synthetic",
        digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      },
      started_at: "2026-08-04T08:00:00.000Z",
      finished_at: "2026-08-04T08:00:01.000Z",
      exit_status: "passed",
      exit_code: 0,
      data_root_before_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      data_root_after_digest: "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      artifacts: [{
        kind: "browser-trace-digest",
        path: "missing-trace.zip",
        digest: "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        redacted: true,
      }],
      network: { loopback_only: true, non_loopback_requests: [] },
      result: "passed",
    }));

    const result = spawnSync(
      process.execPath,
      ["scripts/release/verify-evidence.mjs", "--validate-only", evidenceRoot],
      { cwd: appRoot, encoding: "utf8" },
    );

    expect(result.status).not.toBe(0);
    expect(`${result.stdout}\n${result.stderr}`).toMatch(/source commit|artifact/i);
  });
});
