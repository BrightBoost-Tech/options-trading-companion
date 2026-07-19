"""One-contract shadow-only single-leg (long_call / long_put) candidate generator.

Owner decision: SINGLE_LEG=ONE_CONTRACT_SHADOW_ONLY_EXPERIMENT (authorized).
Single-leg (long call / long put) candidate generation existed NOWHERE before
this (verticals/condors only), and the historical verdict was DON'T-BUILD
(commits 9f002e3e / 0ddb3fea). This ships it back as a HARD-GATED, DARK
experiment — no live selector-pool change, no env activation.

DARK BY CONSTRUCTION (all four must hold before a single candidate is emitted):
  1. POLICY OPT-IN — the policy's ``policy_config`` (jsonb on the policy
     registry, PR #1279) must carry the explicit key
     ``single_leg_experiment_enabled = true``. No existing policy has it; the
     50-policy shadow-fleet design does NOT include it. Absent/false -> the
     generator produces nothing (``enabled=False``), never a rejection.
  2. SHADOW-ONLY ROUTING — the policy/portfolio routing_mode must be
     ``shadow_only``. A ``live_eligible`` routing REFUSES the whole experiment
     (LIVE_ROUTING_FORBIDDEN) even when the flag is set: this is the structural
     proof that the champion / live cohort path cannot emit single-leg
     candidates. (Defense-in-depth: the execution-seam guard
     ``execution_router.assert_single_leg_shadow_only`` independently refuses to
     broker-submit any single-leg experiment order.)
  3. ALL ENTRY CONDITIONS — low-IV, strong directional signal, no earnings
     proximity, strict contract liquidity, explicit max debit, and an
     INDEPENDENT EV estimate (H9: any condition that cannot be honestly
     evaluated REJECTS with a typed reason; nothing is fabricated).
  4. EXACTLY ONE CONTRACT — every emitted candidate is ``contracts == 1``,
     ``routing == shadow_only``, ``lifecycle_state == experimental``,
     ``experiment == single_leg``. Structurally, never more.

CONDITIONS -> EXISTING SURFACES (cited, not reinvented):
  * low-IV                 guardrails.compute_conviction_score (iv_rank < 20 is
                           the BUY/long-premium low-IV convention) +
                           opportunity_scorer VRP (iv_rv_spread <= 0 = IV cheap)
  * strong directional     services.momentum_signals.direction_from_strategy +
                           compute_momentum_signals (signed_run_up_in_direction)
  * no earnings proximity  analytics.guardrails.is_earnings_safe (14-day window)
  * strict liquidity       analytics.guardrails.apply_slippage_guardrail
                           (spread) + check_liquidity (OI/volume)
  * explicit max debit     policy_config-bounded (single_leg_max_debit_per_contract)
  * independent EV         INJECTED estimator (the queue-⑤ challenger/adapter
                           path) — DI so this module never imports that package
                           (the observe-only import-lock stays intact).

The INDEPENDENT EV estimator is INJECTED (``ev_estimator``): the generator is
estimator-agnostic and this file deliberately carries NO import of / reference
to the observe-only challenger package. The production wiring (a future
experimental policy) supplies the estimator; the tests supply the real adapter.
A candidate whose EV estimate is missing/unavailable REJECTS (H9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional

from packages.quantum.analytics.guardrails import (
    apply_slippage_guardrail,
    check_liquidity,
    is_earnings_safe,
)
from packages.quantum.brokers.execution_router import (
    LIVE_ROUTING_MODE,
    SHADOW_ONLY_ROUTING,
    SINGLE_LEG_EXPERIMENT,
)
from packages.quantum.services.momentum_signals import (
    compute_momentum_signals,
    direction_from_strategy,
)

# ── Policy-config opt-in key + bounded defaults ─────────────────────────────
OPT_IN_KEY = "single_leg_experiment_enabled"
LIFECYCLE_STATE = "experimental"

# Low-IV ceiling: guardrails.compute_conviction_score awards the vol bonus to a
# BUY (long premium) only when iv_rank < 20 — that IS the existing low-IV
# convention for long premium. Reused verbatim as the default; policy-config
# bounded.
DEFAULT_MAX_IV_RANK = 20.0
# Strong-directional magnitude: |20d run-up in the trade's direction|. Bounded
# default; policy-config overridable.
DEFAULT_MIN_DIRECTIONAL_RUN = 0.03
# Explicit maximum debit per ONE contract, in dollars. Bounded default.
DEFAULT_MAX_DEBIT_PER_CONTRACT = 150.0


# ── Typed rejection reason codes ────────────────────────────────────────────
EXPERIMENT_DISABLED = "experiment_disabled"
LIVE_ROUTING_FORBIDDEN = "live_routing_forbidden"
CONTRACT_MISSING = "contract_missing"
IV_RANK_UNAVAILABLE = "iv_rank_unavailable"
IV_NOT_LOW = "iv_not_low"
DIRECTIONAL_SIGNAL_UNAVAILABLE = "directional_signal_unavailable"
NO_DIRECTIONAL_BIAS = "no_directional_bias"
DIRECTIONAL_SIGNAL_WEAK = "directional_signal_weak"
EARNINGS_PROXIMITY = "earnings_proximity"
ILLIQUID_CONTRACT = "illiquid_contract"
DEBIT_UNPRICEABLE = "debit_unpriceable"
DEBIT_EXCEEDS_MAX = "debit_exceeds_max"
EV_ESTIMATOR_UNAVAILABLE = "ev_estimator_unavailable"
EV_UNAVAILABLE = "ev_unavailable"


@dataclass(frozen=True)
class SingleLegEVInputs:
    """The exact request shape the injected EV estimator receives. Kept local so
    the generator never imports the estimator's package (import-lock intact)."""

    option_type: str          # "call" | "put"
    strike: float
    debit_per_share: float
    iv: Optional[float]
    spot: Optional[float]
    dte_days: Optional[float]
    known_at: str
    contracts: int = 1


