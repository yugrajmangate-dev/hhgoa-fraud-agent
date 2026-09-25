"""Checks every positional column in loading.gsql against the staging file headers and the
vertex attribute order in schema.gsql (skipped when staging files are absent)."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GSQL = ROOT / "src" / "hhg" / "graph" / "gsql"
STAGING = ROOT / "data" / "staging"
FILES = {"customers": "customers", "cards": "cards", "devices": "devices", "regions": "regions", "emails": "emails",
         "patterns": "patterns", "rules": "rules", "txns": "transactions.part000", "nxt": "next.part000",
         "cases": "closed_cases.part000", "involves": "cc_involves", "on_card": "cc_on_card",
         "connected": "cc_connected", "first": "cc_first", "pattern": "cc_pattern", "chunks": "knowledge",
         "kc_rule": "kc_rule", "kc_pattern": "kc_pattern"}
# staging column name -> schema attribute name where they differ
RENAME = {"customer_id": "customer_id"}


def header(tag):
    return (STAGING / f"{FILES[tag]}.tsv").read_text(encoding="utf-8").split("\n", 1)[0].split("\t")


def schema_attrs(vertex):
    text = (GSQL / "schema.gsql").read_text(encoding="utf-8")
    body = re.search(rf"ADD VERTEX {vertex} \((.*?)\) WITH", text, re.S).group(1)
    return [a.split()[-2] if a.strip().startswith("PRIMARY_ID") else a.split()[0]
            for a in [x.strip() for x in body.split(",")]]


@unittest.skipUnless((STAGING / "staging_manifest.json").is_file(), "staging files not built")
class LoadingColumnsTest(unittest.TestCase):
    def loads(self):
        text = (GSQL / "loading.gsql").read_text(encoding="utf-8")
        for m in re.finditer(r"LOAD (\w+) (TO .*?)USING", text, re.S):
            clause = m.group(2)
            for target in re.finditer(r"TO (VERTEX|EDGE) (\w+) VALUES \(", clause):
                depth, i = 1, target.end()
                while depth:  # balanced scan so SPLIT(...) does not end the VALUES list
                    depth += {"(": 1, ")": -1}.get(clause[i], 0)
                    i += 1
                yield m.group(1), target.group(1), target.group(2), clause[target.end():i - 1]

    def test_vertex_columns_match_schema_attributes(self):
        for tag, kind, name, values in self.loads():
            if kind != "VERTEX":
                continue
            cols = header(tag)
            idx = [int(i) for i in re.findall(r"\$(\d+)", values)]
            attrs = schema_attrs(name)
            self.assertEqual(len(idx), len(attrs), f"{tag}->{name}: {len(idx)} values vs {len(attrs)} attributes")
            for i, attr in zip(idx, attrs):
                self.assertEqual(cols[i], attr, f"{tag}->{name}: ${i} is '{cols[i]}' but attribute is '{attr}'")

    def test_edge_endpoint_columns(self):
        expect = {"OWNS": ("customer_id", "card_id"), "MADE": ("card_id", "txn_id"),
                  "FROM_DEVICE": ("txn_id", "profile_key"), "PURCHASER_EMAIL": ("txn_id", "p_email"),
                  "RECIPIENT_EMAIL": ("txn_id", "r_email"), "BILLED_IN": ("txn_id", "addr1"),
                  "NEXT": ("from_txn", "to_txn")}
        for tag, kind, name, values in self.loads():
            if kind == "EDGE" and name in expect:
                cols = header(tag)
                idx = [int(i) for i in re.findall(r"\$(\d+)", values)][:2]
                self.assertEqual((cols[idx[0]], cols[idx[1]]), expect[name], f"{tag}->{name}")


if __name__ == "__main__":
    unittest.main()
