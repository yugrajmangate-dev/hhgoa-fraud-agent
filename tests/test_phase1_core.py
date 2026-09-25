"""Phase 1 unit tests: card_id rule, policy engine, scorer, simulator, gateway guards,
embedding, audit chain, detectors, schema sync. Offline; fixtures are generic."""

import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hhg import config  # noqa: E402
from hhg.audit.log import AuditLog, verify  # noqa: E402
from hhg.casefile.validate import SCHEMA  # noqa: E402
from hhg.detectors import features as fx  # noqa: E402
from hhg.etl.card_id import derive_card_ids  # noqa: E402
from hhg.memory import embed  # noqa: E402
from hhg.policy.engine import PolicyInput, PolicyViolation, decide, route  # noqa: E402
from hhg.scoring import scorer  # noqa: E402
from hhg.simulate import responder  # noqa: E402
from hhg.tools.gateway import Gateway, LeakageError, ToolDenied  # noqa: E402


def pin(**kw):
    base = dict(trigger_type="risk_score", p=0.5, n_support=1, n_exculpatory=0, conflict=False,
                verdict="uncertain", pattern="card_not_present_fraud", exposure=100.0)
    base.update(kw)
    return PolicyInput(**base)


def names(decision):
    return [a["action"] for a in decision.actions]


class CardIdTest(unittest.TestCase):
    def test_rule(self):
        got = derive_card_ids(pd.Series(["C00001", "C00001", "C00001", "C00002"]),
                              pd.Series(["debit", "", "credit", "debit"]))
        self.assertEqual(got.tolist(), ["C00001-K3", "C00001-K1", "C00001-K2", "C00002-K1"])

    def test_matches_validator_script(self):
        import validate_dataset as vd
        df = pd.DataFrame({"customer_id": ["C1", "C1", "C2"], "card6": ["debit", "credit", ""]})
        self.assertEqual(vd.derive_card_ids(df).tolist(), derive_card_ids(df["customer_id"], df["card6"]).tolist())


class RoutingTest(unittest.TestCase):
    def test_routes(self):
        self.assertEqual(route("BLOCK_CARD", 2500.0), "L1")
        self.assertEqual(route("BLOCK_CARD", 2500.01), "L2")
        self.assertEqual(route("FILE_REPORT", 1), "L2")
        self.assertEqual(route("DECLINE_TRANSACTION", 1), "L1")
        self.assertEqual(route("CREATE_CASE", 1e6), "auto")


