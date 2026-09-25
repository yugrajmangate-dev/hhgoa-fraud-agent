"""Analyst UI (Streamlit). Presentation only: reads real run outputs (cases/ + runs/cases/),
never calls external systems, never executes actions, never changes answer or audit data.

    .venv/Scripts/streamlit run ui/app.py
"""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hhg import config  # noqa: E402
from hhg.audit.log import verify  # noqa: E402

CASES_DIR = ROOT / "cases"
RUNS_DIR = ROOT / "runs" / "cases"
RECOMMENDED = "HHG-017"
RING_DEMO = "HHG-014"
SIM = "SIMULATED"
SECTIONS = [  # (heading text, anchor, icon, short label); anchors equal the slugs Streamlit generates
    ("1. Case input", "1-case-input", ":material/input:", "Case input"),
    ("2. Graph evidence and provenance", "2-graph-evidence-and-provenance", ":material/hub:", "Graph evidence"),
    ("3. Assessment and initial decision", "3-assessment-and-initial-decision", ":material/analytics:",
     "Assessment"),
    ("4. Additional evidence (SIMULATED response)", "4-additional-evidence-simulated-response",
     ":material/science:", "Simulated response"),
    ("5. Final decision, approval routes and report", "5-final-decision-approval-routes-and-report",
     ":material/gavel:", "Final decision"),
    ("6. Audit trail and graph persistence", "6-audit-trail-and-graph-persistence", ":material/verified:",
     "Audit and persistence"),
]
COLOR = {"fraud": "red", "legitimate": "green", "uncertain": "orange",
         "closed_fraud": "red", "closed_legitimate": "green", "escalated": "orange", "open": "blue",
         "auto": "blue", "L1": "orange", "L2": "red"}
ROUTE_RANK = {"auto": 0, "L1": 1, "L2": 2}
TRIGGER_LABEL = {"risk_score": "Model risk-score alert", "customer_report": "Customer report",
                 "analyst_request": "Analyst request"}
_MD = str.maketrans({c: "\\" + c for c in "\\`*_[]<>$#|~"})


def md(x) -> str:
    """Escape free text for st.markdown (e.g. '$100.09' must not start LaTeX)."""
    return str(x).translate(_MD)


def section(i: int):
    text, anchor, icon, _ = SECTIONS[i]
    st.header(text, anchor=anchor, icon=icon)


def highest_route(actions) -> str:
    routes = [a["route"] for a in actions]
    return max(routes, key=lambda r: ROUTE_RANK.get(r, -1)) if routes else "none"


def dot_id(x) -> str:
    return '"' + str(x).replace("\\", "\\\\").replace('"', '\\"') + '"'


def case_label(c: str, overview: dict) -> str:
    o = overview.get(c)
    if not o or o.get("error"):
        return f"{c}  · unreadable"
    return f"{c}  · {o['verdict']} · p {o['p']:.2f}"


@st.cache_data(show_spinner=False, max_entries=8)
def load_overview(stamp: tuple) -> dict:
    """One summary row per answer file; `stamp` (name, mtime, size) invalidates the cache on change."""
    out = {}
    for name, _, _ in stamp:
        cid = Path(name).stem
        try:
            a = json.loads((CASES_DIR / name).read_bytes())
            c = a["case"]
            out[cid] = {"verdict": c["verdict"], "p": c["fraud_probability"], "status": c["status"],
                        "route": highest_route(a["next_best_actions"]["final"]), "sar": bool(a["sar"]["file"]),
                        "evidence": len(c["evidence"]), "exposure": c["exposure_usd"]}
        except (OSError, ValueError, KeyError, TypeError) as exc:
            out[cid] = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def load_case(choice: str):
    """Answer file plus the run directory that produced exactly these bytes (trace + audit log)."""
    body = (CASES_DIR / f"{choice}.json").read_bytes()
    answer = json.loads(body)
    run_dir = next((r for r in sorted(RUNS_DIR.glob(f"{choice}-*"), reverse=True)
                    if (r / f"{choice}.json").exists() and (r / f"{choice}.json").read_bytes() == body), None)
    if run_dir is None:
        return answer, None, None, None
    trace = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
    events = [json.loads(line) for line in (run_dir / "audit.jsonl").read_text(encoding="utf-8").splitlines()]
    return answer, run_dir, trace, events


