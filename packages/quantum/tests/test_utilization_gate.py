"""Tests for the #1044 85% total-utilization entry gate (Phase B).

Pins, per the B3/B4 contract:
- utilization math on broker-basis committed capital + candidate inclusion
- <=cap passes / >cap blocks / boundary at exactly the cap passes
- FAIL-CLOSED on every unreadable input (OBP, broker positions, cost_basis,
  threshold env, candidate cost)
- flag polarity INVERTED from safety controls: explicit "1" required;
  absent/empty/true/other -> legacy (disabled) — test-pinned BOTH ways
- B2 demotion: concentration_symbol WARN only when the config field is set
  by a call site; default stays BLOCK (legacy regression pin)
- other envelope severities unchanged (sector/expiry/stress warn,
  earnings block, loss_per_symbol force_close)
- multi-position accumulation 0->1->2->3 passes under the cap (the exact
  shape the legacy share-of-book BLOCK made impossible)
"""

import logging

import pytest

from packages.quantum.risk import utilization_gate as ug
from packages.quantum.risk.risk_envelope import (
    EnvelopeConfig,
    check_all_envelopes,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

class _FakeAlpaca:
    def __init__(self, positions=None, raise_on_positions=None):
        self._positions = positions or []
        self._raise = raise_on_positions

    def get_positions(self):
        if self._raise is not None:
            raise self._raise
        return self._positions


def _opt(cost_basis, symbol="NFLX260710P00086000"):
    return {
        "symbol": symbol,
        "symbol_alpaca": symbol,
        "asset_class": "us_option",
        "cost_basis": cost_basis,
    }


def _equity_pos(cost_basis=1234.0):
    return {
        "symbol": "SPY",
        "symbol_alpaca": "SPY",
        "asset_class": "us_equity",
        "cost_basis": cost_basis,
    }


def _optq(cost_basis, qty, symbol="NFLX260710P00086000"):
    return {**_opt(cost_basis, symbol), "qty": qty}


def _todays_book():
    """The actual 06-11 broker book (10 legs): the NFLX debit spread plus the
    two live condors whose credit premiums netted committed down to $56 under
    the old per-leg sum, while Alpaca held $1,000 of condor margin.
    cost_basis values are the broker's (signed; short legs negative)."""
    return [
        # NFLX 7/10 bear-put debit spread — net +365
        _optq(516.0, 1, "NFLX260710P00086000"),
        _optq(-151.0, -1, "NFLX260710P00079000"),
        # QQQ 7/10 iron condor — net −161 credit, 5-wide wings
        _optq(-646.0, -1, "QQQ260710P00645000"),
        _optq(584.0, 1, "QQQ260710P00640000"),
        _optq(-541.0, -1, "QQQ260710C00750000"),
        _optq(442.0, 1, "QQQ260710C00755000"),
        # SPY 7/24 iron condor — net −148 credit, 5-wide wings
        _optq(-539.0, -1, "SPY260724P00681000"),
        _optq(486.0, 1, "SPY260724P00676000"),
        _optq(-381.0, -1, "SPY260724C00765000"),
        _optq(286.0, 1, "SPY260724C00770000"),
    ]


@pytest.fixture
def gate_on(monkeypatch):
    monkeypatch.setenv(ug.FLAG_ENV, "1")
    monkeypatch.setenv(ug.THRESHOLD_ENV, "0.85")


# ---------------------------------------------------------------------------
# B3 — flag polarity (INVERTED: explicit "1" required), pinned both ways
# ---------------------------------------------------------------------------

class TestFlagPolarity:
    def test_unset_is_disabled_legacy(self, monkeypatch):
        monkeypatch.delenv(ug.FLAG_ENV, raising=False)
        assert ug.is_enabled() is False

    def test_empty_is_disabled_legacy(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, "")
        assert ug.is_enabled() is False

    def test_whitespace_is_disabled_legacy(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, "   ")
        assert ug.is_enabled() is False

    def test_true_string_is_DISABLED_strict_parse(self, monkeypatch):
        # The INTRADAY_TARGET_PROFIT lesson, inverted on purpose: for a
        # behavioral-change flag, a sloppy value must fail SAFE to legacy.
        monkeypatch.setenv(ug.FLAG_ENV, "true")
        assert ug.is_enabled() is False

    def test_zero_is_disabled(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, "0")
        assert ug.is_enabled() is False

    def test_explicit_1_enables(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, "1")
        assert ug.is_enabled() is True

    def test_padded_1_enables(self, monkeypatch):
        monkeypatch.setenv(ug.FLAG_ENV, " 1 ")
        assert ug.is_enabled() is True

    def test_echo_warns_on_nonempty_non_1(self, monkeypatch, caplog):
        monkeypatch.setenv(ug.FLAG_ENV, "true")
        with caplog.at_level(logging.WARNING):
            ug.echo_flag_state()
        assert any(
            "does NOT parse as enabled" in r.message for r in caplog.records
        )


# ---------------------------------------------------------------------------
# B1 — threshold: explicit env, NO implicit default
# ---------------------------------------------------------------------------

class TestThreshold:
    def test_missing_raises_fail_closed(self, monkeypatch):
        monkeypatch.delenv(ug.THRESHOLD_ENV, raising=False)
        with pytest.raises(ug.UtilizationGateError):
            ug.max_utilization_pct()

    def test_empty_raises(self, monkeypatch):
        monkeypatch.setenv(ug.THRESHOLD_ENV, "")
        with pytest.raises(ug.UtilizationGateError):
            ug.max_utilization_pct()

    def test_garbage_raises(self, monkeypatch):
        monkeypatch.setenv(ug.THRESHOLD_ENV, "eighty-five")
        with pytest.raises(ug.UtilizationGateError):
            ug.max_utilization_pct()

    def test_zero_raises(self, monkeypatch):
        monkeypatch.setenv(ug.THRESHOLD_ENV, "0")
        with pytest.raises(ug.UtilizationGateError):
            ug.max_utilization_pct()

    def test_above_one_raises(self, monkeypatch):
        monkeypatch.setenv(ug.THRESHOLD_ENV, "1.5")
        with pytest.raises(ug.UtilizationGateError):
            ug.max_utilization_pct()

    def test_085_parses(self, monkeypatch):
        monkeypatch.setenv(ug.THRESHOLD_ENV, "0.85")
        assert ug.max_utilization_pct() == 0.85


# ---------------------------------------------------------------------------
# B1 — committed capital from BROKER positions (cost basis), fail-closed
# ---------------------------------------------------------------------------

class TestCommittedCapital:
    def test_net_debit_spread_sums_to_net_basis(self, monkeypatch):
        # The live NFLX book shape: long P86 $516, short P79 -$151 -> $365.
        monkeypatch.setattr(
            ug, "_get_alpaca",
            lambda: _FakeAlpaca([_opt(516.0), _opt(-151.0, "NFLX260710P00079000")]),
        )
        assert ug.fetch_committed_capital() == pytest.approx(365.0)

    def test_equity_positions_excluded(self, monkeypatch):
        monkeypatch.setattr(
            ug, "_get_alpaca",
            lambda: _FakeAlpaca([_opt(516.0), _equity_pos(99999.0)]),
        )
        assert ug.fetch_committed_capital() == pytest.approx(516.0)

    def test_flat_book_is_zero(self, monkeypatch):
        monkeypatch.setattr(ug, "_get_alpaca", lambda: _FakeAlpaca([]))
        assert ug.fetch_committed_capital() == 0.0

    def test_missing_cost_basis_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            ug, "_get_alpaca", lambda: _FakeAlpaca([_opt(None)]),
        )
        with pytest.raises(ug.UtilizationGateError):
            ug.fetch_committed_capital()

    def test_client_unavailable_fails_closed(self, monkeypatch):
        monkeypatch.setattr(ug, "_get_alpaca", lambda: None)
        with pytest.raises(ug.UtilizationGateError):
            ug.fetch_committed_capital()

    def test_positions_read_error_fails_closed(self, monkeypatch):
        monkeypatch.setattr(
            ug, "_get_alpaca",
            lambda: _FakeAlpaca(raise_on_positions=RuntimeError("api down")),
        )
        with pytest.raises(ug.UtilizationGateError):
            ug.fetch_committed_capital()

    def test_lone_short_leg_fails_closed(self, monkeypatch):
        # DELIBERATE semantic change (06-11): the old behavior clamped a
        # net-credit book to $0 committed — i.e. it silently UNDERSTATED.
        # A lone negative-cost-basis option is a naked short whose margin
        # this gate cannot bound from one leg → fail-closed, block entries
        # loudly (this book never legitimately holds naked shorts).
        monkeypatch.setattr(
            ug, "_get_alpaca", lambda: _FakeAlpaca([_optq(-120.0, -1)]),
        )
        with pytest.raises(ug.UtilizationGateError, match="no covering long"):
            ug.fetch_committed_capital()


