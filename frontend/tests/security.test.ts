import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");

function files(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).flatMap((name) => {
    const p = path.join(dir, name);
    return statSync(p).isDirectory() ? files(p) : [p];
  });
}

describe("API key never reaches browser code", () => {
  it("browser source (src/) never reads server secrets or non-BASE_URL env values", () => {
    for (const f of files(path.join(ROOT, "src"))) {
      const text = readFileSync(f, "utf-8");
      expect(text, f).not.toMatch(/OPENROUTER_API_KEY|OPENROUTER_MODEL|process\.env/);
      for (const m of text.matchAll(/import\.meta\.env\.(\w+)/g)) expect(m[1], f).toBe("BASE_URL");
    }
  });

  it("no .env file with a value is committed inside frontend/", () => {
    for (const f of files(ROOT).filter((p) => !p.includes("node_modules") && /[\\/]\.env/.test(p))) {
      const values = readFileSync(f, "utf-8")
        .split(/\r?\n/)
        .filter((l) => l.trim() && !l.trim().startsWith("#"))
        .map((l) => l.split("=").slice(1).join("=").trim());
      expect(values.every((v) => v === ""), f).toBe(true);
    }
  });

  it("the built bundle (if present) contains no server-side settings", () => {
    const dist = files(path.join(ROOT, "dist", "assets"));
    for (const f of dist) {
      const text = readFileSync(f, "utf-8");
      expect(text, f).not.toMatch(/OPENROUTER_API_KEY|OPENROUTER_MODEL|openrouter\.ai|Bearer /);
    }
  });
});
