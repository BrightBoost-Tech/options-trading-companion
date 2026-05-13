"""Unit tests for Tier 1C (2026-05-13) per-rejection persistence in
``RejectionStats``.

Tests cover the new behavior added in
``packages/quantum/options_scanner.py``:

- ``RejectionStats.__init__`` accepts ``supabase`` + ``cycle_date`` +
  ``job_run_id`` kwargs (all optional, default None)
- ``set_symbol(symbol)`` stores per-thread context via threading.local
- ``record()`` and ``record_with_sample()`` write a row to
  ``suggestion_rejections`` when persistence is configured AND a
  symbol is set on the current thread
- Persistence failures are LOGGED but NOT raised (observability ≠
  load-bearing); the aggregate increment still completes
- No-symbol calls don't write spurious unattributed rows
- No-supabase calls (test mode) don't crash
- Threading: per-thread symbol context doesn't leak between threads

Pure-Python tests; no Supabase round-trip. The supabase client is
mocked via a stub object that captures insert payloads for
inspection.
"""

from __future__ import annotations

import logging
import threading
import unittest
from datetime import date
from typing import Any, Dict, List
from unittest.mock import MagicMock

from packages.quantum.options_scanner import RejectionStats


class _FakeTable:
    """Minimal stand-in for the supabase fluent API (.table().insert().execute())."""

    def __init__(self, parent: "_FakeSupabase", name: str):
        self._parent = parent
        self._name = name
        self._payload: Dict[str, Any] | None = None

    def insert(self, payload: Dict[str, Any]) -> "_FakeTable":
        self._payload = payload
        return self

    def execute(self) -> Any:
        # Capture into parent's recorded list
        self._parent.recorded.append(
            {"table": self._name, "payload": self._payload}
        )
        if self._parent.raise_on_execute:
            raise RuntimeError("simulated db failure")
        # Mimic supabase's returned object shape minimally
        m = MagicMock()
        m.data = []
        return m


class _FakeSupabase:
    """Captures insert payloads for assertion. Optional raise-on-execute
    for failure-isolation tests."""

    def __init__(self, raise_on_execute: bool = False):
        self.recorded: List[Dict[str, Any]] = []
        self.raise_on_execute = raise_on_execute

    def table(self, name: str) -> _FakeTable:
        return _FakeTable(self, name)


# ────────────────────────────────────────────────────────────────────


class TestPersistenceConfiguration(unittest.TestCase):
    """Constructor + helper signature behavior."""

    def test_default_construction_no_persistence(self):
        rs = RejectionStats()
        # No supabase / cycle_date → record() must not crash and
        # must not attempt any DB call (no FakeSupabase to assert
        # against, but the fact that record() returns without
        # exception is the contract).
        rs.set_symbol("PFE")
        rs.record("entry_cost_too_low")
        # Aggregate count must still increment.
        self.assertEqual(rs._counts["entry_cost_too_low"], 1)

    def test_constructor_accepts_supabase_cycle_date(self):
        fake = _FakeSupabase()
        rs = RejectionStats(supabase=fake, cycle_date=date(2026, 5, 13))
        # Sanity: state stored.
        self.assertIs(rs._supabase, fake)
        self.assertEqual(rs._cycle_date, date(2026, 5, 13))

    def test_set_symbol_stores_on_thread_local(self):
        rs = RejectionStats()
        rs.set_symbol("AAPL")
        self.assertEqual(rs._tls.current_symbol, "AAPL")
        rs.set_symbol(None)
        self.assertIsNone(rs._tls.current_symbol)


class TestPersistenceWrites(unittest.TestCase):
    """record() / record_with_sample() write to suggestion_rejections
    when configured."""

    def setUp(self):
        self.fake = _FakeSupabase()
        self.rs = RejectionStats(
            supabase=self.fake, cycle_date=date(2026, 5, 13)
        )

    def test_record_writes_row_when_symbol_set(self):
        self.rs.set_symbol("PFE")
        self.rs.record("entry_cost_too_low", strategy="LONG_CALL_DEBIT_SPREAD")
        # Aggregate side
        self.assertEqual(self.rs._counts["entry_cost_too_low"], 1)
        # Persistence side
        self.assertEqual(len(self.fake.recorded), 1)
        rec = self.fake.recorded[0]
        self.assertEqual(rec["table"], "suggestion_rejections")
        payload = rec["payload"]
        self.assertEqual(payload["symbol"], "PFE")
        self.assertEqual(payload["reason"], "entry_cost_too_low")
        self.assertEqual(payload["strategy_key"], "LONG_CALL_DEBIT_SPREAD")
        self.assertEqual(payload["cycle_date"], "2026-05-13")

    def test_record_no_symbol_no_persistence(self):
        # No set_symbol call — record() must not attempt to write
        # an unattributed row.
        self.rs.record("micro_tier_underlying_too_high")
        self.assertEqual(self.rs._counts["micro_tier_underlying_too_high"], 1)
        self.assertEqual(len(self.fake.recorded), 0)

    def test_record_strategy_none_persists_null_strategy_key(self):
        self.rs.set_symbol("AAPL")
        self.rs.record("missing_quotes", strategy=None)
        self.assertEqual(len(self.fake.recorded), 1)
        self.assertIsNone(self.fake.recorded[0]["payload"]["strategy_key"])

    def test_record_with_sample_includes_spread_debug(self):
        self.rs.set_symbol("CMCSA")
        sample = {"entry_cost": 0.06, "threshold": 0.30, "spread_pct": 2.0}
        self.rs.record_with_sample(
            "entry_cost_too_low",
            sample,
            strategy="LONG_PUT_DEBIT_SPREAD",
        )
        self.assertEqual(self.rs._counts["entry_cost_too_low"], 1)
        self.assertEqual(len(self.fake.recorded), 1)
        payload = self.fake.recorded[0]["payload"]
        self.assertEqual(payload["spread_debug"]["entry_cost"], 0.06)
        self.assertEqual(payload["spread_debug"]["threshold"], 0.30)

    def test_record_clears_symbol_via_set_none(self):
        self.rs.set_symbol("F")
        self.rs.record("dte_out_of_range")
        self.rs.set_symbol(None)
        self.rs.record("agent_veto")
        # Only the F record should have persisted.
        self.assertEqual(len(self.fake.recorded), 1)
        self.assertEqual(self.fake.recorded[0]["payload"]["symbol"], "F")

    def test_job_run_id_omitted_when_none(self):
        self.rs.set_symbol("BAC")
        self.rs.record("no_chain")
        payload = self.fake.recorded[0]["payload"]
        # When job_run_id is None we omit the key (vs writing NULL),
        # since DB column has no default — both work but omitted is
        # cleaner for partial inserts.
        self.assertNotIn("job_run_id", payload)