class PolicyTest(unittest.TestCase):
    def test_r1_verify_and_no_block(self):
        d = decide(pin(p=0.45))
        self.assertIn("VERIFY_WITH_CUSTOMER", names(d))
        self.assertFalse({"BLOCK_CARD", "BLOCK_ALL_CARDS"} & set(names(d)))
        self.assertIn("CREATE_CASE", names(d))  # §3a p >= 0.30

    def test_r1_step_up_for_online_device_signal(self):
        self.assertIn("STEP_UP_AUTH", names(decide(pin(p=0.45, online_device_signal=True))))

    def test_r2_deny_blocks_and_reports_over_1000(self):
        d = decide(pin(p=0.93, n_support=3, verdict="fraud", response="deny", exposure=1500.0,
                       evidence_requested=True))
        self.assertEqual(names(d), ["BLOCK_CARD", "CREATE_CASE", "FILE_REPORT"])
        self.assertEqual({a["action"]: a["route"] for a in d.actions}["FILE_REPORT"], "L2")

    def test_r2_no_report_under_1000_without_link(self):
        d = decide(pin(p=0.93, n_support=3, verdict="fraud", response="deny", exposure=300.0,
                       evidence_requested=True))
        self.assertNotIn("FILE_REPORT", names(d))

    def test_r3_confirm_closes(self):
        d = decide(pin(p=0.03, verdict="legitimate", response="confirm", exposure=0.0, evidence_requested=True))
        self.assertIn("CLOSE_NO_FRAUD", names(d))
        self.assertFalse({"BLOCK_CARD", "FILE_REPORT", "DECLINE_TRANSACTION"} & set(names(d)))

    def test_r4_no_reply_escalates_over_500(self):
        d = decide(pin(p=0.6, response="no_reply", exposure=600.0, evidence_requested=True))
        self.assertTrue({"MONITOR_CARD", "DECLINE_TRANSACTION", "ESCALATE_TO_ANALYST"} <= set(names(d)))
        d2 = decide(pin(p=0.6, response="no_reply", exposure=100.0, evidence_requested=True))
        self.assertNotIn("ESCALATE_TO_ANALYST", names(d2))

    def test_r5_card_testing(self):
        d = decide(pin(p=0.95, n_support=2, verdict="fraud", card_testing=True, cleared_over_100=True,
                       pattern="card_testing"))
        self.assertTrue({"DECLINE_TRANSACTION", "STEP_UP_AUTH", "BLOCK_CARD"} <= set(names(d)))

    def test_r6_shared_origin(self):
        d = decide(pin(p=0.9, n_support=3, verdict="fraud", shared_link=True, shared_cards=2,
                       shared_element="DeviceProfile X", response="deny", evidence_requested=True))
        self.assertTrue({"CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS"} <= set(names(d)))

    def test_r7_recurring_never_blocks(self):
        d = decide(pin(trigger_type="customer_report", p=0.4, recurring_match=True, evidence_requested=True))
        self.assertEqual(names(d), ["VERIFY_WITH_CUSTOMER", "CREATE_CASE", "WARN_CUSTOMER"])

    def test_r8_uncertain_exposed(self):
        self.assertIn("ESCALATE_TO_ANALYST", names(decide(pin(p=0.55, exposure=800.0, n_support=2))))

    def test_r9_undocumented(self):
        d = decide(pin(p=0.9, n_support=3, verdict="fraud", pattern="undocumented", coordinated_cross_customer=True))
        self.assertTrue({"CREATE_CASE", "FILE_REPORT", "ESCALATE_TO_ANALYST"} <= set(names(d)))

    def test_r10_block_all_only_with_condition(self):
        d = decide(pin(p=0.95, n_support=3, verdict="fraud", response="deny", confirmed_fraud_cards=2,
                       customer_visible_cards=2, evidence_requested=True))
        self.assertIn("BLOCK_ALL_CARDS", names(d))
        d2 = decide(pin(p=0.95, n_support=3, verdict="fraud", response="deny", customer_visible_cards=2,
                        evidence_requested=True))
        self.assertNotIn("BLOCK_ALL_CARDS", names(d2))

    def test_legitimate_without_case(self):
        d = decide(pin(p=0.08, n_support=0, n_exculpatory=2, verdict="legitimate", exposure=0.0))
        self.assertEqual(names(d), ["ALLOW_TRANSACTION", "GENERATE_REPORT", "CLOSE_NO_FRAUD"])

    def test_every_reason_cites_a_rule_and_order_is_canonical(self):
        for kw in [dict(p=0.45), dict(p=0.9, n_support=3, verdict="fraud"), dict(p=0.6, response="no_reply")]:
            for a in decide(pin(**kw)).actions:
                self.assertRegex(a["reason"], r"R\d+|§3a|§3b|§6")

    def test_requested_evidence_appears_in_initial_and_no_close(self):
        d = decide(pin(p=0.14, n_support=0, n_exculpatory=1, verdict="uncertain", evidence_requested=True,
                       evidence_request_type="customer_validation"))
        self.assertIn("VERIFY_WITH_CUSTOMER", names(d))
        self.assertIn("CREATE_CASE", names(d))
        self.assertNotIn("CLOSE_NO_FRAUD", names(d))
        d2 = decide(pin(p=0.75, n_support=2, verdict="fraud", evidence_requested=True,
                        evidence_request_type="step_up_auth"))
        self.assertIn("STEP_UP_AUTH", names(d2))

    def test_dispute_is_r2(self):
        d = decide(pin(trigger_type="customer_report", p=0.8, n_support=2, verdict="fraud"))
        self.assertIn("BLOCK_CARD", names(d))
        self.assertIn("CREATE_CASE", names(d))