# ---------------------------------------------------------------------------
# 06-11 — per-structure commitment: credit structures commit MARGIN basis,
# never the signed premium (the committed=$56 incident)
# ---------------------------------------------------------------------------

class TestStructureCommitment:
    def test_todays_book_pins_1365(self):
        # NFLX net debit $365 + condor margin $500 (max wing, 5-wide × 100
        # × 1ct) + $500 = $1,365 — matching the broker's $1,000
        # initial_margin + the $365 debit. NOT $56 (the old signed netting).
        assert ug.structure_commitment_usd(_todays_book()) == pytest.approx(1365.0)

    def test_old_signed_netting_would_have_said_56(self):
        # Document the incident arithmetic the fix removes.
        raw_sum = sum(l["cost_basis"] for l in _todays_book())
        assert raw_sum == pytest.approx(56.0)

    def test_debit_only_book_identical_to_old_sum(self):
        legs = [
            _optq(516.0, 1, "NFLX260710P00086000"),
            _optq(-151.0, -1, "NFLX260710P00079000"),
        ]
        assert ug.structure_commitment_usd(legs) == pytest.approx(365.0)

    def test_credit_vertical_commits_wing_margin(self):
        legs = [
            _optq(-646.0, -1, "QQQ260710P00645000"),
            _optq(584.0, 1, "QQQ260710P00640000"),
        ]
        assert ug.structure_commitment_usd(legs) == pytest.approx(500.0)

    def test_multi_qty_condor_scales_margin(self):
        legs = [
            _optq(-1292.0, -2, "QQQ260710P00645000"),
            _optq(1168.0, 2, "QQQ260710P00640000"),
            _optq(-1082.0, -2, "QQQ260710C00750000"),
            _optq(884.0, 2, "QQQ260710C00755000"),
        ]
        assert ug.structure_commitment_usd(legs) == pytest.approx(1000.0)

    def test_unequal_wings_margin_the_larger(self):
        # 5-wide put wing, 10-wide call wing → margined on the call wing.
        legs = [
            _optq(-646.0, -1, "QQQ260710P00645000"),
            _optq(584.0, 1, "QQQ260710P00640000"),
            _optq(-541.0, -1, "QQQ260710C00750000"),
            _optq(380.0, 1, "QQQ260710C00760000"),
        ]
        assert ug.structure_commitment_usd(legs) == pytest.approx(1000.0)

    def test_unparseable_credit_leg_fails_closed(self):
        with pytest.raises(ug.UtilizationGateError, match="unparseable"):
            ug.structure_commitment_usd([_optq(-100.0, -1, "NOT_AN_OCC")])

    def test_unparseable_debit_leg_commits_standalone(self):
        # A debit leg we can't group still commits its own cost basis —
        # identical to the original per-leg sum (keeps synthetic/legacy
        # symbols from blocking an all-debit book).
        assert ug.structure_commitment_usd(
            [_optq(300.0, 1, "NOT_AN_OCC")]
        ) == pytest.approx(300.0)

    def test_naked_short_wing_fails_closed(self):
        with pytest.raises(ug.UtilizationGateError, match="no covering long"):
            ug.structure_commitment_usd(
                [_optq(-646.0, -1, "QQQ260710P00645000")]
            )

    def test_missing_qty_in_credit_group_fails_closed(self):
        legs = [
            _opt(-646.0, "QQQ260710P00645000"),  # no qty key
            _opt(584.0, "QQQ260710P00640000"),
        ]
        with pytest.raises(ug.UtilizationGateError, match="qty missing"):
            ug.structure_commitment_usd(legs)

    def test_fetch_integration_todays_book(self, monkeypatch):
        monkeypatch.setattr(
            ug, "_get_alpaca", lambda: _FakeAlpaca(_todays_book() + [_equity_pos()]),
        )
        assert ug.fetch_committed_capital() == pytest.approx(1365.0)

    def test_polygon_prefixed_symbols_also_parse(self):
        legs = [
            _optq(-646.0, -1, "O:QQQ260710P00645000"),
            _optq(584.0, 1, "O:QQQ260710P00640000"),
        ]
        assert ug.structure_commitment_usd(legs) == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# B1 — candidate cost from the suggestion's order_json, fail-closed
