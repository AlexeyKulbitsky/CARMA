import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run build` writes into the Python package, so `carma serve` and the wheel ship the map.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: { outDir: "../carma/_ui", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
  test: { environment: "jsdom" },
});
