"""Paper-shadow executor Phase 1a — BIDIRECTIONAL ISOLATION TEST SUITE.

This is the load-bearing deliverable of Phase 1a. It proves, before any
executor moves an order, that the isolation boundary holds in BOTH directions
plus the byte-identical-when-off property on the 3 live real-money job edits.

DIRECTION 1 — an executor order can NEVER reach the live account (211900084):
  - the dedicated paper client is built from dedicated paper creds, paper=True,
    and is INJECTED into the router so the global live get_alpaca_client() is
    never consulted;
  - the PA3I8CYLXBOS guard ABORTS (no order) if the broker reports any other
    account;
  - the executor FAILS CLOSED if the dedicated paper creds are absent.

DIRECTION 2 — the exclusion filter can NEVER hide a LIVE position:
  - no code path sets routing_mode='paper_shadow' on a live portfolio (in
    Phase 1a there is no setter at all);
  - the 3 live jobs' filters skip ONLY genuine paper_shadow portfolios; a live
    position is ALWAYS selected/managed, never orphaned.

BYTE-IDENTICAL-WHEN-OFF:
  - with no paper_shadow rows (always, pre-Phase-1b), each live job selects
    EXACTLY the same positions as before the filter was added.

All unit-level, mocked broker — no real creds, no market, no live calls.
"""

import os
import re
import unittest
from pathlib import Path
from unittest import mock

from packages.quantum.services import paper_shadow_isolation as iso

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────
# In-memory PostgREST-ish fake (applies eq/neq/in_ over fixture rows) so the
# REAL job code paths run through the REAL filter semantics.
# ─────────────────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = list(rows)

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) == val])

    def neq(self, col, val):
        return _FakeQuery([r for r in self._rows if r.get(col) != val])

    def in_(self, col, vals):
        s = set(vals)
        return _FakeQuery([r for r in self._rows if r.get(col) in s])

    def gt(self, col, val):
        return _FakeQuery(
            [r for r in self._rows if r.get(col) is not None and r.get(col) > val]
        )

    def execute(self):
        return _Resp(list(self._rows))


class _FakeSupabase:
    def __init__(self, tables):
        self._tables = tables  # {table_name: [rows]}

    def table(self, name):
        return _FakeQuery(self._tables.get(name, []))


