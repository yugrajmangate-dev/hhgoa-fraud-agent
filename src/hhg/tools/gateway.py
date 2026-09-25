"""Controlled tool layer in front of the official TigerGraph MCP server (ARCHITECTURE.md §7).

Path: orchestrator -> Gateway (allow-list, server-side as_of injection, known-entity check,
budget, provenance envelope, leakage post-check) -> MCP client (stdio) -> official
`tigergraph-mcp` (started with --allowed-tools limited to the three tools used) -> Savanna.
"""

import hashlib
import json
import re
import sys
from contextlib import AsyncExitStack
from datetime import datetime, timezone
from pathlib import Path

from hhg import config

MCP_TOOLS = "run_installed_query,add_nodes,add_edges"

# LLM-callable read tools -> (installed query, {param: entity kind that must be known})
READ_TOOLS = {
    "get_transaction": ("get_transaction", {"txn": "txn"}),
    "customer_cards": ("customer_cards", {"customer": "customer"}),
    "card_history": ("card_history", {"card": "card"}),
    "shared_origin_scan": ("shared_origin_scan", {"card": "card"}),
    "shared_device_components": ("shared_device_components", {"seed": "device"}),
    "case_history": ("case_history", {"customer": "customer"}),
    "related_cases_structural": ("related_cases_structural", {"card": "card"}),
    "similar_cases": ("similar_cases_vector", {}),
    "knowledge_search": ("knowledge_search", {}),
}
WRITE_QUERIES = {"clear_case_edges": "delete_case_edges", "verify_case": "verify_investigation_case"}
TIME_ATTRS = {"ts": "le", "closed_at": "le", "case_as_of": "lt"}


class ToolDenied(RuntimeError):
    pass


class LeakageError(RuntimeError):
    pass


class ToolError(RuntimeError):
    pass


def parse_mcp_text(text: str) -> dict:
    """The official server returns text whose first ```json block is the ToolResponse."""
    m = re.search(r"```json\n(.*?)\n```", text, re.S)
    if not m:
        raise ToolError(f"unparseable MCP response: {text[:200]}")
    return json.loads(m.group(1))


