import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // Tests must never see a real key from the developer's shell.
    env: { OPENROUTER_API_KEY: "", OPENROUTER_MODEL: "" },
  },
});
