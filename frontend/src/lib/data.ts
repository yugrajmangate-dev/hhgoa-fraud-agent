import type { CaseBundle, IndexRow } from "../types";

// Static JSON exported from committed artifacts (see scripts/export_data.py). Paths are relative
// so the build works from any host or sub-path.
const BASE = `${import.meta.env.BASE_URL}data`;
const bundles = new Map<string, Promise<CaseBundle>>();

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}/${path}`, { cache: "no-cache" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadIndex(): Promise<IndexRow[]> {
  const data = await getJson<{ cases: IndexRow[] }>("index.json");
  return data.cases;
}

export function loadCase(caseId: string): Promise<CaseBundle> {
  if (!/^HHG-\d{3}$/.test(caseId)) return Promise.reject(new Error(`Unknown case id: ${caseId}`));
  let p = bundles.get(caseId);
  if (!p) {
    p = getJson<CaseBundle>(`cases/${caseId}.json`).then((b) => deepFreeze(b));
    p.catch(() => bundles.delete(caseId));
    bundles.set(caseId, p);
  }
  return p;
}

// Case data is read-only everywhere in the UI, including the Evidence Copilot.
function deepFreeze<T>(obj: T): T {
  if (obj && typeof obj === "object" && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    for (const v of Object.values(obj as Record<string, unknown>)) deepFreeze(v);
  }
  return obj;
}