class ScorerTest(unittest.TestCase):
    def fams(self, **s):
        out = {}
        for name in config.W:
            if name != "F14_familiar":
                out[name] = fx.Family(name, s=s.get(name, 0.0))
        return out

    def test_no_evidence_gives_fitted_intercept(self):
        self.assertEqual(scorer.score(self.fams(), 0).p, round(scorer.sigmoid(config.INTERCEPT), 2))

    def test_bounds_and_determinism(self):
        a = scorer.score(self.fams(F6_testing=1, F8_network=1, F4_device=1), 0)
        self.assertLessEqual(a.p, 0.99)
        self.assertEqual(a, scorer.score(self.fams(F6_testing=1, F8_network=1, F4_device=1), 0))
        self.assertGreaterEqual(scorer.score(self.fams(F13_recurring=1), 3).p, 0.01)

    def test_familiarity_never_raises(self):
        self.assertLessEqual(scorer.score(self.fams(), 3).p, scorer.score(self.fams(), 0).p)

    def test_response_update_and_verdict(self):
        a = scorer.score(self.fams(F4_device=1), 0)
        self.assertEqual(scorer.verdict(scorer.update_with_response(a, "deny"), "deny"), "fraud")
        self.assertEqual(scorer.verdict(scorer.update_with_response(a, "confirm"), "confirm"), "legitimate")

    def test_low_p_on_one_exculpatory_piece_is_uncertain(self):
        a = scorer.score(self.fams(F5_trip=1), 0)   # one exculpatory family only
        self.assertEqual(a.n_exculpatory, 1)
        self.assertEqual(scorer.verdict(a), "uncertain")
        self.assertFalse(scorer.stop_rule_met(a))
        b = scorer.score(self.fams(F13_recurring=1, F5_trip=1), 0)   # two independent exculpatory families
        self.assertEqual(scorer.verdict(b), "legitimate")

    def test_risk_score_has_no_weight(self):
        self.assertEqual(scorer.score(self.fams(F10_risk=1), 0).p, scorer.score(self.fams(), 0).p)


class SimulatorTest(unittest.TestCase):
    def respond(self, p, **kw):
        args = dict(flagged_id="3000001", pattern_hint="card_not_present_fraud", region="100.0",
                    recurring=False, clearance_reason="")
        args.update(kw)
        return responder.respond(p, "customer_validation", **args)

    def test_thresholds(self):
        self.assertEqual(self.respond(0.60)[0], "deny")
        self.assertEqual(self.respond(0.59)[0], "no_reply")
        self.assertEqual(self.respond(0.41)[0], "no_reply")
        self.assertEqual(self.respond(0.40)[0], "confirm")
        self.assertEqual(self.respond(0.9, recurring=True)[0], "confirm")

    def test_marked_simulated(self):
        for p in (0.1, 0.5, 0.9):
            self.assertTrue(self.respond(p)[1].startswith("Simulated: "))


class FakeTransport:
    def __init__(self, result):
        self.result, self.calls = result, []

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return {"success": True, "data": {"result": self.result}}


class GatewayTest(unittest.TestCase):
    def gw(self, result):
        tmp = tempfile.mkdtemp()
        audit = AuditLog(Path(tmp) / "a.jsonl", "r", "HHG-000")
        return Gateway(FakeTransport(result), case_id="HHG-000", as_of="2016-11-12 00:46:24", run_id="r",
                       audit=audit, seeds={"txn": {"3000001"}, "card": {"C00001-K1"}, "customer": {"C00001"}})

    def test_injects_as_of(self):
        g = self.gw([{"txn": []}])
        asyncio.run(g.call("get_transaction", txn="3000001"))
        self.assertEqual(g.transport.calls[0][1]["params"]["as_of"], "2016-11-12 00:46:24")

    def test_rejects_as_of_argument(self):
        with self.assertRaises(ToolDenied):
            asyncio.run(self.gw([{}]).call("get_transaction", txn="3000001", as_of="2016-12-31 00:00:00"))

    def test_rejects_unknown_entity_and_tool(self):
        with self.assertRaises(ToolDenied):
            asyncio.run(self.gw([{}]).call("get_transaction", txn="3999999"))
        with self.assertRaises(ToolDenied):
            asyncio.run(self.gw([{}]).call("gsql", query="DROP ALL"))

    def test_leakage_post_check(self):
        future = [{"txns": [{"v_id": "3000002", "v_type": "Transaction",
                             "attributes": {"ts": "2016-11-12 00:46:25"}}]}]
        with self.assertRaises(LeakageError):
            asyncio.run(self.gw(future).call("card_history", card="C00001-K1", lookback_days=10))
        closed = [{"x": [{"v_id": "CC-0001", "v_type": "ClosedCase", "attributes": {"C.closed_at": "2016-11-13 00:00:00"}}]}]
        with self.assertRaises(LeakageError):
            asyncio.run(self.gw(closed).call("case_history", customer="C00001"))

    def test_boundary_row_at_as_of_is_visible(self):
        ok = [{"txns": [{"v_id": "3000002", "v_type": "Transaction", "attributes": {"ts": "2016-11-12 00:46:24"}}]}]
        res, env = asyncio.run(self.gw(ok).call("card_history", card="C00001-K1", lookback_days=10))
        self.assertIn("3000002", env["visible_ids"])

    def test_budget(self):
        g = self.gw([{}])
        g.max_calls = 1
        asyncio.run(g.call("get_transaction", txn="3000001"))
        with self.assertRaises(ToolDenied):
            asyncio.run(g.call("get_transaction", txn="3000001"))


