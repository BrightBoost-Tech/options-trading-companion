"""Route-driven single-leg CONTRACT SELECTION (Lane A completion of #1287/#1292).

Drives the full seam end-to-end:
    real chain -> select_single_leg_contract (pick ONE) -> generate_single_leg_
    candidates (gate + one-contract stamp) -> should_submit_to_broker HARD VETO
    -> close/expiry helpers on the generated shape.

Doctrine (§9): the injected EV estimator is the REAL #1287 challenger adapter,
so an abstention is injected at the DEEPEST callee (the adapter, given a
contract with no IV) and asserted at the TOP (selection rejects NO_VIABLE_
CONTRACT — never a fabricated EV). A separate CONTROLLED estimator drives the
deterministic tie-breaker exactly. The chain source is INJECTED (a fake truth
layer) using the SAME option_chain(min_expiry, max_expiry, spot) call shape the
scanner uses.
"""

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

from packages.quantum.analytics.terminal_distribution import (
    evaluate_single_leg_from_inputs,
)
from packages.quantum.brokers.execution_router import (
    SHADOW_ONLY_ROUTING,
    is_single_leg_experiment_row,
    should_submit_to_broker,
)
from packages.quantum.services.paper_autopilot_service import PaperAutopilotService
from packages.quantum.services.paper_exit_evaluator import (
    _is_debit_spread,
    days_to_expiry,
)
from packages.quantum.strategies import single_leg_experiment as sl
from packages.quantum.strategies import single_leg_selection as sel

KNOWN_AT = "2026-07-01T15:00:00Z"
# DTE window [25,45] from 2026-07-01 -> expiries in [2026-07-26, 2026-08-15].
EXP_IN = "2026-08-07"       # 37 DTE — inside
EXP_IN_2 = "2026-07-30"     # 29 DTE — inside
EXP_IN_3 = "2026-08-14"     # 44 DTE — inside
EXP_OUT_LATE = "2026-08-20"  # 50 DTE — outside
EXP_OUT_EARLY = "2026-07-20"  # 19 DTE — outside

ENABLED = {"single_leg_experiment_enabled": True}


# ── The REAL #1287 adapter as the injected estimator (deepest callee) ────────
def real_estimator(inp: sl.SingleLegEVInputs):
    return evaluate_single_leg_from_inputs(
        option_type=inp.option_type, strike=inp.strike,
        debit_per_share=inp.debit_per_share, iv=inp.iv, spot=inp.spot,
        dte_days=inp.dte_days, known_at=inp.known_at, contracts=inp.contracts,
    )


# ── Controlled estimator for the deterministic tie-breaker ───────────────────
class _FakeEV:
    def __init__(self, ev, pop=0.4, source="fake_estimator", version="fake@1"):
        self.expected_value = ev
        self.pop = pop
        self.provenance = type("P", (), {"source": source, "version": version})()


def const_ev(value=50.0):
    return lambda inp: _FakeEV(value)


def strike_ev(mapping, default=1.0):
    return lambda inp: _FakeEV(mapping.get(inp.strike, default))


def rising_closes(n=60, step=1.003):
    return [100.0 * (step ** i) for i in range(n)]


def falling_closes(n=60, step=0.997):
    return [100.0 * (step ** i) for i in range(n)]


# ── Fake truth layer: SAME option_chain(min_expiry, max_expiry, spot) shape ──
class FakeTruthLayer:
    def __init__(self, chains=None, raise_exc=None):
        self.chains = chains or {}
        self.calls = []
        self.raise_exc = raise_exc

    def option_chain(self, underlying, *, min_expiry=None, max_expiry=None,
                     spot=None, **kw):
        self.calls.append({"underlying": underlying, "min_expiry": min_expiry,
                           "max_expiry": max_expiry, "spot": spot})
        if self.raise_exc is not None:
            raise self.raise_exc
        return list(self.chains.get(underlying, []))


