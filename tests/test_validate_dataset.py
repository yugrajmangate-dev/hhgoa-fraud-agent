"""Tests for scripts/validate_dataset.py.

Unit tests use tiny generic fixtures. The integration test runs every check against the
real dataset and is skipped when data/raw/ is absent.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
import validate_dataset as vd  # noqa: E402


class HelperTest(unittest.TestCase):
    def test_derive_card_ids_ranks_card6_lexically_with_blank_first(self):
        txn = pd.DataFrame({
            "customer_id": ["C00001", "C00001", "C00001", "C00002", "C00003", "C00003"],
            "card6": ["debit", "", "credit", "debit", "debit", "debit or credit"],
        })
        self.assertEqual(vd.derive_card_ids(txn).tolist(),
                         ["C00001-K3", "C00001-K1", "C00001-K2", "C00002-K1",
                          "C00003-K1", "C00003-K2"])

    def test_expected_case_ids(self):
        self.assertTrue(vd.expected_case_ids_ok([f"HHG-{n:03d}" for n in range(1, 21)]))
        self.assertFalse(vd.expected_case_ids_ok([f"HHG-{n:03d}" for n in range(1, 20)]))
        self.assertFalse(vd.expected_case_ids_ok([f"HHG-{n:03d}" for n in range(20, 0, -1)]))

    def test_split_pipe_ignores_blanks(self):
        self.assertEqual(vd.split_pipe(""), [])
        self.assertEqual(vd.split_pipe("a|b|"), ["a", "b"])

    def test_parse_ts_rejects_other_formats(self):
        parsed = vd.parse_ts(pd.Series(["2016-07-02 00:00:01", "2016-07-02T00:00:01", "02/07/2016"]))
        self.assertEqual(parsed.isna().tolist(), [False, True, True])


class IntegrityTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.raw = tmp / "data" / "raw"
        self.raw.mkdir(parents=True)
        for name in vd.EXPECTED_FILES:
            (self.raw / name).write_text(f"placeholder {name}\n")
        self.baseline = tmp / "config" / "manifest.json"
        self.out = tmp / "reports" / "validation.json"

    def tearDown(self):
        self._tmp.cleanup()

    def args(self, *extra):
        return ["--data-dir", str(self.raw), "--baseline", str(self.baseline),
                "--out", str(self.out), *extra]

    def integrity_statuses(self):
        report = vd.Report()
        vd.check_integrity(report, self.raw, self.baseline)
        return {c["id"]: c["status"] for c in report.checks}

    def test_write_baseline_then_refuse_overwrite(self):
        self.assertEqual(vd.main(self.args("--write-baseline")), 0)
        files = json.loads(self.baseline.read_text())["files"]
        self.assertEqual(sorted(files), sorted(vd.EXPECTED_FILES))
        self.assertEqual(vd.main(self.args("--write-baseline")), 4)
        self.assertEqual(vd.main(self.args("--write-baseline", "--force")), 0)

    def test_unchanged_files_pass(self):
        vd.main(self.args("--write-baseline"))
        statuses = self.integrity_statuses()
        self.assertTrue(all(s == "pass" for k, s in statuses.items() if k.startswith("integrity:unchanged")))

    def test_modified_file_fails(self):
        vd.main(self.args("--write-baseline"))
        (self.raw / "case_pack.csv").write_text("tampered\n")
        statuses = self.integrity_statuses()
        self.assertEqual(statuses["integrity:unchanged:case_pack.csv"], "fail")
        self.assertEqual(statuses["integrity:unchanged:README.md"], "pass")

    def test_missing_baseline_fails(self):
        self.assertEqual(self.integrity_statuses()["integrity:baseline_present"], "fail")

    def test_missing_file_fails(self):
        vd.main(self.args("--write-baseline"))
        (self.raw / "identity.csv").unlink()
        statuses = self.integrity_statuses()
        self.assertEqual(statuses["file_exists:identity.csv"], "fail")
        self.assertEqual(statuses["integrity:unchanged:identity.csv"], "fail")

    def test_extra_file_warns(self):
        vd.main(self.args("--write-baseline"))
        (self.raw / "notes.txt").write_text("x")
        self.assertEqual(self.integrity_statuses()["integrity:no_extra_files"], "warn")

    def test_output_inside_raw_refused(self):
        inside = ["--data-dir", str(self.raw), "--out", str(self.raw / "v.json")]
        self.assertEqual(vd.main(inside), 3)

    def test_missing_data_dir_blocked(self):
        self.assertEqual(vd.main(["--data-dir", str(self.raw / "nope"), "--out", str(self.out)]), 2)


@unittest.skipUnless((vd.DEFAULT_DATA_DIR / "transactions.csv").is_file()
                     and vd.DEFAULT_BASELINE.is_file(), "official dataset not present")
class RealDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = vd.check_all(vd.DEFAULT_DATA_DIR, vd.DEFAULT_BASELINE)
        cls.status = {c["id"]: c["status"] for c in cls.result["report"].checks}

    def test_no_failed_checks(self):
        failed = [k for k, s in self.status.items() if s == "fail"]
        self.assertEqual(failed, [])

    def test_raw_files_unchanged(self):
        for name in vd.EXPECTED_FILES:
            self.assertEqual(self.status[f"integrity:unchanged:{name}"], "pass")

    def test_known_warnings_only(self):
        warned = sorted(k for k, s in self.status.items() if s == "warn")
        self.assertEqual(warned, ["consistency:first_fraud_txn_is_earliest",
                                  "join:online_transactions_with_identity",
                                  "time:closed_cases.within_july_october"])

    def test_asof_availability_covers_all_cases(self):
        rows = self.result["asof_availability"]
        self.assertEqual([r["case_id"] for r in rows], vd.BENCHMARK_IDS)
        self.assertTrue(all(r["closed_cases_opened_not_closed"] == 0 for r in rows))


if __name__ == "__main__":
    unittest.main()