def select_case(case_id: str):
    st.session_state["case"] = case_id


# ---------------------------------------------------------------- page header
st.set_page_config(page_title="HHGoa Fraud Investigation", page_icon=":material/policy:", layout="wide")
st.title("Agentic fraud investigation on TigerGraph", anchor=False)
st.caption("Each benchmark alert is investigated as of the moment it opened. Graph queries run through the "
           "official TigerGraph MCP server with that `as_of` injected, the evidence is scored, the bank's policy "
           "rules R1–R10 choose the next-best actions, and every run is kept as a hash-chained audit log and "
           "written back to the graph.")
st.warning("**SIMULATED ENVIRONMENT** · Customer responses, actions, approvals and reports (SARs) are simulated. "
           "Nothing here touches a real card, customer or regulator.", icon=":material/science:")
st.markdown("**Workflow** &nbsp; " + " &nbsp;→&nbsp; ".join(
    f"[{i + 1}. {short}](#{anchor})" for i, (_, anchor, _, short) in enumerate(SECTIONS)))

files = sorted(CASES_DIR.glob("HHG-*.json"))
if not files:
    st.info("No answer files found in `cases/`. Generate them with "
            "`PYTHONPATH=src python -m hhg.cli run all --llm off`, then reload this page.",
            icon=":material/folder_open:")
    st.stop()
ids = [f.stem for f in files]
overview = load_overview(tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in files))

# ---------------------------------------------------------------- sidebar: case selection
if "case" not in st.session_state or st.session_state["case"] not in ids:
    st.session_state["case"] = RECOMMENDED if RECOMMENDED in ids else ids[0]
with st.sidebar:
    st.subheader("Case selection", anchor=False)
    with st.container(horizontal=True):
        if RECOMMENDED in ids:
            st.button(f"{RECOMMENDED}  demo", icon=":material/play_circle:", width="stretch",
                      type="primary" if st.session_state["case"] == RECOMMENDED else "secondary",
                      help="Recommended demo case: verification flow", on_click=select_case, args=(RECOMMENDED,))
        if RING_DEMO in ids:
            st.button(f"{RING_DEMO}  ring", icon=":material/hub:", width="stretch",
                      type="primary" if st.session_state["case"] == RING_DEMO else "secondary",
                      help="Device-ring demo case", on_click=select_case, args=(RING_DEMO,))
    choice = st.selectbox(f"All {len(ids)} benchmark cases", ids, key="case",
                          format_func=lambda c: case_label(c, overview))
    st.subheader("Investigation stages", anchor=False)
    st.markdown("\n".join(f"{i + 1}. [{short}](#{anchor})" for i, (_, anchor, _, short) in enumerate(SECTIONS)))

# ---------------------------------------------------------------- benchmark overview (all cases)
ok_rows = {c: o for c, o in overview.items() if not o.get("error")}
counts = {v: sum(1 for o in ok_rows.values() if o["verdict"] == v) for v in ("fraud", "uncertain", "legitimate")}
with st.expander(f"Benchmark overview: {len(ids)} cases · {counts['fraud']} fraud · {counts['uncertain']} uncertain · "
                 f"{counts['legitimate']} legitimate", icon=":material/table_chart:"):
    st.dataframe(pd.DataFrame([{
        "case": c, "verdict": o["verdict"], "fraud probability": o["p"], "status": o["status"],
        "highest route (simulated approval)": o["route"], "SAR (simulated)": o["sar"],
        "evidence items": o["evidence"], "exposure (USD)": o["exposure"]} for c, o in ok_rows.items()]),
        hide_index=True, width="stretch",
        column_config={"fraud probability": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=1),
                       "exposure (USD)": st.column_config.NumberColumn(format="$%.2f")})
    st.caption("Read from the committed answer files. Open a case from the sidebar. "
               "There is no answer key, so these are the agent's decisions, not measured accuracy.")
    bad = {c: o["error"] for c, o in overview.items() if o.get("error")}
    if bad:
        st.error("Unreadable answer files: " + "; ".join(f"`{c}`: {md(e)}" for c, e in bad.items()),
                 icon=":material/error:")

