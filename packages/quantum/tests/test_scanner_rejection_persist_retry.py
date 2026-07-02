"""A5 2026-07-01: transient-disconnect retry at the scanner persist seam.

The 16:00Z scheduled scan's post-scan write burst hit stale-keepalive
connections ("Server disconnected") on 8 consecutive suggestion_rejections
inserts (07-01; same class as 06-30's storm). #1100 added a right-sized
retry for the risk_alerts insert only — this seam reuses its classifier
(``observability.alerts._is_transient_disconnect``) inside
``RejectionStats._persist_rejection``:

- transient disconnect → retry with backoff (PERSIST_RETRY_BACKOFFS), row
  recovered, ``persist_retry_recoveries`` counted (persist_failures stays 0)
- transient exhausts every retry → DISTINCT ``rejection_row_lost_after_
  retries`` marker + the unchanged fail-soft counter/warning
- non-transient exception → NO retry (single attempt), unchanged fallback
- clean insert → single attempt, zero sleeps (hot path unchanged)

Pure-Python; supabase mocked. The backoff sleep is injected through the
constructor (``retry_sleep=``) — NOT ``@patch`` on the scanner module:
dotted-path patching on options_scanner is order-fragile in the full CI
suite (module attributes end up MagicMock-shadowed by neighbor tests; see
test_credit_spread_emission._read_anomaly_threshold — both prior CI runs
failed on exactly that, with the patched mock seeing zero calls while the
real sleep executed).
"""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any, Dict, List
from unittest.mock import MagicMock

from packages.quantum.options_scanner import RejectionStats


class _RemoteProtocolError(Exception):
    """Class-name match for the httpx/httpcore transient (matched via MRO
    by _is_transient_disconnect without importing httpx)."""


# Rename so type(exc).__mro__ carries the exact class name the classifier
# looks for.
_RemoteProtocolError.__name__ = "RemoteProtocolError"


class _ScriptedTable:
    """supabase fluent stand-in whose execute() raises the next scripted
    exception (or succeeds when the script is exhausted)."""

    def __init__(self, parent: "_ScriptedSupabase", name: str):
        self._parent = parent
        self._name = name
        self._payload: Dict[str, Any] | None = None

    def insert(self, payload: Dict[str, Any]) -> "_ScriptedTable":
        self._payload = payload
        return self

    def execute(self) -> Any:
        self._parent.attempts.append(
            {"table": self._name, "payload": self._payload}
        )
        if self._parent.failures:
            raise self._parent.failures.pop(0)
        m = MagicMock()
        m.data = []
        return m


class _ScriptedSupabase:
    def __init__(self, failures: List[BaseException] | None = None):
        self.attempts: List[Dict[str, Any]] = []
        self.failures: List[BaseException] = list(failures or [])

    def table(self, name: str) -> _ScriptedTable:
        return _ScriptedTable(self, name)


def _transient(msg: str = "Server disconnected") -> RuntimeError:
    return RuntimeError(msg)


def _make_stats(fake: _ScriptedSupabase) -> tuple[RejectionStats, MagicMock]:
    """RejectionStats wired with an injected mock sleep (constructor DI)."""
    mock_sleep = MagicMock()
    rs = RejectionStats(
        supabase=fake, cycle_date=date(2026, 7, 1), retry_sleep=mock_sleep
    )
    return rs, mock_sleep


