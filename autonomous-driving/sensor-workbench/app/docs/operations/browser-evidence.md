# Browser evidence

`npm --prefix app run verify:evidence` is the release evidence collector for
`SWB-ASSEMBLY-005-R3`. It builds `app/dist`, serves that immutable output on a
loopback-only HTTP server, and reruns the synthetic, nuScenes, and OpenLane
Playwright specs with HAR and trace capture enabled.

The collector writes ignored runtime artifacts below
`app/artifacts/e2e/evidence/`. Each command receipt binds:

- the canonical task command and the stronger production-run invocation;
- the current Git `HEAD`, contract revision, and a digest of the built tree;
- the installed Playwright version and the launched Chromium version;
- the fixture tree digest before and after the browser run;
- observed start/finish/exit state, redacted HAR summary, Playwright result,
  command output, and digests of the retained browser traces.

The verifier recomputes every referenced digest, checks the current Git/build
and fixture bindings, opens the Playwright result, and rejects non-loopback
network activity, missing traces, stale values, failed/interrupted runs, or
artifact paths outside the evidence directory.

The receipt rendered inside the synthetic UI is a browser-session view used by
the upstream feature specs. The release claim is made only by the runtime files
above; source text or a UI fixture is never accepted as execution evidence.
