"""Mirror parity — model_review.fetch_study_rows ↔ challenger_study.STUDY_SQL.

fetch_study_rows is the PostgREST-side re-implementation of the operator's raw
STUDY_SQL (scripts/analytics/challenger_study.py). The #1286 review flagged
THREE clauses that the SQL guarantees but that no test drove through the REAL
fetch_study_rows:

  1. DEDUP-LATEST-CLOSE — ``DISTINCT ON (o.suggestion_id) ... ORDER BY
     o.suggestion_id, o.closed_at DESC``: multiple v3 rows for one suggestion
     collapse to ONE, keeping the LATEST close's realized/pop/ev.
  2. EARLIEST-STAGED TIE-BREAK, NULLS LAST — the OPEN-order LATERAL's
     ``ORDER BY po.staged_at ASC NULLS LAST LIMIT 1``: among the capture-marked
     opening orders for a suggestion, the EARLIEST staged wins, and a NULL
     staged_at sorts LAST (chosen only when nothing else is staged).
  3. GEOMETRY-AUTHORITY — ``ts.order_json->'legs'`` is the geometry; the
     close/open ORDER legs never are. captured iv/delta merge on top BY OCC
     symbol from the OPEN order, but the structure stays the suggestion's.

Plus the JOIN shape the SQL encodes: ``JOIN trade_suggestions`` (INNER — a
suggestion with no ts row drops); a suggestion with no legs is unmappable and
drops; and the F-CREDIT-SIGN ``corrected`` LATERAL routed through the #1042
learning quarantine (only a TRUSTED outcome_type may set it).

Failure injected at the ORIGIN (the four source tables a fake client serves),
truth asserted at the TOP (the dict fetch_study_rows returns). READ-ONLY: the
fake records any write verb so the mirror is proven never to mutate.
"""

import pytest

from packages.quantum.analytics import model_review as mr

LONG_SYM = "O:ABC260417C00090000"
SHORT_SYM = "O:ABC260417C00100000"
# A structurally different close-order leg set (single reversed leg) — the SQL
# comment's exact hazard: "a 1-leg buy-to-close vs the 4-leg condor open".
CLOSE_LEG_SYM = "O:ABC260417C00090000"