# ---------------------------------------------------------------- load the selected case
try:
    with st.spinner(f"Loading {choice}: answer file, trace and audit log…"):
        answer, run_dir, trace, events = load_case(choice)
        if run_dir is not None:
            chain_ok, n_events = verify(run_dir / "audit.jsonl")
except (OSError, ValueError) as exc:
    st.error(f"Could not load `{choice}`: {md(type(exc).__name__)}: {md(exc)}", icon=":material/error:")
    st.stop()
if run_dir is None:
    st.error(f"No run directory in `runs/cases/` produced this exact answer file (`cases/{choice}.json`), so its "
             "provenance and audit trail cannot be shown.", icon=":material/error:")
    st.stop()

case, sar, nba = answer["case"], answer["sar"], answer["next_best_actions"]
row = trace["case"]
envelopes = trace["envelopes"]
a0 = trace["assessment_initial"]
persist = next((e for e in events if e["event"] == "persist"), None)
readback = persist["payload"]["read_back"] if persist else "not verified"
mode = next((s.get("llm") for s in trace["states"] if s["state"] == "INIT"), None)
route_top = highest_route(nba["final"])

with st.sidebar:
    st.subheader("Run", anchor=False)
    st.caption(f"Run ID `{run_dir.name}`")
    st.caption(f"Answer file `cases/{choice}.json`")
    st.caption(f"Mode: deterministic (`--llm {mode}`) · tokens {answer['tokens']}" if mode
               else f"Mode: unknown · tokens {answer['tokens']}")
    st.caption("Read-only view of committed run outputs. This page calls no external system.")

# ---------------------------------------------------------------- case header + KPIs
st.subheader(f"{choice} · {TRIGGER_LABEL.get(row['trigger_type'], row['trigger_type'])}", anchor=False)
with st.container(horizontal=True, gap="small"):
    st.badge(f"verdict: {case['verdict']}", color=COLOR.get(case["verdict"], "gray"))
    st.badge(f"status: {case['status']}", color=COLOR.get(case["status"], "gray"))
    st.badge(f"as_of {row['opened_at']}", icon=":material/schedule:", color="gray")
    if choice == RECOMMENDED:
        st.badge("recommended demo", icon=":material/star:", color="violet")
    elif choice == RING_DEMO:
        st.badge("device-ring demo", icon=":material/star:", color="violet")

p0, p1 = a0["p"], case["fraud_probability"]
k1, k2, k3, k4, k5 = st.columns([1.3, 1, 1, 1, 1])
k1.metric("Verdict", case["verdict"], border=True, help="Final verdict in the answer file.")
k2.metric("Fraud probability", f"{p1:.2f}", delta=f"{p1 - p0:+.2f} from {p0:.2f}" if p1 != p0 else None,
          delta_color="inverse", border=True,
          help="Final calibrated fraud probability. The change is from the initial assessment, before any "
               "(simulated) customer response.")
k3.metric("Model risk score", row.get("risk_score") or "n/a", border=True,
          help="The bank model's score on the flagged transaction, recorded as an input, not a verdict. "
               "Only risk-score alerts carry one.")
k4.metric("Approval route", route_top, border=True,
          help="Highest route among the final next-best actions (auto < L1 < L2). "
               "Approvals are SIMULATED: L1/L2 items only await approval.")
k5.metric("Evidence items", len(case["evidence"]), border=True,
          help=f"Evidence entries in the answer file. Each graph claim cites one of the {len(envelopes)} graph calls.")
with st.container(horizontal=True, gap="small"):
    if chain_ok:
        st.badge(f"audit chain verified · {n_events} events", icon=":material/verified:", color="green")
    else:
        st.badge(f"audit chain broken at event {n_events}", icon=":material/error:", color="red")
    st.badge(f"graph read-back {readback}", icon=":material/sync_alt:",
             color="green" if readback == "verified" else "orange")
    st.badge(f"{len(envelopes)} graph calls via TigerGraph MCP", icon=":material/hub:", color="gray")
    st.badge(f"approvals and actions {SIM}", icon=":material/science:", color="orange")
