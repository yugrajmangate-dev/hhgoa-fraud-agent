"""Tests for scripts/inventory_dataset.py.

Fixtures are deliberately generic (col_a, col_b) and do not model the HHGoa dataset.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import inventory_dataset  # noqa: E402


class DefaultPathsTest(unittest.TestCase):
    def test_default_data_dir_is_data_raw(self):
        self.assertEqual(inventory_dataset.DEFAULT_DATA_DIR, PROJECT_ROOT / "data" / "raw")

    def test_default_output_is_outside_data(self):
        out = inventory_dataset.DEFAULT_OUT
        self.assertEqual(out, PROJECT_ROOT / "reports" / "dataset_inventory.json")
        self.assertFalse(out.is_relative_to(PROJECT_ROOT / "data"))


class InventoryDatasetTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.raw = self.tmp / "data" / "raw"
        self.out = self.tmp / "reports" / "inventory.json"

    def tearDown(self):
        self._tmp.cleanup()

    def run_main(self, out=None):
        return inventory_dataset.main(["--data-dir", str(self.raw), "--out", str(out or self.out)])

    def test_missing_directory_is_blocked(self):
        self.assertEqual(self.run_main(), 2)
        self.assertFalse(self.out.exists())

    def test_empty_directory_is_blocked(self):
        self.raw.mkdir(parents=True)
        self.assertEqual(self.run_main(), 2)
        self.assertFalse(self.out.exists())

    def test_directory_with_only_gitkeep_is_blocked(self):
        self.raw.mkdir(parents=True)
        (self.raw / ".gitkeep").write_text("")
        self.assertEqual(self.run_main(), 2)

    def test_output_inside_dataset_dir_is_refused(self):
        self.raw.mkdir(parents=True)
        (self.raw / "README.md").write_text("# readme\n")
        inside = self.raw / "reports" / "inventory.json"
        self.assertEqual(self.run_main(out=inside), 3)
        self.assertFalse((self.raw / "reports").exists())

    def test_missing_readme_warns(self):
        self.raw.mkdir(parents=True)
        (self.raw / "a.csv").write_text("col_a,col_b\n1,2\n")
        self.assertEqual(self.run_main(), 1)
        self.assertTrue(self.out.exists())

    def test_inventory_contents(self):
        (self.raw / "sub").mkdir(parents=True)
        (self.raw / "README.md").write_text("# readme\n")
        (self.raw / "a.csv").write_text('col_a,col_b\n1,"multi\nline"\n3,4\n')
        (self.raw / "b.tsv").write_text("col_a\tcol_b\n1\t2\n")
        (self.raw / "c.json").write_text('{"k2": 1, "k1": 2}')
        (self.raw / "d.json").write_text("[1, 2, 3]")
        (self.raw / "e.json").write_text("{not json")
        (self.raw / "sub" / "f.csv").write_text("col_a\n1\n")
        before = {p: p.read_bytes() for p in self.raw.rglob("*") if p.is_file()}

        self.assertEqual(self.run_main(), 0)
        report = json.loads(self.out.read_text())
        files = {f["path"]: f for f in report["files"]}

        self.assertEqual(report["readme_candidates"], ["README.md"])
        self.assertEqual(report["file_count"], 7)
        self.assertEqual(files["a.csv"]["header"], ["col_a", "col_b"])
        self.assertEqual(files["a.csv"]["data_rows"], 2)  # quoted newline is one row
        self.assertEqual(files["b.tsv"]["column_count"], 2)
        self.assertEqual(files["c.json"]["top_level_keys"], ["k1", "k2"])
        self.assertEqual(files["d.json"]["length"], 3)
        self.assertIn("json_error", files["e.json"])
        self.assertEqual(files["sub/f.csv"]["data_rows"], 1)
        self.assertEqual(len(files["README.md"]["sha256"]), 64)
        # the inventory must never modify the dataset or write into it
        after = {p: p.read_bytes() for p in self.raw.rglob("*") if p.is_file()}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
