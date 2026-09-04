// Vitest runs with `web/` as its root. Keep the contract-owned tests in
// `tests/web/hmi/`, and import them here so the literal VC-HMI filter discovers
// and executes them instead of succeeding through `--passWithNoTests`.
import "../../../../../../tests/web/hmi/apiBoundary.test.js";
import "../../../../../../tests/web/hmi/appShell.test.js";
import "../../../../../../tests/web/hmi/highwayScene.test.js";
import "../../../../../../tests/web/hmi/hmiState.test.js";
