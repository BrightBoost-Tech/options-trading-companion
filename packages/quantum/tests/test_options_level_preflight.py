"""Options-level entry preflight (2026-07-16) — unit layer.

Covers the three seams the lane touches, at the unit level (the route test
that drives _stage_order_internal end-to-end lives in
test_options_level_preflight_route.py):

1. AlpacaClient.get_account() wrapper: options_approved_level /
   options_trading_level serialized INDEPENDENTLY, None-preserving
   (missing attr → None, never 0; a real 0 stays 0; malformed → None +
   one loud typed log — never a whole-account-read failure).
2. services/options_level_preflight: STRATEGY_MIN_LEVEL map (selector ids
   → L3, long premium → L2, covered/CSP → L1, unknown → conservative L3),
   permission basis = EFFECTIVE options_trading_level (approved level is
   diagnostics-only), missing/malformed effective level → fail CLOSED with
   the typed unavailable reason, closes never evaluated.
3. alpaca_order_handler terminal classification: permission-shaped broker
   rejection strings classify TERMINAL (1 attempt, no retry) via
   _TERMINAL_REJECT_MARKERS, driven through the REAL submit_and_track loop
   — not a reimplementation of the marker match.
"""

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Stub alpaca-py so transitive imports resolve in the test venv (same
# pattern as test_entry_quote_validation.py).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.services.options_level_preflight import (  # noqa: E402
    ACCOUNT_LEVEL_TTL_SECONDS,
    FUTURE_CAPABILITY_IDS,
    STRATEGY_MIN_LEVEL,
    UNKNOWN_STRATEGY_MIN_LEVEL,
    EntryOptionsLevelInsufficient,
    EntryOptionsLevelUnavailable,
    _assert_permission_map_locked,
    _permission_map_drift,
    check_options_level,
    get_account_with_ttl,
    is_no_trade_verdict,
    normalize_strategy_id,
    required_options_level,
    reset_account_cache,
)


# ─────────────────────────────────────────────────────────────────────
# 1. Wrapper: get_account() level-field serialization
# ─────────────────────────────────────────────────────────────────────


