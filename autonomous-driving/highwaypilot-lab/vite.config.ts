import { defineConfig } from "vite";

export default defineConfig({
  root: "web",
  server: {
    host: "127.0.0.1",
  },
  build: {
    outDir: "../dist/web",
    emptyOutDir: true,
  },
});