def chain_contract(strike, *, expiry=EXP_IN, right="call", bid=1.30, ask=1.40,
                   iv=0.18, delta=0.50, oi=500, volume=200, occ=None,
                   source="alpaca"):
    """A truth-layer-shaped contract (nested quote/greeks)."""
    if occ is None:
        cp = "C" if right == "call" else "P"
        occ = f"O:SPY{expiry.replace('-', '')[2:]}{cp}{int(round(strike * 1000)):08d}"
    mid = (bid + ask) / 2.0 if (bid and ask and bid > 0 and ask > 0) else None
    return {
        "contract": occ, "underlying": "SPY", "strike": strike, "expiry": expiry,
        "right": right,
        "quote": {"bid": bid, "ask": ask, "mid": mid, "last": None},
        "iv": iv,
        "greeks": {"delta": delta, "gamma": None, "theta": None, "vega": None},
        "oi": oi, "volume": volume, "source": source,
    }


def underlying_ctx(**over):
    ctx = {
        "symbol": "SPY", "iv_rank": 15.0, "iv_rv_spread": -0.02,
        "closes": rising_closes(), "spot": 112.5, "known_at": KNOWN_AT,
        "market_data": {},
    }
    ctx.update(over)
    return ctx


def run(chains, ctx_over=None, config=ENABLED, routing=SHADOW_ONLY_ROUTING,
        estimator=real_estimator, raise_exc=None):
    tl = FakeTruthLayer(chains, raise_exc=raise_exc)
    ctxs = [underlying_ctx(**(ctx_over or {}))]
    res = sel.select_and_generate_single_leg(
        ctxs, config, routing_mode=routing, truth_layer=tl, ev_estimator=estimator,
    )
    return res, tl


# ════════════════════════════════════════════════════════════════════════════
# GROUP A — full route with the real adapter
# ════════════════════════════════════════════════════════════════════════════

def test_selects_one_contract_and_generates_candidate():
    chains = {"SPY": [chain_contract(111.0), chain_contract(113.0),
                      chain_contract(115.0)]}
    res, tl = run(chains)
    # exactly ONE selection + ONE stageable candidate
    assert len(res.selections) == 1
    assert len(res.generation.candidates) == 1
    c = res.generation.candidates[0]
    assert c.strategy_type == "long_call" and c.option_type == "call"
    assert c.contracts == 1
    assert c.routing == SHADOW_ONLY_ROUTING
    assert c.lifecycle_state == "experimental"
    assert c.experiment == "single_leg"
    # the candidate's contract IS the one selection chose
    assert c.occ_symbol == res.selections[0].occ_symbol
    assert isinstance(c.ev_expected_value, float)
    # VRP evidence (#1292) rides through onto the candidate
    assert c.vrp_iv_rv_spread == -0.02 and c.vrp_multiplier >= 1.0
    # selection provenance recorded
    s = res.selections[0]
    assert s.ev_source and s.ev_version and s.ev_known_at == KNOWN_AT
    assert s.considered >= 1 and 1 <= s.viable <= s.considered
    assert s.chain_source == "alpaca"
    assert s.tie_breaker == sel.TIE_BREAKER
    # chain fetched with the SAME call shape as the scanner, DTE window applied
    assert tl.calls == [{"underlying": "SPY", "min_expiry": "2026-07-26",
                         "max_expiry": "2026-08-15", "spot": 112.5}]


def test_bearish_trend_selects_long_put():
    chains = {"SPY": [chain_contract(111.0, right="put", occ="O:SPY260807P00111000"),
                      chain_contract(109.0, right="put", occ="O:SPY260807P00109000")]}
    res, _ = run(chains, ctx_over={"closes": falling_closes(), "spot": 110.0})
    assert len(res.generation.candidates) == 1
    assert res.generation.candidates[0].strategy_type == "long_put"
    assert res.selections[0].option_type == "put"


def test_selection_side_matches_generator_strategy_drift_guard():
    # call side
    res_c, _ = run({"SPY": [chain_contract(113.0)]})
    assert res_c.selections[0].option_type == "call"
    assert res_c.generation.candidates[0].strategy_type == "long_call"
    # put side (independent run)
    res_p, _ = run({"SPY": [chain_contract(109.0, right="put")]},
                   ctx_over={"closes": falling_closes(), "spot": 110.0})
    assert res_p.selections[0].option_type == "put"
    assert res_p.generation.candidates[0].strategy_type == "long_put"


# ════════════════════════════════════════════════════════════════════════════
# GROUP B — dark / live-pool structural (NO chain fetch)
# ════════════════════════════════════════════════════════════════════════════

