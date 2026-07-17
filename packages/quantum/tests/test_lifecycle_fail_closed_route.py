"""Lifecycle fail-closed ROUTE tests (2026-07-16 tightening).

Doctrine: inject the failure at its ORIGIN, assert the truth at the TOP.
These tests drive the REAL ``scan_for_opportunities`` end-to-end — real
``process_symbol``, real leg selection, real EV math, real unified
scoring, real ``RejectionStats`` (with persistence configured) — with
stubs ONLY at genuine external data boundaries (market data services,
regime engine, strategy selector, agents) and the failure injected at
the DEEPEST callee: the supabase ``strategy_lifecycle_states`` query.

Contract under test: a failed, malformed, empty, or missing
strategy-lifecycle read must never silently mean ``live_full`` for
ENTRIES. Assertions are on the scan's OUTPUT (candidates + the typed
rejection recorded in RejectionStats AND the durable
``suggestion_rejections`` insert) — never on internal flags.

Fixture note: the healthy path in this harness EMITS a candidate. Every
fail-closed case therefore proves the lifecycle gate (and only the
lifecycle gate) removed it; a broken fixture would fail the healthy-path
test first, so a fail-closed test cannot pass vacuously. The
``processing_error`` counter is asserted zero everywhere to keep the
scanner's outer try/except from masking a fixture drift as a "pass".
"""

import unittest
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import packages.quantum.options_scanner as scanner_mod
from packages.quantum.analytics.regime_engine_v3 import RegimeState
from packages.quantum.services.sizing_engine import calculate_sizing

STRATEGY = "LONG_CALL_DEBIT_SPREAD"
SYMBOL = "TEST"


# ─────────────────────────────────────────────────────────────────
# Fake supabase — the ORIGIN of the injected failure. Only the
# strategy_lifecycle_states select is scriptable; every other table
# op is a permissive recorder so real fail-soft observability paths
# (suggestion_rejections persist, option-liquidity observe, alert
# dedup) run against it unchanged.
# ─────────────────────────────────────────────────────────────────


