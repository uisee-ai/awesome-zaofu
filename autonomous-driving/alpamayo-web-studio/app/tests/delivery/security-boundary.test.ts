import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appRoot = new URL("../..", import.meta.url);

test("the public FastAPI boundary redacts sensitive values and does not expose internal upstream addresses", () => {
  const main = readFileSync(new URL("backend/studio/app/main.py", appRoot), "utf8");
  const provider = readFileSync(new URL("backend/studio/app/provider.py", appRoot), "utf8");
  const verifier = readFileSync(new URL("deploy/scripts/verify-local-studio.sh", appRoot), "utf8");

  assert.match(main, /def public_value/);
  assert.match(main, /\[REDACTED\]/);
  assert.match(main, /\[REDACTED_BASE64\]/);
  assert.doesNotMatch(main, /svc\.cluster\.local/);
  assert.doesNotMatch(main, /Authorization:\s*Bearer/);
  assert.doesNotMatch(main, /print\(/);
  assert.match(provider, /responseSha256/);
  assert.match(provider, /os\.chmod\(temporary, 0o600\)/);
  assert.match(verifier, /Public health response contains protected data/);
});
