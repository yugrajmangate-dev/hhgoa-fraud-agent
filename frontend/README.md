# HHGoa Analyst Cockpit (React)

A second, static frontend for the HHGoa fraud-investigation benchmark. It is a read-only analyst
cockpit over the **committed** run artifacts, built with React, Vite and TypeScript. The Streamlit
app in `ui/app.py` is unchanged and deploys independently.

Customer responses, actions, approvals and suspicious activity reports (SARs) are **simulated**,
and the UI labels them that way everywhere they appear. There is no answer key, so nothing here is a
measured accuracy claim.

## What it shows

| Area | Content | Source |
|---|---|---|
| Case queue | All 20 cases: verdict, fraud probability, pattern, exposure, SAR, highest route. HHG-017 and HHG-014 are pinned as demo cases | `cases/HHG-*.json` |
| Investigation workspace | Trigger text, `as_of`, and KPIs for verdict, probability (initial → final), model risk score, approval route, evidence count and audit status | answer file, `trace.json`, audit log |
| Interactive graph | Customer, card, transactions, device profile, shared element, connected cards and prior closed cases. Click a node to see the evidence, scorer families and graph calls that name it | see "Graph relationships" |
| Evidence timeline | Every hash-chained audit event grouped by phase, with timestamps, provenance references and result hashes | `audit.jsonl`, `trace.envelopes` |
| Decision comparison | Initial vs final probability and actions, the recorded `what_changed` and `stop_reason`, routes with the policy engine's reasons, and the SAR decision | answer file, `trace.policy_fired` |
| Evidence Copilot | Chat panel in **grounded deterministic mode**: five quick questions answered from the selected case only | exported case bundle |

### Graph relationships

The graph draws only relationships recorded in the artifacts:
- the edges the agent wrote back to TigerGraph for the case (`FLAGGED`, `ON_CARD`, `INVOLVES`, `FIRST_FRAUD`, `CONNECTED_TO`, `NAMES_DEVICE`, `SIMILAR_TO`);
- the alert row (customer `OWNS` card, card `MADE` the flagged transaction);
- scorer family F4 (the flagged transaction's device profile);
- the policy's `shared_link` (the flagged card shares an element with other customers' cards).

Each group shows at most 24 nodes; the rest are counted in a "+N more" node and listed in the answer file.

### Evidence Copilot

The Copilot always computes the **grounded deterministic** answer first (`src/lib/copilot/deterministic.ts`): it is assembled from the selected case's answer file, trace and audit log. An optional server-side LLM can replace it with a written explanation; without one, nothing changes.

The panel shows which mode is active:
- **LLM unavailable — deterministic fallback**: no key on the server, a static host with no `/api/copilot`, or any error. Each fallback answer names the reason (no key, timeout, quota, rate limit, provider error, network, or an answer that failed validation).
- **LLM enabled — evidence-grounded explanation**: the server has a key and the model's answer passed validation.

Guarantees, enforced in code and covered by tests:
- **Read-only.** Case data is deep-frozen in the browser. The model returns text only, and the recorded verdict, probability and route are always appended from the case file, not from the model. Requests to change a decision ("mark as fraud", "change the verdict", "approve", "delete the SAR", …) are refused in the browser before any network call, and again on the server.
- **The key stays on the server.** `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` are read only by `server/copilot/` (the Vite dev/preview middleware, or the Vercel function in `api/copilot.ts`). Browser code only calls this app's own `/api/copilot`. `vite.config.ts` refuses to run if a key-like `VITE_*` variable is set, and a test checks that `src/` never reads server settings.
- **Only sanitized evidence is sent.** The server loads the case bundle itself (it never trusts context from the browser) and sends a whitelist of fields: trigger, decision, evidence claims and refs, actions, `what_changed`, `stop_reason`, SAR decision, scorer-family claims, graph-call refs, entity IDs and audit status. It sends no audit hashes, file paths, raw dataset rows, knowledge text, credentials or hostnames, and it aborts if the context matches a secret/URL/hostname pattern.
- **Validated or discarded.** The model must reply with JSON `{answer, citations}`. Every citation must be a real provenance ref or context field, the answer may not introduce decimal numbers that aren't in the evidence (such as a different probability), may not state a different verdict, and may not contain URLs. Anything else falls back to the deterministic answer. The provider call times out after 15 s (25 s end to end).

