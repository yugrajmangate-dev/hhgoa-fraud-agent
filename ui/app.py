"""Analyst UI (Streamlit). Presentation only: reads real run outputs (cases/ + runs/cases/),
never calls external systems, never executes actions, never changes answer or audit data.

    .venv/Scripts/streamlit run ui/app.py
"""

import html
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hhg import config  # noqa: E402
from hhg.audit.log import verify  # noqa: E402

RECOMMENDED = "HHG-017"
RING_DEMO = "HHG-014"
SIM = "SIMULATED"
SECTIONS = [  # (heading text, anchor); anchors equal the slugs Streamlit generates for these headings
    ("1. Case input", "1-case-input"),
    ("2. Graph evidence and provenance", "2-graph-evidence-and-provenance"),
    ("3. Assessment and initial decision", "3-assessment-and-initial-decision"),
    ("4. Additional evidence (SIMULATED response)", "4-additional-evidence-simulated-response"),
    ("5. Final decision, approval routes and report", "5-final-decision-approval-routes-and-report"),
    ("6. Audit trail and graph persistence", "6-audit-trail-and-graph-persistence"),
]
TONE = {"fraud": "red", "legitimate": "green", "uncertain": "amber",
        "closed_fraud": "red", "closed_legitimate": "green", "escalated": "amber", "open": "blue",
        "auto": "blue", "L1": "amber", "L2": "red"}

CSS = """
<style>
:root { --navy:#0B1220; --panel:#111A2B; --panel2:#16213A; --line:#24324D; --text:#E5E7EB; --muted:#94A3B8;
        --blue:#3B82F6; --green:#22C55E; --amber:#F59E0B; --red:#EF4444; }
.block-container { padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1400px; }
h1 { font-size: 1.55rem !important; font-weight: 650 !important; letter-spacing: -0.01em; margin-bottom: .2rem; }
h2 { font-size: 1.15rem !important; font-weight: 620 !important; border-bottom: 1px solid var(--line);
     padding-bottom: .45rem; margin-top: 2.1rem !important; }
.sim-banner { background:#F5C518; color:#111827; border-radius:8px; padding:.7rem 1rem; font-weight:600;
              border:1px solid #D4A500; margin:.4rem 0 1rem 0; font-size:.93rem; }
.sim-banner span { font-weight:800; letter-spacing:.04em; }
.subtle { color: var(--muted); font-size: .86rem; }
.summary { display:grid; grid-template-columns: repeat(8, minmax(0,1fr)); gap:.5rem; margin:.3rem 0 .9rem 0; }
@media (max-width: 1100px) { .summary { grid-template-columns: repeat(4, minmax(0,1fr)); } }
.chip { background: var(--panel); border:1px solid var(--line); border-radius:8px; padding:.55rem .7rem; min-width:0; }
.chip .k { color: var(--muted); font-size:.68rem; text-transform:uppercase; letter-spacing:.06em; }
.chip .v { color: var(--text); font-size:.95rem; font-weight:600; margin-top:.15rem; white-space:nowrap;
           overflow:hidden; text-overflow:ellipsis; font-variant-numeric: tabular-nums; }
.tone-red .v, .t-red { color: var(--red) !important; }
.tone-green .v, .t-green { color: var(--green) !important; }
.tone-amber .v, .t-amber { color: var(--amber) !important; }
.tone-blue .v, .t-blue { color: var(--blue) !important; }
.stepper { display:flex; gap:.35rem; flex-wrap:wrap; margin:.2rem 0 .4rem 0; }
.stepper a { text-decoration:none !important; color: var(--text) !important; background: var(--panel);
             border:1px solid var(--line); border-radius:999px; padding:.3rem .75rem; font-size:.8rem; }
.stepper a:hover { border-color: var(--blue); }
.stepper b { display:inline-block; width:1.25rem; height:1.25rem; border-radius:50%; background: var(--panel2);
             border:1px solid var(--blue); color: var(--blue); text-align:center; font-size:.72rem; line-height:1.15rem;
             margin-right:.35rem; }
.card { background: var(--panel); border:1px solid var(--line); border-radius:10px; padding:.9rem 1rem; }
.kv { display:grid; grid-template-columns: repeat(4, minmax(0,1fr)); gap:.6rem; }
.kv .k { color: var(--muted); font-size:.7rem; text-transform:uppercase; letter-spacing:.06em; }
.kv .v { font-size:1rem; font-weight:600; font-variant-numeric: tabular-nums; overflow-wrap:anywhere; }
.decision { border-left: 4px solid var(--blue); }
.decision.red { border-left-color: var(--red); } .decision.green { border-left-color: var(--green); }
.decision.amber { border-left-color: var(--amber); }
.big { font-size:2.1rem; font-weight:700; line-height:1.1; font-variant-numeric: tabular-nums; }
.badge { display:inline-block; padding:.12rem .5rem; border-radius:6px; font-size:.75rem; font-weight:700;
         letter-spacing:.03em; border:1px solid currentColor; }
.simtag { display:inline-block; background:#F5C518; color:#111827; border-radius:5px; padding:.08rem .45rem;
          font-size:.7rem; font-weight:800; letter-spacing:.05em; margin-right:.4rem; }
.simbox { background: rgba(245,197,24,.08); border:1px solid #8A6D00; border-radius:10px; padding:.8rem 1rem; }
.quote { color: var(--text); font-style: italic; border-left:3px solid var(--line); padding-left:.7rem; }
code { font-size: .8rem !important; }
</style>
"""