# ---------------------------------------------------------------------------

class TestCandidateCost:
    def test_xlf_shape(self):
        s = {"order_json": {"limit_price": 1.47, "contracts": 4}}
        assert ug.candidate_cost_usd(s) == pytest.approx(588.0)

    def test_missing_order_json_fails_closed(self):
        with pytest.raises(ug.UtilizationGateError):
            ug.candidate_cost_usd({})

    def test_zero_contracts_fails_closed(self):
        s = {"order_json": {"limit_price": 1.47, "contracts": 0}}
        with pytest.raises(ug.UtilizationGateError):
            ug.candidate_cost_usd(s)

    def test_garbage_limit_fails_closed(self):
        s = {"order_json": {"limit_price": "n/a", "contracts": 4}}
        with pytest.raises(ug.UtilizationGateError):
            ug.candidate_cost_usd(s)


# ---------------------------------------------------------------------------
# B1 — the gate itself
# ---------------------------------------------------------------------------

class TestEvaluateEntry:
    def _wire(self, monkeypatch, committed_positions, obp):
        monkeypatch.setattr(
            ug, "_get_alpaca", lambda: _FakeAlpaca(committed_positions),
        )
        monkeypatch.setattr(ug, "_get_obp", lambda user_id, supabase=None: obp)

    def test_todays_live_numbers_pass(self, monkeypatch, gate_on, caplog):
        # committed $365 (NFLX), OBP $1,885.85, candidate XLF $588:
        # utilization = 953 / 2250.85 = 42.3% <= 85% -> ALLOW.
        self._wire(
            monkeypatch,
            [_opt(516.0), _opt(-151.0, "NFLX260710P00079000")],
            1885.85,
        )
        with caplog.at_level(logging.INFO):
            result = ug.evaluate_entry("user", "XLF", 588.0)
        assert result["allowed"] is True
        assert result["utilization"] == pytest.approx(953.0 / 2250.85)
        assert any(
            "decision=ALLOW" in r.getMessage()
            for r in caplog.records if "[UTILIZATION_GATE]" in r.getMessage()
        )

    def test_over_cap_blocks(self, monkeypatch, gate_on, caplog):
        # (1500 + 300) / (1500 + 500) = 0.90 > 0.85 -> BLOCK.
        self._wire(monkeypatch, [_opt(1500.0)], 500.0)
        with caplog.at_level(logging.INFO):
            with pytest.raises(ug.EntryUtilizationBlocked) as exc:
                ug.evaluate_entry("user", "XLF", 300.0)
        assert exc.value.utilization == pytest.approx(0.90)
        assert exc.value.cap == pytest.approx(0.85)
        # the evaluation line is logged BEFORE the raise (log every evaluation)
        assert any(
            "decision=BLOCK" in r.getMessage() for r in caplog.records
        )

    def test_boundary_exactly_at_cap_passes(self, monkeypatch, gate_on):
        # (600 + 250) / (600 + 400) = 850/1000 = 0.85 -> allowed (<=).
        self._wire(monkeypatch, [_opt(600.0)], 400.0)
        result = ug.evaluate_entry("user", "XLF", 250.0)
        assert result["allowed"] is True
        assert result["utilization"] == pytest.approx(0.85)

    def test_just_above_cap_blocks(self, monkeypatch, gate_on):
        # (600 + 251) / 1000 = 0.851 > 0.85 -> BLOCK.
        self._wire(monkeypatch, [_opt(600.0)], 400.0)
        with pytest.raises(ug.EntryUtilizationBlocked):
            ug.evaluate_entry("user", "XLF", 251.0)

    def test_obp_unreadable_fails_closed(self, monkeypatch, gate_on):
        self._wire(monkeypatch, [_opt(365.0)], None)
        with pytest.raises(ug.UtilizationGateError):
            ug.evaluate_entry("user", "XLF", 588.0)

    def test_positions_unreadable_fails_closed(self, monkeypatch, gate_on):
        monkeypatch.setattr(
            ug, "_get_alpaca",
            lambda: _FakeAlpaca(raise_on_positions=RuntimeError("api down")),
        )
        monkeypatch.setattr(ug, "_get_obp", lambda u, supabase=None: 1885.85)
        with pytest.raises(ug.UtilizationGateError):
            ug.evaluate_entry("user", "XLF", 588.0)

    def test_threshold_missing_fails_closed_before_broker_io(
        self, monkeypatch,
    ):
        monkeypatch.setenv(ug.FLAG_ENV, "1")
        monkeypatch.delenv(ug.THRESHOLD_ENV, raising=False)

        def _boom():
            raise AssertionError("broker IO must not run on config error")

        monkeypatch.setattr(ug, "_get_alpaca", _boom)
        with pytest.raises(ug.UtilizationGateError):
            ug.evaluate_entry("user", "XLF", 588.0)

    def test_invalid_candidate_cost_fails_closed(self, monkeypatch, gate_on):
        self._wire(monkeypatch, [_opt(365.0)], 1885.85)
        with pytest.raises(ug.UtilizationGateError):
            ug.evaluate_entry("user", "XLF", 0.0)

    def test_zero_pool_fails_closed(self, monkeypatch, gate_on):
        self._wire(monkeypatch, [], 0.0)
        with pytest.raises(ug.UtilizationGateError):
            ug.evaluate_entry("user", "XLF", 100.0)

    def test_accumulation_0_to_3_positions_under_cap(
        self, monkeypatch, gate_on,
    ):
        # The shape the legacy share-of-book BLOCK made impossible:
        # sequential accumulation. Fixed pool of $2,000; three $300
        # entries land at 15% / 30% / 45% utilization — all allowed.
        steps = [
            ([], 2000.0),                                    # flat book
            ([_opt(300.0)], 1700.0),                         # after entry 1
            ([_opt(300.0), _opt(300.0, "B")], 1400.0),       # after entry 2
        ]
        for committed_positions, obp in steps:
            self._wire(monkeypatch, committed_positions, obp)
            result = ug.evaluate_entry("user", "XLF", 300.0)
            assert result["allowed"] is True
        # and a 4th that would push past the cap blocks:
        self._wire(
            monkeypatch,
            [_opt(300.0), _opt(300.0, "B"), _opt(300.0, "C")],
            1100.0,
        )
        with pytest.raises(ug.EntryUtilizationBlocked):
            ug.evaluate_entry("user", "XLF", 900.0)  # 1800/2000 = 0.90