class _FakeQuery:
    def __init__(self, parent, table_name):
        self._parent = parent
        self._table = table_name
        self._op = "select"
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def eq(self, *a, **k):
        return self

    def neq(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def lte(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return self._parent._execute(self._table, self._op, self._payload)


class FakeSupabase:
    """``lifecycle_rows`` scripts the strategy_lifecycle_states read;
    ``lifecycle_raises`` (an exception instance) makes it THROW —
    the origin injection for the query-failure route test."""

    def __init__(self, lifecycle_rows=None, lifecycle_raises=None):
        self.lifecycle_rows = lifecycle_rows
        self.lifecycle_raises = lifecycle_raises
        self.inserted = defaultdict(list)
        self.lifecycle_reads = 0

    def table(self, name):
        return _FakeQuery(self, name)

    @property
    def rejection_rows(self):
        return self.inserted["suggestion_rejections"]

    def _execute(self, table, op, payload):
        if table == "strategy_lifecycle_states" and op == "select":
            self.lifecycle_reads += 1
            if self.lifecycle_raises is not None:
                raise self.lifecycle_raises
            return SimpleNamespace(data=list(self.lifecycle_rows or []))
        if op == "insert":
            self.inserted[table].append(payload)
            return SimpleNamespace(data=[payload])
        if table == "risk_alerts" and op == "select":
            # Non-empty → the iv-pipeline alert dedup short-circuits;
            # keeps this observability tangent out of the route.
            return SimpleNamespace(data=[{"id": "dedup-hit"}])
        return SimpleNamespace(data=[])


# ─────────────────────────────────────────────────────────────────
# Data-boundary fixtures (external market inputs, all healthy)
# ─────────────────────────────────────────────────────────────────


class _FakeGlobalSnapshot:
    state = RegimeState.NORMAL

    def to_dict(self):
        return {"state": "NORMAL"}


class _FakeSymbolSnapshot:
    iv_rank = 50.0
    iv_rank_quality = "real"
    iv_rv_spread = None


def _fixture_chain():
    """Two liquid calls ~35 DTE building a debit vertical with positive
    EV (pop≈0.447, EV≈+$17.5/contract) that clears the spread gate
    (5.8% < 10%) and the execution-cost gate (~$4.30 < EV)."""
    expiry = (datetime.now().date() + timedelta(days=35)).isoformat()

    def contract(strike, delta, bid, ask):
        mid = round((bid + ask) / 2.0, 4)
        return {
            "contract": f"{SYMBOL}{int(strike)}C",
            "strike": strike,
            "expiry": expiry,
            "type": "call",
            "greeks": {
                "delta": delta, "gamma": 0.02, "vega": 0.10, "theta": -0.05,
            },
            "quote": {"bid": bid, "ask": ask, "mid": mid, "last": mid},
        }

    return [
        contract(100.0, 0.55, 3.00, 3.06),
        contract(105.0, 0.30, 1.00, 1.06),
    ]


def _suggestion():
    return {
        "strategy": STRATEGY,
        "legs": [
            {"side": "buy", "type": "call", "delta_target": 0.55},
            {"side": "sell", "type": "call", "delta_target": 0.30},
        ],
    }


def _run_scan(fake_supabase):
    """Drive the REAL scan_for_opportunities for one symbol through the
    full process_symbol pipeline (leg selection, EV, scoring, gates)."""
    truth = MagicMock()
    truth.normalize_symbol.side_effect = lambda s: s
    truth.snapshot_many.return_value = {
        SYMBOL: {
            "quote": {"bid": 99.95, "ask": 100.05, "mid": 100.0,
                      "last": 100.0},
        }
    }
    truth.daily_bars.return_value = [{"close": 100.0}] * 60
    truth.option_chain.return_value = _fixture_chain()

    regime = MagicMock()
    regime.iv_repo = None
    regime.compute_symbol_snapshot.return_value = _FakeSymbolSnapshot()
    regime.get_effective_regime.return_value = SimpleNamespace(value="normal")

    selector = MagicMock()
    selector.get_candidates.return_value = [_suggestion()]
    selector.determine_strategy.return_value = _suggestion()

    polygon = MagicMock()
    polygon.get_ticker_details.return_value = {"sic_description": "Tech"}

    earnings = MagicMock()
    earnings.get_earnings_map.return_value = {}

    with patch.object(scanner_mod, "MarketDataTruthLayer",
                      return_value=truth), \
         patch.object(scanner_mod, "RegimeEngineV3", return_value=regime), \
         patch.object(scanner_mod, "StrategySelector",
                      return_value=selector), \
         patch.object(scanner_mod, "PolygonService", return_value=polygon), \
         patch.object(scanner_mod, "EarningsCalendarService",
                      return_value=earnings), \
         patch.object(scanner_mod, "UniverseService", MagicMock()), \
         patch.object(scanner_mod, "ExecutionService", MagicMock()), \
         patch.object(scanner_mod, "IVRepository", MagicMock()), \
         patch.object(scanner_mod, "IVPointService", MagicMock()), \
         patch.object(scanner_mod, "build_agent_pipeline",
                      lambda *a, **k: []):
        return scanner_mod.scan_for_opportunities(
            symbols=[SYMBOL],
            supabase_client=fake_supabase,
            global_snapshot=_FakeGlobalSnapshot(),
        )


def _lifecycle_reasons(stats_dict):
    return {
        k: v for k, v in stats_dict["rejection_counts"].items()
        if k.startswith("strategy_lifecycle")
    }


class TestLifecycleFailClosedRoute(unittest.TestCase):

    def _assert_route_reached_gate(self, stats_dict):
        """The outer try/except must not have eaten a fixture error —
        otherwise a fail-closed assertion could pass vacuously."""
        self.assertNotIn(
            "processing_error", stats_dict["rejection_counts"],
            f"fixture drift: {stats_dict['rejection_counts']}",
        )

    # ── healthy path (byte-identical decisions) ──────────────────

    def test_live_full_healthy_path_emits_unchanged(self):
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": STRATEGY, "current_state": "live_full"},
        ])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(len(candidates), 1, d["rejection_counts"])
        cand = candidates[0]
        self.assertEqual(cand["strategy"], STRATEGY)
        self.assertEqual(cand["lifecycle_state"], "live_full")
        self.assertGreater(cand["ev"], 0)
        # No lifecycle rejection recorded anywhere — in-memory or durable.
        self.assertEqual(_lifecycle_reasons(d), {})
        self.assertEqual(
            [r for r in fake.rejection_rows
             if r["reason"].startswith("strategy_lifecycle")],
            [],
        )
        self.assertEqual(d["emission_counts_by_strategy"], {STRATEGY: 1})
        # Exactly one lifecycle read per cycle (unchanged contract).
        self.assertEqual(fake.lifecycle_reads, 1)

    def test_live_full_healthy_path_deterministic(self):
        """Two identical runs produce the identical candidate dict —
        the byte-comparison-style pin for the healthy path."""
        rows = [{"strategy_name": STRATEGY, "current_state": "live_full"}]
        c1, _ = _run_scan(FakeSupabase(lifecycle_rows=rows))
        c2, _ = _run_scan(FakeSupabase(lifecycle_rows=rows))
        self.assertEqual(len(c1), 1)
        self.assertEqual(c1, c2)

    def test_experimental_emits_tagged_and_sizing_caps_to_one(self):
        """Experimental still emits; the existing 1-contract cap fires
        when sizing is driven the way the orchestrator drives it
        (cand.get('lifecycle_state', 'live_full'))."""
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": STRATEGY, "current_state": "experimental"},
        ])
        candidates, rej_stats = _run_scan(fake)
        self._assert_route_reached_gate(rej_stats.to_dict())
        self.assertEqual(len(candidates), 1)
        cand = candidates[0]
        self.assertEqual(cand["lifecycle_state"], "experimental")
        sizing = calculate_sizing(
            account_buying_power=10000.0,
            max_loss_per_contract=cand["max_loss_per_contract"],
            collateral_required_per_contract=(
                cand["collateral_required_per_contract"]
            ),
            risk_budget_dollars=2000.0,
            max_contracts=100,
            strategy=cand["strategy"],
            lifecycle_state=cand.get("lifecycle_state", "live_full"),
        )
        self.assertEqual(sizing["contracts"], 1)
        self.assertTrue(sizing["experimental_capped"])

    def test_designed_filtered_with_legacy_reason(self):
        """designed/deprecated keep their pre-tightening typed reasons —
        the healthy-path filter is unchanged."""
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": STRATEGY, "current_state": "designed"},
        ])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [])
        self.assertEqual(d["rejection_counts"].get("strategy_designed"), 1)
        self.assertEqual(_lifecycle_reasons(d), {})

    # ── fail-closed classifications (entries only) ───────────────

    def test_query_failure_fails_closed_with_typed_rejection(self):
        """ORIGIN INJECTION: the supabase lifecycle query THROWS. The
        same fixture that emits under live_full must emit NOTHING, and
        the typed rejection must be recorded both in-memory and via the
        durable suggestion_rejections insert."""
        fake = FakeSupabase(
            lifecycle_raises=ConnectionError("simulated DB blip"),
        )
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [], "a DB blip full-sized an entry")
        self.assertEqual(
            d["rejection_counts"].get("strategy_lifecycle_unavailable"), 1,
            d["rejection_counts"],
        )
        # Per-strategy attribution (feeds operator queries).
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"][STRATEGY][
                "strategy_lifecycle_unavailable"],
            1,
        )
        # Durable rejection row — the scan result's degradation is
        # visible via the scanner's existing persistence mechanism.
        rows = [r for r in fake.rejection_rows
                if r["reason"] == "strategy_lifecycle_unavailable"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], SYMBOL)
        self.assertEqual(rows[0]["strategy_key"], STRATEGY)
        self.assertEqual(d["emission_counts_by_strategy"], {})

    def test_empty_table_fails_closed_distinct_reason(self):
        """Empty table = broken/missing seed → fail closed, with a
        reason DISTINCT from query-failure."""
        fake = FakeSupabase(lifecycle_rows=[])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [])
        self.assertEqual(
            d["rejection_counts"].get("strategy_lifecycle_empty"), 1,
            d["rejection_counts"],
        )
        self.assertNotIn("strategy_lifecycle_unavailable",
                         d["rejection_counts"])
        self.assertEqual(
            [r["reason"] for r in fake.rejection_rows
             if r["reason"].startswith("strategy_lifecycle")],
            ["strategy_lifecycle_empty"],
        )

    def test_missing_strategy_row_fails_closed(self):
        """Map loaded fine but this strategy has no row — the seed
        covers every shipped strategy, so absence means unregistered."""
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": "IRON_CONDOR", "current_state": "live_full"},
        ])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [])
        self.assertEqual(
            d["rejection_counts"].get("strategy_lifecycle_missing"), 1,
            d["rejection_counts"],
        )

    def test_unknown_state_fails_closed_never_full_size(self):
        """State 'foo' is outside the DB CHECK's 4 values — pre-fix it
        passed the gate untagged-as-experimental and full-sized."""
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": STRATEGY, "current_state": "foo"},
        ])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [])
        self.assertEqual(
            d["rejection_counts"].get("strategy_lifecycle_invalid_state"),
            1,
            d["rejection_counts"],
        )

    def test_malformed_state_row_fails_closed(self):
        """A row with current_state=None (malformed) classifies as
        invalid-state — attributable, fail closed."""
        fake = FakeSupabase(lifecycle_rows=[
            {"strategy_name": STRATEGY, "current_state": None},
        ])
        candidates, rej_stats = _run_scan(fake)
        d = rej_stats.to_dict()
        self._assert_route_reached_gate(d)
        self.assertEqual(candidates, [])
        self.assertEqual(
            d["rejection_counts"].get("strategy_lifecycle_invalid_state"),
            1,
            d["rejection_counts"],
        )