# The injected estimator returns "something with a finite .expected_value" when
# it can price the leg, or an abstention (None, or an object WITHOUT a finite
# .expected_value — e.g. the challenger's typed Unavailable). Duck-typed on
# purpose so the generator need not import the estimator's result types.
EvEstimator = Callable[[SingleLegEVInputs], Any]


@dataclass(frozen=True)
class SingleLegRejection:
    """One typed rejection: which symbol, which reason, human detail."""

    symbol: str
    reason_code: str
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"symbol": self.symbol, "reason_code": self.reason_code, "detail": self.detail}


@dataclass(frozen=True)
class SingleLegCandidate:
    """A dark, shadow-only, one-contract long-option candidate."""

    symbol: str
    option_type: str            # "call" | "put"
    strategy_type: str          # "long_call" | "long_put"
    strike: float
    expiry: Optional[str]
    debit_per_contract: float
    ev_expected_value: float
    ev_pop: Optional[float]
    ev_basis: Optional[str]
    ev_model: Optional[str]
    iv: Optional[float]
    spot: Optional[float]
    dte_days: Optional[float]
    known_at: str
    occ_symbol: Optional[str] = None
    contracts: int = 1                       # INVARIANT: always 1
    routing: str = SHADOW_ONLY_ROUTING       # INVARIANT: always shadow_only
    lifecycle_state: str = LIFECYCLE_STATE   # INVARIANT: always experimental
    experiment: str = SINGLE_LEG_EXPERIMENT  # INVARIANT: single_leg marker

    def to_order_request(self) -> Dict[str, Any]:
        """Downstream order shape carrying the markers the execution-seam guard
        inspects. The single leg is a BUY (long premium)."""
        return {
            "symbol": self.symbol,
            "strategy_type": self.strategy_type,
            "experiment": self.experiment,
            "routing": self.routing,
            "lifecycle_state": self.lifecycle_state,
            "contracts": self.contracts,
            "quantity": self.contracts,
            "legs": [
                {
                    "symbol": self.occ_symbol or "",
                    "occ_symbol": self.occ_symbol or "",
                    "action": "buy",
                    "quantity": self.contracts,
                    "type": self.option_type,
                    "strike": self.strike,
                    "expiry": self.expiry,
                }
            ],
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "option_type": self.option_type,
            "strategy_type": self.strategy_type,
            "strike": self.strike,
            "expiry": self.expiry,
            "contracts": self.contracts,
            "debit_per_contract": self.debit_per_contract,
            "ev_expected_value": self.ev_expected_value,
            "ev_pop": self.ev_pop,
            "ev_basis": self.ev_basis,
            "ev_model": self.ev_model,
            "routing": self.routing,
            "lifecycle_state": self.lifecycle_state,
            "experiment": self.experiment,
            "occ_symbol": self.occ_symbol,
            "known_at": self.known_at,
        }