# ---------------------------------------------------------------------------
# tier scoping for the B2 demotion
# ---------------------------------------------------------------------------

class TestTierIsSmall:
    def test_small_obp_true(self, monkeypatch):
        monkeypatch.setattr(ug, "_get_obp", lambda u, supabase=None: 1885.85)
        assert ug.tier_is_small("user") is True

    def test_micro_obp_false(self, monkeypatch):
        monkeypatch.setattr(ug, "_get_obp", lambda u, supabase=None: 900.0)
        assert ug.tier_is_small("user") is False

    def test_standard_obp_false(self, monkeypatch):
        monkeypatch.setattr(ug, "_get_obp", lambda u, supabase=None: 6000.0)
        assert ug.tier_is_small("user") is False

    def test_obp_unreadable_false_fail_safe(self, monkeypatch, caplog):
        monkeypatch.setattr(ug, "_get_obp", lambda u, supabase=None: None)
        with caplog.at_level(logging.WARNING):
            assert ug.tier_is_small("user") is False
        assert any(
            "demotion NOT applied" in r.message for r in caplog.records
        )


# ---------------------------------------------------------------------------
# B2 — concentration_symbol severity demotion (and legacy regression pins)
# ---------------------------------------------------------------------------

def _one_position_book():
    # One open debit position -> 100% symbol/sector/expiry concentration.
    return [{
        "id": "pos-1",
        "symbol": "NFLX",
        "quantity": 1,
        "avg_entry_price": 3.65,
        "max_credit": 0,
        "legs": [
            {"symbol": "NFLX260918P00100000", "action": "buy",
             "type": "put", "strike": 100.0, "expiry": "2026-09-18",
             "quantity": 1},
            {"symbol": "NFLX260918P00095000", "action": "sell",
             "type": "put", "strike": 95.0, "expiry": "2026-09-18",
             "quantity": 1},
        ],
        "nearest_expiry": "2026-07-10",
        "sector": "Communication Services",
        "unrealized_pl": 0,
        "status": "open",
    }]