if not chain_ok:
    st.error(f"The audit hash chain does not verify (broken at event {n_events}). Treat this run's evidence as "
             "untrusted.", icon=":material/error:")
if readback != "verified":
    st.warning(f"Graph read-back: {md(readback)}.", icon=":material/sync_problem:")

# ---------------------------------------------------------------- 1
section(0)
with st.container(border=True):
    c1, c2, c3, c4 = st.columns(4)
    for col, (k, v) in zip((c1, c2, c3, c4), [
            ("Trigger", row["trigger_type"]), ("as_of (case_pack.opened_at)", row["opened_at"]),
            ("Flagged transaction", row["flagged_txn_id"]), ("Card / customer", f"{row['card_id']} / {row['customer_id']}")]):
        col.caption(k)
        col.markdown(f"**`{v}`**")
    st.markdown(f"> {md(row['trigger_text'])}")
st.caption("Every graph query below runs with this as_of injected by the gateway; rows after it are rejected.")

# ---------------------------------------------------------------- 2
section(1)
st.caption("Graph calls made through the gateway to the official `tigergraph-mcp` server and TigerGraph, in order. "
           "Each graph claim in the evidence references one of these calls.")
t_calls, t_evidence, t_graph = st.tabs([f":material/hub: Graph calls ({len(envelopes)})",
                                        f":material/fact_check: Evidence ({len(case['evidence'])})",
                                        ":material/account_tree: Entity graph"])
with t_calls:
    if envelopes:
        st.dataframe(pd.DataFrame([{"call": e["call_id"], "tool": e["tool"], "installed query": e["query"],
                                    "params (as_of injected)": ", ".join(f"{k}={v}" for k, v in e["params"].items()),
                                    "rows": e["row_count"], "result sha256": e["result_sha256"][:12]}
                                   for e in envelopes]),
                     hide_index=True, width="stretch",
                     column_config={"call": st.column_config.TextColumn(width="small"),
                                    "rows": st.column_config.NumberColumn(width="small"),
                                    "params (as_of injected)": st.column_config.TextColumn(width="large")})
        with st.expander("Full provenance per call", icon=":material/data_object:"):
            by_id = {e["call_id"]: e for e in envelopes}
            picked = st.segmented_control("Graph call", list(by_id), default=next(iter(by_id)), key=f"call_{choice}")
            e = by_id.get(picked) or envelopes[0]
            st.markdown(f"**{e['call_id']}** · `{e['query']}` · {e['row_count']} row{'' if e['row_count'] == 1 else 's'}")
            st.markdown(f"Executed at `{e['executed_at']}` · tool `{e['tool']}` · reference `{e['ref']}`")
            st.markdown(f"Result SHA-256 `{e['result_sha256']}`")
            st.json({"params": e["params"], "visible_ids": e["visible_ids"]}, expanded=1)
    else:
        st.info("No graph calls were recorded for this run.", icon=":material/info:")
with t_evidence:
    if case["evidence"]:
        st.dataframe(pd.DataFrame([{
            "source": ev["source"] + (f" ({SIM})" if ev["source"] == "customer" and ev["ref"].startswith("evidence_request") else ""),
            "claim": ev["claim"], "reference": ev["ref"], "entities": ", ".join(ev["entity_ids"][:8]) or "-"}
            for ev in case["evidence"]]), hide_index=True, width="stretch",
            column_config={"source": st.column_config.TextColumn(width="small"),
                           "claim": st.column_config.TextColumn(width="large"),
                           "reference": st.column_config.TextColumn(width="medium")})
        st.caption(f"Rows marked {SIM} come from the simulated customer response, not from the dataset.")
    else:
        st.info("The answer file lists no evidence items for this case.", icon=":material/info:")
