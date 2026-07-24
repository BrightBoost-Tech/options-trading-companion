"""⑤ Score-on-scan observer job — enqueue gating + child body (services.td_scan_observe).

Proves the enqueue is flag-gated / scheduler-only / tape-required / idempotent,
and the child body reads envelopes, scores both models, links outcomes honestly
(resolved vs counterfactual_unmarkable, never fabricated), writes to td_scan_scores,
is fail-soft on a missing table, isolates one candidate's failure from its
siblings, touches NO provider/broker, and survives a load of many candidates.
"""

import unittest
from unittest.mock import patch

from packages.quantum.services import td_scan_observe as O
from packages.quantum.services.td_scan_observe import (
    JOB_NAME,
    maybe_enqueue_td_scan_observe,
    run_td_scan_score_observe,
)

CID = "11111111-1111-1111-1111-111111111111"


def _envelope(fp, *, emitted=False, iv=0.22, strategy="LONG_CALL_DEBIT_SPREAD"):
    return {
        "candidate_fingerprint": fp, "symbol": "SPY", "strategy": strategy,
        "premium_direction": "debit", "net_premium": 1.5, "spot": 500.0,
        "dte_days": 35.0, "known_at": "2026-07-20T14:00:00Z", "production_ev": 17.5,
        "emitted": emitted,
        "legs": [
            {"symbol": "O:SPY260824C00500000", "side": "buy", "option_type": "call",
             "strike": 500.0, "expiry": "2026-08-24", "delta": 0.55, "iv": iv},
            {"symbol": "O:SPY260824C00510000", "side": "sell", "option_type": "call",
             "strike": 510.0, "expiry": "2026-08-24", "delta": 0.30, "iv": iv},
        ],
    }


def _env_row(fp, **over):
    row = {
        "cycle_id": CID, "cycle_date": "2026-07-23", "user_id": None,
        "symbol": "SPY", "strategy": "LONG_CALL_DEBIT_SPREAD", "strategy_key": "k",
        "candidate_fingerprint": fp, "emitted": False,
        "reject_reason": "unattributed_post_ev", "reject_gate": "post_ev_gate",
        "known_at": "2026-07-20T14:00:00Z", "envelope": _envelope(fp),
    }
    row.update(over)
    return row


# ── flexible fake supabase ──────────────────────────────────────────────────
class _Query:
    def __init__(self, sb, table):
        self._sb = sb
        self._t = table
        self._op = "select"
        self._payload = None
        self._filters = {}

    def select(self, *a, **k):
        self._op = "select"
        return self

    def upsert(self, payload, **k):
        self._op = "upsert"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return self._sb._exec(self._t, self._op, self._payload, self._filters)


class _SB:
    def __init__(self, *, envelopes=None, suggestions=None, v3=None, missing=()):
        self.tables_accessed = []
        self.upserts = []
        self._envelopes = envelopes or []
        self._suggestions = suggestions or []
        self._v3 = v3 or []
        self._missing = set(missing)

    def table(self, name):
        self.tables_accessed.append(name)
        return _Query(self, name)

    def _exec(self, table, op, payload, filters):
        if table in self._missing:
            raise Exception(f"relation {table} does not exist")
        if op == "upsert":
            self.upserts.append((table, payload))
            return _Res([payload])
        # select
        if table == "td_scan_envelopes":
            return _Res([r for r in self._envelopes if r.get("cycle_id") == filters.get("cycle_id")])
        if table == "trade_suggestions":
            fp = filters.get("legs_fingerprint")
            return _Res([r for r in self._suggestions if r.get("legs_fingerprint") == fp])
        if table == "learning_trade_outcomes_v3":
            sid = filters.get("suggestion_id")
            return _Res([r for r in self._v3 if r.get("suggestion_id") == sid])
        return _Res([])


class _Res:
    def __init__(self, data):
        self.data = data


