# Building a verifiable fraud investigator on TigerGraph Savanna

*Draft. TigerGraph × Hacker House Goa 2026. Every number in this post comes from the project's own artifacts (`reports/`, `runs/`, `cases/`, and the test and verifier output). Customer replies, actions, approvals and suspicious activity reports (SARs) are **simulated**. This is a hackathon prototype, not a production system, and it makes no claim of real-world fraud accuracy.*

## 1. The problem

A fraud alert is not a verdict. The challenge dataset makes the point bluntly: the bank's model scores every transaction, yet "above 0.7, most flagged transactions turn out to be legitimate", and half of the benchmark cases are legitimate. The task is to build an agent that:
- starts from an alert;
- investigates the connected evidence;
- decides what kind of fraud it is (if any) and how far it goes;
- recommends next-best actions with the right approval route, before and after any evidence it requests;
- explains every step.

We set ourselves one extra constraint: **every claim must be verifiable after the fact.**

## 2. The dataset

The dataset is based on IEEE-CIS Fraud Detection, extended by the organisers:

| File | Rows | Notes |
|---|---:|---|
| `transactions.csv` | 590,742 | 393 original Vesta columns + `customer_id`, `ts`, `channel`, `risk_score`; no fraud label |
| `identity.csv` | 144,432 | Device and connection records for online transactions |
| `closed_cases_history.csv` | 5,565 | 4,665 confirmed fraud, 900 cleared: the only labels |
| `case_pack.csv` | 20 | The benchmark alerts HHG-001 … HHG-020 |

Reconnaissance findings that shaped the design:
- **Card IDs are not a column.** The cases use IDs such as `C12382-K1`. We found a rule that reproduces all 14,975 labelled (transaction, card) pairs: rank the card type (`card6`) within each customer. It is inferred, not documented, so it runs as a build gate and the IDs are treated as opaque labels.
- **`ts` is exactly `2016-07-02 00:00:00 + TransactionDT`.**
- **The file contains the future.** Every benchmark card has transactions after its alert, so time filtering has to be enforced, not assumed.

## 3. Graph schema

The schema is local to a new graph, `FraudGraph`:
- **Entity vertices:** `Customer`, `Card`, `Transaction`, `DeviceProfile` (DeviceInfo + OS + browser + screen), `EmailDomain`, `BillingRegion`, `ClosedCase`.
- **Agent vertices:** `InvestigationCase`, `EvidenceItem`, `ActionRecommendation`.
- **Knowledge vertices:** `KnowledgeChunk`, `PolicyRule`, `FraudPattern`.
- **Edges** follow the README's suggestion (`OWNS`, `MADE`, `FROM_DEVICE`, `BILLED_IN`, `NEXT`, `INVOLVES`, …) plus audit and memory edges (`HAS_EVIDENCE`, `HAS_ACTION`, `CITES_RULE`, `SIMILAR_TO`).

One design rule does most of the work against leakage: **no attribute stores an aggregate computed over all time.** Baselines, home region, known devices and degrees are all computed at query time from rows visible at the alert's `as_of`.

## 4. Savanna deployment

The target is a TigerGraph Savanna workspace running TigerGraph 4.2.5, with authentication by GSQL secret only.
- A Python ETL writes tab-separated staging files, gated on the card rule and on expected counts.
- GSQL loading jobs upload them in 4 MB parts, and each part's server-side valid-line count must equal its row count.
- **Load verification:** all 18 expected vertex and edge counts matched exactly, including 590,742 transactions and 576,425 `NEXT` edges.
- **Queries:** 12 installed queries, every one taking `as_of` as its first parameter.

Lessons from the real server:
- GSQL rejected an attribute named `proxy` after `new_found`, so we renamed it `proxy_type`.
- A global `DESCRIBES` edge in the workspace forced a rename to `KC_DESCRIBES`.
- Data posted over REST ignores `header="true"`: header rows loaded as vertices until we stripped them.
- 20 MB uploads hit gateway timeouts.

## 5. MCP gateway

The investigating code never talks to TigerGraph directly. The path is:

```
orchestrator → hhg gateway → MCP client (stdio) → official tigergraph-mcp → Savanna
```

The official server is started with `--allowed-tools run_installed_query,add_nodes,add_edges`, so generic GSQL, schema and delete tools are never served. In front of it, our gateway:
- **injects `as_of` server-side:** tool schemas have no `as_of`, and any attempt to pass one is rejected;
- **checks entities:** callers can only name IDs already returned in this case;
- **enforces a call budget;**
- **post-checks leakage:** any returned row with `ts > as_of` or `closed_at > as_of` aborts the call;
- **records a provenance envelope** for every call: query, parameters including `as_of`, row count, visible IDs and a result SHA-256.

## 6. A deterministic agent

Each case runs through an explicit state machine:

```
INIT → TRIAGE → CONTEXT → PATTERN_SCAN → NETWORK → MEMORY → ASSESS
     → DECIDE_INITIAL → EVIDENCE_GATE → [REQUEST → SIMULATE → REASSESS → DECIDE_FINAL]
     → NARRATE → VALIDATE → PERSIST
```

The submission runs entirely in `--llm off` mode:
- decisions, probabilities, patterns, episodes, actions and routes come from tested Python;
- the narrative text comes from deterministic templates;
- `tokens` is 0 in every answer file.

A language-model path is designed (proposing leads and writing text, never deciding), but **it has not been exercised in the submitted run**. So "agentic" here means a tool-using state machine with its own evidence gate, not free-form LLM autonomy.

Customer replies don't exist in the dataset, so the evidence gate uses a **simulator**:
- the response is a deterministic function of the probability before the request;
- every response text starts with `Simulated:` and states the threshold it used.

## 7. Policy engine

