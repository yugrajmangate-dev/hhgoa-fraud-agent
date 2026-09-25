"""Tests for scripts/check_architecture.py.

Runs the checker on the real ARCHITECTURE.md, then on mutated copies to prove each
safeguard actually fails when the document drifts from the README.
"""

import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import check_architecture as ca  # noqa: E402


@unittest.skipUnless(ca.DEFAULT_README.is_file() and ca.DEFAULT_DOC.is_file(),
                     "README or ARCHITECTURE.md not present")
class CheckArchitectureTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.text = ca.DEFAULT_DOC.read_text(encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def failures(self, text):
        path = Path(self._tmp.name) / "ARCHITECTURE.md"
        path.write_text(text, encoding="utf-8")
        return [name for name, ok, _ in ca.run(path, ca.DEFAULT_README).items if not ok]

    def mutate(self, old, new):
        self.assertIn(old, self.text)
        return self.text.replace(old, new, 1)

    def test_real_document_passes(self):
        self.assertEqual(self.failures(self.text), [])

    def test_query_without_as_of_fails(self):
        bad = self.mutate("`as_of DATETIME, txn_id STRING`", "`txn_id STRING`")
        self.assertIn("queries: every query's first input is as_of DATETIME", self.failures(bad))

    def test_missing_answer_field_fails(self):
        bad = self.mutate('"stop_reason": {"type": "string", "minLength": 1},', "")
        self.assertIn("schema: top level fields equal README", self.failures(bad))

    def test_wrong_route_fails(self):
        bad = self.mutate("| 9 | `FILE_REPORT` | `L2` |", "| 9 | `FILE_REPORT` | `auto` |")
        self.assertIn("actions: routes match README approval routing", self.failures(bad))

    def test_llm_callable_write_fails(self):
        bad = self.mutate("| `write_case` | `upsert_investigation_case` | no |",
                          "| `write_case` | `upsert_investigation_case` | yes |")
        self.assertIn("tools: write queries are not LLM-callable", self.failures(bad))

    def test_undeclared_edge_endpoint_fails(self):
        bad = self.mutate("| `OWNS` | `Customer` | `Card` |", "| `OWNS` | `Person` | `Card` |")
        self.assertIn("graph: edge endpoints are declared vertices", self.failures(bad))

    def test_probability_out_of_range_fails(self):
        bad = self.mutate('"fraud_probability": {"type": "number", "minimum": 0, "maximum": 1}',
                          '"fraud_probability": {"type": "number", "minimum": 0, "maximum": 100}')
        self.assertIn("schema: fraud_probability is a number in [0, 1]", self.failures(bad))


if __name__ == "__main__":
    unittest.main()