# ── enqueue tests ───────────────────────────────────────────────────────────
class TestEnqueue(unittest.TestCase):
    def _call(self, **over):
        kw = dict(
            user_id="u1", source_job_run_id="jr1", source_decision_id=CID,
            source_code_sha="sha", as_of="2026-07-23T00:00:00Z",
            parent_origin="scheduler",
            enqueue_fn=lambda **k: {"status": "queued", "rq_job_id": "rq1", "job_run_id": "j1"},
            origin_builder=lambda ev, **k: {"origin": "event", "event": ev},
        )
        kw.update(over)
        with patch.object(O, "td_scan_observe_enabled", return_value=over.pop("_flag", True)):
            return maybe_enqueue_td_scan_observe(_SB(), **{k: v for k, v in kw.items() if not k.startswith("_")})

    def test_flag_off_is_noop(self):
        with patch.object(O, "td_scan_observe_enabled", return_value=False):
            out = maybe_enqueue_td_scan_observe(
                _SB(), user_id="u", source_job_run_id="j", source_decision_id=CID,
                source_code_sha="s", as_of="t", parent_origin="scheduler")
        self.assertEqual(out["status"], "flag_disabled")
        self.assertFalse(out["enqueued"])
        self.assertEqual(out["errors"], 0)

    def test_non_scheduler_parent_noop(self):
        out = self._call(parent_origin="manual")
        self.assertEqual(out["status"], "non_natural_parent")
        self.assertFalse(out["enqueued"])

    def test_missing_decision_id_is_noop_not_error(self):
        out = self._call(source_decision_id=None)
        self.assertEqual(out["status"], "source_identity_missing")
        self.assertEqual(out["errors"], 0)  # REPLAY-off is a no-op, not a failure

    def test_happy_path_enqueues_with_idempotency_key(self):
        captured = {}

        def _enq(**k):
            captured.update(k)
            return {"status": "queued", "rq_job_id": "rq1", "job_run_id": "j1"}

        out = self._call(enqueue_fn=_enq)
        self.assertTrue(out["enqueued"])
        self.assertEqual(captured["job_name"], JOB_NAME)
        self.assertEqual(captured["idempotency_key"], f"{JOB_NAME}:{CID}")
        self.assertEqual(captured["payload"]["source_decision_id"], CID)

    def test_skipped_terminal_not_counted_enqueued(self):
        out = self._call(enqueue_fn=lambda **k: {"status": "cancelled", "skipped": True})
        self.assertFalse(out["enqueued"])
        self.assertTrue(out["skipped"])