def test_disabled_opt_in_is_dark_and_never_fetches_chain():
    res, tl = run({"SPY": [chain_contract(113.0)]}, config={})
    assert res.generation.enabled is False
    assert res.generation.candidates == []
    assert res.selections == [] and res.selection_rejections == []
    assert tl.calls == []  # dark by construction — no market data touched


def test_live_routing_forbidden_and_never_fetches_chain():
    res, tl = run({"SPY": [chain_contract(113.0)]}, routing="live_eligible")
    assert res.generation.enabled is True
    assert res.generation.candidates == []
    assert len(res.generation.rejections) == 1
    assert res.generation.rejections[0].reason_code == sl.LIVE_ROUTING_FORBIDDEN
    assert tl.calls == []  # a live-routed batch never even reads the chain


def test_internal_paper_routing_forbidden_no_fetch():
    res, tl = run({"SPY": [chain_contract(113.0)]}, routing="internal_paper")
    assert res.generation.candidates == []
    assert res.generation.rejections[0].reason_code == sl.LIVE_ROUTING_FORBIDDEN
    assert tl.calls == []


# ════════════════════════════════════════════════════════════════════════════
# GROUP C — selection-stage typed rejections (H9)
# ════════════════════════════════════════════════════════════════════════════

def test_dark_chain_rejects_typed():
    res, tl = run({"SPY": []})
    assert res.generation.candidates == []
    assert res.selections == []
    assert len(res.selection_rejections) == 1
    assert res.selection_rejections[0].reason_code == sel.CHAIN_UNAVAILABLE
    assert tl.calls  # it DID attempt the fetch


def test_chain_fetch_exception_rejects_typed():
    res, _ = run({"SPY": [chain_contract(113.0)]}, raise_exc=RuntimeError("boom"))
    assert res.selection_rejections[0].reason_code == sel.CHAIN_UNAVAILABLE
    assert res.generation.candidates == []


def test_no_contract_in_dte_window_rejects():
    chains = {"SPY": [chain_contract(113.0, expiry=EXP_OUT_EARLY),
                      chain_contract(113.0, expiry=EXP_OUT_LATE)]}
    res, _ = run(chains)
    assert res.selection_rejections[0].reason_code == sel.NO_CONTRACT_IN_DTE_WINDOW


def test_all_illiquid_zero_quote_no_viable_contract():
    res, _ = run({"SPY": [chain_contract(113.0, bid=0.0, ask=0.0)]})
    assert res.selection_rejections[0].reason_code == sel.NO_VIABLE_CONTRACT


def test_low_oi_no_viable_contract():
    res, _ = run({"SPY": [chain_contract(113.0, oi=50)]})
    assert res.selection_rejections[0].reason_code == sel.NO_VIABLE_CONTRACT


def test_wide_spread_no_viable_contract():
    # 30% spread -> apply_slippage_guardrail returns 0.0 (reject).
    res, _ = run({"SPY": [chain_contract(113.0, bid=1.00, ask=1.30)]})
    assert res.selection_rejections[0].reason_code == sel.NO_VIABLE_CONTRACT


def test_all_over_max_debit_no_viable_contract():
    # mid 2.05 -> $205 > $150 default cap -> excluded.
    res, _ = run({"SPY": [chain_contract(113.0, bid=2.00, ask=2.10)]})
    assert res.selection_rejections[0].reason_code == sel.NO_VIABLE_CONTRACT


def test_ev_unavailable_all_contracts_rejects_h9():
    # No IV on any contract -> the REAL adapter abstains for ALL -> H9 reject
    # (deepest callee injects the failure; asserted at the top).
    res, _ = run({"SPY": [chain_contract(113.0, iv=None),
                          chain_contract(115.0, iv=None)]})
    assert res.selection_rejections[0].reason_code == sel.NO_VIABLE_CONTRACT
    assert res.generation.candidates == []


def test_directional_signal_unavailable_no_chain_fetch():
    res, tl = run({"SPY": [chain_contract(113.0)]}, ctx_over={"closes": [100.0] * 5})
    assert res.selection_rejections[0].reason_code == sel.DIRECTIONAL_SIGNAL_UNAVAILABLE
    assert tl.calls == []  # direction decided before any chain read


