"""Route-driven single-leg experiment generation (§9).

Drives generate_single_leg_candidates end to end with the REAL queue-⑤
challenger adapter as the injected EV estimator (failure injected at the
deepest callee — the adapter abstains — and asserted at the top: the generator
rejects). Pins: opt-in gating, the live-pool structural proof, each condition's
absence -> a distinct typed rejection, the one-contract invariant, and the
EV-missing (H9) rejection.
"""

from packages.quantum.analytics.terminal_distribution import (
    evaluate_single_leg_from_inputs,
)
from packages.quantum.brokers.execution_router import SHADOW_ONLY_ROUTING
from packages.quantum.strategies import single_leg_experiment as sl

KNOWN_AT = "2026-07-01T15:00:00Z"


def real_estimator(inp: sl.SingleLegEVInputs):
    return evaluate_single_leg_from_inputs(
        option_type=inp.option_type,
        strike=inp.strike,
        debit_per_share=inp.debit_per_share,
        iv=inp.iv,
        spot=inp.spot,
        dte_days=inp.dte_days,
        known_at=inp.known_at,
        contracts=inp.contracts,
    )


def rising_closes(n=60, step=1.003):
    return [100.0 * (step ** i) for i in range(n)]


def falling_closes(n=60, step=0.997):
    return [100.0 * (step ** i) for i in range(n)]


ENABLED_CONFIG = {"single_leg_experiment_enabled": True}


def passing_context(**overrides):
    ctx = {
        "symbol": "SPY",
        "iv_rank": 15.0,                       # < 20 (low IV, guardrails convention)
        "iv_rv_spread": -0.02,                 # <= 0 (VRP: IV cheap/fair vs realized)
        "closes": rising_closes(),             # bullish, |20d run| ~6% > 3%
        "market_data": {"open_interest": 500, "volume": 200},  # liquid; no earnings
        "spot": 112.5,
        "known_at": KNOWN_AT,
        "contract": {
            "strike": 113.0,
            "expiry": "2026-08-21",
            "iv": 0.18,
            "bid": 1.30,
            "ask": 1.40,
            "occ_symbol": "O:SPY260821C00113000",
        },
    }
    ctx.update(overrides)
    return ctx


def _gen(contexts, config=ENABLED_CONFIG, routing=SHADOW_ONLY_ROUTING, estimator=real_estimator):
    return sl.generate_single_leg_candidates(contexts, config, routing_mode=routing, ev_estimator=estimator)


def _only_rejection(res):
    assert res.candidates == []
    assert len(res.rejections) == 1
    return res.rejections[0]


# ── Happy path + one-contract invariant ─────────────────────────────────────

def test_generates_one_contract_long_call_when_all_conditions_met():
    res = _gen([passing_context()])
    assert res.enabled is True and res.rejections == []
    assert len(res.candidates) == 1
    c = res.candidates[0]
    assert c.strategy_type == "long_call" and c.option_type == "call"
    # ONE CONTRACT + shadow-only + experimental — structural invariants.
    assert c.contracts == 1
    assert c.routing == SHADOW_ONLY_ROUTING
    assert c.lifecycle_state == "experimental"
    assert c.experiment == "single_leg"
    req = c.to_order_request()
    assert len(req["legs"]) == 1 and req["legs"][0]["quantity"] == 1
    assert req["legs"][0]["action"] == "buy"
    # Independent EV was actually computed (finite).
    assert isinstance(c.ev_expected_value, float)


def test_generates_long_put_on_bearish_trend():
    ctx = passing_context(
        closes=falling_closes(), spot=100.0,
        contract={"strike": 97.0, "expiry": "2026-08-21", "iv": 0.20,
                  "bid": 1.20, "ask": 1.30, "occ_symbol": "O:SPY260821P00097000"},
    )
    res = _gen([ctx])
    assert len(res.candidates) == 1
    assert res.candidates[0].strategy_type == "long_put"


# ── Opt-in gating (dark) ─────────────────────────────────────────────────────