class TestPersistenceFailureIsolation(unittest.TestCase):
    """Persistence failures must not raise — observability writes
    are best-effort. Aggregate counts complete regardless."""

    def test_db_exception_does_not_propagate(self):
        fake = _FakeSupabase(raise_on_execute=True)
        rs = RejectionStats(supabase=fake, cycle_date=date(2026, 5, 13))
        rs.set_symbol("MSFT")
        # Must not raise.
        rs.record("processing_error")
        # Aggregate side still completed even though DB raised.
        self.assertEqual(rs._counts["processing_error"], 1)
        # The persistence path was taken (the fake captured the
        # payload before raising in execute()), confirming the
        # try/except in _persist_rejection caught the failure.
        self.assertEqual(len(fake.recorded), 1)
        self.assertEqual(fake.recorded[0]["payload"]["symbol"], "MSFT")

    def test_db_exception_logged_at_warning(self):
        fake = _FakeSupabase(raise_on_execute=True)
        rs = RejectionStats(supabase=fake, cycle_date=date(2026, 5, 13))
        rs.set_symbol("NVDA")
        with self.assertLogs(
            "packages.quantum.options_scanner", level="WARNING"
        ) as cm:
            rs.record("dte_out_of_range")
        # At least one warning mentions "suggestion_rejections insert failed"
        joined = "\n".join(cm.output)
        self.assertIn("suggestion_rejections insert failed", joined)
        self.assertIn("NVDA", joined)


class TestThreadingIsolation(unittest.TestCase):
    """Per-thread symbol context must NOT leak between threads.
    Scanner runs symbols in a ThreadPoolExecutor; each worker
    sets its own symbol."""

    def test_per_thread_symbol_does_not_leak(self):
        fake = _FakeSupabase()
        rs = RejectionStats(supabase=fake, cycle_date=date(2026, 5, 13))

        seen_symbols: List[str] = []

        def worker(symbol: str) -> None:
            rs.set_symbol(symbol)
            # Pretend to do other work, then record.
            rs.record("dte_out_of_range")
            # Each thread sees its own symbol.
            seen_symbols.append(rs._tls.current_symbol)

        threads = [
            threading.Thread(target=worker, args=(s,))
            for s in ("AAPL", "MSFT", "NVDA", "GOOG")
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All four symbols got persisted with correct attribution.
        self.assertEqual(len(fake.recorded), 4)
        recorded_symbols = sorted(
            r["payload"]["symbol"] for r in fake.recorded
        )
        self.assertEqual(recorded_symbols, ["AAPL", "GOOG", "MSFT", "NVDA"])
        # Each thread saw its own symbol (not a leaked one).
        self.assertEqual(sorted(seen_symbols), ["AAPL", "GOOG", "MSFT", "NVDA"])


class TestAggregateUnaffected(unittest.TestCase):
    """Sanity: persistence layer must not change aggregate flow."""

    def test_aggregate_counts_match_with_or_without_persistence(self):
        # Without persistence
        rs1 = RejectionStats()
        rs1.set_symbol("PFE")
        rs1.record("entry_cost_too_low")
        rs1.record("entry_cost_too_low")
        rs1.record_with_sample(
            "spread_too_wide", {"k": "v"}, strategy="LONG_CALL"
        )

        # With persistence
        fake = _FakeSupabase()
        rs2 = RejectionStats(supabase=fake, cycle_date=date(2026, 5, 13))
        rs2.set_symbol("PFE")
        rs2.record("entry_cost_too_low")
        rs2.record("entry_cost_too_low")
        rs2.record_with_sample(
            "spread_too_wide", {"k": "v"}, strategy="LONG_CALL"
        )

        # Aggregate dicts must match.
        self.assertEqual(dict(rs1._counts), dict(rs2._counts))
        self.assertEqual(
            dict(rs1._per_strategy_counts.get("LONG_CALL", {})),
            dict(rs2._per_strategy_counts.get("LONG_CALL", {})),
        )

        # Persistence-only side recorded 3 rows.
        self.assertEqual(len(fake.recorded), 3)


if __name__ == "__main__":
    unittest.main()
