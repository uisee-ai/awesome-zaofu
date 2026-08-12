import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const manifestPath = path.join(appRoot, "fixtures/golden-scene/provenance.json");
const roadImagePath = path.join(appRoot, "e2e/studio/fixtures/highway.png");

function readManifest(): Record<string, unknown> {
  return JSON.parse(readFileSync(manifestPath, "utf8")) as Record<string, unknown>;
}

test("golden fixture provides four synchronized cameras, history, navigation, and audit provenance", () => {
  const manifest = readManifest();
  const scene = manifest.scene as Record<string, unknown>;
  const cameras = scene.cameras as Array<Record<string, unknown>>;
  const history = scene.history as Record<string, unknown>;
  const provenance = manifest.provenance as Record<string, unknown>;
  const authorization = provenance.authorization as Record<string, unknown>;

  assert.equal(manifest.schemaVersion, "golden-scene-provenance.v1");
  assert.deepEqual(cameras.map(({ cameraId }) => cameraId), [0, 1, 2, 6]);
  assert.ok(cameras.every(({ frames }) => Array.isArray(frames) && frames.length === 4));
  assert.equal((history.positions as unknown[]).length, 16);
  assert.equal((history.rotations as unknown[]).length, 16);
  assert.match(scene.navigationInstruction as string, /\S/);
  assert.match(provenance.sourceId as string, /\S/);
  assert.match(authorization.reference as string, /\S/);
  assert.match(authorization.approvedFor as string, /internal demo/i);
});

test("golden fixture binds a shipped, non-synthetic road photograph by digest", () => {
  const manifest = readManifest();
  const provenance = manifest.provenance as Record<string, unknown>;
  const roadVisual = provenance.roadVisual as Record<string, unknown>;

  assert.doesNotMatch(provenance.sourceId as string, /synthetic/i);
  assert.doesNotMatch(provenance.sourceType as string, /synthetic/i);
  assert.equal(roadVisual.assetRef, "e2e/studio/fixtures/highway.png");
  assert.equal(roadVisual.contentType, "image/png");
  assert.equal(
    roadVisual.sourceUrl,
    "https://commons.wikimedia.org/wiki/File:Road_(24769469397).png",
  );
  assert.equal(roadVisual.license, "CC0-1.0");
  assert.match(roadVisual.sha256 as string, /^[0-9a-f]{64}$/);
  assert.equal(
    createHash("sha256").update(readFileSync(roadImagePath)).digest("hex"),
    roadVisual.sha256,
  );
});

test("backend provenance validation permits replayable metadata and rejects sensitive or unverifiable fixture content", () => {
  const validation = spawnSync(
    "python3",
    [
      "-c",
      [
        "import json",
        "from studio.fixtures.golden_scene import GoldenSceneProvenanceError, validate_golden_scene_provenance",
        `manifest = json.load(open(${JSON.stringify(manifestPath)}, encoding='utf-8'))`,
        "validate_golden_scene_provenance(manifest)",
        "unsafe = dict(manifest)",
        "unsafe['secret'] = 'must-not-be-committed'",
        "unsafe_base64 = dict(manifest)",
        "unsafe_base64['payload'] = 'A' * 256",
        "unsafe_wrapped_base64 = dict(manifest)",
        "unsafe_wrapped_base64['payload'] = 'A' * 128 + '\\n' + 'A' * 128",
        "missing_asset = json.loads(json.dumps(manifest))",
        "missing_asset['scene']['cameras'][0]['frames'][0]['assetRef'] = 'renders/camera-0/missing.png'",
        "mismatched_digest = json.loads(json.dumps(manifest))",
        "mismatched_digest['scene']['cameras'][0]['frames'][0]['sha256'] = '0' * 64",
        "for unsafe_fixture in (unsafe, unsafe_base64, unsafe_wrapped_base64, missing_asset, mismatched_digest):",
        "    try:",
        "        validate_golden_scene_provenance(unsafe_fixture)",
        "    except GoldenSceneProvenanceError:",
        "        continue",
        "    raise SystemExit(1)",
      ].join("\n"),
    ],
    {
      cwd: appRoot,
      encoding: "utf8",
      env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") },
    },
  );

  assert.equal(validation.status, 0, validation.stderr);
});

test("LiteLLM vision prompt carries explicit driving-analysis semantics without secrets or image bytes", () => {
  const validation = spawnSync("python3", ["-c", [
    "import json",
    "from studio.app import main",
    "messages = main.build_inference_messages(main._controlled_visual_input())",
    "content = messages[1]['content']",
    "text = content[0]['text']",
    "prompt = json.loads(text)",
    "assert 'autonomous-driving' in messages[0]['content'].lower()",
    "assert 'driving' in prompt['task'].lower()",
    "assert prompt['navigationInstruction']",
    "assert prompt['cameraIds'] == [0, 1, 2, 6]",
    "assert 'trajectory' in prompt['outputContract']",
    "assert 'base64' not in text.lower()",
    "assert not any(token in text.lower() for token in ('secret', 'api_key', 'authorization', 'token', 'password'))",
  ].join("\n")], { cwd: appRoot, encoding: "utf8", env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") } });
  assert.equal(validation.status, 0, validation.stderr);
});

test("LiteLLM retries one invalid HTTP 200 response but never retries an HTTP error", () => {
  const validation = spawnSync("python3", ["-c", [
    "import json, os, tempfile",
    "from urllib.error import HTTPError",
    "os.environ.update(LITELLM_BASE_URL='http://litellm.test', LITELLM_API_KEY='test-key', LITELLM_MODEL_NAME='alpamayo-vqa', ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR=tempfile.mkdtemp())",
    "from studio.app import main",
    "import studio.app.provider as provider_module",
    "class Response:",
    "    def __init__(self, body): self.body = body",
    "    def read(self): return self.body",
    "    def __enter__(self): return self",
    "    def __exit__(self, *args): return False",
    "calls = []",
    "payload = {'vqaAnswer': 'safe', 'chainOfCausation': 'clear lane', 'metaAction': 'MAINTAIN_LANE', 'trajectory': [{'timeSeconds': round(i * 0.1, 1), 'position': [i, 0, 0], 'rotation': [[1,0,0],[0,1,0],[0,0,1]]} for i in range(1, 65)]}",
    "valid = json.dumps({'model': 'alpamayo-vqa', 'choices': [{'message': {'content': json.dumps(payload)}}]}).encode()",
    "def transient(request, timeout):",
    "    calls.append((request, timeout))",
    "    return Response(b'{\\\"choices\\\":[{\\\"message\\\":{\\\"content\\\":\\\"\\\"}}]}' if len(calls) == 1 else valid)",
    "provider_module.urlopen = transient",
    "assert main.invoke_inference(main._controlled_visual_input())['responseSha256'] and len(calls) == 2",
    "calls.clear()",
    "def http_error(request, timeout):",
    "    calls.append((request, timeout))",
    "    raise HTTPError('http://litellm.test', 503, 'unavailable', None, None)",
    "provider_module.urlopen = http_error",
    "try: main.invoke_inference(main._controlled_visual_input())",
    "except Exception as error: assert getattr(error, 'status_code', None) == 502",
    "else: raise AssertionError('HTTP error must fail')",
    "assert len(calls) == 1",
  ].join("\n")], { cwd: appRoot, encoding: "utf8", env: { ...process.env, PYTHONPATH: path.join(appRoot, "backend") } });
  assert.equal(validation.status, 0, validation.stderr);
});
