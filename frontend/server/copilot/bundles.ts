import { readFile } from "node:fs/promises";
import path from "node:path";
import type { CaseBundle } from "../../src/types";

/** Reads an exported case bundle from disk; the case id is validated before it touches the path. */
export function fileBundleLoader(dataDir: string) {
  return async (caseId: string): Promise<CaseBundle | null> => {
    if (!/^HHG-\d{3}$/.test(caseId)) return null;
    try {
      return JSON.parse(await readFile(path.join(dataDir, "cases", `${caseId}.json`), "utf-8")) as CaseBundle;
    } catch {
      return null;
    }
  };
}