with t_graph:
    theme_type = st.context.theme.type or "dark"
    pal = ({"fill": "#16213A", "line": "#3B82F6", "font": "#E5E7EB", "edge": "#94A3B8", "device": "#F59E0B",
            "card": "#EF4444", "prior": "#94A3B8"} if theme_type == "dark" else
           {"fill": "#EEF2FF", "line": "#2563EB", "font": "#0F172A", "edge": "#64748B", "device": "#B45309",
            "card": "#DC2626", "prior": "#64748B"})
    dot = ['digraph G { rankdir=LR; bgcolor="transparent"; pad=0.2;',
           f'node [shape=box, style="rounded,filled", fillcolor="{pal["fill"]}", color="{pal["line"]}", '
           f'fontcolor="{pal["font"]}", fontname="Helvetica", fontsize=10]; '
           f'edge [color="{pal["edge"]}", fontcolor="{pal["edge"]}", fontname="Helvetica", fontsize=9];',
           f'{dot_id(row["customer_id"])} -> {dot_id(row["card_id"])} [label=OWNS];',
           f'{dot_id(row["card_id"])} -> {dot_id(row["flagged_txn_id"])} [label="MADE (flagged)"];']
    for t in case["affected_txn_ids"]:
        dot.append(f'{dot_id(row["card_id"])} -> {dot_id(t)} [label=MADE];')
    for d in case["connected_device_profiles"]:
        dot.append(f'{dot_id(d)} [shape=ellipse, color="{pal["device"]}"]; '
                   f'{dot_id(row["card_id"])} -> {dot_id(d)} [label=device];')
    hub = (case["connected_device_profiles"] or [row["card_id"]])[0]
    for k in case["connected_card_ids"][:12]:
        dot.append(f'{dot_id(k)} [color="{pal["card"]}"]; {dot_id(k)} -> {dot_id(hub)} [style=dashed];')
    for p in case["similar_prior_cases"]:
        dot.append(f'{dot_id(p)} [shape=note, color="{pal["prior"]}"]; '
                   f'{dot_id(p)} -> {dot_id(row["card_id"])} [style=dotted, label="prior case"];')
    dot.append("}")
    st.graphviz_chart("\n".join(dot))
    legend = "Boxes: customer, card and transactions. Ellipses: connected device profiles. Red boxes: connected cards"
    if len(case["connected_card_ids"]) > 12:
        legend += f" (first 12 of {len(case['connected_card_ids'])} shown)"
    st.caption(legend + ". Notes: prior closed cases that informed the decision.")

# ---------------------------------------------------------------- 3
section(2)
m1, m2, m3, m4 = st.columns(4)
m1.metric("Initial fraud probability", f"{a0['p']:.2f}", border=True,
          help="Before any evidence request or (simulated) customer response.")
m2.metric("Supporting / exculpatory families", f"{a0['n_support']} / {a0['n_exculpatory']}", border=True)
with m3.container(border=True, height="stretch"):
    st.caption("Pattern (leading hypothesis)")
    st.markdown(f"### {md(case['pattern'])}", anchors=False)
m4.metric("Evidence coverage", f"{a0['coverage']:.0%}", border=True,
          help="Share of the scorer's applicable evidence families that had data for this case.")
st.caption(f"Scorer `{config.SCORER_VERSION}` · policy `{config.POLICY_VERSION}`")
contrib = sorted(({"family": k, "contribution (logit)": v} for k, v in a0["contributions"].items() if v),
                 key=lambda r: -abs(r["contribution (logit)"]))
c1, c2 = st.columns([2, 3])
with c1:
    with st.container(border=True):
        st.markdown("**Non-zero evidence contributions**")
        if contrib:
            st.dataframe(pd.DataFrame(contrib), hide_index=True, width="stretch",
                         column_config={"contribution (logit)": st.column_config.NumberColumn(format="%+.3f")})
        else:
            st.caption("No evidence family contributed; the probability is the fitted base rate.")
with c2:
    with st.container(border=True):
        st.markdown("**Initial next-best actions** (policy engine, README rules R1–R10)")
        st.dataframe(pd.DataFrame([{"action": x["action"], "route": x["route"], "reason": x["reason"]}
                                   for x in nba["initial"]]), hide_index=True, width="stretch",
                     column_config={"route": st.column_config.TextColumn(width="small"),
                                    "reason": st.column_config.TextColumn(width="large")})
        st.caption(f":orange-badge[{SIM}] Actions and approvals are not executed against any real system.")