class TestTransientRetryRecovers(unittest.TestCase):
    """Disconnect ×2 then success → row written, no persist_failure,
    recovery counted + WARNING-visible."""

    def test_two_transients_then_success_recovers(self):
        fake = _ScriptedSupabase(failures=[_transient(), _transient()])
        rs, mock_sleep = _make_stats(fake)
        rs.set_symbol("SOFI")

        with self.assertLogs(
            "packages.quantum.options_scanner", level="WARNING"
        ) as cm:
            rs.record("edge_below_minimum")

        # Three attempts total; the third wrote the row.
        self.assertEqual(len(fake.attempts), 3)
        self.assertEqual(fake.attempts[-1]["payload"]["symbol"], "SOFI")
        # No loss counted; recovery counted and surfaced via to_dict().
        d = rs.to_dict()
        self.assertEqual(d["persist_failures"], 0)
        self.assertEqual(d["persist_retry_recoveries"], 1)
        # Backoffs consumed in order.
        self.assertEqual(
            [c.args[0] for c in mock_sleep.call_args_list],
            list(RejectionStats.PERSIST_RETRY_BACKOFFS),
        )
        # Recovery is WARNING-visible (deployed workers filter INFO).
        joined = "\n".join(cm.output)
        self.assertIn("recovered after transient-disconnect retry", joined)
        self.assertIn("SOFI", joined)

    def test_remote_protocol_error_class_is_retried(self):
        # Class-name (MRO) match, message deliberately unhelpful.
        fake = _ScriptedSupabase(failures=[_RemoteProtocolError("boom")])
        rs, mock_sleep = _make_stats(fake)
        rs.set_symbol("QQQ")
        rs.record("spread_too_wide")
        self.assertEqual(len(fake.attempts), 2)
        self.assertEqual(mock_sleep.call_count, 1)
        self.assertEqual(rs.to_dict()["persist_failures"], 0)
        self.assertEqual(rs.to_dict()["persist_retry_recoveries"], 1)


class TestTransientExhaustsRetries(unittest.TestCase):
    """A transient that survives every retry is a counted loss with a
    DISTINCT marker — never an exception into the scan."""

    def test_exhausted_transient_counts_failure_with_marker(self):
        n = 1 + len(RejectionStats.PERSIST_RETRY_BACKOFFS)
        fake = _ScriptedSupabase(failures=[_transient() for _ in range(n)])
        rs, mock_sleep = _make_stats(fake)
        rs.set_symbol("MSFT")

        with self.assertLogs(
            "packages.quantum.options_scanner", level="WARNING"
        ) as cm:
            rs.record("processing_error")  # must NOT raise

        self.assertEqual(len(fake.attempts), n)
        self.assertEqual(
            mock_sleep.call_count, len(RejectionStats.PERSIST_RETRY_BACKOFFS)
        )
        d = rs.to_dict()
        self.assertEqual(d["persist_failures"], 1)
        self.assertEqual(d["persist_retry_recoveries"], 0)
        # Aggregate flow unaffected.
        self.assertEqual(rs._counts["processing_error"], 1)
        joined = "\n".join(cm.output)
        # Distinct loss marker AND the unchanged final fallback line.
        self.assertIn("rejection_row_lost_after_retries", joined)
        self.assertIn("suggestion_rejections insert failed", joined)


class TestNonTransientNotRetried(unittest.TestCase):
    """Every other exception keeps the pre-A5 behavior exactly: one
    attempt, counted, warned, never raised, never slept on."""

    def test_non_transient_single_attempt(self):
        fake = _ScriptedSupabase(
            failures=[RuntimeError("simulated db failure")]
        )
        rs, mock_sleep = _make_stats(fake)
        rs.set_symbol("NVDA")
        rs.record("dte_out_of_range")
        self.assertEqual(len(fake.attempts), 1)
        mock_sleep.assert_not_called()
        d = rs.to_dict()
        self.assertEqual(d["persist_failures"], 1)
        self.assertEqual(d["persist_retry_recoveries"], 0)


class TestCleanPathUnchanged(unittest.TestCase):
    """Success on the first attempt: no sleep, no recovery count — the
    hot path is byte-for-byte the old behavior. Also pins the default
    wiring: no retry_sleep kwarg → real time.sleep bound."""

    def test_clean_insert_single_attempt_no_sleep(self):
        fake = _ScriptedSupabase()
        rs, mock_sleep = _make_stats(fake)
        rs.set_symbol("AAPL")
        rs.record("entry_cost_too_low")
        self.assertEqual(len(fake.attempts), 1)
        mock_sleep.assert_not_called()
        d = rs.to_dict()
        self.assertEqual(d["persist_failures"], 0)
        self.assertEqual(d["persist_retry_recoveries"], 0)

    def test_default_retry_sleep_is_time_sleep(self):
        import time as _time

        rs = RejectionStats()
        self.assertIs(rs._retry_sleep, _time.sleep)


if __name__ == "__main__":
    unittest.main()