def esc(x) -> str:
    return html.escape(str(x))


def chip(key: str, value, tone: str = "") -> str:
    return f'<div class="chip {("tone-" + tone) if tone else ""}"><div class="k">{esc(key)}</div>' \
           f'<div class="v" title="{esc(value)}">{esc(value)}</div></div>'


def badge(text: str) -> str:
    return f'<span class="badge t-{TONE.get(text, "blue")}">{esc(text)}</span>'


def section(i: int):
    text, anchor = SECTIONS[i]
    st.header(text, anchor=anchor)


st.set_page_config(page_title="HHGoa Fraud Investigation", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
st.title("Agentic fraud investigation on TigerGraph")
st.markdown('<div class="sim-banner"><span>SIMULATED ENVIRONMENT</span> &nbsp;·&nbsp; Customer responses, actions, '
            'approvals and reports are simulated. Nothing here touches a real card, customer or regulator.</div>',
            unsafe_allow_html=True)

files = sorted((ROOT / "cases").glob("HHG-*.json"))
if not files:
    st.info("No answer files yet. Run: python -m hhg.cli run all --llm off")
    st.stop()
ids = [f.stem for f in files]

# ---------------------------------------------------------------- sidebar: case selection
with st.sidebar:
    st.markdown("### Case selection")
    if "case" not in st.session_state:
        st.session_state["case"] = RECOMMENDED if RECOMMENDED in ids else ids[0]
    b1, b2 = st.columns(2)
    if RECOMMENDED in ids and b1.button(f"{RECOMMENDED}  demo", width="stretch",
                                        help="Recommended demo case: verification flow"):
        st.session_state["case"] = RECOMMENDED
    if RING_DEMO in ids and b2.button(f"{RING_DEMO}  ring", width="stretch",
                                      help="Device-ring demo case"):
        st.session_state["case"] = RING_DEMO
    choice = st.selectbox("All 20 benchmark cases", ids, key="case",
                          format_func=lambda c: f"{c}   (recommended demo)" if c == RECOMMENDED
                          else (f"{c}   (device-ring demo)" if c == RING_DEMO else c))
    st.markdown("### Stages")
    st.markdown("\n".join(f"{i + 1}. [{t.split('. ', 1)[1]}](#{a})" for i, (t, a) in enumerate(SECTIONS)))

path = ROOT / "cases" / f"{choice}.json"
body = path.read_bytes()
answer = json.loads(body)
run_dir = next((r for r in sorted((ROOT / "runs" / "cases").glob(f"{choice}-*"), reverse=True)
                if (r / f"{choice}.json").exists() and (r / f"{choice}.json").read_bytes() == body), None)
if run_dir is None:
    st.error("No run directory produced this exact answer file; provenance cannot be shown.")
    st.stop()
trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
events = [json.loads(line) for line in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
case, sar, nba = answer["case"], answer["sar"], answer["next_best_actions"]
row = trace["case"]
chain_ok, n_events = verify(run_dir / "audit.jsonl")
persist = next((e for e in events if e["event"] == "persist"), None)
readback = persist["payload"]["read_back"] if persist else "not verified"
mode = next((s.get("llm") for s in trace["states"] if s["state"] == "INIT"), None)
with st.sidebar:
    st.markdown("### Run")
    st.caption(f"`{run_dir.name}`")
    st.caption(f"Answer file: `cases/{choice}.json`")

# ---------------------------------------------------------------- top summary + stepper
st.markdown('<div class="summary">' + "".join([
    chip("Selected case", choice + ("  · demo" if choice == RECOMMENDED else "")),
    chip("Run ID", run_dir.name),
    chip("Mode", f"deterministic (--llm {mode})" if mode else "unknown"),
    chip("Tokens", answer["tokens"]),
    chip("Verdict", case["verdict"], TONE.get(case["verdict"], "")),
    chip("Fraud probability", f"{case['fraud_probability']:.2f}"),
    chip("Audit chain", f"verified · {n_events} events" if chain_ok else f"broken at event {n_events}",
         "green" if chain_ok else "red"),
    chip("Graph read-back", readback, "green" if readback == "verified" else "amber"),
]) + "</div>", unsafe_allow_html=True)
st.markdown('<div class="stepper">' + "".join(
    f'<a href="#{a}"><b>{i + 1}</b>{esc(t.split(". ", 1)[1])}</a>' for i, (t, a) in enumerate(SECTIONS)) + "</div>",
    unsafe_allow_html=True)

# ---------------------------------------------------------------- 1
section(0)
st.markdown('<div class="card"><div class="kv">' + "".join(
    f'<div><div class="k">{esc(k)}</div><div class="v">{esc(v)}</div></div>' for k, v in [
        ("Trigger", row["trigger_type"]), ("as_of (case_pack.opened_at)", row["opened_at"]),
        ("Flagged transaction", row["flagged_txn_id"]), ("Card / customer", f"{row['card_id']} / {row['customer_id']}")])
    + f'</div><div style="margin-top:.7rem" class="quote">{esc(row["trigger_text"])}</div></div>',
    unsafe_allow_html=True)
st.caption("Every graph query below runs with this as_of injected by the gateway; rows after it are rejected.")

# ---------------------------------------------------------------- 2
section(1)
st.markdown('<div class="subtle">Graph calls made through the gateway to the official <code>tigergraph-mcp</code> '
            'server and TigerGraph, in order.</div>', unsafe_allow_html=True)
st.dataframe(pd.DataFrame([{"call": e["call_id"], "tool": e["tool"], "installed query": e["query"],
                            "params (as_of injected)": ", ".join(f"{k}={v}" for k, v in e["params"].items()),
                            "rows": e["row_count"], "result sha256": e["result_sha256"][:12]}
                           for e in trace["envelopes"]]),
             hide_index=True, width="stretch",
             column_config={"call": st.column_config.TextColumn(width="small"),
                            "rows": st.column_config.NumberColumn(width="small"),
                            "params (as_of injected)": st.column_config.TextColumn(width="large")})
st.markdown('<div class="subtle" style="margin-top:.6rem">Evidence in the answer file. Each graph claim '
            'references one of the calls above.</div>', unsafe_allow_html=True)
st.dataframe(pd.DataFrame([{
    "source": ev["source"] + (f" ({SIM})" if ev["source"] == "customer" and ev["ref"].startswith("evidence_request") else ""),
    "claim": ev["claim"], "reference": ev["ref"], "entities": ", ".join(ev["entity_ids"][:8]) or "-"}
    for ev in case["evidence"]]), hide_index=True, width="stretch",
    column_config={"source": st.column_config.TextColumn(width="small"),
                   "claim": st.column_config.TextColumn(width="large"),
                   "reference": st.column_config.TextColumn(width="medium")})
dot = ['digraph G { rankdir=LR; bgcolor="transparent"; pad=0.2;',
       'node [shape=box, style="rounded,filled", fillcolor="#16213A", color="#3B82F6", fontcolor="#E5E7EB", '
       'fontname="Helvetica", fontsize=10]; edge [color="#94A3B8", fontcolor="#94A3B8", fontname="Helvetica", fontsize=9];',
       f'"{row["customer_id"]}" -> "{row["card_id"]}" [label=OWNS];',
       f'"{row["card_id"]}" -> "{row["flagged_txn_id"]}" [label="MADE (flagged)"];']
for t in case["affected_txn_ids"]:
    dot.append(f'"{row["card_id"]}" -> "{t}" [label=MADE];')
for d in case["connected_device_profiles"]:
    dot.append(f'"{d}" [shape=ellipse, color="#F59E0B"]; "{row["card_id"]}" -> "{d}" [label=device];')
for k in case["connected_card_ids"][:12]:
    dot.append(f'"{k}" [color="#EF4444"]; "{k}" -> "{(case["connected_device_profiles"] or [row["card_id"]])[0]}" [style=dashed];')
for p in case["similar_prior_cases"]:
    dot.append(f'"{p}" [shape=note, color="#94A3B8"]; "{p}" -> "{row["card_id"]}" [style=dotted, label="prior case"];')
dot.append("}")
with st.expander("Entity graph for this case", expanded=True):
    st.graphviz_chart("\n".join(dot))

# ---------------------------------------------------------------- 3
section(2)
a0 = trace["assessment_initial"]
st.markdown('<div class="card"><div class="kv">' + "".join(
    f'<div><div class="k">{esc(k)}</div><div class="v">{v}</div></div>' for k, v in [
        ("Fraud probability (before request)", esc(f"{a0['p']:.2f}")),
        ("Supporting / exculpatory families", esc(f"{a0['n_support']} / {a0['n_exculpatory']}")),
        ("Pattern (leading hypothesis)", esc(case["pattern"])),
        ("Scorer (code version)", esc(config.SCORER_VERSION))]) + "</div></div>", unsafe_allow_html=True)
contrib = [{"family": k, "contribution (logit)": v} for k, v in a0["contributions"].items() if v]
c1, c2 = st.columns([2, 3])
with c1:
    st.markdown('<div class="subtle">Non-zero evidence contributions</div>', unsafe_allow_html=True)
    if contrib:
        st.dataframe(pd.DataFrame(contrib), hide_index=True, width="stretch")
    else:
        st.caption("No evidence family contributed; the probability is the fitted base rate.")
with c2:
    st.markdown('<div class="subtle">Initial next-best actions (policy engine, README rules R1-R10)</div>',
                unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{"action": x["action"], "route": x["route"], "reason": x["reason"]}
                               for x in nba["initial"]]), hide_index=True, width="stretch",
                 column_config={"route": st.column_config.TextColumn(width="small"),
                                "reason": st.column_config.TextColumn(width="large")})

