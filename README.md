# TigerGraph × HHGoa 2026: Agentic Fraud Investigation

> **Status: working prototype, set up for the demo.** The pipeline has been built: loading
> the data, the TigerGraph Savanna graph, the MCP gateway, the policy engine, the agent, the
> UI and an independent verifier. All 20 answer files are committed in `cases/`. Customer
> replies, actions, approvals and SARs are **simulated**. This is a hackathon prototype,
> not a production system, and it makes no benchmark accuracy claim: there is no answer key.

Code: https://github.com/yugrajmangate-dev/hhgoa-fraud-agent

## How it works

Every graph read goes through `src/hhg/tools/gateway.py`. The gateway adds `as_of` to each
call, allows only listed tools and known entities, rejects any returned row later than
`as_of`, and records a provenance entry for the call. It then calls the official
`tigergraph-mcp` server, which is started with only `run_installed_query`, `add_nodes` and
`add_edges` enabled. Each run writes a hash-chained audit log, and each case written to the
graph is read back and compared.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design, [DATASET_NOTES.md](DATASET_NOTES.md)
for the dataset, and [TECHNICAL_BLOG_DRAFT.md](TECHNICAL_BLOG_DRAFT.md) for results and
limitations.

## Current state

| Check | Result | Source |
|---|---|---|
| Answer files | Exactly `cases/HHG-001.json` … `HHG-020.json` | `ls cases` |
| Run bundles (answer, audit log, trace) | 20, committed under `runs/cases/` | `git ls-files runs/cases` |
| Unit and integration tests | `Ran 77 tests … OK` | `python -m unittest discover -s tests` |
| Architecture checks | 51 passed, 0 failed | `python scripts/check_architecture.py` |
| Independent verifier | 20/20 on the last full run, including the TigerGraph read-back | Saved in `reports/phase2_verification.json` |
| Outcomes | 8 fraud · 11 uncertain · 1 legitimate | `cases/` |

The full verifier needs the Savanna workspace to be running. See
[RECORDING_STATUS.md](RECORDING_STATUS.md) for when it was last checked.

## Layout

| Path | Purpose |
|---|---|
| `src/hhg/etl/` | Builds staging files from `data/raw/`, with build checks (card_id coverage, expected counts) |
| `src/hhg/graph/` | TigerGraph admin: schema, loading jobs and installed GSQL queries (`gsql/`) |
| `src/hhg/tools/gateway.py` | The only way to read the graph: `as_of` injection, allowlist, leakage check, provenance |
| `src/hhg/agent/` | Deterministic investigation orchestrator, assessment and narrative templates |
| `src/hhg/policy/engine.py` | Policy rules R1–R10 and approval routes |
| `src/hhg/scoring/`, `src/hhg/detectors/` | Constrained, calibrated scorer and evidence features |
| `src/hhg/simulate/responder.py` | Deterministic **simulated** customer replies |
| `src/hhg/memory/` | Hashed TF-IDF case memory (zero weight in the score) |
| `src/hhg/audit/log.py` | Hash-chained audit log and its verifier |
| `src/hhg/casefile/validate.py` | Checks answer files against the README answer schema |
| `src/hhg/eval/backtest.py` | Closed-case backtest for the scorer |
| `src/hhg/cli.py` | Runs benchmark cases in `as_of` order |
| `ui/app.py` | Analyst UI (Streamlit). Presentation only: reads `cases/` and `runs/cases/` |
| `scripts/verify_cases.py` | Independent verifier. Writes `reports/phase2_verification.json` |
| `scripts/redact.py` | Hides secrets in command output |
| `scripts/inventory_dataset.py`, `validate_dataset.py`, `profile_dataset.py` | Dataset inventory, integrity checks and profiling |
| `scripts/check_architecture.py` | Checks `ARCHITECTURE.md` against the dataset README |
| `config/raw_dataset_manifest.json` | Pinned SHA-256 of the official files |
| `reports/` | Generated reports (aggregates only) and the verification report |
| `tests/` | Unit tests, plus integration tests that run when the dataset is present |
| `DEMO_SCRIPT.md`, `DEMO_CHECKLIST.md`, `RECORDING_STATUS.md` | Demo narration, pre-flight checks and recording status |
| `data/raw/` | **Official dataset, extracted unchanged.** Git-ignored; never modified |

## Setup

There are two sets of requirements:

- `requirements-dev.txt` is the full local environment (Python 3.11.9). It includes
  `pyTigerGraph`, `tigergraph-mcp`, `jsonschema` and `python-dotenv`, and is needed for the
  pipeline, the tests and the verifier.
- `requirements.txt` is only for the Streamlit Community Cloud UI. That deployment is
  read-only: it shows the committed cases and run bundles and doesn't connect to Savanna.

```bash
cd /c/Users/yugra/source/hhgoa-fraud-agent
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
```

Create `.env` in the project root. It is git-ignored, so never commit it or show it on
screen. It must contain your Savanna workspace's `TG_HOST` and `TG_SECRET`. Optional
settings: `TG_GRAPHNAME` (default `FraudGraph`), `TG_TGCLOUD`, `TG_RESTPP_PORT` and
`TG_GS_PORT` (default `443`).

Place the official dataset, unchanged, in `data/raw/`.

## Run the pipeline

```bash
export PYTHONPATH=src
.venv/Scripts/python scripts/validate_dataset.py      # dataset integrity against pinned hashes
.venv/Scripts/python -m hhg.etl.build                 # staging files + build checks
.venv/Scripts/python -m hhg.graph.admin all           # schema, loading jobs, install queries, verify counts
.venv/Scripts/python -m hhg.cli run HHG-017           # one case end to end through the official TigerGraph MCP
.venv/Scripts/python -m hhg.cli run all --llm off     # all 20 cases in as_of order -> cases/
.venv/Scripts/python scripts/verify_cases.py          # independent verifier (needs the workspace running)
.venv/Scripts/python -m unittest discover -s tests    # 77 tests
.venv/Scripts/streamlit run ui/app.py                 # analyst UI at http://localhost:8501 (HHG-017 recommended)
```

`scripts/verify_cases.py --no-graph` runs only the offline checks. Both modes overwrite
`reports/phase2_verification.json`. To restore the committed full-run report after an
offline run, use `git checkout -- reports/phase2_verification.json`.

Graph IDs and decisions are deterministic. Run IDs and latencies change on every run.

## Dataset scripts

```bash
python scripts/inventory_dataset.py      # file inventory      -> reports/dataset_inventory.json
python scripts/validate_dataset.py       # validation (~40 s)  -> reports/dataset_validation.json
python scripts/profile_dataset.py        # data dictionary (~50 s) -> reports/data_dictionary.md
python scripts/check_architecture.py     # design-document consistency checks
```

`validate_dataset.py` exit codes:

| Code | Meaning |
|---|---|
| `0` | No failed checks (warnings allowed) |
| `1` | At least one failed check |
| `2` | `data/raw/` is missing |
| `3` | Refused: output path is inside `data/raw/` |
| `4` | Refused: `--write-baseline` would overwrite an existing baseline (needs `--force`) |

The integrity baseline was pinned once, from the unchanged extract, with
`python scripts/validate_dataset.py --write-baseline`. Only re-pin it (`--force`) if the
organisers publish a new dataset version.

`DATASET_BLOCKER.md` is historical: the blocker it describes has been resolved.
