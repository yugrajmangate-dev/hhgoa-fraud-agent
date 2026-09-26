import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// base "./" keeps every asset and data path relative, so the build works from any static host or sub-path.
export default defineConfig({
  base: "./",
  plugins: [react()],
  build: { outDir: "dist", sourcemap: false },
});