@dataclass
class SingleLegGenerationResult:
    """Typed generator output. ``enabled`` is False when the policy did not opt
    in (dark no-op — not a rejection). ``candidates`` are one-contract
    shadow-only; ``rejections`` explain every symbol that did not qualify."""

    enabled: bool
    routing_mode: str
    candidates: List[SingleLegCandidate] = field(default_factory=list)
    rejections: List[SingleLegRejection] = field(default_factory=list)


# ── Config extraction (bounded) ─────────────────────────────────────────────

def _cfg_get(policy_config: Optional[Mapping[str, Any]], key: str, default: Any) -> Any:
    if not isinstance(policy_config, Mapping):
        return default
    val = policy_config.get(key, default)
    return default if val is None else val


def experiment_enabled(policy_config: Optional[Mapping[str, Any]]) -> bool:
    """Strict opt-in: only an explicit boolean True (or the string 'true'/'1')
    enables. Absent/false/anything-else -> disabled (dark)."""
    raw = _cfg_get(policy_config, OPT_IN_KEY, False)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def _max_iv_rank(policy_config) -> float:
    try:
        v = float(_cfg_get(policy_config, "single_leg_max_iv_rank", DEFAULT_MAX_IV_RANK))
    except (TypeError, ValueError):
        v = DEFAULT_MAX_IV_RANK
    return max(0.0, min(100.0, v))


def _min_directional_run(policy_config) -> float:
    try:
        v = float(_cfg_get(policy_config, "single_leg_min_directional_run", DEFAULT_MIN_DIRECTIONAL_RUN))
    except (TypeError, ValueError):
        v = DEFAULT_MIN_DIRECTIONAL_RUN
    return max(0.0, min(1.0, v))


def _max_debit_per_contract(policy_config) -> float:
    try:
        v = float(_cfg_get(policy_config, "single_leg_max_debit_per_contract", DEFAULT_MAX_DEBIT_PER_CONTRACT))
    except (TypeError, ValueError):
        v = DEFAULT_MAX_DEBIT_PER_CONTRACT
    return v if v > 0 else DEFAULT_MAX_DEBIT_PER_CONTRACT


# ── Per-symbol condition evaluation ─────────────────────────────────────────

def _dte_days(contract: Mapping[str, Any], known_at: str) -> Optional[float]:
    dte = contract.get("dte_days")
    if isinstance(dte, (int, float)) and math.isfinite(dte) and dte > 0:
        return float(dte)
    expiry = contract.get("expiry") or contract.get("expiration")
    if not expiry:
        return None
    try:
        exp = date.fromisoformat(str(expiry)[:10])
        asof = datetime.fromisoformat(str(known_at).replace("Z", "+00:00")).date()
        days = (exp - asof).days
        return float(days) if days > 0 else None
    except (ValueError, TypeError):
        return None


def _debit_per_share(contract: Mapping[str, Any]) -> Optional[float]:
    """Long-option debit paid per share. Prefer an explicit debit, else mid,
    else ask; must be finite and > 0 (H9 — unpriceable -> None -> reject)."""
    for key in ("debit_per_share", "mid", "mark"):
        v = contract.get(key)
        if isinstance(v, (int, float)) and math.isfinite(v) and v > 0:
            return float(v)
    bid = contract.get("bid")
    ask = contract.get("ask")
    if isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0:
        return (float(bid) + float(ask)) / 2.0
    if isinstance(ask, (int, float)) and math.isfinite(ask) and ask > 0:
        return float(ask)
    return None