# ---------------------------------------------------------------- 4
section(3)
if answer["evidence_requests"]:
    for r in answer["evidence_requests"]:
        st.markdown(f'<div class="simbox"><span class="simtag">{SIM}</span><b>{esc(r["type"])}</b> '
                    f'<span class="subtle">requested after step {esc(r["asked_after_step"])}</span>'
                    f'<div style="margin-top:.45rem">{esc(r["assumed_response"])}</div></div>',
                    unsafe_allow_html=True)
    st.caption("The dataset provides no customer replies. The response is a deterministic, recorded assumption "
               "derived only from the pre-response probability (ARCHITECTURE.md §13).")
else:
    st.info("No additional evidence was requested for this case (stopping rule or trigger already settled it).")

# ---------------------------------------------------------------- 5
section(4)
tone = TONE.get(case["verdict"], "blue")
st.markdown(
    f'<div class="card decision {tone}"><div class="kv">'
    f'<div><div class="k">Verdict</div><div class="big t-{tone}">{esc(case["verdict"])}</div></div>'
    f'<div><div class="k">Fraud probability (final)</div><div class="big">{case["fraud_probability"]:.2f}</div></div>'
    f'<div><div class="k">Status</div><div class="v" style="margin-top:.35rem">{badge(case["status"])}</div></div>'
    f'<div><div class="k">Exposure</div><div class="big">${case["exposure_usd"]:,.2f}</div></div>'
    f'</div></div>', unsafe_allow_html=True)