def test_disabled_when_no_opt_in():
    res = _gen([passing_context()], config={})
    assert res.enabled is False
    assert res.candidates == [] and res.rejections == []


def test_disabled_when_flag_explicitly_false():
    res = _gen([passing_context()], config={"single_leg_experiment_enabled": False})
    assert res.enabled is False and res.candidates == []


# ── Live-pool STRUCTURAL proof ───────────────────────────────────────────────

def test_live_routing_forbidden_even_with_flag_and_passing_context():
    # A live_eligible policy config CANNOT enable the experiment: enabled=True
    # is acknowledged, but zero candidates are emitted and the batch is refused.
    res = _gen([passing_context()], routing="live_eligible")
    assert res.enabled is True
    assert res.candidates == []
    r = _only_rejection(res)
    assert r.reason_code == sl.LIVE_ROUTING_FORBIDDEN


def test_non_shadow_routing_forbidden():
    res = _gen([passing_context()], routing="internal_paper")
    assert res.candidates == []
    assert _only_rejection(res).reason_code == sl.LIVE_ROUTING_FORBIDDEN


# ── Each condition's ABSENCE -> a distinct typed rejection ───────────────────

def test_missing_iv_rank_rejects():
    ctx = passing_context()
    ctx.pop("iv_rank")
    assert _only_rejection(_gen([ctx])).reason_code == sl.IV_RANK_UNAVAILABLE


def test_high_iv_rank_rejects():
    assert _only_rejection(_gen([passing_context(iv_rank=55.0)])).reason_code == sl.IV_NOT_LOW


# ── VRP (low-IV gate (b)) — real second condition, consumed + provenance ─────

def test_missing_vrp_spread_rejects_h9():
    # iv_rv_spread absent -> VRP proxy unavailable -> reject (never assume cheap).
    ctx = passing_context()
    ctx.pop("iv_rv_spread")
    assert _only_rejection(_gen([ctx])).reason_code == sl.VRP_UNAVAILABLE


def test_nonfinite_vrp_spread_rejects_h9():
    assert _only_rejection(_gen([passing_context(iv_rv_spread=float("nan"))])).reason_code == sl.VRP_UNAVAILABLE


def test_iv_rich_vs_realized_rejects():
    # Positive spread = IV rich vs realized -> vrp_score_multiplier < 1.0 -> reject
    # (a long-premium buy wants cheap IV). iv_rank still low, so ONLY the VRP gate fires.
    assert _only_rejection(_gen([passing_context(iv_rv_spread=0.05)])).reason_code == sl.IV_NOT_CHEAP_VS_REALIZED


def test_vrp_provenance_stamped_on_candidate():
    from packages.quantum.analytics.opportunity_scorer import vrp_score_multiplier
    c = _gen([passing_context(iv_rv_spread=-0.03)]).candidates[0]
    assert c.vrp_iv_rv_spread == -0.03
    # The REAL versioned surface was consumed (not a reimplemented threshold).
    assert c.vrp_multiplier == vrp_score_multiplier(-0.03) and c.vrp_multiplier >= 1.0
    assert "vrp_score_multiplier" in (c.vrp_source or "")
    assert c.as_dict()["vrp_iv_rv_spread"] == -0.03


def test_vrp_zero_spread_fair_iv_passes():
    # Exactly fair (spread == 0 -> multiplier == 1.0) is acceptable for a buyer.
    c = _gen([passing_context(iv_rv_spread=0.0)]).candidates[0]
    assert c.vrp_multiplier == 1.0


def test_vrp_ceiling_cannot_be_loosened_above_zero():
    # A policy trying to loosen the VRP ceiling above 0.0 is clamped to 0.0:
    # rich IV still rejects even with single_leg_max_vrp_spread=0.10.
    cfg = {"single_leg_experiment_enabled": True, "single_leg_max_vrp_spread": 0.10}
    res = sl.generate_single_leg_candidates(
        [passing_context(iv_rv_spread=0.05)], cfg,
        routing_mode=SHADOW_ONLY_ROUTING, ev_estimator=real_estimator,
    )
    assert _only_rejection(res).reason_code == sl.IV_NOT_CHEAP_VS_REALIZED