def _evaluate_symbol(
    scan_context: Mapping[str, Any],
    policy_config: Optional[Mapping[str, Any]],
    ev_estimator: Optional[EvEstimator],
) -> Any:
    """Return a SingleLegCandidate or a SingleLegRejection for one symbol's
    scan context. Fail-fast on the first failed condition (typed)."""
    symbol = str(scan_context.get("symbol") or "").strip()
    if not symbol:
        return SingleLegRejection("<unknown>", CONTRACT_MISSING, "scan_context has no symbol")

    contract = scan_context.get("contract")
    if not isinstance(contract, Mapping) or not contract:
        return SingleLegRejection(symbol, CONTRACT_MISSING, "no chosen option contract in scan_context")

    known_at = str(scan_context.get("known_at") or datetime.now(timezone.utc).isoformat())

    # 1. LOW-IV (guardrails BUY convention: iv_rank < 20). Missing -> reject (H9).
    iv_rank = scan_context.get("iv_rank")
    if not isinstance(iv_rank, (int, float)) or not math.isfinite(iv_rank):
        return SingleLegRejection(symbol, IV_RANK_UNAVAILABLE, "iv_rank missing/non-finite — cannot confirm low IV")
    if float(iv_rank) > _max_iv_rank(policy_config):
        return SingleLegRejection(symbol, IV_NOT_LOW, f"iv_rank {iv_rank} > max {_max_iv_rank(policy_config)}")

    # 2. STRONG DIRECTIONAL SIGNAL (momentum_signals surface).
    closes = scan_context.get("closes")
    momo = scan_context.get("momentum") if isinstance(scan_context.get("momentum"), Mapping) else None
    run20 = None
    if momo is not None:
        run20 = momo.get("run_up_20d")
    if run20 is None:
        probe = compute_momentum_signals(list(closes or []), "bullish")
        run20 = probe.get("run_up_20d")
    if run20 is None or not isinstance(run20, (int, float)) or not math.isfinite(run20):
        return SingleLegRejection(symbol, DIRECTIONAL_SIGNAL_UNAVAILABLE, "no 20d run-up (insufficient bars/signal)")
    if run20 > 0:
        direction, option_type, strategy_type = "bullish", "call", "long_call"
    elif run20 < 0:
        direction, option_type, strategy_type = "bearish", "put", "long_put"
    else:
        return SingleLegRejection(symbol, NO_DIRECTIONAL_BIAS, "flat 20d trend — no directional bias")
    signals = compute_momentum_signals(list(closes or []), direction)
    signed = signals.get("signed_run_up_in_direction")
    if signed is None and momo is not None:
        signed = momo.get("signed_run_up_in_direction")
    if signed is None:
        # signed run-up only requires closes; if precomputed momentum lacked it,
        # fall back to |run20| (already in the chosen direction by construction).
        signed = abs(float(run20))
    if float(signed) < _min_directional_run(policy_config):
        return SingleLegRejection(
            symbol, DIRECTIONAL_SIGNAL_WEAK,
            f"signed run-up {signed:.4f} < min {_min_directional_run(policy_config)}",
        )
    # Consistency guard: the chosen strategy must map to the chosen direction.
    if direction_from_strategy(strategy_type) != direction:
        return SingleLegRejection(symbol, NO_DIRECTIONAL_BIAS, "strategy/direction inconsistency")

    # 3. NO EARNINGS PROXIMITY (guardrails.is_earnings_safe, 14-day).
    market_data = scan_context.get("market_data") if isinstance(scan_context.get("market_data"), Mapping) else {}
    if not is_earnings_safe(symbol, dict(market_data)):
        return SingleLegRejection(symbol, EARNINGS_PROXIMITY, "earnings within the 14-day window")

    # 4. STRICT CONTRACT LIQUIDITY (spread guardrail + OI/volume).
    bid = contract.get("bid")
    ask = contract.get("ask")
    if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0):
        return SingleLegRejection(symbol, ILLIQUID_CONTRACT, "missing/zero bid or ask (strict — no dev leniency)")
    slippage = apply_slippage_guardrail({"symbol": symbol}, {"bid": float(bid), "ask": float(ask)})
    if slippage <= 0.0:
        return SingleLegRejection(symbol, ILLIQUID_CONTRACT, f"spread guardrail rejected (mult={slippage})")
    if not check_liquidity(symbol, dict(market_data)):
        return SingleLegRejection(symbol, ILLIQUID_CONTRACT, "open_interest/volume below liquidity floor")

    # 5. EXPLICIT MAX DEBIT (policy-config bounded).
    debit_per_share = _debit_per_share(contract)
    if debit_per_share is None:
        return SingleLegRejection(symbol, DEBIT_UNPRICEABLE, "no priceable debit (bid/ask/mid all unusable)")
    debit_per_contract = debit_per_share * 100.0
    if debit_per_contract > _max_debit_per_contract(policy_config):
        return SingleLegRejection(
            symbol, DEBIT_EXCEEDS_MAX,
            f"debit ${debit_per_contract:.2f} > max ${_max_debit_per_contract(policy_config):.2f}",
        )

    # 6. INDEPENDENT EV (injected challenger/adapter). Missing -> reject (H9).
    if ev_estimator is None:
        return SingleLegRejection(symbol, EV_ESTIMATOR_UNAVAILABLE, "no independent EV estimator injected")
    strike = contract.get("strike")
    if not isinstance(strike, (int, float)) or not math.isfinite(strike) or strike <= 0:
        return SingleLegRejection(symbol, CONTRACT_MISSING, f"invalid strike {strike!r}")
    spot = scan_context.get("spot")
    if spot is None:
        spot = contract.get("spot")
    iv = contract.get("iv")
    dte = _dte_days(contract, known_at)
    ev_inputs = SingleLegEVInputs(
        option_type=option_type,
        strike=float(strike),
        debit_per_share=float(debit_per_share),
        iv=float(iv) if isinstance(iv, (int, float)) else None,
        spot=float(spot) if isinstance(spot, (int, float)) else None,
        dte_days=dte,
        known_at=known_at,
        contracts=1,
    )
    ev_result = ev_estimator(ev_inputs)
    ev_val = getattr(ev_result, "expected_value", None)
    if ev_result is None or not isinstance(ev_val, (int, float)) or not math.isfinite(ev_val):
        detail = getattr(ev_result, "reason_code", None) or "estimator abstained / non-finite EV"
        return SingleLegRejection(symbol, EV_UNAVAILABLE, f"independent EV unavailable ({detail})")

    return SingleLegCandidate(
        symbol=symbol,
        option_type=option_type,
        strategy_type=strategy_type,
        strike=float(strike),
        expiry=(str(contract.get("expiry") or contract.get("expiration")) if (contract.get("expiry") or contract.get("expiration")) else None),
        debit_per_contract=round(debit_per_contract, 2),
        ev_expected_value=float(ev_val),
        ev_pop=(float(getattr(ev_result, "pop")) if isinstance(getattr(ev_result, "pop", None), (int, float)) else None),
        ev_basis=getattr(ev_result, "basis", None),
        ev_model=getattr(ev_result, "model", None),
        iv=ev_inputs.iv,
        spot=ev_inputs.spot,
        dte_days=dte,
        known_at=known_at,
        occ_symbol=(str(contract.get("occ_symbol")) if contract.get("occ_symbol") else None),
        contracts=1,
    )


