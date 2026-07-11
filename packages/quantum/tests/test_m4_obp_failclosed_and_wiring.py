"""M4 (2026-07-06) — OBP/serializer fix (items 0.1–0.3), bias wiring (0b),
and the M2 strike-modulus filter.

THE PIN (item 0.3, production call path): "OBP/account=None must not
silently change the scanned universe" — in live mode a failed broker read
yields deployable 0.0 → CapitalScanPolicy blocks the cycle (entries
blocked, LOUD critical); the $500 baseline can never set the tier. The
07-06 incident: broker nulled the retired daytrade fields → int(None) in
the serializer → account read died → $500 fallback → micro tier → $60
price cap → 56 rejections → the viable set price-capped out (an INVERTED
universe, not a smaller one).
"""

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# --- sys.modules de-poisoning (CI 2026-07-06 failure class) ---------------
# test_weekly_report_win_rate.py replaces whole modules with MagicMocks at
# import time and never restores them, so a lazy in-test import that runs
# AFTER its collection binds a mock (green single-file local, red full-suite
# CI). Bind the REAL modules at THIS module's import, whatever the order.
for _key in (
    "packages.quantum.services.cash_service",
    "packages.quantum.options_scanner",
):
    if isinstance(sys.modules.get(_key), MagicMock):
        del sys.modules[_key]

from packages.quantum.brokers.alpaca_client import AlpacaClient
from packages.quantum.analytics.capital_scan_policy import CapitalScanPolicy
from packages.quantum.services.cash_service import CashService
from packages.quantum import options_scanner as _real_options_scanner


def _acct(**over):
    base = dict(
        id="acct-uuid", status="ACTIVE", equity="2093.74",
        last_equity="2093.74", cash="2093.74", buying_power="8374.96",
        options_buying_power="2093.74", portfolio_value="2093.74",
        pattern_day_trader=False, daytrade_count=0,
        daytrading_buying_power="8374.96",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _client_with(acct):
    c = AlpacaClient.__new__(AlpacaClient)
    c.paper = False
    c._client = MagicMock()
    c._call_with_retry = lambda fn, *a, **k: acct
    return c


class TestSerializerNullTolerance:
    def test_nulled_retired_daytrade_fields_do_not_crash(self):
        """The 07-06 incident shape: broker returns None for the retired PDT
        fields — the account read must SUCCEED with placeholder defaults."""
        acct = _acct(daytrade_count=None, daytrading_buying_power=None,
                     pattern_day_trader=None)
        out = _client_with(acct).get_account()
        assert out["daytrade_count"] == 0
        assert out["daytrading_buying_power"] == 0.0
        assert out["pattern_day_trader"] is False
        assert out["options_buying_power"] == 2093.74  # the field that matters

    def test_missing_daytrade_attr_entirely(self):
        acct = _acct()
        del acct.daytrade_count
        out = _client_with(acct).get_account()
        assert out["daytrade_count"] == 0

    def test_required_field_none_fails_loud_by_name(self):
        acct = _acct(equity=None)
        with pytest.raises(ValueError, match="required field 'equity'"):
            _client_with(acct).get_account()

    def test_none_preserving_fields_stay_none(self):
        acct = _acct(options_buying_power=None, last_equity=None)
        out = _client_with(acct).get_account()
        assert out["options_buying_power"] is None
        assert out["last_equity"] is None


class TestFailClosedCapital:
    """Item 0.2 — owner design: fully fail-closed in live mode."""

    def _svc(self):
        return CashService(MagicMock())

    def test_live_mode_obp_none_blocks_cycle_loudly(self):
        svc = self._svc()
        with patch("packages.quantum.services.equity_state."
                   "get_alpaca_options_buying_power", return_value=None):
            with patch.object(type(svc), "_is_paper_mode", return_value=False):
                with patch("packages.quantum.observability.alerts.alert") as m_alert:
                    with patch("packages.quantum.observability.alerts."
                               "_get_admin_supabase", return_value=MagicMock()):
                        out = asyncio.run(svc.get_deployable_capital("u1"))
        assert out == 0.0
        assert m_alert.called
        kwargs = m_alert.call_args.kwargs
        assert kwargs["alert_type"] == "account_unreadable_entries_blocked"
        assert kwargs["severity"] == "critical"
        # THE PIN: 0.0 deployable → the cycle is blocked by the existing
        # test-pinned CapitalScanPolicy path — the universe is never scanned
        # on fallback capital.
        allowed, _reason = CapitalScanPolicy.can_scan(out)
        assert allowed is False

    def test_paper_mode_retains_baseline(self):
        svc = self._svc()
        with patch("packages.quantum.services.equity_state."
                   "get_alpaca_options_buying_power", return_value=None):
            with patch.object(type(svc), "_is_paper_mode", return_value=True):
                with patch.object(type(svc), "_read_paper_baseline",
                                  return_value=500.0):
                    with patch("packages.quantum.observability.alerts.alert"):
                        with patch("packages.quantum.observability.alerts."
                                   "_get_admin_supabase",
                                   return_value=MagicMock()):
                            out = asyncio.run(svc.get_deployable_capital("u1"))
        assert out == 500.0  # explicit paper operation keeps its baseline

    def test_unreadable_ops_mode_treated_as_live(self):
        svc = CashService(MagicMock())
        with patch("packages.quantum.ops_endpoints.get_global_ops_control",
                   side_effect=RuntimeError("db down")):
            assert svc._is_paper_mode() is False  # cannot prove paper → live

    def test_healthy_obp_unchanged(self):
        svc = self._svc()
        with patch("packages.quantum.services.equity_state."
                   "get_alpaca_options_buying_power", return_value=2093.74):
            out = asyncio.run(svc.get_deployable_capital("u1"))
        assert out == 2093.74


class TestBiasWiringExecutorPath:
    """Viability-tier membership (real data). The bias's WIRING is now pinned
    by test_e7_viability_rewire_executor_route.py, which DRIVES the production
    route (_execute_per_cohort) end-to-end.

    RETIRED here 2026-07-11 (E7): test_executor_sort_applies_bias_when_armed
    (it REIMPLEMENTED the sort in-test, never touching the route) and
    test_production_call_path_is_wired (an inspect.getsource string-pin). Both
    were the #1126 costume in test form — green while the ACTIVE route
    (_execute_per_cohort) bypassed the wired method entirely (07-06→07-11). Per
    CLAUDE.md §9: a wiring test EXECUTES the production route, it does not
    REFERENCE the production function."""

    def test_new_tier_members_present(self):
        from packages.quantum.analytics.canonical_ranker import _VIABILITY_TIERS

        assert _VIABILITY_TIERS.get("DIA") == 1.15
        assert _VIABILITY_TIERS.get("CVX") == 1.15
        assert _VIABILITY_TIERS.get("GLD") == 1.15


class TestStrikeModulus:
    def test_gld_default_and_env_parse(self, monkeypatch):
        sc = _real_options_scanner

        assert sc._strike_modulus_for("GLD") == 5.0
        assert sc._strike_modulus_for("SPY") == 0.0
        assert sc._parse_strike_modulus("GLD:5,IWM:2.5") == {"GLD": 5.0, "IWM": 2.5}
        assert sc._parse_strike_modulus("garbage") == {}
        assert sc._parse_strike_modulus("X:-1,Y:banana") == {}
