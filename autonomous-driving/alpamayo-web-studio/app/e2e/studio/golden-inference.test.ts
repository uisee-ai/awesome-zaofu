import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

test("authorized golden asset references become PNG image_url content for Alpamayo VQA", () => {
  const result = spawnSync(
    "python3",
    [
      "-c",
      [
        "import json",
        "import os, tempfile",
        "from base64 import b64decode",
        "from hashlib import sha256",
        "os.environ.update(LITELLM_BASE_URL='http://litellm.test', LITELLM_API_KEY='test-key', LITELLM_MODEL_NAME='alpamayo-vqa', ALPAMAYO_STUDIO_PROVIDER_ARTIFACT_DIR=tempfile.mkdtemp())",
        "from studio.app import main",
        "import studio.app.provider as provider_module",
        "fixture = json.load(open('fixtures/golden-release/authorized-first-inference.json', encoding='utf-8'))",
        "scene = fixture['eligibleSamples'][0]['scene']",
        "captured = {}",
        "payload = {'vqaAnswer': 'Maintain lane', 'chainOfCausation': 'The lane is clear', 'metaAction': 'MAINTAIN_LANE', 'trajectory': [{'timeSeconds': round(i * 0.1, 1), 'position': [i, 0, 0], 'rotation': [[1,0,0],[0,1,0],[0,0,1]]} for i in range(1, 65)]}",
        "class Response:",
        "    def read(self): return json.dumps({'model': 'alpamayo-vqa', 'choices': [{'message': {'content': json.dumps(payload)}}]}).encode()",
        "    def __enter__(self): return self",
        "    def __exit__(self, *args): return False",
        "def provider(request, timeout):",
        "    captured['body'] = json.loads(request.data.decode('utf-8'))",
        "    captured['timeout'] = timeout",
        "    return Response()",
        "provider_module.urlopen = provider",
        "result = main.invoke_inference(scene)",
        "content = captured['body']['messages'][1]['content']",
        "images = [part for part in content if part['type'] == 'image_url']",
        "assert len(images) == 1",
        "assert all(part['image_url']['url'].startswith('data:image/png;base64,iVBORw0KGgo') for part in images)",
        "expected = sha256(open('e2e/studio/fixtures/highway.png', 'rb').read()).hexdigest()",
        "assert {sha256(b64decode(part['image_url']['url'].split(',', 1)[1])).hexdigest() for part in images} == {expected}",
        "assert captured['body']['model'] == 'alpamayo-vqa'",
        "assert len(captured['body']['messages']) == 2",
        "assert captured['body']['messages'][0]['role'] == 'system'",
        "assert captured['body']['messages'][1]['role'] == 'user'",
        "assert [part['type'] for part in content] == ['text', 'image_url']",
        "assert captured['body']['max_tokens'] == 2048",
        "assert captured['body']['temperature'] == 0.2",
        "assert captured['timeout'] == 300",
        "assert result['provider'] == 'litellm' and result['responseSha256']",
        "assert len(result['trajectory']) == 64 and result['metaAction'] == 'MAINTAIN_LANE'",
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