# ── Public entrypoint ───────────────────────────────────────────────────────

def generate_single_leg_candidates(
    scan_contexts: List[Mapping[str, Any]],
    policy_config: Optional[Mapping[str, Any]],
    *,
    routing_mode: str,
    ev_estimator: Optional[EvEstimator] = None,
) -> SingleLegGenerationResult:
    """Generate one-contract shadow-only single-leg candidates.

    Gate order (any failure short-circuits with a typed outcome):
      * policy opt-in absent/false -> enabled=False, zero candidates (dark).
      * routing_mode != shadow_only -> LIVE_ROUTING_FORBIDDEN, zero candidates
        (the live-pool structural proof — a live_eligible policy config can
        never enable the experiment, flag notwithstanding).
      * per symbol: every entry condition must pass, else a typed rejection.

    ``scan_contexts`` is one mapping per symbol (symbol, iv_rank, closes/momentum,
    market_data, spot, known_at, and a chosen ``contract`` dict). Contract
    SELECTION (which strike/expiry) is the caller's responsibility — this
    generator owns the experiment's GATES and the one-contract stamping.
    """
    if not experiment_enabled(policy_config):
        return SingleLegGenerationResult(enabled=False, routing_mode=str(routing_mode or ""))

    result = SingleLegGenerationResult(enabled=True, routing_mode=str(routing_mode or ""))

    # STRUCTURAL live-pool guard: the experiment is shadow-only. A live-routed
    # policy config cannot enable it — refuse the whole batch, emit nothing.
    if str(routing_mode or "").strip().lower() != SHADOW_ONLY_ROUTING:
        detail = (
            f"routing_mode={routing_mode!r} is not shadow_only "
            f"({'live_eligible — champion/live pool' if str(routing_mode).strip().lower() == LIVE_ROUTING_MODE else 'non-shadow'}); "
            "single-leg experiment is shadow-only by construction"
        )
        for ctx in scan_contexts or []:
            sym = str((ctx or {}).get("symbol") or "<unknown>")
            result.rejections.append(SingleLegRejection(sym, LIVE_ROUTING_FORBIDDEN, detail))
        if not scan_contexts:
            result.rejections.append(SingleLegRejection("<batch>", LIVE_ROUTING_FORBIDDEN, detail))
        return result

    for ctx in scan_contexts or []:
        outcome = _evaluate_symbol(ctx or {}, policy_config, ev_estimator)
        if isinstance(outcome, SingleLegCandidate):
            result.candidates.append(outcome)
        else:
            result.rejections.append(outcome)
    return result