# ── fake supabase client (routes .table() by name; records writes) ──────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Returns the table's canned rows verbatim (the fetch does its own
    Python-side join/dedup/tie-break by id), and records any write verb so a
    test can prove the mirror is read-only."""

    def __init__(self, name, data, writes):
        self._name = name
        self._data = data
        self._writes = writes

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(list(self._data))

    def update(self, payload):
        self._writes.append((self._name, "update", payload))
        return self

    def insert(self, payload):
        self._writes.append((self._name, "insert", payload))
        return self

    def upsert(self, payload, **k):
        self._writes.append((self._name, "upsert", payload))
        return self

    def delete(self):
        self._writes.append((self._name, "delete", None))
        return self


class _FakeClient:
    def __init__(self, tables):
        self._tables = tables
        self.writes = []

    def table(self, name):
        return _Query(name, self._tables.get(name, []), self.writes)


@pytest.fixture
def _quarantine_on(monkeypatch):
    # Pin the #1042 kill switch ON so the corrected-flag quarantine is
    # deterministic regardless of the ambient env.
    monkeypatch.setenv("LEARNING_HISTORICAL_QUARANTINE_ENABLED", "1")


def _captured_leg(sym, action, iv, delta):
    return {"action": action, "symbol": sym, "quantity": 1,
            "iv": iv, "iv_status": "populated_at_stage",
            "greeks": {"delta": delta}, "greeks_status": "populated_at_stage"}


def _suggestion_legs():
    return [
        {"side": "buy", "symbol": LONG_SYM, "quantity": 1},
        {"side": "sell", "symbol": SHORT_SYM, "quantity": 1},
    ]


def _tables(*, v3, ts, po, lfl=None):
    return {
        "learning_trade_outcomes_v3": list(v3),
        "trade_suggestions": list(ts),
        "paper_orders": list(po),
        "learning_feedback_loops": list(lfl or []),
        "job_runs": [],
    }


def _v3_row(sid, *, closed_at, pnl, pop=0.55, ev=42.0, is_paper=False,
            strategy="LONG_CALL_DEBIT_SPREAD"):
    return {
        "suggestion_id": sid, "is_paper": is_paper, "strategy": strategy,
        "regime": "normal", "entry_ts": "2026-03-19T15:19:13Z",
        "closed_at": closed_at, "pnl_realized": pnl,
        "pop_predicted": pop, "ev_predicted": ev,
    }


def _ts_row(sid, *, legs=None, limit_price=4.55, contracts=1):
    return {
        "id": sid, "created_at": "2026-03-19T15:19:13Z",
        "order_json": {
            "legs": _suggestion_legs() if legs is None else legs,
            "limit_price": limit_price, "contracts": contracts,
        },
    }


def _open_po(sid, *, staged_at, spot, legs=None):
    return {
        "suggestion_id": sid, "staged_at": staged_at,
        "order_json": {
            "legs": legs if legs is not None else [
                _captured_leg(LONG_SYM, "buy", 0.20, 0.60),
                _captured_leg(SHORT_SYM, "sell", 0.18, 0.45),
            ],
            "entry_underlying_spot": {"value": spot,
                                      "status": "populated_at_stage"},
        },
    }


# ── Clause 1: dedup by suggestion, keep the LATEST close ─────────────────────
class TestDedupLatestClose:
    def test_multi_row_same_suggestion_collapses_to_latest_close(self):
        # The fake preserves list order == the DB's ORDER BY closed_at DESC, so
        # the LATER close is placed first (as PostgREST would return it). Only
        # one row must survive, carrying the latest close's realized P&L.
        v3 = [
            _v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=120.0),   # latest
            _v3_row("s-1", closed_at="2026-03-20T20:00:00Z", pnl=-999.0),  # stale
        ]
        client = _FakeClient(_tables(
            v3=v3, ts=[_ts_row("s-1")],
            po=[_open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0)]))
        rows = mr.fetch_study_rows(client)

        assert list(rows) == ["s-1"], "exactly one row per suggestion_id"
        assert rows["s-1"]["realized_pnl"] == 120.0  # latest close won
        assert client.writes == []                   # read-only mirror

    def test_first_seen_wins_is_the_dedup_contract(self):
        # DISTINCT ON keeps the first row per key in the ordered stream; the
        # mirror keeps the first-seen (== latest close under desc order).
        v3 = [
            _v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=10.0, pop=0.7),
            _v3_row("s-1", closed_at="2026-03-24T20:00:00Z", pnl=20.0, pop=0.1),
        ]
        client = _FakeClient(_tables(
            v3=v3, ts=[_ts_row("s-1")],
            po=[_open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0)]))
        rows = mr.fetch_study_rows(client)
        assert rows["s-1"]["pop_pred"] == 0.7  # the first-seen row's fields


# ── Clause 2: OPEN-order tie-break — earliest staged, NULLS LAST ─────────────
class TestEarliestStagedTieBreak:
    def test_earliest_staged_open_order_supplies_captured_inputs(self):
        # Three capture-marked opening orders for one suggestion. The SQL takes
        # ORDER BY staged_at ASC LIMIT 1 → the earliest. Distinct spot values
        # make the winner observable.
        po = [
            _open_po("s-1", staged_at="2026-03-19T15:19:30Z", spot=93.0),  # later
            _open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0),  # EARLIEST
            _open_po("s-1", staged_at="2026-03-19T15:19:20Z", spot=94.0),  # middle
        ]
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")], po=po))
        rows = mr.fetch_study_rows(client)
        spot = rows["s-1"]["entry_underlying_spot"]
        assert spot["value"] == 95.0  # earliest staged won

    def test_null_staged_at_sorts_last(self):
        # NULLS LAST: a NULL staged_at loses to any real timestamp. The real
        # (later-but-non-null) order still wins over the NULL one.
        po = [
            _open_po("s-1", staged_at=None, spot=1.0),                     # NULL → last
            _open_po("s-1", staged_at="2026-03-19T23:59:59Z", spot=88.0),  # real
        ]
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")], po=po))
        rows = mr.fetch_study_rows(client)
        assert rows["s-1"]["entry_underlying_spot"]["value"] == 88.0

    def test_null_staged_at_chosen_only_when_alone(self):
        # With no non-null-staged order available, the NULL one is the only
        # opening order and supplies the capture (LIMIT 1 still returns it).
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")],
            po=[_open_po("s-1", staged_at=None, spot=77.0)]))
        rows = mr.fetch_study_rows(client)
        assert rows["s-1"]["entry_underlying_spot"]["value"] == 77.0

    def test_unmarked_orders_are_not_opening_orders(self):
        # A paper_orders row WITHOUT the entry_underlying_spot marker is a close
        # (capture-exempt) and can never supply captured inputs, even if it is
        # staged earlier than the real opening order.
        close_order = {
            "suggestion_id": "s-1", "staged_at": "2026-03-01T00:00:00Z",
            "order_json": {"legs": [{"side": "sell", "symbol": CLOSE_LEG_SYM,
                                     "quantity": 1}]},  # no marker
        }
        open_order = _open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0)
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")], po=[close_order, open_order]))
        rows = mr.fetch_study_rows(client)
        # The marked (open) order won despite being staged later than the close.
        assert rows["s-1"]["entry_underlying_spot"]["value"] == 95.0


# ── Clause 3: geometry authority — suggestion legs, never order legs ─────────
class TestGeometryAuthority:
    def test_geometry_is_suggestion_legs_not_close_order_legs(self):
        # The OPEN order carries a DIFFERENT (single-leg) structure than the
        # suggestion. Geometry must be the suggestion's 2-leg structure;
        # captured_legs is the OPEN order's legs (used only for iv/delta merge).
        open_legs = [_captured_leg(LONG_SYM, "buy", 0.20, 0.60)]  # 1 leg only
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")],
            po=[_open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0,
                         legs=open_legs)]))
        rows = mr.fetch_study_rows(client)
        row = rows["s-1"]

        # geometry == the suggestion's two legs (authority)
        assert row["legs"] == _suggestion_legs()
        assert [l["symbol"] for l in row["legs"]] == [LONG_SYM, SHORT_SYM]
        # captured_legs == the OPEN order's legs (merge source, not geometry)
        assert row["captured_legs"] == open_legs
        assert len(row["captured_legs"]) == 1

    def test_net_premium_and_contracts_from_suggestion_order_json(self):
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1", limit_price=3.21, contracts=4)],
            po=[_open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0)]))
        rows = mr.fetch_study_rows(client)
        assert rows["s-1"]["net_premium"] == 3.21
        assert rows["s-1"]["contracts"] == 4


# ── JOIN / mappability shape the SQL encodes ────────────────────────────────
class TestJoinShape:
    def test_inner_join_drops_outcome_without_suggestion(self):
        # No trade_suggestions row for the sid → INNER JOIN drops it entirely.
        client = _FakeClient(_tables(
            v3=[_v3_row("s-orphan", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[], po=[]))
        assert mr.fetch_study_rows(client) == {}

    def test_suggestion_without_legs_is_unmappable(self):
        # order_json with no legs → no geometry → the row is skipped.
        ts = [{"id": "s-1", "created_at": "2026-03-19T15:19:13Z",
               "order_json": {"limit_price": 4.55, "contracts": 1}}]
        client = _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=ts, po=[]))
        assert mr.fetch_study_rows(client) == {}

    def test_empty_population_returns_empty(self):
        assert mr.fetch_study_rows(_FakeClient(_tables(v3=[], ts=[], po=[]))) == {}


# ── F-CREDIT-SIGN corrected LATERAL routed through the #1042 quarantine ──────
@pytest.mark.usefixtures("_quarantine_on")
class TestCorrectedFlagQuarantine:
    def _base(self, lfl):
        return _FakeClient(_tables(
            v3=[_v3_row("s-1", closed_at="2026-03-25T20:00:00Z", pnl=40.0)],
            ts=[_ts_row("s-1")],
            po=[_open_po("s-1", staged_at="2026-03-19T15:19:10Z", spot=95.0)],
            lfl=lfl))

    def test_trusted_outcome_marker_sets_corrected(self):
        lfl = [{"suggestion_id": "s-1", "outcome_type": "trade_closed",
                "details_json": {"f_credit_sign_correction": True}}]
        rows = mr.fetch_study_rows(self._base(lfl))
        assert rows["s-1"]["corrected"] is True

    def test_untrusted_historical_marker_never_sets_corrected(self):
        # A synthetic/historical row carrying the marker must NOT flip corrected
        # (the #1042 fail-closed allowlist — historical rows can't drive a
        # live/paper study's display flag).
        lfl = [{"suggestion_id": "s-1", "outcome_type": "historical_win",
                "details_json": {"f_credit_sign_correction": True}}]
        rows = mr.fetch_study_rows(self._base(lfl))
        assert rows["s-1"]["corrected"] is False

    def test_no_marker_no_correction(self):
        lfl = [{"suggestion_id": "s-1", "outcome_type": "trade_closed",
                "details_json": {"something_else": 1}}]
        rows = mr.fetch_study_rows(self._base(lfl))
        assert rows["s-1"]["corrected"] is False


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
