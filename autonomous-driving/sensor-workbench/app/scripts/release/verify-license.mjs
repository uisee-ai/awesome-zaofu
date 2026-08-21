import { readdir, readFile } from "node:fs/promises";
import { extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixtureRoot = join(appRoot, "tests", "fixtures", "synthetic");
const policy = await readFile(join(appRoot, "docs", "operations", "synthetic-demo-data-policy.md"), "utf8");
const forbiddenExtensions = new Set([".bin", ".jpg", ".jpeg", ".pcd", ".png", ".tar", ".zip"]);

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? listFiles(path) : [path];
  }));
  return nested.flat();
}

const files = await listFiles(fixtureRoot);
const rawFixtures = files.filter((path) => forbiddenExtensions.has(extname(path).toLowerCase()));
if (rawFixtures.length > 0) throw new Error(`synthetic fixtures contain raw-data extensions: ${rawFixtures.join(", ")}`);
for (const required of ["does not bundle nuScenes, OpenLane, or Waymo raw data", "non-commercial only"]) {
  if (!policy.includes(required)) throw new Error(`data policy is missing: ${required}`);
}

console.log(`license boundary verified: ${files.length} synthetic fixture files, no raw-data extensions`);
