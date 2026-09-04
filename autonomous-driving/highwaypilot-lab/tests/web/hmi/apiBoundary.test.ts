import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";


describe("same-port API boundary", () => {
  it("passes the authoritative HTTP Host/Origin/path/MIME matrix", () => {
    const output = execFileSync(
      "python",
      ["-m", "pytest", "tests/api", "-q"],
      { encoding: "utf8", env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" } },
    );

    expect(output).toMatch(/passed/);
  }, 120_000);
});