st.markdown('<div class="subtle" style="margin-top:.8rem">Final next-best actions and approval routes '
            f'(<span class="simtag">{SIM}</span>execution)</div>', unsafe_allow_html=True)
st.dataframe(pd.DataFrame([{
    "action": x["action"], "route": x["route"],
    "execution": f"{SIM}: auto-executed in sandbox" if x["route"] == "auto" else f"{SIM}: awaiting {x['route']} approval",
    "reason": x["reason"]} for x in nba["final"]]), hide_index=True, width="stretch",
    column_config={"route": st.column_config.TextColumn(width="small"),
                   "execution": st.column_config.TextColumn(width="medium"),
                   "reason": st.column_config.TextColumn(width="large")})
st.markdown(f'<div class="card" style="margin-top:.6rem"><div class="k subtle">WHAT CHANGED</div>'
            f'<div>{esc(nba["what_changed"])}</div>'
            f'<div class="k subtle" style="margin-top:.6rem">SUMMARY</div><div>{esc(case["summary"])}</div>'
            f'<div class="k subtle" style="margin-top:.6rem">STOP REASON</div><div>{esc(answer["stop_reason"])}</div>'
            f'</div>', unsafe_allow_html=True)
st.markdown(f'<div class="card" style="margin-top:.6rem"><span class="simtag">{SIM}</span>'
            f'<b>Suspicious activity report</b> <span class="subtle">(not filed with any regulator)</span>'
            f'<div style="margin-top:.4rem">file = <b>{esc(sar["file"])}</b> · {esc(sar["reason"])}</div>'
            + (f'<div style="margin-top:.5rem" class="quote">{esc(sar["narrative"])}</div>' if sar["file"] else "")
            + '</div>', unsafe_allow_html=True)

# ---------------------------------------------------------------- 6
section(5)
st.markdown('<div class="summary" style="grid-template-columns: repeat(4, minmax(0,1fr));">' + "".join([
    chip("Audit hash chain", "verified" if chain_ok else f"broken at event {n_events}", "green" if chain_ok else "red"),
    chip("Audit events", n_events),
    chip("Graph case vertex", case["graph_case_id"] or "not written", "" if case["graph_case_id"] else "amber"),
    chip("Graph read-back", readback, "green" if readback == "verified" else "amber"),
]) + "</div>", unsafe_allow_html=True)
with st.expander("State sequence, persistence details and audit events", expanded=False):
    st.markdown(" → ".join(f"`{e['payload']['state']}`" for e in events if e["event"] == "state"))
    if persist:
        st.markdown(f"Persisted edges: `{json.dumps(persist['payload'].get('edges', {}))}`")
    st.code((run_dir / "audit.jsonl").read_text(encoding="utf-8")[:30000], language="json")
with st.expander(f"Answer file (cases/{choice}.json)", expanded=False):
    st.json(answer)
