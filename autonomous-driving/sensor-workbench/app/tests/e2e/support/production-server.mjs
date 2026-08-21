import { createReadStream } from "node:fs";
import { access, readFile, stat } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const appRoot = fileURLToPath(new URL("../../..", import.meta.url));
const distRoot = join(appRoot, "dist");
const port = Number.parseInt(process.env.SWB_EVIDENCE_PORT ?? "4273", 10);
const sourceCommit = process.env.SWB_SOURCE_COMMIT;
const productionBuildDigest = process.env.SWB_PRODUCTION_BUILD_DIGEST;
const runnerVersion = process.env.SWB_RUNNER_VERSION;
if (!sourceCommit || !productionBuildDigest || !runnerVersion) {
  throw new Error("production evidence metadata is required");
}
const contentTypes = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".map", "application/json; charset=utf-8"],
  [".svg", "image/svg+xml"],
]);

await access(join(distRoot, "index.html"));

const server = createServer(async (request, response) => {
  try {
    const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://127.0.0.1").pathname);
    const relative = normalize(pathname).replace(/^[/\\]+/, "");
    let filePath = join(distRoot, relative);
    if (filePath !== distRoot && !filePath.startsWith(`${distRoot}/`)) throw new Error("path escapes production root");
    const metadata = await stat(filePath).catch(() => null);
    if (!metadata?.isFile()) filePath = join(distRoot, "index.html");
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-type": contentTypes.get(extname(filePath)) ?? "application/octet-stream",
      "x-content-type-options": "nosniff",
    });
    if (filePath === join(distRoot, "index.html")) {
      const html = await readFile(filePath, "utf8");
      const metadata = [
        `<meta name="swb-source-commit" content="${sourceCommit}">`,
        `<meta name="swb-production-build-digest" content="${productionBuildDigest}">`,
        `<meta name="swb-runner-version" content="${runnerVersion}">`,
      ].join("");
      response.end(html.replace("</head>", `${metadata}</head>`));
      return;
    }
    createReadStream(filePath).pipe(response);
  } catch (error) {
    response.writeHead(404, { "content-type": "text/plain; charset=utf-8" });
    response.end(error instanceof Error ? error.message : "not found");
  }
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`production evidence server listening on http://127.0.0.1:${port}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.close(() => process.exit(0)));
}
