"""GraphRAG knowledge corpus from the dataset README: Fraud Policy rules and sections,
and the documented fraud patterns. Regulatory documents are deferred (Phase 1)."""

import hashlib
import re
from pathlib import Path

PATTERN_NAMES = ["card_testing", "card_not_present_fraud", "card_not_present_new_device",
                 "out_of_region_use", "account_takeover"]
POLICY_SECTIONS = {"### 0.": "§0", "### 1.": "§1", "### 2.": "§2", "### 3a.": "§3a", "### 3b.": "§3b",
                   "### 4.": "§4", "### 5.": "§5", "### 6.": "§6", "### 7.": "§7"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\t", " ")).strip()


def chunks(readme_text: str) -> list:
    """Deterministic chunks: one per policy rule R1-R10, one per policy section, one per
    documented pattern, plus the 'Things to know' list."""
    out = []
    lines = readme_text.splitlines()

    def add(chunk_id, source, section, text, links):
        text = _clean(text)
        out.append({"chunk_id": chunk_id, "source": source, "section": section, "text": text,
                    "url": "data/raw/README.md", "sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "links": links})

    for line in lines:
        m = re.match(r"\*\*(R\d+)\. (.+?)\*\* (.*)", line)
        if m:
            add(f"policy-{m.group(1)}", "policy", m.group(1), f"{m.group(1)}. {m.group(2)} {m.group(3)}",
                [m.group(1)])
    # policy sections (text until next ### heading)
    policy_start = next(i for i, l in enumerate(lines) if l.strip() == "# Fraud Policy")
    policy_end = next(i for i, l in enumerate(lines) if l.strip() == "# Answer Format")
    current, buf = None, []
    for line in lines[policy_start:policy_end] + ["### end"]:
        head = next((sec for prefix, sec in POLICY_SECTIONS.items() if line.startswith(prefix)), None)
        if line.startswith("### "):
            if current and current != "§3":
                add(f"policy-{current.strip('§')}", "policy", current, " ".join(buf), [rule_vertex_id(current)])
            current, buf = head, [line.lstrip("# ")]
            if line.startswith("### 3. Rules"):
                current = "§3"
        elif current:
            buf.append(line)
    for i, name in enumerate(PATTERN_NAMES, start=1):
        line = next(l for l in lines if l.startswith(f"**{i}. "))
        add(f"pattern-{name}", "pattern", name, line.replace("**", ""), [name])
    start = next(i for i, l in enumerate(lines) if l.strip() == "## Things to know")
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## "):
            break
        body.append(line)
    add("readme-things-to-know", "readme", "Things to know", " ".join(body), [])
    return out


def rule_vertex_id(rule: str) -> str:
    """ASCII PolicyRule vertex ID: '§3a' -> 'S3a' (avoids URL-encoding issues); R-rules unchanged."""
    return rule.replace("§", "S")


def policy_rule_ids() -> list:
    return [f"R{i}" for i in range(1, 11)] + ["S3a", "S3b", "S4", "S5", "S6", "S7"]


def load_readme(path: Path) -> str:
    return path.read_text(encoding="utf-8")