# ── child body tests ────────────────────────────────────────────────────────
class TestRunBody(unittest.TestCase):
    def test_scores_and_writes_each_candidate(self):
        sb = _SB(envelopes=[_env_row("fpA", emitted=True), _env_row("fpB")])
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        self.assertTrue(out["ok"])
        self.assertEqual(out["counts"]["envelopes"], 2)
        self.assertEqual(out["counts"]["scored"], 2)
        self.assertEqual(out["counts"]["written"], 2)
        # both upserted to td_scan_scores with both models present
        self.assertEqual(len(sb.upserts), 2)
        row = sb.upserts[0][1]
        self.assertIn("baseline_ev", row)
        self.assertIn("challenger_ev", row)
        self.assertEqual(row["challenger_model_version"], out["model_version"])

    def test_missing_decision_id_errors(self):
        out = run_td_scan_score_observe(_SB(), {})
        self.assertFalse(out["ok"])
        self.assertEqual(out["status"], "source_decision_missing")
        self.assertEqual(out["counts"]["errors"], 1)

    def test_envelope_table_missing_typed_noop(self):
        sb = _SB(envelopes=[_env_row("fpA")], missing={"td_scan_envelopes"})
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        self.assertTrue(out["ok"])  # typed no-op, not a failure
        self.assertEqual(out["status"], "envelope_table_missing")

    def test_scores_table_missing_typed_noop(self):
        sb = _SB(envelopes=[_env_row("fpA")], missing={"td_scan_scores"})
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "scores_table_missing")

    def test_no_envelopes_is_ok_empty(self):
        out = run_td_scan_score_observe(_SB(envelopes=[]), {"source_decision_id": CID})
        self.assertTrue(out["ok"])
        self.assertEqual(out["status"], "no_envelopes")

    def test_outcome_linkage_resolved(self):
        sb = _SB(
            envelopes=[_env_row("fpX", emitted=True)],
            suggestions=[{"id": "sug1", "legs_fingerprint": "fpX", "execution_mode": "alpaca_live"}],
            v3=[{"suggestion_id": "sug1", "pnl_realized": 42.0, "is_paper": False, "closed_at": "2026-07-22"}],
        )
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        row = sb.upserts[0][1]
        self.assertEqual(row["outcome_status"], "resolved")
        self.assertEqual(row["suggestion_id"], "sug1")
        self.assertEqual(row["realized_pnl"], 42.0)
        self.assertTrue(row["realized_win"])
        self.assertFalse(row["is_paper"])
        self.assertEqual(row["execution_mode"], "alpaca_live")
        self.assertEqual(out["counts"]["resolved"], 1)

    def test_outcome_linkage_counterfactual_when_no_suggestion(self):
        sb = _SB(envelopes=[_env_row("fpY")])  # no suggestion → unmarkable
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        row = sb.upserts[0][1]
        self.assertEqual(row["outcome_status"], "counterfactual_unmarkable")
        self.assertIsNone(row["realized_pnl"])
        self.assertIsNone(row["realized_win"])
        self.assertEqual(out["counts"]["counterfactual"], 1)

    def test_outcome_linkage_open_when_persisted_not_closed(self):
        sb = _SB(
            envelopes=[_env_row("fpZ", emitted=True)],
            suggestions=[{"id": "sug2", "legs_fingerprint": "fpZ", "execution_mode": None}],
            v3=[],  # persisted but no closed outcome
        )
        run_td_scan_score_observe(sb, {"source_decision_id": CID})
        row = sb.upserts[0][1]
        self.assertEqual(row["outcome_status"], "open")
        self.assertEqual(row["suggestion_id"], "sug2")

    def test_one_candidate_failure_isolated(self):
        # one malformed envelope (no legs / bad) + two good; goods still write.
        bad = _env_row("bad", envelope={"candidate_fingerprint": "bad", "legs": None})
        sb = _SB(envelopes=[_env_row("g1", emitted=True), bad, _env_row("g2")])
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        # all three "scored" (bad abstains cleanly, not a crash) and written.
        self.assertEqual(out["counts"]["scored"], 3)
        self.assertEqual(out["counts"]["written"], 3)

    def test_no_provider_or_broker_tables_touched(self):
        sb = _SB(envelopes=[_env_row("fpA", emitted=True)])
        run_td_scan_score_observe(sb, {"source_decision_id": CID})
        allowed = {"td_scan_envelopes", "trade_suggestions",
                   "learning_trade_outcomes_v3", "td_scan_scores"}
        self.assertTrue(set(sb.tables_accessed).issubset(allowed),
                        f"unexpected table: {set(sb.tables_accessed) - allowed}")

    def test_load_many_candidates(self):
        envs = [_env_row(f"fp{i}", emitted=(i % 3 == 0)) for i in range(150)]
        sb = _SB(envelopes=envs)
        out = run_td_scan_score_observe(sb, {"source_decision_id": CID})
        self.assertTrue(out["ok"])
        self.assertEqual(out["counts"]["scored"], 150)
        self.assertEqual(out["counts"]["written"], 150)
        # ranks assigned over the identical set
        ranks = [r[1].get("current_rank") for r in sb.upserts]
        self.assertTrue(any(x == 1 for x in ranks))


if __name__ == "__main__":
    unittest.main()
