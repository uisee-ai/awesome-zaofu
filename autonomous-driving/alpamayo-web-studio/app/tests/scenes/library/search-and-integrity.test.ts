import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createServer } from "node:http";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  createSceneLibraryPage,
} from "../../../web/src/features/scene-library/scene-library-product.js";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

test("catalog searches name, Camera ID, tags, source, and an inclusive time window", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from datetime import datetime, timezone",
        "from studio.catalog import CatalogScene, SceneCatalog, SceneCatalogSearch",
        "catalog = SceneCatalog([",
        "    CatalogScene(scene_id='scene-1', name='Rainy right turn', camera_ids=(0, 2, 6), tags=('rain', 'urban'), source='fleet-a', created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), asset_ids=('a-1', 'a-2', 'a-3')),",
        "    CatalogScene(scene_id='scene-2', name='Sunny merge', camera_ids=(1, 3), tags=('sunny', 'highway'), source='fleet-b', created_at=datetime(2026, 8, 2, tzinfo=timezone.utc), asset_ids=('b-1', 'b-2')),",
        "])",
        "results = catalog.search(SceneCatalogSearch(name='right', camera_id=2, tags=('rain',), source='fleet-a', created_after=datetime(2026, 8, 1, tzinfo=timezone.utc), created_before=datetime(2026, 8, 1, tzinfo=timezone.utc)))",
        "assert [result.scene_id for result in results] == ['scene-1']",
        "assert catalog.search(SceneCatalogSearch(camera_id=3))[0].scene_id == 'scene-2'",
        "assert catalog.search(SceneCatalogSearch(tags=('urban', 'rain')))[0].scene_id == 'scene-1'",
        "assert catalog.search(SceneCatalogSearch(source='FLEET-B'))[0].scene_id == 'scene-2'",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(result.status, 0, result.stderr);
});

test("catalog reports complete and attention-needed data integrity with actionable issues", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "from datetime import datetime, timezone",
        "from studio.catalog import CatalogScene, SceneCatalog",
        "catalog = SceneCatalog([",
        "    CatalogScene(scene_id='complete', name='Complete scene', camera_ids=(0, 1), tags=('verified',), source='fixture', created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), asset_ids=('asset-0', 'asset-1')),",
        "    CatalogScene(scene_id='incomplete', name='Incomplete scene', camera_ids=(0, 0), tags=(), source='', created_at=datetime(2026, 8, 2, tzinfo=timezone.utc), asset_ids=('asset-0', 'asset-0')),",
        "])",
        "complete, incomplete = catalog.search()",
        "assert complete.integrity.state == 'complete'",
        "assert complete.integrity.issues == ()",
        "assert incomplete.integrity.state == 'needs_attention'",
        "assert {issue.code for issue in incomplete.integrity.issues} == {'DUPLICATE_CAMERA_ID', 'MISSING_SOURCE', 'DUPLICATE_ASSET_REFERENCE'}",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(result.status, 0, result.stderr);
});

test("scene library product entry calls the catalog API and exposes search results with integrity labels", async (t) => {
  const server = createServer((request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const result = spawnSync(
      "python3",
      [
        "-c",
        [
          "import json, sys",
          "from datetime import datetime, timezone",
          "from studio.catalog import CatalogScene, SceneCatalog, SceneCatalogApi",
          "catalog = SceneCatalog([",
          "    CatalogScene(scene_id='scene-1', name='Rainy right turn', camera_ids=(0, 2, 6), tags=('rain', 'urban'), source='fleet-a', created_at=datetime(2026, 8, 1, tzinfo=timezone.utc), asset_ids=('a-1', 'a-2', 'a-3')),",
          "    CatalogScene(scene_id='scene-2', name='Missing source', camera_ids=(1,), tags=(), source='', created_at=datetime(2026, 8, 2, tzinfo=timezone.utc), asset_ids=('b-1',)),",
          "])",
          "print(json.dumps(SceneCatalogApi(catalog).get(json.loads(sys.argv[1]))))",
        ].join("\n"),
        JSON.stringify(Object.fromEntries(url.searchParams.entries())),
      ],
      {
        cwd: appRoot,
        encoding: "utf8",
        env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
      },
    );
    assert.equal(result.status, 0, result.stderr);
    response.setHeader("content-type", "application/json");
    response.end(result.stdout);
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => server.close());
  const address = server.address();
  assert.ok(address && typeof address !== "string");

  const page = createSceneLibraryPage(`http://127.0.0.1:${address.port}`);
  await page.search({
    name: "rain",
    cameraId: 2,
    tags: ["rain"],
    source: "fleet-a",
    createdAfter: "2026-08-01T00:00:00.000Z",
    createdBefore: "2026-08-01T23:59:59.999Z",
  });

  assert.deepEqual(page.snapshot(), {
    phase: "ready",
    rows: [
      {
        sceneId: "scene-1",
        name: "Rainy right turn",
        cameraIds: [0, 2, 6],
        tags: ["rain", "urban"],
        source: "fleet-a",
        createdAt: "2026-08-01T00:00:00Z",
        integrityLabel: "数据完整",
        integrityIssues: [],
      },
    ],
  });

  await page.search();
  assert.equal(page.snapshot().phase, "ready");
  assert.deepEqual(page.snapshot().rows[1]?.integrityIssues, ["数据来源缺失"]);
  assert.equal(page.snapshot().rows[1]?.integrityLabel, "需要补充数据");
});
