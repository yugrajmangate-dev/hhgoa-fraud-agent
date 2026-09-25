"""Documentation and schema-consistency checks for ARCHITECTURE.md.

Checks ARCHITECTURE.md against data/raw/README.md (the authoritative spec). It reads both
files only and implements no system behaviour:

  sections   the 20 required sections are present, in order
  schema     the case JSON Schema is valid draft 2020-12, and its fields and enums equal
             the README Answer Format and Fraud Policy
  example    the README example fails only on its documented non-dataset ID formats, and
             validates once those ID patterns are relaxed
  queries    every GSQL query takes as_of DATETIME as its first input; IDs and names unique
  tools      every tool maps to a catalogued query; write queries are never LLM-callable
  graph      every edge endpoint is a declared vertex; README-suggested schema present
  actions    the canonical action table matches the README actions and approval routes
  mermaid    diagram blocks are present and use known diagram types

Exit code 0 if every check passes, 1 otherwise.
"""

import argparse
import copy
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC = PROJECT_ROOT / "ARCHITECTURE.md"
DEFAULT_README = PROJECT_ROOT / "data" / "raw" / "README.md"

REQUIRED_SECTIONS = [
    "System architecture", "TigerGraph vertex and edge schema",
    "Derived `card_id` strategy and validation plan", "`as_of` filtering and temporal-safety rules",
    "GSQL query catalog", "TigerGraph loading strategy", "TigerGraph MCP / tool-layer design",
    "GraphRAG and prior-case memory design", "Agent state machine", "Deterministic policy-engine design",
    "Case JSON schema", "Initial and final next-best-action flow", "Additional-evidence simulation design",
    "Approval-routing design", "SAR-generation design", "Graph case-write and idempotency design",
    "UI design", "Evaluation and test strategy", "Demo plan", "Risks and mitigations",
]
# The README example uses "T0412877"-style transaction IDs (DATASET_NOTES.md §9); only these
# schema paths may fail on it.
EXAMPLE_EXPECTED_FAILURES = {"case/affected_txn_ids/0", "case/affected_txn_ids/1",
                             "case/affected_txn_ids/2", "case/affected_txn_ids/3",
                             "case/first_suspicious_txn_id"}
MERMAID_TYPES = {"flowchart", "stateDiagram-v2", "sequenceDiagram"}
WRITE_QUERIES = {"upsert_investigation_case", "verify_investigation_case", "delete_case_edges"}


class Results:
    def __init__(self):
        self.items = []

    def check(self, name, ok, detail=""):
        self.items.append((name, bool(ok), detail))
        return ok

    @property
    def failed(self):
        return [i for i in self.items if not i[1]]


# ---------------------------------------------------------------- markdown helpers

def ticks(text):
    return re.findall(r"`([^`]+)`", text)


def split_row(line):
    cells = re.split(r"(?<!\\)\|", line.strip().strip("|"))
    return [c.strip().replace("\\|", "|") for c in cells]


def table_after(lines, header_prefix):
    """Rows (as cell lists) of the first table whose header row starts with header_prefix."""
    for i, line in enumerate(lines):
        if line.strip().startswith(header_prefix):
            rows = []
            for row in lines[i + 2:]:
                if not row.strip().startswith("|"):
                    break
                rows.append(split_row(row))
            return rows
    return []


