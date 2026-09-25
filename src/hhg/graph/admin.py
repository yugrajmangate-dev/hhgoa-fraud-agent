"""Build-time TigerGraph administration (not an agent tool): connect, create schema, load
staging files, install queries, verify the load against ARCHITECTURE.md §2.

    python -m hhg.graph.admin ping|schema|load|install|verify|all
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
from pyTigerGraph import TigerGraphConnection

from hhg import config
from hhg.etl.build import EXPECTED

FULL_AS_OF = "2016-12-31 23:59:59"
LOAD_PLAN = [  # (job, file tag, staging name)
    ("load_entities", "customers", "customers"), ("load_entities", "cards", "cards"),
    ("load_entities", "devices", "devices"), ("load_entities", "regions", "regions"),
    ("load_entities", "emails", "emails"), ("load_entities", "patterns", "patterns"),
    ("load_entities", "rules", "rules"),
    ("load_transactions", "txns", "transactions"), ("load_next", "nxt", "next"),
    ("load_closed_cases", "cases", "closed_cases"), ("load_closed_cases", "involves", "cc_involves"),
    ("load_closed_cases", "on_card", "cc_on_card"), ("load_closed_cases", "connected", "cc_connected"),
    ("load_closed_cases", "first", "cc_first"), ("load_closed_cases", "pattern", "cc_pattern"),
    ("load_knowledge", "chunks", "knowledge"), ("load_knowledge", "kc_rule", "kc_rule"),
    ("load_knowledge", "kc_pattern", "kc_pattern"),
]


def connect(graph: bool = True) -> TigerGraphConnection:
    """Secret-only authentication for both the ping (no graph) and graph connections.

    With gsqlSecret set, pyTigerGraph authenticates GSQL and REST++ requests as the
    '__GSQL__secret' principal with the secret; TG_USERNAME / TG_PASSWORD are never read.
    Graph connections additionally request a REST++ token from the secret (best effort).
    """
    load_dotenv(config.ENV_FILE)
    env = os.environ
    missing = [k for k in ("TG_HOST", "TG_SECRET") if not env.get(k) or "<" in env.get(k, "")]
    if missing:
        raise SystemExit(f"missing or placeholder in .env: {missing}")
    conn = TigerGraphConnection(
        host=env["TG_HOST"], graphname=env.get("TG_GRAPHNAME", config.GRAPH_NAME) if graph else "",
        gsqlSecret=env["TG_SECRET"], tgCloud=env.get("TG_TGCLOUD", "true").lower() == "true",
        restppPort=env.get("TG_RESTPP_PORT", "443"), gsPort=env.get("TG_GS_PORT", "443"))
    assert conn.username == "__GSQL__secret", "secret authentication not applied"
    if graph:
        try:
            conn.getToken(env["TG_SECRET"])
            print("auth: TG_SECRET (GSQL basic-secret + REST++ token)")
        except Exception as exc:  # token endpoint optional when REST++ accepts the secret directly
            print(f"auth: TG_SECRET (GSQL basic-secret; REST++ token not issued: {type(exc).__name__})")
    else:
        print("auth: TG_SECRET (GSQL basic-secret)")
    return conn


def gsql_file(conn, name: str) -> str:
    out = conn.gsql((config.GSQL_DIR / name).read_text(encoding="utf-8"))
    print(out)
    return out


def graph_exists(conn) -> bool:
    return config.GRAPH_NAME in conn.gsql("SHOW GRAPH *")


def cmd_ping():
    conn = connect(graph=False)
    print(conn.gsql("SHOW GRAPH *")[:2000])


def cmd_schema():
    """Idempotent: create the graph if missing; apply the schema job only if the graph has
    no vertex types yet. Never drops anything and never touches other graphs."""
    conn = connect(graph=False)
    if not graph_exists(conn):
        print(conn.gsql(f"CREATE GRAPH {config.GRAPH_NAME}()"))
    types = conn.gsql(f"USE GRAPH {config.GRAPH_NAME}\nSHOW VERTEX *")
    if "Transaction" in types:
        print(f"graph {config.GRAPH_NAME} already has the schema; step skipped")
        return
    out = gsql_file(conn, "schema.gsql")
    if any(w in out.lower() for w in ("encountered", "semantic check fails", "failed")):
        raise SystemExit("schema creation reported errors")


LOAD_JOBS = ["load_entities", "load_transactions", "load_next", "load_closed_cases", "load_knowledge"]


def cmd_load():
    conn = connect()
    existing = conn.gsql(f"USE GRAPH {config.GRAPH_NAME}\nSHOW JOB *")
    ours = [j for j in LOAD_JOBS if re.search(rf"\b{j}\b", existing)]
    if ours:  # only this project's jobs, only in FraudGraph
        print(conn.gsql(f"USE GRAPH {config.GRAPH_NAME}\nDROP JOB {', '.join(ours)}"))
    out = gsql_file(conn, "loading.gsql")
    if any(w in out.lower() for w in ("semantic check fails", "failed to create", "encountered")):
        raise SystemExit("loading job creation failed; nothing loaded")
    manifest = json.loads((config.STAGING_DIR / "staging_manifest.json").read_text())
    only = set(os.environ.get("HHG_LOAD_ONLY", "").split(",")) - {""}
    for job, tag, name in LOAD_PLAN:
        if only and name not in only:
            continue
        for part in manifest["files"][name]["parts"]:
            path = config.STAGING_DIR / part["file"]
            data = path.read_text(encoding="utf-8").split("\n", 1)[1]  # header removed (REST ignores header="true")
            t0 = time.time()
            for attempt in range(3):
                try:
                    res = conn.runLoadingJobWithData(data, tag, job, sep="\t", timeout=600000)
                    break
                except Exception as exc:  # gateway timeouts: upserts are idempotent, so retry is safe
                    print(f"  retry {attempt + 1} after {type(exc).__name__}: {str(exc)[:120]}")
                    time.sleep(10)
            else:
                raise SystemExit(f"load failed for {part['file']}")
            stats = res[0]["statistics"]["parsingStatistics"] if res else {}
            valid = stats.get("fileLevel", {}).get("validLine")
            objects = {o["typeName"]: o["validObject"] for kind in ("vertex", "edge")
                       for o in stats.get("objectLevel", {}).get(kind, [])}
            print(f"{job}/{tag} {part['file']} rows={part['rows']} validLine={valid} {time.time() - t0:.1f}s {objects}")
            if valid != part["rows"]:
                raise SystemExit(f"validLine {valid} != rows {part['rows']} for {part['file']}")
    conn.upsertVertex("DatasetMeta", "current", {
        "raw_manifest_sha256": manifest["raw_manifest_sha256"], "card_rule_version": config.CARD_RULE_VERSION,
        "embedding_model": config.EMBED_VERSION, "schema_version": config.SCHEMA_VERSION,
        "loaded_at": datetime.now(timezone.utc).isoformat()})


def query_names() -> list:
    text = (config.GSQL_DIR / "queries.gsql").read_text(encoding="utf-8")
    return re.findall(r"CREATE QUERY (\w+)\(", text)


def cmd_install():
    conn = connect()
    names = query_names()
    existing = conn.gsql("SHOW QUERY *")
    drops = [n for n in names if re.search(rf"\b{n}\b", existing)]
    if drops:
        print(conn.gsql(f"USE GRAPH {config.GRAPH_NAME}\nDROP QUERY {', '.join(drops)}"))
    gsql_file(conn, "queries.gsql")
    print(conn.gsql(f"USE GRAPH {config.GRAPH_NAME}\nINSTALL QUERY {', '.join(names)}"))


def cmd_verify() -> bool:
    conn = connect()
    res = conn.runInstalledQuery("load_verification_counts", {"as_of": FULL_AS_OF})
    counts = res[0]["counts"]
    ok = True
    for key, want in EXPECTED.items():
        got = counts.get(key)
        mark = "ok" if got == want else "MISMATCH"
        ok &= got == want
        print(f"{mark:8s} {key:16s} expected {want:>8,}  graph {got}")
    print(f"KnowledgeChunk: {counts.get('KnowledgeChunk')}")
    return ok


def main(argv=None) -> int:
    cmd = (argv or sys.argv[1:] or ["ping"])[0]
    steps = {"ping": cmd_ping, "schema": cmd_schema, "load": cmd_load, "install": cmd_install}
    if cmd == "all":
        for step in ("schema", "load", "install"):
            steps[step]()
        return 0 if cmd_verify() else 1
    if cmd == "verify":
        return 0 if cmd_verify() else 1
    steps[cmd]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