def test_insufficient_bars_directional_unavailable():
    assert _only_rejection(_gen([passing_context(closes=[100.0] * 5)])).reason_code == sl.DIRECTIONAL_SIGNAL_UNAVAILABLE


def test_flat_trend_no_directional_bias():
    assert _only_rejection(_gen([passing_context(closes=[100.0] * 60)])).reason_code == sl.NO_DIRECTIONAL_BIAS


def test_weak_trend_rejects():
    assert _only_rejection(_gen([passing_context(closes=rising_closes(step=1.0003))])).reason_code == sl.DIRECTIONAL_SIGNAL_WEAK


def test_earnings_proximity_rejects():
    ctx = passing_context(market_data={"open_interest": 500, "volume": 200, "earnings_date": "2026-07-05"})
    assert _only_rejection(_gen([ctx])).reason_code == sl.EARNINGS_PROXIMITY


def test_illiquid_zero_quote_rejects():
    ctx = passing_context()
    ctx["contract"] = dict(ctx["contract"], bid=0.0, ask=0.0)
    assert _only_rejection(_gen([ctx])).reason_code == sl.ILLIQUID_CONTRACT


def test_illiquid_low_oi_rejects():
    ctx = passing_context(market_data={"open_interest": 50, "volume": 200})
    assert _only_rejection(_gen([ctx])).reason_code == sl.ILLIQUID_CONTRACT


def test_wide_spread_rejects():
    # 20% spread -> apply_slippage_guardrail returns 0.0 (reject).
    ctx = passing_context()
    ctx["contract"] = dict(ctx["contract"], bid=1.00, ask=1.30)  # 30% spread
    assert _only_rejection(_gen([ctx])).reason_code == sl.ILLIQUID_CONTRACT


def test_debit_exceeds_max_rejects():
    # Raise the quote so the per-contract debit blows past the $150 default cap.
    ctx = passing_context()
    ctx["contract"] = dict(ctx["contract"], bid=2.00, ask=2.10)  # mid 2.05 -> $205 > $150
    assert _only_rejection(_gen([ctx])).reason_code == sl.DEBIT_EXCEEDS_MAX


def test_debit_max_is_policy_config_bounded():
    ctx = passing_context()
    ctx["contract"] = dict(ctx["contract"], bid=2.00, ask=2.10)  # $205
    cfg = {"single_leg_experiment_enabled": True, "single_leg_max_debit_per_contract": 250.0}
    res = sl.generate_single_leg_candidates([ctx], cfg, routing_mode=SHADOW_ONLY_ROUTING, ev_estimator=real_estimator)
    assert len(res.candidates) == 1  # now under the raised cap


# ── EV requirement (H9) ──────────────────────────────────────────────────────

def test_missing_ev_estimator_rejects():
    res = sl.generate_single_leg_candidates([passing_context()], ENABLED_CONFIG,
                                            routing_mode=SHADOW_ONLY_ROUTING, ev_estimator=None)
    assert _only_rejection(res).reason_code == sl.EV_ESTIMATOR_UNAVAILABLE


def test_ev_adapter_abstention_rejects():
    # Deepest callee (the real adapter) abstains because the contract carries no
    # IV -> the generator rejects EV_UNAVAILABLE (never fabricates an EV).
    ctx = passing_context()
    ctx["contract"] = dict(ctx["contract"])
    ctx["contract"]["iv"] = None
    assert _only_rejection(_gen([ctx])).reason_code == sl.EV_UNAVAILABLE


# ── Batch mix ────────────────────────────────────────────────────────────────

def test_batch_mixes_candidates_and_rejections():
    good = passing_context(symbol="SPY")
    bad = passing_context(symbol="QQQ", iv_rank=80.0)
    res = _gen([good, bad])
    assert len(res.candidates) == 1 and res.candidates[0].symbol == "SPY"
    assert len(res.rejections) == 1 and res.rejections[0].symbol == "QQQ"
    assert res.rejections[0].reason_code == sl.IV_NOT_LOW
