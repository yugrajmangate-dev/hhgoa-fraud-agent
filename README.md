# TigerGraph × HHGoa 2026: Agentic Fraud Investigation

> **Status: Phase 2 (design) complete, awaiting review.** No TigerGraph, policy, agent, UI,
> GraphRAG, or case-generation code exists yet. See [ARCHITECTURE.md](ARCHITECTURE.md) and
> [DATASET_NOTES.md](DATASET_NOTES.md).

## What exists now

| Path | Purpose |
|---|---|
| `ARCHITECTURE.md` | Phase 2 design: architecture, TigerGraph schema, queries, tool layer, GraphRAG, state machine, policy engine, case JSON schema, evaluation, demo, risks |
| `DATASET_NOTES.md` | Reconnaissance findings: files, columns, keys, time semantics, temporal-leakage rules, answer format, policy, open questions |
| `scripts/check_architecture.py` | Checks `ARCHITECTURE.md` against the dataset README (schema fields and enums, as_of on every query, routes, graph schema) |
| `DATASET_BLOCKER.md` | Historical. The dataset blocker, now resolved |
| `scripts/inventory_dataset.py` | Schema-agnostic, read-only inventory of `data/raw/` (standard library only) |
| `scripts/validate_dataset.py` | Validates `data/raw/` against its README and writes `reports/dataset_validation.json` |
| `scripts/profile_dataset.py` | Profiles every column and writes `reports/data_dictionary.md` and `reports/column_profile.json` |
| `config/raw_dataset_manifest.json` | Pinned SHA-256 of the official files; the validator fails if any raw file changes |
| `reports/` | Generated reconnaissance outputs (aggregates only) |
| `tests/` | Unit tests, plus integration tests that run when the dataset is present |
| `data/raw/` | **Official dataset, extracted unchanged.** Git-ignored; never modified |

## Phase 1 system (minimum working system)

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env            # fill in the Savanna workspace credentials (never commit .env)
export PYTHONPATH=src
.venv/Scripts/python -m hhg.etl.build            # staging files + build gates (card_id 100%, expected counts)
.venv/Scripts/python -m hhg.graph.admin all      # schema, loading jobs, install queries, verify counts
.venv/Scripts/python -m hhg.cli run HHG-017      # one end-to-end case via the official TigerGraph MCP
.venv/Scripts/streamlit run ui/app.py            # minimal analyst UI
```

Every graph read goes through `src/hhg/tools/gateway.py`, which injects `as_of`, allows only
listed tools and known entities, rejects any returned row after `as_of`, and records a
provenance envelope. The gateway then calls the official `tigergraph-mcp` server, started
limited to `run_installed_query`, `add_nodes` and `add_edges`.

## Setup

Requires Python 3.11+.

```bash
cd C:/Users/yugra/source/hhgoa-fraud-agent
python -m pip install -r requirements.txt
```

Place the official dataset, unchanged, in `C:\Users\yugra\source\hhgoa-fraud-agent\data\raw\`.

## Run

```bash
python scripts/inventory_dataset.py      # file inventory      -> reports/dataset_inventory.json
python scripts/validate_dataset.py       # validation (~40 s)  -> reports/dataset_validation.json
python scripts/profile_dataset.py        # data dictionary (~50 s) -> reports/data_dictionary.md
python scripts/check_architecture.py     # design-document consistency checks
python -m unittest discover -s tests -v  # all tests (~40 s with the dataset present)
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