class MCPTransport:
    """stdio MCP client to the official tigergraph-mcp server."""

    def __init__(self, env_file: Path = config.ENV_FILE):
        self.env_file = env_file
        self._stack = None
        self.session = None

    async def start(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        exe = Path(sys.executable).parent / ("tigergraph-mcp.exe" if sys.platform == "win32" else "tigergraph-mcp")
        params = StdioServerParameters(command=str(exe), args=[
            "--env-file", str(self.env_file), "--allowed-tools", MCP_TOOLS])
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        return self

    async def call(self, tool: str, args: dict) -> dict:
        res = await self.session.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") for c in res.content)
        return parse_mcp_text(text)

    async def close(self):
        if self._stack:
            await self._stack.aclose()


def _walk_vertices(obj):
    if isinstance(obj, dict):
        if "v_id" in obj and "v_type" in obj:
            yield obj
        for v in obj.values():
            yield from _walk_vertices(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_vertices(v)


def _attr(vertex: dict, name: str):
    for k, v in (vertex.get("attributes") or {}).items():
        if k.split(".")[-1] == name:
            return v
    return None


class Gateway:
    def __init__(self, transport, *, case_id: str, as_of: str, run_id: str, audit, seeds: dict,
                 max_calls: int = config.T["max_tool_calls"], graph: str = config.GRAPH_NAME):
        self.transport, self.case_id, self.as_of, self.run_id = transport, case_id, as_of, run_id
        self.audit, self.max_calls, self.graph = audit, max_calls, graph
        self.known = {kind: set(ids) for kind, ids in seeds.items()}
        self.envelopes = []
        self.read_calls = 0

    # ---------------------------------------------------------------- guards
    def learn(self, kind: str, ids):
        self.known.setdefault(kind, set()).update(i for i in ids if i)

    def _check_known(self, tool, params, spec):
        for param, kind in spec.items():
            if params.get(param) not in self.known.get(kind, set()):
                raise ToolDenied(f"{tool}: {param}={params.get(param)!r} is not a known {kind} for this case")

    def post_check(self, result):
        as_of = self.as_of
        for v in _walk_vertices(result):
            for attr, op in TIME_ATTRS.items():
                val = _attr(v, attr)
                if val in (None, ""):
                    continue
                if (op == "le" and str(val) > as_of) or (op == "lt" and str(val) >= as_of):
                    raise LeakageError(f"{v['v_type']} {v['v_id']} has {attr}={val} vs as_of {as_of}")

    # ---------------------------------------------------------------- calls
    async def _run(self, query: str, params: dict) -> dict:
        res = await self.transport.call("tigergraph__run_installed_query",
                                        {"query_name": query, "params": params, "graph_name": self.graph})
        if not res.get("success"):
            raise ToolError(f"{query}: {res.get('error') or res.get('summary')}")
        return res["data"]["result"]

    async def call(self, tool: str, **params):
        if tool not in READ_TOOLS:
            raise ToolDenied(f"{tool} is not an allowed read tool")
        if any(k.lower().replace("_", "") in ("asof", "as_of") for k in params):
            raise ToolDenied("as_of is injected by the gateway and may not be supplied")
        query, spec = READ_TOOLS[tool]
        self._check_known(tool, params, spec)
        if self.read_calls >= self.max_calls:
            raise ToolDenied(f"tool budget of {self.max_calls} calls exhausted")
        self.read_calls += 1
        full = {"as_of": self.as_of, **params}
        result = await self._run(query, full)
        self.post_check(result)
        self._auto_learn(result)
        return result, self._envelope(tool, query, full, result)

    KIND = {"Transaction": "txn", "Card": "card", "Customer": "customer", "DeviceProfile": "device",
            "ClosedCase": "closed", "InvestigationCase": "agent_case", "BillingRegion": "region",
            "EmailDomain": "email"}

    def _auto_learn(self, result):
        for v in _walk_vertices(result):
            kind = self.KIND.get(v["v_type"])
            if kind:
                self.learn(kind, [str(v["v_id"])])
            pk = _attr(v, "profile_key")
            if pk:
                self.learn("device", [pk])
            for key in ("fraud_closed_cases", "@fraud_closed_cases"):
                ids = _attr(v, key.lstrip("@")) or _attr(v, key)
                if isinstance(ids, list):
                    self.learn("closed", [str(i) for i in ids])
            for key in ("@fraud_agent_cases",):
                ids = _attr(v, key)
                if isinstance(ids, list):
                    self.learn("agent_case", [str(i) for i in ids])
            for key in ("card_id", "customer_id"):
                val = _attr(v, key)
                if val:
                    self.learn("card" if key == "card_id" else "customer", [str(val)])

    def known_ids(self) -> set:
        return set().union(*self.known.values()) if self.known else set()

    def _envelope(self, tool, query, params, result):
        vids = sorted({str(v["v_id"]) for v in _walk_vertices(result)})
        shown = {k: (f"<{len(v)} values>" if isinstance(v, list) else v) for k, v in params.items()}
        env = {
            "call_id": f"call-{len(self.envelopes) + 1}", "tool": tool, "query": query, "params": shown,
            "executed_at": datetime.now(timezone.utc).isoformat(), "row_count": len(vids),
            "visible_ids": vids,
            "result_sha256": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
            "ref": f"query:{query}(" + ", ".join(f"{k}={v}" for k, v in shown.items()) + ")",
        }
        env["ref"] += f"#{env['call_id']}"
        self.envelopes.append(env)
        self.audit.append("tool_call", {k: env[k] for k in env if k != "visible_ids"} | {"n_visible": len(vids)})
        return env

    # ---------------------------------------------------------------- writer role (orchestrator only)
    async def write_query(self, name: str, **params):
        query = WRITE_QUERIES[name]
        result = await self._run(query, {"as_of": self.as_of, **params})
        self.audit.append("write_call", {"query": query, "params": params})
        return result

    async def add_nodes(self, vertex_type: str, id_field: str, vertices: list):
        res = await self.transport.call("tigergraph__add_nodes", {
            "vertex_type": vertex_type, "vertex_id": id_field, "vertices": vertices, "graph_name": self.graph})
        if not res.get("success"):
            raise ToolError(f"add_nodes {vertex_type}: {res.get('error') or res.get('summary')}")
        self.audit.append("write_call", {"tool": "add_nodes", "vertex_type": vertex_type, "n": len(vertices)})
        return res

    async def add_edges(self, edge_type: str, edges: list):
        if not edges:
            return None
        res = await self.transport.call("tigergraph__add_edges", {
            "edge_type": edge_type, "edges": edges, "graph_name": self.graph})
        if not res.get("success"):
            raise ToolError(f"add_edges {edge_type}: {res.get('error') or res.get('summary')}")
        self.audit.append("write_call", {"tool": "add_edges", "edge_type": edge_type, "n": len(edges)})
        return res
