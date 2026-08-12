export const DESKTOP_WORKBENCH_MIN_WIDTH = 1280;

export interface DesktopWorkbench {
  css: string;
  html: string;
}

export function createDesktopWorkbench(): DesktopWorkbench {
  return {
    css: `
      * { box-sizing: border-box; }
      body { margin: 0; min-width: ${DESKTOP_WORKBENCH_MIN_WIDTH}px; font-family: system-ui, sans-serif; }
      .desktop-workbench { min-width: ${DESKTOP_WORKBENCH_MIN_WIDTH}px; min-height: 100vh; display: grid; grid-template-rows: auto minmax(0, 1fr); background: #f6f8fb; color: #172033; }
      .desktop-workbench__header { align-items: center; background: #172033; color: #fff; display: flex; justify-content: space-between; min-height: 64px; padding: 12px 24px; }
      .desktop-workbench__body { display: grid; gap: 16px; grid-template-columns: 280px minmax(0, 1fr) 320px; min-height: 0; padding: 16px 24px; }
      .desktop-workbench__panel { background: #fff; border: 1px solid #d7deea; border-radius: 8px; min-width: 0; padding: 16px; }
      .desktop-workbench__viewport { display: grid; gap: 16px; grid-template-rows: auto minmax(240px, 1fr); }
      .desktop-workbench__canvas { align-items: center; background: linear-gradient(135deg, #253b5a, #486a8e); border-radius: 6px; color: #fff; display: flex; justify-content: center; min-height: 360px; }
      .desktop-workbench__toolbar { display: flex; gap: 8px; justify-content: flex-end; }
      .desktop-workbench button { background: #165dba; border: 0; border-radius: 4px; color: #fff; cursor: pointer; min-height: 36px; padding: 8px 12px; }
      .desktop-workbench button:focus-visible { outline: 3px solid #f4c542; outline-offset: 2px; }
      .desktop-workbench ul { margin: 12px 0 0; padding-left: 20px; }
    `,
    html: `
      <main class="desktop-workbench" aria-label="Alpamayo desktop workbench">
        <header class="desktop-workbench__header">
          <strong>Alpamayo Workbench</strong>
          <span data-testid="run-status" aria-live="polite">Ready to run</span>
        </header>
        <section class="desktop-workbench__body">
          <aside class="desktop-workbench__panel" data-testid="scene-library" aria-label="Scene library">
            <h2>Scenes</h2>
            <ul><li>Golden intersection</li><li>Rainy merge</li><li>Night crossing</li></ul>
            <div aria-label="Demo entries">
              <button type="button" data-demo="workbench">Workbench</button>
              <button type="button" data-demo="navigation">Navigation</button>
              <button type="button" data-demo="ablation">Ablation</button>
              <button type="button" data-demo="vqa">VQA</button>
              <button type="button" data-demo="auto-label">Auto label</button>
              <button type="button" data-demo="regression-judge">Regression judge</button>
            </div>
          </aside>
          <section class="desktop-workbench__panel desktop-workbench__viewport" data-testid="viewport" aria-label="Scene viewport">
            <div class="desktop-workbench__toolbar">
              <button type="button" data-testid="run-inference">Run inference</button>
            </div>
            <div class="desktop-workbench__canvas">1280px desktop scene viewport</div>
          </section>
          <aside class="desktop-workbench__panel" aria-label="Run details">
            <h2>Run details</h2>
            <p>Trajectory and safety checks appear here.</p>
            <p data-testid="run-id"></p>
            <pre data-testid="run-result"></pre>
          </aside>
        </section>
        <script>
          const params = new URLSearchParams(location.search);
          const sceneId = params.get("sceneVersionId");
          let demoId = params.get("demo") || "workbench";
          const status = document.querySelector('[data-testid="run-status"]');
          const runId = document.querySelector('[data-testid="run-id"]');
          const result = document.querySelector('[data-testid="run-result"]');
          document.querySelectorAll("[data-demo]").forEach((button) => button.addEventListener("click", () => {
            demoId = button.dataset.demo;
            status.textContent = "Selected " + demoId;
          }));
          document.querySelector('[data-testid="run-inference"]').addEventListener("click", async () => {
            if (!sceneId) { status.textContent = "Select a persisted scene first"; return; }
            status.textContent = "Inference running";
            const submitted = await fetch("/api/scenes/" + encodeURIComponent(sceneId) + "/runs", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ demoId }) }).then((response) => response.json());
            const saved = await fetch("/api/runs/" + encodeURIComponent(submitted.runId)).then((response) => response.json());
            runId.textContent = "Run " + submitted.runId;
            result.textContent = JSON.stringify(saved.result ?? saved);
            status.textContent = saved.status + " (" + submitted.runId + ")";
          });
        </script>
      </main>
    `,
  };
}
