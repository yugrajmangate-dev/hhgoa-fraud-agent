"""Tests for scripts/profile_dataset.py (generic fixtures only)."""

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import profile_dataset as pd_mod  # noqa: E402


class ProfileSeriesTest(unittest.TestCase):
    def test_types_and_blanks(self):
        p = pd_mod.profile_series(pd.Series(["1", "2", "", "3"]))
        self.assertEqual((p["type"], p["blank"], p["distinct"], p["min"], p["max"]),
                         ("integer", 1, 3, 1.0, 3.0))
        self.assertEqual(pd_mod.profile_series(pd.Series(["1.0", "2.0"]))["type"],
                         "integer-valued, written as N.0")
        self.assertEqual(pd_mod.profile_series(pd.Series(["1.5", "2"]))["type"], "decimal")
        self.assertEqual(pd_mod.profile_series(pd.Series(["2016-07-02 00:00:01"]))["type"], "timestamp")
        self.assertEqual(pd_mod.profile_series(pd.Series(["a", "b", "a"]))["top"], {"a": 2, "b": 1})
        self.assertEqual(pd_mod.profile_series(pd.Series(["", ""]))["type"], "empty")

    def test_pipes_escaped_for_markdown(self):
        p = pd_mod.profile_series(pd.Series(["x|y", "x|y", "z"]))
        self.assertIn("x\\|y", pd_mod.fmt_range(p))

    def test_v_blocks_group_consecutive_equal_blank_counts(self):
        rows = [{"column": c, "blank": b, "type": "decimal"}
                for c, b in [("V1", 5), ("V2", 5), ("V3", 7), ("V4", 5), ("C1", 5)]]
        blocks = pd_mod.v_blocks(rows)
        self.assertEqual([[c["column"] for c in b["cols"]] for b in blocks], [["V1", "V2"], ["V3"], ["V4"]])

    def test_meaning_lookup(self):
        self.assertIn("Vesta", pd_mod.meaning("V127"))
        self.assertIn("Counts", pd_mod.meaning("C3"))
        self.assertIn("rating", pd_mod.meaning("id_05"))
        self.assertEqual(pd_mod.meaning("id_30"), "OS")


if __name__ == "__main__":
    unittest.main()