def test_flat_trend_no_directional_bias():
    res, _ = run({"SPY": [chain_contract(113.0)]}, ctx_over={"closes": [100.0] * 60})
    assert res.selection_rejections[0].reason_code == sel.NO_DIRECTIONAL_BIAS


# ════════════════════════════════════════════════════════════════════════════
# GROUP D — filters SELECT among survivors
# ════════════════════════════════════════════════════════════════════════════

def test_max_debit_selects_cheaper_when_expensive_excluded():
    expensive = chain_contract(120.0, bid=2.00, ask=2.10, occ="O:SPY_EXP")  # $205 -> out
    cheap = chain_contract(113.0, bid=1.25, ask=1.35, occ="O:SPY_CHEAP")     # $130 -> in
    res, _ = run({"SPY": [expensive, cheap]})
    assert len(res.generation.candidates) == 1
    assert res.selections[0].occ_symbol == "O:SPY_CHEAP"
    assert res.selections[0].considered == 2 and res.selections[0].viable == 1


def test_dte_window_policy_config_bounded():
    # A 50-DTE contract is out by default; widening max_dte to 55 admits it.
    chains = {"SPY": [chain_contract(113.0, expiry=EXP_OUT_LATE, occ="O:SPY_50DTE")]}
    res_default, _ = run(chains)
    assert res_default.selection_rejections[0].reason_code == sel.NO_CONTRACT_IN_DTE_WINDOW
    cfg = {"single_leg_experiment_enabled": True, "single_leg_max_dte": 55}
    res_wide, _ = run(chains, config=cfg)
    assert len(res_wide.generation.candidates) == 1
    assert res_wide.selections[0].occ_symbol == "O:SPY_50DTE"


# ════════════════════════════════════════════════════════════════════════════
# GROUP E — deterministic tie-breaker (controlled estimator)
# ════════════════════════════════════════════════════════════════════════════

def test_tie_breaker_prefers_highest_ev():
    chains = {"SPY": [
        chain_contract(110.0, occ="O:A"), chain_contract(113.0, occ="O:B"),
        chain_contract(115.0, occ="O:C"),
    ]}
    est = strike_ev({110.0: 10.0, 113.0: 50.0, 115.0: 30.0})
    res, _ = run(chains, estimator=est)
    assert res.selections[0].occ_symbol == "O:B"  # EV 50 wins
    assert res.selections[0].ev_expected_value == 50.0


def test_tie_breaker_ev_tie_broken_by_nearest_delta():
    chains = {"SPY": [
        chain_contract(110.0, delta=0.30, occ="O:A"),
        chain_contract(113.0, delta=0.50, occ="O:B"),   # nearest to target 0.50
        chain_contract(115.0, delta=0.70, occ="O:C"),
    ]}
    res, _ = run(chains, estimator=const_ev(50.0))
    assert res.selections[0].occ_symbol == "O:B"


def test_tie_breaker_delta_tie_broken_by_lowest_debit():
    # deltas 0.40 & 0.60 are EQUIDISTANT from target 0.50 -> debit decides.
    chains = {"SPY": [
        chain_contract(112.0, delta=0.40, bid=1.35, ask=1.45, occ="O:HI"),   # $140
        chain_contract(114.0, delta=0.60, bid=1.25, ask=1.35, occ="O:LO"),   # $130
    ]}
    res, _ = run(chains, estimator=const_ev(50.0))
    assert res.selections[0].occ_symbol == "O:LO"
    assert res.selections[0].debit_per_contract == 130.0


def test_tie_breaker_full_tie_broken_by_lexical_occ():
    # identical EV, delta, debit -> lexically smallest occ_symbol wins.
    chains = {"SPY": [
        chain_contract(113.0, expiry=EXP_IN_3, delta=0.50, occ="O:BBB"),
        chain_contract(113.0, expiry=EXP_IN, delta=0.50, occ="O:AAA"),
    ]}
    res, _ = run(chains, estimator=const_ev(50.0))
    assert res.selections[0].occ_symbol == "O:AAA"


# ════════════════════════════════════════════════════════════════════════════
# GROUP F — determinism
# ════════════════════════════════════════════════════════════════════════════

