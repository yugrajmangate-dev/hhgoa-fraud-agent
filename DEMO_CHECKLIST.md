# Demo checklist

Run these from `C:\Users\yugra\source\hhgoa-fraud-agent` in Git Bash. `.env` must contain the Savanna `TG_HOST` and `TG_SECRET`. Never show `.env` on screen.

## Before recording (about 3 minutes)

| # | Command | Expected |
|---|---|---|
| 1 | `.venv/Scripts/python -m unittest discover -s tests` | `Ran 77 tests … OK` |
| 2 | `PYTHONPATH=src .venv/Scripts/python scripts/verify_cases.py 2>&1 \| .venv/Scripts/python scripts/redact.py` | `exact file set …: True` and `cases passing every check: 20/20` |
| 3 | `ls cases` | Exactly `HHG-001.json` … `HHG-020.json` |
| 4 | Workspace running in the Savanna console | The workspace is active (the verifier's read-back needs it) |

**Optional:** to regenerate the answers live, run `PYTHONPATH=src .venv/Scripts/python -m hhg.cli run all --llm off` (about 2 minutes), then repeat step 2. Graph IDs and decisions are deterministic; run IDs and latencies change.

## Launch the demo

```bash
cd /c/Users/yugra/source/hhgoa-fraud-agent
.venv/Scripts/streamlit run ui/app.py
```

Open http://localhost:8501. The health check `curl http://localhost:8501/_stcore/health` should return `ok`.

## Screens to show, in order

| # | Screen | Must be visible |
|---|---|---|
| 1 | Page top | Yellow **SIMULATED ENVIRONMENT** banner |
| 2 | Sidebar | Case selector showing **HHG-017 (recommended demo case)**, run ID, mode `--llm off`, tokens 0 |
| 3 | 1. Case input | Trigger `risk_score`, as_of `2016-11-12 00:46:24`, flagged `3450629`, card `C04570-K1` |
| 4 | 2. Graph evidence and provenance | 8 calls table (params include `as_of=2016-11-12 00:46:24`), evidence list with `query:…#call-n` refs, entity graph |
| 5 | 3. Assessment and initial decision | p = 0.34, initial `VERIFY_WITH_CUSTOMER`, `CREATE_CASE` (auto) |
| 6 | 4. Additional evidence | Red **SIMULATED** box: customer confirms (0.34 ≤ 0.40) |
| 7 | 5. Final decision | Verdict legitimate, p 0.03, `CREATE_CASE`, `CLOSE_NO_FRAUD`, SAR not filed, what changed |
| 8 | 6. Audit trail | Hash chain **verified** (42 events), graph case `INV-HHG-017-0e29f8b20a`, read-back **verified** |
| 9 | Switch to HHG-014 | Device ring (19 other customers' cards), `undocumented`, R6/R9 actions, `FILE_REPORT` route **L2**, `DECLINE_TRANSACTION` route **L1**, cited CC-2649/2971/2985/3035 |
| 10 | Terminal | `verify_cases.py` → `20/20` |

## Do not

- Show `.env`, the Savanna console credentials page, or build logs (`runs/build/`), which contain the workspace host.
- Claim real customer replies, real card blocks or real regulatory filings. All of these are simulated.
- Claim accuracy numbers for the benchmark. There is no answer key; the only measured numbers are the closed-case backtest (constrained scorer test AUC 0.596; pattern accuracy 0.807 on 150 fraud cases, in-sample).