def _acct(**over):
    """SimpleNamespace SDK-account fake — mirrors only the fields
    get_account() reads (the test_m4_obp_failclosed_and_wiring pattern;
    SimpleNamespace so a MISSING attribute is genuinely missing, unlike
    MagicMock's auto-attributes)."""
    base = dict(
        id="acct-uuid", status="ACTIVE", equity="2093.74",
        last_equity="2093.74", cash="2093.74", buying_power="8374.96",
        options_buying_power="2093.74", portfolio_value="2093.74",
        pattern_day_trader=False, daytrade_count=0,
        daytrading_buying_power="8374.96",
        options_approved_level=3, options_trading_level=3,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _client_with(acct):
    from packages.quantum.brokers.alpaca_client import AlpacaClient
    c = AlpacaClient.__new__(AlpacaClient)
    c.paper = False
    c._client = MagicMock()
    c._call_with_retry = lambda fn, *a, **k: acct
    return c


class TestWrapperLevelFields(unittest.TestCase):
    def test_approved_and_effective_serialized_independently(self):
        """The broker can throttle the effective level below the approved
        level — the two fields must never be conflated."""
        out = _client_with(
            _acct(options_approved_level=3, options_trading_level=2)
        ).get_account()
        self.assertEqual(out["options_approved_level"], 3)
        self.assertEqual(out["options_trading_level"], 2)

    def test_missing_attrs_serialize_none_not_zero(self):
        """Legacy paper account lacking the fields entirely → None (the
        cannot-prove-permission signal), NEVER 0."""
        acct = _acct()
        del acct.options_approved_level
        del acct.options_trading_level
        out = _client_with(acct).get_account()
        self.assertIsNone(out["options_approved_level"])
        self.assertIsNone(out["options_trading_level"])

    def test_real_zero_stays_zero_and_is_distinguishable_from_none(self):
        out = _client_with(
            _acct(options_approved_level=0, options_trading_level=0)
        ).get_account()
        self.assertEqual(out["options_approved_level"], 0)
        self.assertEqual(out["options_trading_level"], 0)
        # 0 and None must be distinguishable (is-comparisons, not truthiness)
        self.assertIsNotNone(out["options_approved_level"])
        self.assertIsNotNone(out["options_trading_level"])

    def test_none_values_preserved(self):
        """Attr present but None (broker nulled it) → None preserved."""
        out = _client_with(
            _acct(options_approved_level=None, options_trading_level=None)
        ).get_account()
        self.assertIsNone(out["options_approved_level"])
        self.assertIsNone(out["options_trading_level"])

    def test_string_int_coerced(self):
        """The SDK serializes some numerics as strings — '3' → 3."""
        out = _client_with(
            _acct(options_approved_level="3", options_trading_level="3")
        ).get_account()
        self.assertEqual(out["options_approved_level"], 3)
        self.assertEqual(out["options_trading_level"], 3)

    def test_malformed_serializes_none_with_loud_log_not_account_failure(self):
        """Non-int-coercible → None + ONE loud typed log; the account read
        itself must SUCCEED (M4 item 0.1: optional-field garbage must never
        kill get_account for capital consumers)."""
        acct = _acct(options_trading_level="garbage")
        with self.assertLogs(
            "packages.quantum.brokers.alpaca_client", level="ERROR"
        ) as cm:
            out = _client_with(acct).get_account()
        self.assertIsNone(out["options_trading_level"])
        self.assertEqual(out["options_approved_level"], 3)  # unaffected
        self.assertTrue(
            any("options_trading_level" in m and "malformed" in m
                for m in cm.output),
            cm.output,
        )
        # The read still returned the capital fields.
        self.assertEqual(out["options_buying_power"], 2093.74)

    def test_existing_fields_unchanged(self):
        """Additive: the pre-existing 12-key shape is untouched."""
        out = _client_with(_acct()).get_account()
        for key in ("account_id", "status", "equity", "last_equity", "cash",
                    "buying_power", "options_buying_power", "portfolio_value",
                    "pattern_day_trader", "daytrade_count",
                    "daytrading_buying_power", "paper"):
            self.assertIn(key, out)


# ─────────────────────────────────────────────────────────────────────
# 2. Strategy → minimum level map + preflight decision
# ─────────────────────────────────────────────────────────────────────


# The ids the selector actually emits (analytics/strategy_selector.py,
# UPPERCASE) — every one is a multi-leg spread → L3.
SELECTOR_STRATEGY_IDS = (
    "LONG_CALL_DEBIT_SPREAD",
    "LONG_PUT_DEBIT_SPREAD",
    "SHORT_PUT_CREDIT_SPREAD",
    "SHORT_CALL_CREDIT_SPREAD",
    "IRON_CONDOR",
)


def _account(effective, approved=3):
    return {
        "options_trading_level": effective,
        "options_approved_level": approved,
    }


class TestStrategyMinLevelMap(unittest.TestCase):
    def test_every_selector_strategy_requires_level_3(self):
        for sid in SELECTOR_STRATEGY_IDS:
            with self.subTest(strategy=sid):
                self.assertEqual(required_options_level(sid), 3)

    def test_long_premium_requires_level_2(self):
        self.assertEqual(required_options_level("long_call"), 2)
        self.assertEqual(required_options_level("long_put"), 2)
        self.assertEqual(required_options_level("LONG_CALL"), 2)

    def test_level_1_income_structures(self):
        self.assertEqual(required_options_level("covered_call"), 1)
        self.assertEqual(required_options_level("cash_secured_put"), 1)

    def test_unknown_strategy_requires_conservative_level_3(self):
        """Never permit-by-default: unseen id → the L3 REQUIREMENT."""
        self.assertEqual(UNKNOWN_STRATEGY_MIN_LEVEL, 3)
        for sid in ("custom", "some_future_structure", "", None, "unknown"):
            with self.subTest(strategy=sid):
                self.assertEqual(
                    required_options_level(sid), UNKNOWN_STRATEGY_MIN_LEVEL
                )

    def test_normalization_matches_registry_convention(self):
        """lowercase + strip + spaces/hyphens → underscores (the
        infer_strategy_key_from_suggestion normalization)."""
        self.assertEqual(
            normalize_strategy_id(" Long-Call Debit_Spread "),
            "long_call_debit_spread",
        )

    def test_map_covers_all_selector_ids_exactly_normalized(self):
        for sid in SELECTOR_STRATEGY_IDS:
            self.assertIn(normalize_strategy_id(sid), STRATEGY_MIN_LEVEL)


class TestIdentityIntegration(unittest.TestCase):
    """The preflight consumes the CANONICAL identity source
    (analytics/strategy_identity) — no duplicate normalization, no second
    selector registry, drift-locked permission map."""

    def test_normalize_is_the_canonical_function(self):
        """The module re-exports strategy_identity's normalize — it must be
        the SAME object, not a copy (the duplicate-normalization class)."""
        from packages.quantum.analytics import strategy_identity as si
        self.assertIs(normalize_strategy_id, si.normalize_strategy_id)

    def test_tradable_domain_derived_from_strategy_identity(self):
        """Every canonical tradable id has an explicit mapping, derived
        from TRADABLE_IDS (the selector registry), not a local list — and
        all of today's tradables are multi-leg spreads → L3."""
        from packages.quantum.analytics.strategy_identity import TRADABLE_IDS
        for tid in TRADABLE_IDS:
            with self.subTest(strategy=tid):
                self.assertIn(tid, STRATEGY_MIN_LEVEL)
                self.assertEqual(STRATEGY_MIN_LEVEL[tid], 3)

    def test_future_capability_ids_excluded_from_drift_domain(self):
        """covered_call/CSP + long premium are future-capability keys —
        allowed in the map, declared, and NOT selector-tradable today."""
        from packages.quantum.analytics.strategy_identity import TRADABLE_IDS
        for fid in ("long_call", "long_put", "covered_call",
                    "cash_secured_put"):
            self.assertIn(fid, FUTURE_CAPABILITY_IDS)
            self.assertNotIn(fid, TRADABLE_IDS)
            self.assertIn(fid, STRATEGY_MIN_LEVEL)

    def test_drift_lock_clean_on_current_state(self):
        missing, unexplained = _permission_map_drift()
        self.assertEqual(missing, frozenset())
        self.assertEqual(unexplained, frozenset())
        _assert_permission_map_locked()  # must not raise

    def test_drift_lock_trips_on_new_tradable_missing_from_map(self):
        """A newly added selector strategy absent from the permission map
        must fail LOUDLY (import-time RuntimeError), never be silently
        omitted."""
        from packages.quantum.analytics.strategy_identity import TRADABLE_IDS
        drifted = frozenset(TRADABLE_IDS) | {"brand_new_selector_spread"}
        missing, _ = _permission_map_drift(tradable_ids=drifted)
        self.assertEqual(missing, frozenset({"brand_new_selector_spread"}))
        with self.assertRaises(RuntimeError) as cm:
            _assert_permission_map_locked(tradable_ids=drifted)
        self.assertIn("brand_new_selector_spread", str(cm.exception))

    def test_drift_lock_trips_on_unexplained_map_key(self):
        """A map key that is neither tradable nor declared future-capability
        is a typo/stale entry/second registry — the lock must trip."""
        bad_map = dict(STRATEGY_MIN_LEVEL)
        bad_map["mystery_structure"] = 2
        _, unexplained = _permission_map_drift(permission_map=bad_map)
        self.assertEqual(unexplained, frozenset({"mystery_structure"}))
        with self.assertRaises(RuntimeError):
            _assert_permission_map_locked(permission_map=bad_map)

    def test_hold_cash_are_not_in_the_permission_map(self):
        """No-trade verdicts must never look like permissioned structures."""
        for nid in ("hold", "cash"):
            self.assertNotIn(nid, STRATEGY_MIN_LEVEL)
            self.assertNotIn(nid, FUTURE_CAPABILITY_IDS)


class TestNoTradeVerdicts(unittest.TestCase):
    """HOLD/CASH: not option structures — no requirement, never evaluated
    against the account, never treated as submitted structures."""

    def test_is_no_trade_verdict_truth_table(self):
        for nid in ("HOLD", "hold", "CASH", "cash", " Hold "):
            self.assertTrue(is_no_trade_verdict(nid), nid)
        for sid in ("IRON_CONDOR", "long_call", "unknown_thing", "", None):
            self.assertFalse(is_no_trade_verdict(sid), sid)

    def test_required_level_is_none_for_no_trade(self):
        self.assertIsNone(required_options_level("HOLD"))
        self.assertIsNone(required_options_level("cash"))

    def test_check_options_level_never_evaluates_no_trade(self):
        """Even is_open_order=True with the WORST account payloads: a
        no-trade verdict returns None (no requirement) and never raises —
        it is not a structure that could be submitted."""
        for nid in ("HOLD", "CASH"):
            for account in (_account(effective=None), {}, None,
                            _account(effective=0),
                            _account(effective=2)):
                with self.subTest(strategy=nid, account=account):
                    self.assertIsNone(check_options_level(
                        nid, is_open_order=True, account=account,
                    ))


class _CountingClient:
    """Fake broker client: counts get_account calls; programmable payload."""

    def __init__(self, payload=None):
        self.calls = 0
        self.payload = payload if payload is not None else {
            "options_trading_level": 3, "options_approved_level": 3,
        }
        self.raise_on_next = None

    def get_account(self):
        self.calls += 1
        if self.raise_on_next is not None:
            err, self.raise_on_next = self.raise_on_next, None
            raise err
        return self.payload


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class TestAccountTTLCache(unittest.TestCase):
    """get_account_with_ttl: 60s TTL (the equity_state pattern), keyed per
    client identity, bypass-safe (failure/None never cached)."""

    def setUp(self):
        reset_account_cache()

    def tearDown(self):
        reset_account_cache()

    def test_ttl_is_60_seconds_matching_equity_state(self):
        self.assertEqual(ACCOUNT_LEVEL_TTL_SECONDS, 60.0)

    def test_reuse_within_ttl_single_underlying_read(self):
        client = _CountingClient()
        a1 = get_account_with_ttl(client)
        a2 = get_account_with_ttl(client)
        self.assertEqual(client.calls, 1)
        self.assertIs(a1, a2)

    def test_expiry_after_ttl_rereads(self):
        import packages.quantum.services.options_level_preflight as olp
        clock = _Clock()
        client = _CountingClient()
        with patch.object(olp.time, "monotonic", clock):
            get_account_with_ttl(client)
            clock.t += ACCOUNT_LEVEL_TTL_SECONDS - 0.5  # still fresh
            get_account_with_ttl(client)
            self.assertEqual(client.calls, 1)
            clock.t += 1.0  # now past the TTL
            get_account_with_ttl(client)
            self.assertEqual(client.calls, 2)

    def test_read_failure_never_cached_next_call_rereads(self):
        client = _CountingClient()
        client.raise_on_next = RuntimeError("broker down")
        with self.assertRaises(RuntimeError):
            get_account_with_ttl(client)
        self.assertEqual(client.calls, 1)
        # Recovery: the failure was not cached — the next call re-reads
        # and succeeds.
        out = get_account_with_ttl(client)
        self.assertEqual(client.calls, 2)
        self.assertEqual(out["options_trading_level"], 3)
        # And THAT successful read is now cached.
        get_account_with_ttl(client)
        self.assertEqual(client.calls, 2)

    def test_none_payload_never_cached(self):
        client = _CountingClient(payload=None)
        client.payload = None
        self.assertIsNone(get_account_with_ttl(client))
        self.assertIsNone(get_account_with_ttl(client))
        self.assertEqual(client.calls, 2)  # None re-reads every time
        client.payload = {"options_trading_level": 3}
        self.assertEqual(
            get_account_with_ttl(client)["options_trading_level"], 3
        )
        self.assertEqual(client.calls, 3)

    def test_keyed_per_client_identity(self):
        """Two distinct clients never share an entry (paper/live safety —
        production is a singleton, but the key must not conflate)."""
        c1 = _CountingClient({"options_trading_level": 3})
        c2 = _CountingClient({"options_trading_level": 1})
        self.assertEqual(
            get_account_with_ttl(c1)["options_trading_level"], 3
        )
        self.assertEqual(
            get_account_with_ttl(c2)["options_trading_level"], 1
        )
        self.assertEqual((c1.calls, c2.calls), (1, 1))


class TestCheckOptionsLevel(unittest.TestCase):
    def test_level_2_rejects_vertical_spread_open(self):
        with self.assertRaises(EntryOptionsLevelInsufficient) as cm:
            check_options_level(
                "LONG_PUT_DEBIT_SPREAD", is_open_order=True,
                account=_account(effective=2, approved=3),
            )
        self.assertEqual(cm.exception.required_level, 3)
        self.assertEqual(cm.exception.effective_level, 2)
        self.assertEqual(
            cm.exception.blocked_reason, "entry_options_level_insufficient"
        )

    def test_level_2_permits_long_call_open(self):
        """Test-only candidate — long_call is not selector-reachable today;
        no selector change implied."""
        diag = check_options_level(
            "long_call", is_open_order=True,
            account=_account(effective=2),
        )
        self.assertEqual(diag["required_level"], 2)
        self.assertEqual(diag["effective_level"], 2)

    def test_level_3_permits_all_shipped_structures(self):
        """The healthy path (current live account: approved=3/effective=3)
        — every selector-emitted structure allowed."""
        for sid in SELECTOR_STRATEGY_IDS:
            with self.subTest(strategy=sid):
                diag = check_options_level(
                    sid, is_open_order=True,
                    account=_account(effective=3, approved=3),
                )
                self.assertEqual(diag["effective_level"], 3)

    def test_approved_level_never_grants_permission(self):
        """Permission basis is the EFFECTIVE level; approved=3 with a
        throttled effective=1 must still reject a spread."""
        with self.assertRaises(EntryOptionsLevelInsufficient) as cm:
            check_options_level(
                "IRON_CONDOR", is_open_order=True,
                account=_account(effective=1, approved=3),
            )
        self.assertEqual(cm.exception.approved_level, 3)
        self.assertEqual(cm.exception.effective_level, 1)

    def test_missing_effective_level_fails_closed_typed(self):
        for account in (_account(effective=None), {}, None):
            with self.subTest(account=account):
                with self.assertRaises(EntryOptionsLevelUnavailable) as cm:
                    check_options_level(
                        "LONG_CALL_DEBIT_SPREAD", is_open_order=True,
                        account=account,
                    )
                self.assertEqual(
                    cm.exception.blocked_reason,
                    "entry_options_level_unavailable",
                )

    def test_effective_level_zero_is_not_missing_but_rejects_all(self):
        """A real 0 is a valid read (no options permission at all) — it
        must classify INSUFFICIENT (with the true numbers), not
        unavailable."""
        with self.assertRaises(EntryOptionsLevelInsufficient) as cm:
            check_options_level(
                "long_call", is_open_order=True,
                account=_account(effective=0),
            )
        self.assertEqual(cm.exception.effective_level, 0)

    def test_malformed_effective_level_fails_closed(self):
        with self.assertRaises(EntryOptionsLevelUnavailable):
            check_options_level(
                "IRON_CONDOR", is_open_order=True,
                account=_account(effective="garbage"),
            )

    def test_unknown_strategy_needs_level_3(self):
        # effective 2 < conservative requirement 3 → reject
        with self.assertRaises(EntryOptionsLevelInsufficient):
            check_options_level(
                "brand_new_structure", is_open_order=True,
                account=_account(effective=2),
            )
        # effective 3 → allowed even though unknown
        diag = check_options_level(
            "brand_new_structure", is_open_order=True,
            account=_account(effective=3),
        )
        self.assertEqual(diag["required_level"], 3)

    def test_close_never_evaluated(self):
        """is_open_order=False → None, no raise — even on the worst
        account payload (defensive double guard; the wiring additionally
        never calls the preflight for closes)."""
        for account in (_account(effective=None), {}, None,
                        _account(effective=0)):
            with self.subTest(account=account):
                self.assertIsNone(check_options_level(
                    "IRON_CONDOR", is_open_order=False, account=account,
                ))


# ─────────────────────────────────────────────────────────────────────
# 3. Broker-side permission rejects classify TERMINAL
# ─────────────────────────────────────────────────────────────────────


# Real-shaped Alpaca permission rejection bodies (conservative substring
# targets: "not permitted", "options trading level", "options level",
# "not approved for").
PERMISSION_REJECT_STRINGS = (
    '{"code":40310000,"message":"requested order is not permitted based '
    'on your options trading level"}',
    "account is not approved for options trading",
    "403 Forbidden: your options level does not allow multi-leg orders",
)


def _order_row():
    return {
        "id": "ord-terminal-1",
        "execution_mode": "alpaca_live",
        "position_id": None,
        "side": "buy",
        "requested_price": 1.50,
        "requested_qty": 1,
        "order_json": {
            "symbol": "SPY",
            "legs": [
                {"symbol": "O:SPY260918C00650000", "action": "buy"},
                {"symbol": "O:SPY260918C00655000", "action": "sell"},
            ],
            "limit_price": 1.50,
        },
    }


class TestPermissionRejectIsTerminal(unittest.TestCase):
    """Drives the REAL submit_and_track retry loop (the existing
    classification site — not a copy of the marker match)."""

    def _run(self, error_message):
        from packages.quantum.brokers import alpaca_order_handler as h
        alpaca = MagicMock()
        alpaca.paper = False
        alpaca.submit_option_order.side_effect = Exception(error_message)
        supabase = MagicMock()
        with patch.object(h.time, "sleep"), \
                patch("packages.quantum.observability.alerts.alert"), \
                patch("packages.quantum.observability.alerts."
                      "_get_admin_supabase", return_value=MagicMock()):
            result = h.submit_and_track(
                alpaca, supabase, _order_row(), user_id="user-1",
            )
        return result, alpaca

    def test_permission_shaped_rejects_are_terminal_one_attempt(self):
        for msg in PERMISSION_REJECT_STRINGS:
            with self.subTest(error=msg[:60]):
                result, alpaca = self._run(msg)
                self.assertEqual(result["status"], "needs_manual_review")
                self.assertEqual(
                    result["attempts"], 1,
                    "permission reject must be TERMINAL: 1 attempt, "
                    "no retry",
                )
                self.assertEqual(alpaca.submit_option_order.call_count, 1)

    def test_non_terminal_error_still_retries(self):
        """Control: the terminal classification must not have swallowed the
        retry behavior for ordinary transient errors."""
        from packages.quantum.brokers.alpaca_order_handler import (
            MAX_SUBMIT_ATTEMPTS,
        )
        result, alpaca = self._run("connection reset by peer")
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(result["attempts"], MAX_SUBMIT_ATTEMPTS)
        self.assertEqual(
            alpaca.submit_option_order.call_count, MAX_SUBMIT_ATTEMPTS
        )

    def test_marker_list_stayed_additive(self):
        """The pre-existing markers must all still be present (additive
        change only)."""
        from packages.quantum.brokers.alpaca_order_handler import (
            _TERMINAL_REJECT_MARKERS,
        )
        for legacy in ("42210000", "position intent mismatch",
                       "sign-incoherent", "insufficient", "extra_forbidden"):
            self.assertIn(legacy, _TERMINAL_REJECT_MARKERS)
        for added in ("not permitted", "options trading level",
                      "options level", "not approved for"):
            self.assertIn(added, _TERMINAL_REJECT_MARKERS)
            # markers must be lowercase — the match lowers the error string
            self.assertEqual(added, added.lower())


if __name__ == "__main__":
    unittest.main()
