# DATASET_BLOCKER — TigerGraph × HHGoa 2026 Agentic Fraud Investigation

| | |
|---|---|
| **Status** | **RESOLVED 2026-09-24.** The official dataset was received and extracted unchanged into `data/raw/`; see [DATASET_NOTES.md](DATASET_NOTES.md). This document is kept for history. Where it guesses at structure, DATASET_NOTES.md supersedes it |
| **Raised** | 2026-09-24 |
| **Blocks** | Phase 1 (dataset reconnaissance) and every phase after it |
| **Dataset location** | `C:\Users\yugra\source\hhgoa-fraud-agent\data\raw\` (`data/raw/`, relative to the project root) |
| **Unblocked when** | The official dataset (including its README) is extracted unchanged into `data/raw/` and `python scripts/inventory_dataset.py` exits `0` |

---

## 1. Why implementation is blocked

The challenge brief says the dataset README is **authoritative**: column meanings, the
benchmark case format, and the required answer format must come from it. Guessing them
is forbidden.

The official HHGoa dataset is not available to this project:

- It is not on this machine. On 2026-09-24 we searched the working directory, Downloads,
  Desktop, OneDrive, Documents, the home directory, and all mounted drives by filename
  (`*hhg*`, `*tigergraph*`, `*fraud*`, `*ieee*`, `*typolog*`, `*closed_case*`,
  `*benchmark*`, `transactions*.csv`) and by content (`HHG-0NN`, `HHGoa`, `247pmstudio`).
  Nothing matched.
- There is no public download. Public repositories from other participating teams keep
  the data in a git-ignored `data/` directory and publish no download URL, so the
  dataset appears to go only to registered participants.
- Copies of the dataset README or files held by other teams **must not be used**. They
  are not authoritative, and using them would compromise the originality of this
  submission.

Nearly every graded component depends on facts that only the dataset can provide: the
graph schema, the queries, the policy rules, temporal safety, the case JSON, and the
evaluation. Building any of them now would mean inventing schemas, labels, or formats.

## 2. Required files

These come from the challenge brief. The **file names and formats are unknown**, so each
item describes content, not a file name. All of them are required.

| # | Required content (as described in the brief) | Needed for |
|---|---|---|
| R1 | **Dataset README**, authoritative | Everything |
| R2 | **Transactions**, ~590,000 rows, six months, IEEE-CIS based, **no direct Is Fraud label** | Graph core, traversal, patterns |
| R3 | **Customers**, ~13,500 | Customer vertices, entity resolution |
| R4 | **Device records** | Device-sharing and linkage analysis |
| R5 | **Connection records** (network / connection identity signals) | Connection-sharing analysis |
| R6 | **Card / payment-instrument data**, whether a separate file or columns in R2 (unknown) | Card vertices |
| R7 | **Closed investigations** from the first four months | Case memory, GraphRAG, calibration |
| R8 | **20 benchmark cases** from the final two months (HHG-001 … HHG-020) | Investigation triggers |
| R9 | **Bank fraud policy** | Deterministic policy engine, approval routes, evidence-request permissions |
| R10 | **Five documented fraud patterns** | Pattern detectors, typology retrieval |
| R11 | **Regulatory references** | SAR requirements, GraphRAG corpus |
| R12 | **Expected answer format** for `cases/HHG-001.json` … `HHG-020.json` (a schema, example, or template, if one is supplied) | Answer files |
| R13 | **Scoring / evaluation description**, if any, for "investigation accuracy" and "next-best action" | Evaluation harness |
| R14 | **Staged "additional evidence"**, if supplied: evidence released only after a request, so that the "before" and "after additional evidence" approval routes can differ | Evidence-request workflow |

R12 to R14 might be sections inside R1 rather than separate files. Reconnaissance must confirm this.

## 3. Decisions that cannot be made without the dataset README

| # | Decision | Why it is blocked |
|---|---|---|
| D1 | TigerGraph vertex and edge types, primary keys, attributes | Entity files and join keys are unknown |
| D2 | How transactions link to customers, cards, devices, connections | IEEE-CIS has no native customer ID, so the HHGoa link is dataset-specific |
| D3 | Timestamp semantics | IEEE-CIS `TransactionDT` is a time delta from an **undisclosed** reference. Whether HHGoa supplies an absolute calendar, which timezone it uses, and how the time fields in other files are defined are all unknown |
| D4 | What "investigation time" means for each benchmark case | Needed for the "no future information" rule |
| D5 | How closed cases are dated (opened, closed, or event time) and which date governs leakage filtering | Defines the closed-case memory cutoff |
| D6 | Closed-case outcome and label vocabulary | Must not be invented. No raw fraud label exists |
| D7 | Definitions and detection criteria for the five fraud patterns | Pattern detectors must implement documented definitions, not assumed ones |
| D8 | Policy thresholds, approval tiers, roles, allowed actions, and the conditions under which evidence requests are permitted | Core of the deterministic policy engine |
| D9 | SAR trigger conditions and required SAR fields | Regulatory references define them |
| D10 | The exact answer-file JSON structure: field names, enums, required and optional fields, nesting | The brief lists required content, but the format is authoritative only in the dataset/challenge materials |
| D11 | How the "before" and "after additional evidence" states are represented and what evidence is revealed | Drives the agent state machine |
| D12 | How the cases must be written to TigerGraph (a required representation, or ours to design) | Case vertex schema |
| D13 | Evaluation metric for accuracy and next-best action | Local evaluation harness design |
| D14 | Which engineered columns (IEEE-CIS `C*`, `D*`, `M*`, `V*`, `id_*`) are kept, renamed, or documented | Column semantics must come from the README |
| D15 | The overall design (architecture, schema, query list, state machine, policy engine, case schema, evaluation strategy) | All ten design sections depend on D1–D14 |

## 4. Expected dataset directory structure (**PROVISIONAL**)

> **PROVISIONAL.** This layout is only where we *intend* to place the files. It is not a
> guess at official file names. The official archive's own layout will be kept exactly as
> delivered under `data/raw/`, and this section will be replaced after reconnaissance.

```text
data/                         # git-ignored in full (only data/.gitkeep is tracked)
├── .gitkeep
└── raw/                      # C:\Users\yugra\source\hhgoa-fraud-agent\data\raw\
                              # official archive extracted UNCHANGED (read-only by convention)
    ├── <README>              # R1 — authoritative
    ├── <transactions>        # R2
    ├── <customers>           # R3
    ├── <devices>             # R4
    ├── <connections>         # R5
    ├── <cards?>              # R6 — may not be a separate file
    ├── <closed cases>        # R7
    ├── <benchmark cases>     # R8 — 20 cases
    ├── <policy>              # R9
    ├── <fraud patterns>      # R10 — 5 patterns
    ├── <regulatory refs>     # R11
    └── <answer format?>      # R12 — may be a README section