def _fixture(include_paper_shadow: bool):
    """A LIVE portfolio (+1 open position) and, optionally, a PAPER_SHADOW
    portfolio (+1 open position), for the same user."""
    portfolios = [
        {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
    ]
    positions = [
        {"id": "pos-live", "portfolio_id": "port-live", "status": "open", "quantity": 1},
    ]
    if include_paper_shadow:
        portfolios.append(
            {"id": "port-shadow", "user_id": "U", "routing_mode": "paper_shadow"}
        )
        positions.append(
            {"id": "pos-shadow", "portfolio_id": "port-shadow", "status": "open", "quantity": 1}
        )
    return _FakeSupabase({"paper_portfolios": portfolios, "paper_positions": positions})


# ═════════════════════════════════════════════════════════════════════
# DIRECTION 1 — orders can never reach live
# ═════════════════════════════════════════════════════════════════════
class TestDirection1OrdersCannotReachLive(unittest.TestCase):
    def test_fails_closed_without_paper_creds(self):
        # No dedicated paper creds → cannot construct a client → FAIL CLOSED.
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(iso.PaperShadowConfigError):
                iso.build_paper_client()

    def test_uses_dedicated_paper_creds_paper_true_not_live_env(self):
        # Even with LIVE env present, the executor builds from the DEDICATED
        # paper creds with paper=True — never the live key.
        env = {
            "ALPACA_API_KEY": "LIVEKEY",          # live env present...
            "ALPACA_SECRET_KEY": "LIVESECRET",
            "ALPACA_PAPER_API_KEY": "PAPERKEY",   # ...but executor uses these
            "ALPACA_PAPER_SECRET_KEY": "PAPERSECRET",
        }
        fake_client = mock.MagicMock()
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch(
                 "packages.quantum.brokers.alpaca_client.AlpacaClient",
                 return_value=fake_client,
             ) as ctor:
            client = iso.build_paper_client()
        ctor.assert_called_once_with(
            api_key="PAPERKEY", secret_key="PAPERSECRET", paper=True
        )
        self.assertIs(client, fake_client)

    def test_account_guard_passes_on_paper_account(self):
        fake_client = mock.MagicMock()
        fake_client.get_account_number.return_value = "PA3I8CYLXBOS"
        self.assertEqual(iso.assert_paper_account(fake_client), "PA3I8CYLXBOS")

    def test_account_guard_aborts_on_live_account(self):
        # Broker reports the LIVE account → abort, raise, NO order.
        fake_client = mock.MagicMock()
        fake_client.get_account_number.return_value = "211900084"
        with self.assertRaises(iso.PaperShadowAccountMismatch):
            iso.assert_paper_account(fake_client)

    def test_guarded_router_injects_paper_client_and_never_calls_global(self):
        fake_client = mock.MagicMock()
        fake_client.get_account_number.return_value = "PA3I8CYLXBOS"
        env = {"ALPACA_PAPER_API_KEY": "PAPERKEY", "ALPACA_PAPER_SECRET_KEY": "PAPERSECRET"}
        # If the global live factory is EVER consulted, fail loudly.
        global_spy = mock.MagicMock(side_effect=AssertionError("global get_alpaca_client() must NOT be called"))
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("packages.quantum.brokers.alpaca_client.AlpacaClient", return_value=fake_client), \
             mock.patch("packages.quantum.brokers.alpaca_client.get_alpaca_client", global_spy):
            router = iso.build_guarded_paper_router(supabase=None)
            # Injected client present → property returns it without the global.
            self.assertIs(router._alpaca, fake_client)
            self.assertIs(router.alpaca, fake_client)
        global_spy.assert_not_called()

    def test_guarded_router_aborts_on_live_account_no_router_built(self):
        fake_client = mock.MagicMock()
        fake_client.get_account_number.return_value = "211900084"  # live
        env = {"ALPACA_PAPER_API_KEY": "PAPERKEY", "ALPACA_PAPER_SECRET_KEY": "PAPERSECRET"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("packages.quantum.brokers.alpaca_client.AlpacaClient", return_value=fake_client):
            with self.assertRaises(iso.PaperShadowAccountMismatch):
                iso.build_guarded_paper_router(supabase=None)


# ═════════════════════════════════════════════════════════════════════
# DIRECTION 2 — the filter can never hide a LIVE position
# ═════════════════════════════════════════════════════════════════════
class TestDirection2FilterCannotHideLive(unittest.TestCase):
    def _intraday_fetch(self, supabase):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        m.supabase = supabase
        return m._fetch_open_positions("U")

    def _evaluator_fetch(self, supabase):
        from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
        return PaperExitEvaluator(supabase)._get_open_positions("U")

    def test_intraday_excludes_paper_shadow_keeps_live(self):
        rows = self._intraday_fetch(_fixture(include_paper_shadow=True))
        ids = {r["id"] for r in rows}
        self.assertIn("pos-live", ids, "LIVE position must always be managed")
        self.assertNotIn("pos-shadow", ids, "paper_shadow position must be excluded")

    def test_evaluator_excludes_paper_shadow_keeps_live(self):
        rows = self._evaluator_fetch(_fixture(include_paper_shadow=True))
        ids = {r["id"] for r in rows}
        self.assertIn("pos-live", ids, "LIVE position must always be managed")
        self.assertNotIn("pos-shadow", ids, "paper_shadow position must be excluded")

    def test_no_runtime_code_sets_paper_shadow(self):
        # Direction-2 root guarantee: in Phase 1a NOTHING writes
        # routing_mode='paper_shadow'. Scan production .py (excluding tests +
        # the isolation module's constant/docstring) for a write of the value.
        offenders = []
        write_re = re.compile(r"(insert|update|upsert)\s*\(", re.IGNORECASE)
        for p in (REPO_ROOT).rglob("*.py"):
            rel = p.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in f"/{rel}" or rel.endswith("paper_shadow_isolation.py"):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            for m in re.finditer(r"paper_shadow", text):
                # a line that both mentions paper_shadow AND performs a write
                line_start = text.rfind("\n", 0, m.start()) + 1
                line_end = text.find("\n", m.start())
                line = text[line_start:line_end if line_end != -1 else len(text)]
                if write_re.search(line):
                    offenders.append(f"{rel}: {line.strip()}")
        self.assertEqual(
            offenders, [],
            f"No production code may SET routing_mode='paper_shadow' in Phase 1a; found: {offenders}",
        )


# ═════════════════════════════════════════════════════════════════════
# BYTE-IDENTICAL WHEN OFF (no paper_shadow rows → unchanged selection)
# ═════════════════════════════════════════════════════════════════════
class TestByteIdenticalWhenOff(unittest.TestCase):
    def _intraday_fetch(self, supabase):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor
        m = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
        m.supabase = supabase
        return m._fetch_open_positions("U")

    def _evaluator_fetch(self, supabase):
        from packages.quantum.services.paper_exit_evaluator import PaperExitEvaluator
        return PaperExitEvaluator(supabase)._get_open_positions("U")

    def test_intraday_no_paper_shadow_selects_all_live(self):
        rows = self._intraday_fetch(_fixture(include_paper_shadow=False))
        self.assertEqual({r["id"] for r in rows}, {"pos-live"})

    def test_evaluator_no_paper_shadow_selects_all_live(self):
        rows = self._evaluator_fetch(_fixture(include_paper_shadow=False))
        self.assertEqual({r["id"] for r in rows}, {"pos-live"})


# ═════════════════════════════════════════════════════════════════════
# Source-level regression guards on the live-file edits (filters wired)
# ═════════════════════════════════════════════════════════════════════
class TestLiveJobFiltersWired(unittest.TestCase):
    def _src(self, rel):
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    def test_intraday_filter_present(self):
        s = self._src("jobs/handlers/intraday_risk_monitor.py")
        self.assertIn('.neq("routing_mode", "paper_shadow")', s)

    def test_evaluator_filter_present(self):
        s = self._src("services/paper_exit_evaluator.py")
        self.assertIn('.neq("routing_mode", "paper_shadow")', s)

    def test_order_sync_filter_present(self):
        s = self._src("jobs/handlers/alpaca_order_sync.py")
        # Extends the shadow_only exclusion to also cover paper_shadow.
        self.assertIn('"paper_shadow"', s)
        self.assertIn('.in_("routing_mode", ["shadow_only", "paper_shadow"])', s)


# ═════════════════════════════════════════════════════════════════════
# Flag default OFF
# ═════════════════════════════════════════════════════════════════════
class TestFlagDefaultOff(unittest.TestCase):
    def test_flag_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(iso.is_enabled())

    def test_flag_on_when_set(self):
        for v in ("1", "true", "TRUE", "yes", "on"):
            with mock.patch.dict(os.environ, {iso.FLAG_ENV: v}, clear=True):
                self.assertTrue(iso.is_enabled(), f"{v!r} should enable")

    def test_flag_off_for_falsey(self):
        for v in ("0", "false", "no", "", "off"):
            with mock.patch.dict(os.environ, {iso.FLAG_ENV: v}, clear=True):
                self.assertFalse(iso.is_enabled(), f"{v!r} should NOT enable")


if __name__ == "__main__":
    unittest.main()