def _config(**overrides):
    cfg = EnvelopeConfig(
        max_single_symbol_pct=0.40,
        max_sector_pct=0.40,
        max_same_expiry_pct=0.50,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class TestConcentrationSeverityDemotion:
    def test_legacy_default_blocks(self):
        # Regression pin: with NO demotion, a 100%-concentrated book yields
        # a concentration_symbol violation at severity=block and
        # passed=False — exactly the 2026-06-09 circuit-breaker behavior.
        result = check_all_envelopes(
            positions=_one_position_book(), equity=2240.0, config=_config(),
        )
        sym = [v for v in result.violations if v.envelope == "concentration_symbol"]
        assert len(sym) == 1
        assert sym[0].severity == "block"
        assert result.passed is False

    def test_demoted_config_warns_and_passes(self):
        result = check_all_envelopes(
            positions=_one_position_book(),
            equity=2240.0,
            config=_config(symbol_concentration_severity="warn"),
        )
        sym = [v for v in result.violations if v.envelope == "concentration_symbol"]
        assert len(sym) == 1
        assert sym[0].severity == "warn"
        # the log line survives (violation still recorded), but it no longer
        # trips passed=False on its own
        assert result.passed is True

    def test_other_severities_unchanged_by_demotion(self):
        result = check_all_envelopes(
            positions=_one_position_book(),
            equity=2240.0,
            config=_config(symbol_concentration_severity="warn"),
        )
        by_env = {v.envelope: v.severity for v in result.violations}
        assert by_env.get("concentration_sector") == "warn"
        assert by_env.get("concentration_expiry") == "warn"

    def test_loss_per_symbol_force_close_unaffected(self):
        # Scope-guard pin: the per-symbol LOSS envelope still force-closes
        # regardless of the concentration demotion.
        book = _one_position_book()
        book[0]["unrealized_pl"] = -500.0  # breaches 3% of $2,240 (= $67.20)
        result = check_all_envelopes(
            positions=book,
            equity=2240.0,
            config=_config(symbol_concentration_severity="warn"),
        )
        loss = [v for v in result.violations if v.envelope == "loss_per_symbol"]
        assert len(loss) == 1
        assert loss[0].severity == "force_close"
        assert result.passed is False
        assert "pos-1" in result.force_close_ids

    def test_earnings_block_unaffected(self):
        book = _one_position_book()
        result = check_all_envelopes(
            positions=book,
            equity=2240.0,
            config=_config(
                symbol_concentration_severity="warn",
                max_earnings_positions=0,
            ),
            event_signals={"NFLX": {"is_earnings_week": True}},
        )
        earn = [v for v in result.violations if v.envelope == "event_earnings_count"]
        assert len(earn) == 1
        assert earn[0].severity == "block"
        assert result.passed is False