The README's rules R1–R10 are encoded as pure predicates, together with hard guards:
- never block on a single weak signal (R1);
- never block a recurring charge the customer disputes (R7);
- `BLOCK_ALL_CARDS` only under R10;
- a report always has a case behind it;
- a canonical "what happens first" ordering.

Approval routes come from the README table: `BLOCK_CARD` goes to L1 up to $2,500 exposure and to L2 above it. Only `auto` actions are "executed", in a sandbox that has no network clients; L1 and L2 actions are recorded as awaiting human approval, which is also simulated. Every action reason must cite a rule. The verifier re-runs the engine on the recorded inputs and requires identical output.

## 8. Provenance

- Every graph claim in an answer file carries a reference such as `query:card_history(as_of=…, card=…, lookback_days=180)#call-3`.
- Document evidence cites the README policy or pattern section returned by `knowledge_search`, the lexical GraphRAG step over policy chunks and closed-case notes.
- Customer evidence cites either the alert text or `evidence_request:1`, which is marked simulated.

## 9. Audit chain and read-back

- Each run writes an append-only JSONL log in which every event's hash covers the previous one, so any edit breaks verification.
- After validation, the case is written to TigerGraph through the official MCP (`add_nodes` / `add_edges`) under a deterministic ID, so re-runs update it in place.
- It is then read back with an installed query. The stored SHA-256 must equal the SHA-256 of the answer file's bytes.
- That check caught a real bug: Windows text-mode writes turned `\n` into `\r\n`, so the files differed from the hash stored in the graph. We fixed it and added a regression test.

## 10. Testing

- **77 automated tests**, covering:
  - policy rules and guards, routing boundaries, and the scorer and simulator;
  - gateway guards (`as_of` injection, the leakage post-check including the row exactly at `as_of`, the budget);
  - audit-chain tamper detection, loading-column positions against the staging headers, and canonical byte-exact writes;
  - dataset integrity against pinned SHA-256s.
- **51/51 architecture checks:** the design document's case schema must equal the README answer format, and every query must take `as_of` first.
- **`scripts/verify_cases.py`:** an independent verifier that re-checks each answer against the raw CSVs rather than the graph, and reads each case back from TigerGraph separately.

## 11. Results

| Check | Result |
|---|---|
| Answer files | Exactly `cases/HHG-001.json` … `HHG-020.json` |
| Independent verifier | **20/20** pass every check |
| Tests | **77** passing |
| Architecture checks | **51/51** |
| Mode | Deterministic `--llm off`, tokens 0 |
| Outcomes | **8 fraud · 11 uncertain · 1 legitimate**; 6 with a (simulated) SAR |

One case shows what the graph adds. **HHG-014** is an analyst alert about an unusual device.
- **The ring:** a one-hop expansion found 19 other customers' cards using the same fully specified device profile within 30 days of the alert. Each has window transactions where identity marks the device New.
- **The precedent:** four closed cases on the same device model (CC-2649, CC-2971, CC-2985, CC-3035).
- **The decision:** the agent classifies it as an undocumented shared-device ring and applies R6/R9: create a case, file a report (L2), monitor the connected cards, escalate. The verdict stays *uncertain* at 0.51, and we report it that way.

## 12. Limitations (please read)

- **Simulation.** Customer replies, actions, approvals and SARs are simulated. There is no answer key, so we make **no benchmark accuracy claim**.
- **Too few legitimate verdicts.** We produce 1 of 20 against the challenge's "half are legitimate". Most of the 11 uncertain cases fall in a simulated "no reply" band (probability 0.40–0.60). That band is a design choice with no support in the historical data, and it is still under review.
- **Scorer calibration.** On a 300-case closed-case backtest (150 fraud, 150 cleared), our original hand-set weights did worse than chance (held-out AUC 0.458). We refitted them keeping the README's evidence directions (held-out AUC 0.596). An unconstrained fit scored higher (0.747) but treated unusual amounts, new devices and familiarity in directions that contradict the README, so we rejected it. The backtest is small, and closed cases are not a random sample of alerts.
- **Pattern rules.** These are data-driven: online alerts are split by the identity record's New flag, in-person alerts by home region. They raised pattern accuracy on 150 confirmed-fraud closed cases from 0.213 to 0.807, but that figure is in-sample (0.871 on an October-only subset).
- **Memory.** The case "signature" reuses the detectors' own vocabulary, which makes lexical similarity circular. It therefore carries zero weight in the score, and `similar_prior_cases` lists only closed cases that informed the decision. The embeddings are hashed TF-IDF, not neural.
- **Unconfirmed assumptions.** The card-ID rule and the device-profile string format are inferred and not yet confirmed by the organisers. `pyTigerGraph` emits deprecation warnings for plain vertex parameters.

## 13. Reproduce it

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements.txt
cp .env.example .env                     # fill in your own Savanna host and secret; never commit .env
export PYTHONPATH=src
.venv/Scripts/python scripts/validate_dataset.py      # dataset integrity (official data in data/raw/)
.venv/Scripts/python -m hhg.etl.build                 # staging files + build gates
.venv/Scripts/python -m hhg.graph.admin all           # schema, loading, install queries, verify counts
.venv/Scripts/python -m hhg.cli run all --llm off     # 20 cases in as_of order -> cases/
.venv/Scripts/python scripts/verify_cases.py          # independent verification (expects 20/20)
.venv/Scripts/python -m unittest discover -s tests    # 77 tests
.venv/Scripts/streamlit run ui/app.py                 # analyst UI (HHG-017 recommended)
```

Links: code [GITHUB_URL] · video [VIDEO_URL] · demo [DEMO_URL]

Thanks to @TigerGraphDB and @247pmstudio for the challenge and the dataset.