To enable it locally, create `frontend/.env.local` (git-ignored; see `.env.example`):

```bash
OPENROUTER_API_KEY=...        # your OpenRouter key; never use a VITE_ prefix
OPENROUTER_MODEL=...          # optional; defaults to openrouter/auto
```

Then restart `npm run dev` or `npm run preview`. The Vercel deployment is static and runs the Copilot in deterministic mode: `.vercelignore` excludes the opt-in `api/copilot.ts` function, which has not been verified on Vercel yet. To try LLM mode there, remove `api` from `.vercelignore` and set the two variables as Vercel environment variables (server-side only), then check that `/api/copilot` answers before relying on it. On Netlify or any static host there is no endpoint, so the Copilot stays in deterministic mode.

## Data

The app reads static JSON from `public/data/`:
- `index.json`: one summary row per case;
- `cases/HHG-0NN.json`: one bundle per case (answer, alert row, assessments, policy output, families, graph calls, filtered audit events, persistence result).

These files are generated from committed artifacts by `scripts/export_data.py` and are committed, so static hosts don't need Python. The script:
- reads only git-tracked `cases/HHG-*.json` and the committed `runs/cases/<run_id>/` bundle whose answer bytes equal the case file;
- verifies each audit hash chain with the project's own `hhg.audit.log.verify`;
- never reads `.env` or `data/raw/`, and drops knowledge-chunk text (quoted from the dataset README), keeping only chunk IDs, sections and scores;
- refuses to write any output containing a URL, `tgcloud`, `.env`, `TG_SECRET` or `TG_HOST`;
- is deterministic: the same commit produces byte-identical files.

Regenerate the data after a new pipeline run (from the project root, Git Bash):

```bash
.venv/Scripts/python frontend/scripts/export_data.py
```

## Run locally

Requires Node.js 20 or newer (tested with Node 24). From Git Bash:

```bash
cd /c/Users/yugra/source/hhgoa-fraud-agent/frontend
npm install
npm run dev          # development server at http://localhost:5173/
```

Open `http://localhost:5173/#HHG-017` or `#HHG-014` to go straight to a demo case.

## Build and preview

```bash
cd /c/Users/yugra/source/hhgoa-fraud-agent/frontend
npm run build        # type-check browser + server code, then production build into dist/
npm run preview      # serve dist/ (and /api/copilot) at http://localhost:4173/
npm test             # vitest: Copilot fallback, provider, refusal, error and key-exposure tests
```

`vite.config.ts` sets `base: "./"`, so `dist/` works from any static host or sub-path.

## Deploy

The build is a static site: `dist/` holds `index.html`, the assets and `data/`, and needs no environment variables. The optional LLM endpoint would need a server function (`api/copilot.ts`, opt-in); without it the app runs fully static in deterministic mode.

- **Vercel:** import the repository and set **Root Directory** to `frontend`. `vercel.json` sets the build command (`npm run build`) and output directory (`dist`).
- **Netlify:** set **Base directory** to `frontend`. `netlify.toml` sets `npm run build`, publish directory `dist` and Node 22.

The Streamlit deployment (`ui/app.py`, root `requirements.txt`, `.streamlit/`) is separate and unaffected.

## Layout

```
frontend/
  scripts/export_data.py      committed artifacts -> public/data/ (deterministic)
  public/data/                exported JSON (committed)
  src/App.tsx                 shell: queue + workspace, #HHG-0NN deep links
  src/components/             CaseQueue, WorkspaceHeader, CaseGraph, Timeline, DecisionComparison, Copilot, ui
  src/lib/data.ts             fetch + deep-freeze of case bundles
  src/lib/graph.ts            graph from recorded relationships only; deterministic lane layout
  src/lib/timeline.ts         audit events -> phases
  src/lib/copilot/            deterministic provider, hybrid provider (calls /api/copilot), shared guard and API types
  server/copilot/             server-only: env config, sanitized context, OpenRouter client, validation, Vite middleware
  api/copilot.ts              opt-in Vercel function for /api/copilot (excluded by .vercelignore)
  tests/                      vitest suites
  src/styles.css              dark navy/graphite theme
```

## Limitations

- It shows committed results; it does not run investigations or query TigerGraph.
- The audit status shows the hash-chain check done at export time and the read-back recorded when the run persisted. It is not a live TigerGraph check.
- Timestamps in the timeline are the run's wall clock in UTC.