def section_lines(lines, heading):
    """Lines after an exact heading line up to the next heading of the same or higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    for i, line in enumerate(lines):
        if line.strip() == heading:
            out = []
            for row in lines[i + 1:]:
                m = re.match(r"^(#+) ", row)
                if m and len(m.group(1)) <= level:
                    break
                out.append(row)
            return out
    return []


def fenced_block_after(text, marker, lang):
    idx = text.find(marker)
    if idx < 0:
        return None
    m = re.search(r"```" + lang + r"\n(.*?)\n```", text[idx:], re.S)
    return m.group(1) if m else None


# ---------------------------------------------------------------- README spec

def readme_spec(readme_text):
    lines = readme_text.splitlines()

    def fields(heading):
        return {ticks(r[0])[0]: r for r in table_after(section_lines(lines, heading), "| Field")}

    top = fields("#### Top level")
    case = fields("#### Part 1: `case`")
    sar = fields("#### Part 2: `sar`")
    nba = fields("#### Part 3: `next_best_actions`")

    def enum_in(cell, key):
        m = re.search(r"`" + key + r"`\s*\(([^)]*)\)", cell)
        return set(ticks(m.group(1))) if m else set()

    source_enum = enum_in(case["evidence"][2], "source")
    request_enum = enum_in(top["evidence_requests"][2], "type")
    route_enum = enum_in(nba["initial"][2], "route")
    # The enum is the first non-empty line (values separated by "·"); the prose after it
    # mentions other fields such as pattern_description.
    pattern_line = next(l for l in section_lines(lines, "### `pattern` values") if l.strip())
    actions = [ticks(r[0])[0] for r in table_after(section_lines(lines, "### 1. Actions"), "| Action")]
    routing = {}
    for row in table_after(section_lines(lines, "### 2. Approval routing"), "| Route"):
        route = ticks(row[0])[0]
        for action in ticks(row[1]):
            routing.setdefault(action, set()).add(route)
    return {
        "top_fields": set(top), "case_fields": set(case), "sar_fields": set(sar), "nba_fields": set(nba),
        "evidence_item_fields": set(ticks(case["evidence"][2])) - source_enum,
        "request_fields": set(ticks(top["evidence_requests"][2])) - request_enum,
        "action_item_fields": set(ticks(nba["initial"][2])) - route_enum,
        "status": set(ticks(case["status"][1])), "verdict": set(ticks(case["verdict"][1])),
        "source": source_enum, "request_type": request_enum, "route": route_enum,
        "pattern": set(ticks(pattern_line)), "actions": set(actions), "routing": routing,
        "example": json.loads(fenced_block_after(readme_text, "### Example", "json")),
    }


# ---------------------------------------------------------------- checks

def check_sections(r, lines):
    found = [(int(m.group(1)), m.group(2).strip()) for m in
             (re.match(r"^## (\d+)\. (.+)$", line) for line in lines) if m]
    r.check("sections: 20 numbered sections in order", [n for n, _ in found] == list(range(1, 21)),
            [n for n, _ in found])
    r.check("sections: required titles", [t for _, t in found] == REQUIRED_SECTIONS,
            [t for (_, t), want in zip(found, REQUIRED_SECTIONS) if t != want])


def check_schema(r, schema, spec):
    try:
        Draft202012Validator.check_schema(schema)
        r.check("schema: valid draft 2020-12", True)
    except Exception as exc:  # noqa: BLE001 - report any schema error
        r.check("schema: valid draft 2020-12", False, str(exc)[:300])
        return
    d = schema["$defs"]

    def props(obj):
        return set(obj["properties"]), set(obj.get("required", []))

    for label, obj, want in [("top level", schema, spec["top_fields"]), ("case", d["case"], spec["case_fields"]),
                             ("sar", d["sar"], spec["sar_fields"]),
                             ("next_best_actions", d["next_best_actions"], spec["nba_fields"]),
                             ("evidence item", d["evidence_item"], spec["evidence_item_fields"]),
                             ("evidence request", d["evidence_request"], spec["request_fields"]),
                             ("action item", d["action_item"], spec["action_item_fields"])]:
        have, required = props(obj)
        r.check(f"schema: {label} fields equal README", have == want,
                {"missing": sorted(want - have), "extra": sorted(have - want)})
        r.check(f"schema: {label} all fields required", required == have, sorted(have - required))
        r.check(f"schema: {label} closed (additionalProperties false)",
                obj.get("additionalProperties") is False)
    enums = [("status", set(d["case"]["properties"]["status"]["enum"])),
             ("verdict", set(d["case"]["properties"]["verdict"]["enum"])),
             ("source", set(d["evidence_item"]["properties"]["source"]["enum"])),
             ("request_type", set(d["evidence_request"]["properties"]["type"]["enum"])),
             ("route", set(d["route"]["enum"])), ("pattern", set(d["pattern"]["enum"])),
             ("actions", set(d["action"]["enum"]))]
    for name, have in enums:
        r.check(f"schema: enum {name} equals README", have == spec[name],
                {"missing": sorted(spec[name] - have), "extra": sorted(have - spec[name])})
    fp = d["case"]["properties"]["fraud_probability"]
    r.check("schema: fraud_probability is a number in [0, 1]",
            fp.get("type") == "number" and fp.get("minimum") == 0 and fp.get("maximum") == 1)


def check_example(r, schema, spec):
    errors = Draft202012Validator(schema).iter_errors(spec["example"])
    paths = {"/".join(str(p) for p in e.absolute_path) for e in errors}
    r.check("example: fails only on documented non-dataset transaction ID formats",
            paths == EXAMPLE_EXPECTED_FAILURES, sorted(paths ^ EXAMPLE_EXPECTED_FAILURES))
    relaxed = copy.deepcopy(schema)
    relaxed["$defs"]["txn_id"].pop("pattern", None)
    remaining = [e.message for e in Draft202012Validator(relaxed).iter_errors(spec["example"])]
    r.check("example: validates with ID patterns relaxed", not remaining, remaining[:5])


def check_queries(r, lines):
    rows = table_after(lines, "| ID | Query | Inputs")
    r.check("queries: catalog present", len(rows) > 0, len(rows))
    ids = [row[0] for row in rows]
    names = [ticks(row[1])[0] for row in rows]
    r.check("queries: IDs sequential Q01..", ids == [f"Q{n:02d}" for n in range(1, len(rows) + 1)], ids)
    r.check("queries: names unique", len(set(names)) == len(names))
    no_asof = [name for name, row in zip(names, rows)
               if not (ticks(row[2]) and ticks(row[2])[0].startswith("as_of DATETIME"))]
    r.check("queries: every query's first input is as_of DATETIME", not no_asof, no_asof)
    return set(names)


def check_tools(r, lines, query_names):
    rows = table_after(lines, "| Tool (LLM-facing) | Backing query")
    r.check("tools: table present", len(rows) > 0)
    unknown = [ticks(row[1])[0] for row in rows if ticks(row[1])[0] not in query_names]
    r.check("tools: every backing query is catalogued", not unknown, unknown)
    llm_writes = [ticks(row[0])[0] for row in rows
                  if ticks(row[1])[0] in WRITE_QUERIES and row[2].strip().lower() != "no"]
    r.check("tools: write queries are not LLM-callable", not llm_writes, llm_writes)


def check_graph(r, lines, readme_text):
    vertices = {ticks(row[0])[0] for row in table_after(lines, "| Vertex | Primary key")}
    edges = {}
    for row in table_after(lines, "| Edge | From | To"):
        edges[ticks(row[0])[0]] = (set(ticks(row[1])), set(ticks(row[2])))
    bad = sorted(f"{e}:{v}" for e, (f, t) in edges.items() for v in f | t if v not in vertices)
    r.check("graph: edge endpoints are declared vertices", not bad, bad)
    m = re.search(r"\*\*Vertices:\*\*(.*)", readme_text)
    suggested_v = set(ticks(m.group(1))) if m else set()
    r.check("graph: README-suggested vertices present", suggested_v and suggested_v <= vertices,
            sorted(suggested_v - vertices))
    triples = re.findall(r"`(\w+)` → `(\w+)` → `(\w+)`", readme_text)
    missing = [f"{a}-{e}->{b}" for a, e, b in triples
               if e not in edges or a not in edges[e][0] or b not in edges[e][1]]
    r.check("graph: README-suggested edges present", triples and not missing, missing)


def check_actions(r, lines, spec):
    rows = table_after(lines, "| Order | Action | Route rule")
    table = {ticks(row[1])[0]: set(re.findall(r"`(auto|L1|L2)`", row[2])) for row in rows}
    r.check("actions: canonical table covers exactly the README actions", set(table) == spec["actions"],
            {"missing": sorted(spec["actions"] - set(table)), "extra": sorted(set(table) - spec["actions"])})
    wrong = {a: (sorted(table.get(a, set())), sorted(routes)) for a, routes in spec["routing"].items()
             if table.get(a) != routes}
    r.check("actions: routes match README approval routing", not wrong, wrong)
    orders = [int(row[0]) for row in rows]
    r.check("actions: canonical order is 1..n", orders == list(range(1, len(rows) + 1)))


def check_mermaid(r, text):
    blocks = re.findall(r"```mermaid\n(.*?)\n```", text, re.S)
    r.check("mermaid: at least 4 diagrams", len(blocks) >= 4, len(blocks))
    kinds = [b.strip().split()[0] for b in blocks]
    r.check("mermaid: known diagram types", all(k in MERMAID_TYPES for k in kinds), kinds)
    odd = [i for i, b in enumerate(blocks) if any(line.count('"') % 2 for line in b.splitlines())]
    r.check("mermaid: balanced quotes on every line", not odd, odd)


def run(doc_path: Path, readme_path: Path) -> Results:
    r = Results()
    text = doc_path.read_text(encoding="utf-8")
    readme_text = readme_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    spec = readme_spec(readme_text)
    check_sections(r, lines)
    raw_schema = fenced_block_after(text, "<!-- check:case-schema -->", "json")
    if r.check("schema: block present after marker", raw_schema is not None):
        try:
            schema = json.loads(raw_schema)
        except json.JSONDecodeError as exc:
            r.check("schema: parses as JSON", False, str(exc))
        else:
            check_schema(r, schema, spec)
            check_example(r, schema, spec)
    query_names = check_queries(r, lines)
    check_tools(r, lines, query_names)
    check_graph(r, lines, readme_text)
    check_actions(r, lines, spec)
    check_mermaid(r, text)
    return r


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--doc", type=Path, default=DEFAULT_DOC)
    parser.add_argument("--readme", type=Path, default=DEFAULT_README)
    args = parser.parse_args(argv)
    results = run(args.doc, args.readme)
    for name, ok, detail in results.items:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok or detail == "" else f"  -> {detail}"))
    print(f"{len(results.items) - len(results.failed)} passed, {len(results.failed)} failed")
    return 1 if results.failed else 0


if __name__ == "__main__":
    sys.exit(main())