class TestExitsLifecycleIndependent(unittest.TestCase):
    """EXITS must stay lifecycle-independent: a deprecated strategy's
    open position must still be closeable. This is the one place a
    source-level assertion is honest — it proves an ABSENCE of
    coupling (no strategy-lifecycle identifier is referenced anywhere
    in the close/exit path)."""

    CLOSE_PATH_MODULES = (
        "services/paper_exit_evaluator.py",
        "services/close_helper.py",
        "services/gtc_profit_exit.py",
        "jobs/handlers/intraday_risk_monitor.py",
        "jobs/handlers/alpaca_order_sync.py",
    )
    FORBIDDEN = (
        "strategy_lifecycle",             # table + eval identifiers
        "load_strategy_lifecycle_states",  # the loader
        "LifecycleReadResult",             # the typed result
        "lifecycle_state",                 # the candidate tag
        "classify_for_entry",              # the gate classification
    )

    def test_no_exit_module_references_strategy_lifecycle(self):
        base = Path(scanner_mod.__file__).resolve().parent
        for rel in self.CLOSE_PATH_MODULES:
            src_path = base / rel
            self.assertTrue(src_path.exists(), f"missing module: {rel}")
            src = src_path.read_text(encoding="utf-8")
            for token in self.FORBIDDEN:
                self.assertNotIn(
                    token, src,
                    f"{rel} references {token!r} — exits must be "
                    f"lifecycle-independent",
                )


if __name__ == "__main__":
    unittest.main()