class EmbedAuditSchemaTest(unittest.TestCase):
    def test_embedding_deterministic_unit(self):
        idf = embed.fit_idf(["card testing small authorizations", "travel to the billing region"])
        a, b = embed.embed("card testing", idf), embed.embed("card testing", idf)
        self.assertTrue((a == b).all())
        self.assertAlmostEqual(float(a @ a), 1.0, places=6)

    def test_audit_chain_detects_tampering(self):
        path = Path(tempfile.mkdtemp()) / "a.jsonl"
        log = AuditLog(path, "r", "HHG-000")
        for i in range(3):
            log.append("e", {"i": i})
        self.assertEqual(verify(path), (True, 3))
        lines = path.read_text().splitlines()
        lines[1] = lines[1].replace('"i": 1', '"i": 9')
        path.write_text("\n".join(lines) + "\n")
        self.assertFalse(verify(path)[0])

    def test_schema_in_sync_with_architecture(self):
        import re
        text = (ROOT / "ARCHITECTURE.md").read_text(encoding="utf-8")
        block = re.search(r"```json\n(.*?)\n```", text[text.find("<!-- check:case-schema -->"):], re.S).group(1)
        self.assertEqual(json.loads(block), SCHEMA)


class CanonicalWriteTest(unittest.TestCase):
    def test_file_bytes_hash_equals_canonical_hash(self):
        import hashlib
        from hhg.agent.orchestrator import canonical, write_canonical
        obj = {"case_id": "HHG-000", "text": "line one\nline two", "n": [1, 2]}
        path = Path(tempfile.mkdtemp()) / "x.json"
        digest = write_canonical(path, obj)
        body = path.read_bytes()
        self.assertNotIn(b"\r", body)
        self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
        self.assertEqual(digest, hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest())


class DetectorTest(unittest.TestCase):
    def txn(self, i, minutes, amt, channel="online", **kw):
        base = dict(txn_id=f"{3000000 + i}", ts=datetime(2016, 11, 1) + timedelta(minutes=minutes), amt=amt,
                    product_cd="C", channel=channel, risk_score=0.5, addr1="100.0", p_email="", r_email="",
                    new_found="", proxy="", match_status="", profile_key="", m={})
        base.update(kw)
        return fx.Txn(**base)

    def test_card_testing_sequence(self):
        txns = [self.txn(1, 0, 1.1), self.txn(2, 10, 2.4), self.txn(3, 30, 0.95), self.txn(4, 80, 259.98)]
        fam = fx.card_testing(txns, txns[-1], txns[-1].ts)
        self.assertEqual(fam.s, 1.0)
        self.assertTrue(fam.detail["cleared_over_100"])

    def test_no_card_testing_with_two_small(self):
        txns = [self.txn(1, 0, 1.1), self.txn(2, 10, 2.4), self.txn(4, 80, 259.98)]
        self.assertEqual(fx.card_testing(txns, txns[-1], txns[-1].ts).s, 0.0)

    def test_structuring(self):
        txns = [self.txn(1, 0, 480.0), self.txn(2, 10, 470.0), self.txn(3, 25, 495.0), self.txn(4, 38, 490.0)]
        fam = fx.threshold_avoidance(txns, txns[-1], txns[-1].ts)
        self.assertEqual((fam.s, fam.detail["threshold"]), (1.0, 500.0))


if __name__ == "__main__":
    unittest.main()
