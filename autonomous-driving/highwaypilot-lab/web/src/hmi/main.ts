import { App } from "./App.js";


export function bootstrapHmi(root: HTMLElement): App {
  if (!globalThis.document.querySelector<HTMLLinkElement>('link[data-highwaypilot-hmi="styles"]')) {
    const styles = globalThis.document.createElement("link");
    styles.rel = "stylesheet";
    styles.href = "/hmi.css";
    styles.dataset.highwaypilotHmi = "styles";
    globalThis.document.head.append(styles);
  }
  const app = new App(root);
  app.mount();
  return app;
}

const root = globalThis.document?.querySelector<HTMLElement>("#app");
if (root) bootstrapHmi(root);
