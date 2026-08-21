import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { measureCoordinateFixture } from "../../src/spikes/coordinates.mjs";

const appRoot = resolve(import.meta.dirname, "../..");
const fixturePath = resolve(appRoot, "tests/fixtures/golden/coordinate-fixture.v1.json");
const digestPath = resolve(appRoot, "tests/fixtures/golden/coordinate-fixture.v1.sha256");
const reportPath = resolve(appRoot, "artifacts/spikes/coordinate-report.json");

const fixtureBytes = readFileSync(fixturePath);
const actualDigest = createHash("sha256").update(fixtureBytes).digest("hex");
const digestLine = readFileSync(digestPath, "utf8");
const expectedDigestLine = `${actualDigest}  coordinate-fixture.v1.json\n`;
if (digestLine !== expectedDigestLine) {
  throw new Error(`coordinate fixture digest mismatch: expected sidecar ${digestLine.trim()}, actual ${actualDigest}`);
}

const fixture = JSON.parse(fixtureBytes.toString("utf8"));
const report = measureCoordinateFixture(fixture, actualDigest);
mkdirSync(resolve(appRoot, "artifacts/spikes"), { recursive: true });
writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");

console.log(`spike:coordinates passed: ${reportPath}`);
console.log(
  `raw residuals — nuScenes ${report.measurements.nuscenes.translation_residual_m}m/${report.measurements.nuscenes.projection_residual_px}px; ` +
    `OpenLane ${report.measurements.openlane.translation_residual_m}m/${report.measurements.openlane.projection_residual_px}px`,
);
console.log("1e-5m and 0.5px remain UNVERIFIED candidates; they were not used as pass/fail gates");