```

Derived artifacts go in `reports/` at the project root (for example
`reports/dataset_inventory.json`). That folder is outside `data/raw/` and also git-ignored.
`data/raw/` is never modified. The inventory script refuses (exit `3`) any output path
inside its input directory.

```text
hhgoa-fraud-agent/
├── data/raw/                 # input: official dataset, read-only
└── reports/                  # output: derived artifacts, never inside data/raw/
```

## 5. Validation checklist for the official dataset

**A. Provenance and integrity**
- [ ] The source is official (organiser link or participant portal) and is recorded in `DATASET_NOTES.md`
- [ ] The archive is extracted unchanged into `C:\Users\yugra\source\hhgoa-fraud-agent\data\raw\`
- [ ] `python scripts/inventory_dataset.py` (default input `data/raw/`) exits `0` and writes `reports/dataset_inventory.json` (SHA-256, size, and CSV header/row count per file)
- [ ] The inventory is reviewed and each file is mapped to R1–R14. Missing items are listed

**B. README (read completely, before any design)**
- [ ] Every file described in the README is present, and every present file is described
- [ ] Column meanings, types, units, and null conventions are recorded
- [ ] Time fields, timezone, and reference epoch are recorded (D3)
- [ ] Investigation time is defined for benchmark cases (D4)
- [ ] The answer format is located and copied verbatim into `DATASET_NOTES.md` (D10)
- [ ] The evaluation and scoring description is located (D13)

**C. Counts versus the brief** (report discrepancies; do not "fix" them)
- [ ] Transactions ≈ 590,000
- [ ] Customers ≈ 13,500
- [ ] Six-month span. Closed investigations fall in months 1–4, benchmark cases in months 5–6
- [ ] Exactly 20 benchmark cases, IDs HHG-001 … HHG-020
- [ ] Exactly five documented fraud patterns
- [ ] No direct Is Fraud column on raw transactions. **Record any column that could leak a label.**

**D. Keys and joins**
- [ ] Primary keys are unique and non-null in every entity file
- [ ] Every foreign key resolves, and the orphan rate is measured and recorded
- [ ] Every entity referenced by a benchmark case exists in the entity files

**E. Temporal safety**
- [ ] Each benchmark case's investigation time is parseable and falls in months 5–6
- [ ] Closed-case dates are all before the benchmark window, or any overlap is documented
- [ ] Per case: records after the investigation time are counted, so the leakage filter can be tested against real numbers

**F. Data quality**
- [ ] Null rate per column, duplicate rows, type-coercion failures, and out-of-range values are recorded
- [ ] Known IEEE-CIS quirks are checked: anonymised `id_*`/`V*` columns, masked emails and addresses, and the relative `TransactionDT`

## 6. Safe work that can proceed without the dataset

This work is **generic infrastructure**. It encodes no schema, rule, label, or format.

- **Environment:** choose TigerGraph Savanna or Community Edition. For Community Edition,
  install Docker Desktop or a WSL distribution (none is installed today). Verify
  connectivity with a trivial, schema-free call such as the server version.
- **TigerGraph MCP / tool layer:** install and test that the server connects. Do not define graph-specific tools yet.
- **Dataset tooling:** the schema-agnostic inventory script (`scripts/inventory_dataset.py`, reads `data/raw/` and writes `reports/`) and its tests (**done**).
- **Engineering harness:** project layout, linting, a test runner, and CI skeleton.
- **Generic safety primitives:** an append-only audit log, a provenance envelope
  (source, query, timestamp), a simulated-action sandbox that is guaranteed side-effect-free,
  and an approval-gate *mechanism* with no rules in it. All must be domain-neutral.
- **LLM guardrail harness:** tool allow-listing and a "no graph fact without tool
  provenance" check. The generic mechanics only.
- **UI shell:** layout and navigation with **no** case fields or sample data.
- **Deliverable outlines:** skeletons for the README, blog, demo storyboard, and social
  posts, with no results, numbers, or case content.

## 7. Work that must NOT proceed until the dataset arrives

- TigerGraph schema, loading jobs, and ingestion code
- GSQL queries, graph-algorithm configuration, or pattern detectors
- Policy rules, thresholds, approval tiers, SAR triggers
- Temporal cutoff logic tied to specific fields (D3–D5)
- Case JSON schema and case generation
- Any file under `cases/`, including placeholders or empty `HHG-0NN.json` files
- GraphRAG corpus, chunking, or embeddings built from policy, typology, regulatory, or closed-case content
- The evaluation harness with metrics, labels, or expected outcomes
- Synthetic stand-in data shaped like the dataset (this would amount to guessing the schema)
- Demo recording, blog results, or social posts that describe findings
