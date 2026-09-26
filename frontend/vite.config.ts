import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { copilotApiPlugin } from "./server/copilot/vitePlugin";
import { readServerConfig } from "./server/copilot/handler";

// Only VITE_* variables are ever exposed to browser code (Vite's default envPrefix). The optional
// OPENROUTER_* settings are read here, in Node, and handed only to the server-side /api/copilot
// middleware. Refuse to start if a secret-looking value is placed in a VITE_* variable.
function assertNoClientSecrets(clientEnv: Record<string, string>) {
  const bad = Object.keys(clientEnv).filter((k) => /KEY|SECRET|TOKEN|PASSWORD|OPENROUTER/i.test(k));
  if (bad.length) {
    throw new Error(`Refusing to build: ${bad.join(", ")} would be exposed to the browser. Use OPENROUTER_API_KEY (server-only) instead.`);
  }
}

// base "./" keeps every asset and data path relative, so the build works from any static host or sub-path.
export default defineConfig(({ mode }) => {
  const root = process.cwd();
  assertNoClientSecrets({ ...loadEnv(mode, root, "VITE_"), ...Object.fromEntries(Object.entries(process.env).filter(([k]) => k.startsWith("VITE_")) as [string, string][]) });
  const fileEnv = loadEnv(mode, root, "OPENROUTER_");
  const serverConfig = readServerConfig({
    OPENROUTER_API_KEY: process.env.OPENROUTER_API_KEY ?? fileEnv.OPENROUTER_API_KEY,
    OPENROUTER_MODEL: process.env.OPENROUTER_MODEL ?? fileEnv.OPENROUTER_MODEL,
  });
  return {
    base: "./",
    plugins: [react(), copilotApiPlugin(serverConfig, path.join(root, "public", "data"))],
    build: { outDir: "dist", sourcemap: false },
  };
});
