"""PR-② arm-evidence repair (W2/W3/W4 + heartbeat).

Focus: the W3 NON-NEGOTIABLE — an ARMED unknown-risk / unreadable-equity state
must BLOCK (fail-closed), never silent-zero-proceed — plus W4 structural ordering
(same-ticker structure swaps are visible) and the shadow-log liveness heartbeat.
"""
import unittest

from packages.quantum.risk import bucket_control as bc
from packages.quantum.analytics import calibration_apply_ordering as cao
from packages.quantum.services import risk_basis_shadow as rbs


class TestW3UnknownExplicit(unittest.TestCase):
    def test_risk_unknown_flagged_not_zero(self):
        self.assertEqual(bc._risk_from_fields(None, None), (0.0, True, True))      # UNKNOWN
        self.assertEqual(bc._risk_from_fields(372.0, None), (372.0, False, False))  # honest
        self.assertEqual(bc._risk_from_fields(None, 149.0), (149.0, True, False))   # premium

    def test_candidate_unknown_when_no_basis(self):
        _, _, unknown = bc.candidate_risk_usd({"order_json": {}})
        self.assertTrue(unknown)
        _, _, known = bc.candidate_risk_usd({"max_loss_total": 372.0})
        self.assertFalse(known)

    def test_evaluate_not_armable_on_unknown_candidate(self):
        d = bc.evaluate_bucket("QQQ", 0.0, [], None, 2000.0, candidate_unknown=True)
        self.assertTrue(d["unknown_risk_present"])
        self.assertTrue(d["equity_readable"])
        self.assertTrue(d["not_armable"])

    def test_evaluate_not_armable_on_unreadable_equity(self):
        d = bc.evaluate_bucket("QQQ", 100.0, [], None, 0.0)   # equity 0 → cap 0
        self.assertFalse(d["equity_readable"])
        self.assertFalse(d["would_block"])                     # the legacy fail-open
        self.assertTrue(d["not_armable"])                      # now caught

    def test_evaluate_counts_unknown_open_positions(self):
        d = bc.evaluate_bucket("QQQ", 100.0,
                               [{"symbol": "QQQ"}],           # no risk fields → unknown
                               None, 2000.0)
        self.assertEqual(d["unknown_open_count"], 1)
        self.assertTrue(d["not_armable"])


class TestW3EnforcementNonNegotiable(unittest.TestCase):
    """ARMED + unknown-risk → BLOCK. This is the case that matters when
    BUCKET_CONTROL_ENFORCE eventually flips."""
    def _d(self, **kw):
        base = {"would_block": False, "not_armable": False}
        base.update(kw)
        return base

    def test_armed_unknown_blocks(self):
        self.assertEqual(bc.bucket_enforcement_action(self._d(not_armable=True), armed=True),
                         ("block", "bucket_not_armable_unknown_risk"))

    def test_armed_cap_breach_blocks(self):
        self.assertEqual(bc.bucket_enforcement_action(self._d(would_block=True), armed=True),
                         ("block", "bucket_exposure_cap"))

    def test_armed_clean_proceeds(self):
        self.assertEqual(bc.bucket_enforcement_action(self._d(), armed=True)[0], "proceed")

    def test_observe_unknown_proceeds_logged_not_blocked(self):
        self.assertEqual(bc.bucket_enforcement_action(self._d(not_armable=True), armed=False)[0],
                         "proceed")

    def test_observe_cap_breach_alarms(self):
        self.assertEqual(bc.bucket_enforcement_action(self._d(would_block=True), armed=False),
                         ("alarm", "bucket_exposure_would_block"))


class TestW4StructuralOrdering(unittest.TestCase):
    def test_same_ticker_structure_swap_detected(self):
        # two QQQ structures; frozen ranks A>B, calibrated ranks B>A. The OLD
        # ticker-only list can't see it; the structural key must.
        A = {"ticker": "QQQ", "strategy": "iron_condor", "id": "a", "score": 60}
        B = {"ticker": "QQQ", "strategy": "debit_spread", "id": "b", "score": 55}
        frozen = cao._top_n([A, B], lambda c: c["score"])
        cal = cao._top_n([A, B], lambda c: {"a": 40, "b": 50}[c["id"]])
        self.assertEqual([t[0] for t in frozen], [t[0] for t in cal])   # ticker-only agrees (the bug)
        self.assertNotEqual(cao._order_key(frozen), cao._order_key(cal))  # structural key flips (the fix)

    def test_identity_carries_strategy_id_and_score(self):
        A = {"ticker": "QQQ", "strategy": "iron_condor", "id": "a", "score": 60}
        top = cao._top_n([A], lambda c: c["score"])
        self.assertEqual(top[0][:3], ("QQQ", "iron_condor", "a"))
        self.assertEqual(top[0][-1], 60.0)   # magnitude carried, dropped from _order_key
        self.assertNotIn(60.0, cao._order_key(top)[0])


class TestHeartbeat(unittest.TestCase):
    def test_heartbeat_fires_at_zero(self):
        with self.assertLogs(rbs.__name__, level="INFO") as cm:
            rbs.log_shadow_heartbeat("EXECUTOR_SHADOW", 0, cycle="aggressive")
        line = "\n".join(cm.output)
        self.assertIn("[EXECUTOR_SHADOW_HEARTBEAT]", line)
        self.assertIn("evaluated=0", line)


if __name__ == "__main__":
    unittest.main()