def test_determinism_same_chain_same_contract_twice():
    chains = {"SPY": [chain_contract(111.0), chain_contract(113.0),
                      chain_contract(115.0)]}
    res1, _ = run(chains)
    res2, _ = run(chains)
    assert res1.selections[0].occ_symbol == res2.selections[0].occ_symbol


def test_determinism_independent_of_chain_order():
    forward = [chain_contract(111.0), chain_contract(113.0), chain_contract(115.0)]
    res_fwd, _ = run({"SPY": list(forward)})
    res_rev, _ = run({"SPY": list(reversed(forward))})
    assert res_fwd.selections[0].occ_symbol == res_rev.selections[0].occ_symbol


# ════════════════════════════════════════════════════════════════════════════
# GROUP G — stage seam VETO: a generated candidate can NEVER reach a broker
# ════════════════════════════════════════════════════════════════════════════

_ALERTS = "packages.quantum.observability.alerts"


@contextmanager
def _silence_alerts():
    with patch(f"{_ALERTS}.alert") as m, \
         patch(f"{_ALERTS}._get_admin_supabase", return_value=MagicMock()):
        yield m


def _portfolio_client(routing_mode):
    c = MagicMock()
    data = [] if routing_mode is None else [{"routing_mode": routing_mode}]
    (c.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = MagicMock(data=data)
    return c


def _generated_candidate():
    res, _ = run({"SPY": [chain_contract(113.0)]})
    assert res.generation.candidates, "expected a generated candidate for the veto test"
    return res.generation.candidates[0]


def test_generated_candidate_entry_row_blocked_on_live_eligible():
    # The stage route (_stage_order_internal) hands should_submit_to_broker a
    # paper_orders row whose order_json is the candidate's order request. Even on
    # a live_eligible portfolio the seam MUST refuse broker submission.
    cand = _generated_candidate()
    order_row = {"id": "ord-1", "portfolio_id": "pf-1",
                 "order_json": cand.to_order_request()}
    assert is_single_leg_experiment_row(order_row) is True
    with _silence_alerts() as m_alert:
        assert should_submit_to_broker("pf-1", _portfolio_client("live_eligible"),
                                       order=order_row) is False
        assert m_alert.called  # veto overrode a live route -> critical alert


def test_status_mutation_cannot_reach_broker():
    # Attacker strips the experiment marker AND flips routing to live_eligible in
    # the order_json — the strategy-name recognizer (long_call) still blocks it.
    cand = _generated_candidate()
    oj = cand.to_order_request()
    oj.pop("experiment", None)
    oj["routing"] = "live_eligible"
    order_row = {"id": "ord-x", "portfolio_id": "pf-1", "order_json": oj}
    assert is_single_leg_experiment_row(order_row) is True
    with _silence_alerts():
        assert should_submit_to_broker("pf-1", _portfolio_client("live_eligible"),
                                       order=order_row) is False


def test_generated_candidate_close_shape_blocked_and_flows():
    # Close route hands a paper_positions row (no experiment column — only
    # strategy_key). It must be broker-blocked AND flow coherently through the
    # 1-leg close/expiry helpers.
    cand = _generated_candidate()
    leg = cand.to_order_request()["legs"][0]
    pos = {
        "id": "pos-1", "portfolio_id": "pf-1", "symbol": "SPY",
        "strategy": cand.strategy_type, "strategy_key": cand.strategy_type,
        "quantity": 1, "max_credit": cand.debit_per_contract / 100.0,
        "unrealized_pl": 0.0, "nearest_expiry": None,
        "legs": [{"symbol": cand.occ_symbol, "action": "buy",
                  "type": cand.option_type, "strike": cand.strike,
                  "expiry": cand.expiry}],
    }
    assert is_single_leg_experiment_row(pos) is True
    assert should_submit_to_broker("pf-1", _portfolio_client("live_eligible"),
                                   order=pos) is False
    # 1-leg close/expiry helpers adjudicate the generated shape coherently.
    assert _is_debit_spread(pos) is True
    assert days_to_expiry(pos) == (date.fromisoformat(cand.expiry) - date.today()).days
    assert PaperAutopilotService._resolve_occ_symbol(pos, None) == cand.occ_symbol
    assert leg["action"] == "buy" and leg["quantity"] == 1