# ---------------------------------------------------------------- 4
section(3)
if answer["evidence_requests"]:
    for r in answer["evidence_requests"]:
        st.warning(f"Requested after step {md(r['asked_after_step'])}.\n\n{md(r['assumed_response'])}",
                   title=f"{SIM} · {r['type']}", icon=":material/science:")
    st.caption("The dataset provides no customer replies. The response is a deterministic, recorded assumption "
               "derived only from the pre-response probability (ARCHITECTURE.md §13).")
else:
    st.info("No additional evidence was requested for this case (stopping rule or trigger already settled it).",
            icon=":material/info:")

# ---------------------------------------------------------------- 5
section(4)
f1, f2, f3, f4 = st.columns(4)
f1.metric("Verdict", case["verdict"], border=True)
f2.metric("Fraud probability (final)", f"{p1:.2f}", border=True)
with f3.container(border=True, height="stretch"):
    st.caption("Status")
    st.badge(case["status"], color=COLOR.get(case["status"], "gray"))
f4.metric("Exposure", f"${case['exposure_usd']:,.2f}", border=True)
st.markdown(f"**Final next-best actions and approval routes** &nbsp; :orange-badge[{SIM} execution]")
st.dataframe(pd.DataFrame([{
    "action": x["action"], "route": x["route"],
    "execution": f"{SIM}: auto-executed in sandbox" if x["route"] == "auto" else f"{SIM}: awaiting {x['route']} approval",
    "reason": x["reason"]} for x in nba["final"]]), hide_index=True, width="stretch",
    column_config={"action": st.column_config.TextColumn(width="medium"),
                   "route": st.column_config.TextColumn(width="small"),
                   "execution": st.column_config.TextColumn(width="medium"),
                   "reason": st.column_config.TextColumn(width="large")})
w1, w2 = st.columns(2)
with w1:
    with st.container(border=True, height="stretch"):
        st.markdown("**What changed**")
        st.markdown(md(nba["what_changed"]))
        st.markdown("**Stop reason**")
        st.markdown(md(answer["stop_reason"]))
with w2:
    with st.container(border=True, height="stretch"):
        st.markdown("**Summary**")
        st.markdown(md(case["summary"]))
with st.container(border=True):
    st.markdown(f":orange-badge[{SIM}] **Suspicious activity report** · never sent to a regulator")
    st.markdown(f"Decision: **{'file' if sar['file'] else 'do not file'}** · {md(sar['reason'])}")
    if sar["file"]:
        s1, s2, s3 = st.columns(3)
        s1.metric("Total amount", f"${sar['total_amount_usd']:,.2f}")
        s2.metric("Subjects", len(sar["subjects"]))
        s3.metric("Activity dates", len(sar["activity_dates"]))
        st.markdown(f"> {md(sar['narrative'])}")

# ---------------------------------------------------------------- 6
section(5)
g1, g2, g3, g4 = st.columns(4)
g1.metric("Audit hash chain", "verified" if chain_ok else f"broken at event {n_events}", border=True)
g2.metric("Audit events", n_events, border=True)
g3.metric("Graph read-back", readback, border=True)
with g4.container(border=True, height="stretch"):
    st.caption("Graph case vertex")
    st.markdown(f"**`{case['graph_case_id']}`**" if case["graph_case_id"] else ":orange-badge[not written]")
with st.expander("State sequence, persistence details and audit events", icon=":material/receipt_long:"):
    t_states, t_persist, t_log = st.tabs(["State sequence", "Persistence", "Audit log (raw)"])
    with t_states:
        st.markdown(" → ".join(f"`{e['payload']['state']}`" for e in events if e["event"] == "state"))
    with t_persist:
        if persist:
            st.json(persist["payload"], expanded=2)
        else:
            st.info("This run has no persistence event.", icon=":material/info:")
    with t_log:
        st.code((run_dir / "audit.jsonl").read_text(encoding="utf-8")[:30000], language="json")
with st.expander(f"Answer file (cases/{choice}.json)", icon=":material/description:"):
    st.json(answer)
