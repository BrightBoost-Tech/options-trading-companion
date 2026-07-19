"""One-contract SELECTION for the dark, shadow-only single-leg experiment.

The #1287 generator (``single_leg_experiment.generate_single_leg_candidates``)
owns the experiment's GATES and the one-contract stamping, but it takes a scan
context whose ``contract`` (strike/expiry) is ALREADY chosen — its docstring is
explicit: "Contract SELECTION (which strike/expiry) is the caller's
responsibility." THIS module is that caller. It reads the REAL option chain and
picks THE one contract per symbol, then hands it to the generator so
``generate_single_leg_candidates`` can produce a COMPLETE stageable candidate.

Ships DARK, exactly like the generator: zero production callers, opt-in +
shadow-only routing enforced by the generator it delegates to (this module
NEVER relaxes either). No env activation.

CHAIN SOURCE SEAM (no new fetch patterns):
    The chain comes from ``truth_layer.option_chain(underlying, min_expiry=…,
    max_expiry=…, spot=…)`` — the SAME method + call shape the scanner uses
    (options_scanner.py: ``truth_layer.option_chain(symbol,
    min_expiry=min_expiry, max_expiry=max_expiry, spot=_spot)``). The truth
    layer is INJECTED (DI): production supplies the real
    ``market_data_truth_layer`` instance; tests supply a fake chain. A
    dark/empty chain REJECTS (H9) — never a fabricated contract.

WHAT SELECTION OWNS (per the lane charter):
  * valid DTE window   — policy-config bounded; defaults from the scanner's own
                         conventions (SCANNER_MIN_DTE=25 / SCANNER_MAX_DTE=45,
                         target_dte 35). Each contract's DTE is recomputed
                         precisely from (expiry - known_at) and must fall inside
                         [min_dte, max_dte].
  * exact-contract     — the spread guardrail
    liquidity            (``apply_slippage_guardrail``) AND the OI/volume floor
                         (``check_liquidity``) evaluated on THAT SPECIFIC
                         contract's own bid/ask/oi/volume (not a per-symbol
                         aggregate). The chosen contract's oi/volume ride into
                         the scan context's ``market_data`` so the generator
                         re-confirms the identical exact-contract liquidity.
  * explicit max debit — per-contract debit (mid×100) ≤
                         single_leg_max_debit_per_contract (default $150; the
                         generator's own ceiling, reused verbatim).
  * independent EV/PoP — the INJECTED estimator (the #1287 challenger adapter)
                         prices EACH surviving contract; source/version/known_at
                         are recorded on the selection. A contract the estimator
                         cannot price (typed abstention → no finite EV) is
                         EXCLUDED (H9); if NOTHING prices, the symbol REJECTS —
                         an EV is never fabricated to force a pick.
  * VRP evidence       — the cross-sectional cheap/fair signal (#1292) rides
                         through unchanged in the scan context (``iv_rv_spread``)
                         and the generator applies the gate + stamps
                         vrp_iv_rv_spread/multiplier/source on the candidate.
  * deterministic       — see TIE-BREAKER below. No randomness, no reliance on
    tie-breaker            chain/dict iteration order (the ranking is an explicit
                           total-order sort).
  * one contract        — exactly one scan context (one chosen contract) is
                          handed to the generator per symbol; the generator
                          stamps contracts==1 / shadow_only / experimental.

TIE-BREAKER (documented, deterministic, total order — NO randomness):
  Among the contracts that pass DTE + exact-contract liquidity + max-debit +
  priceable-EV, choose the minimum under the lexicographic key
      (−expected_value, |delta − target_delta|, debit_per_contract, occ_symbol)
  i.e.:
    1. HIGHEST independent EV (the estimator's expected_value), then
    2. NEAREST delta to target (default 0.50 magnitude — an ATM-ish long
       option; target is +0.50 for a call, −0.50 for a put; a contract missing
       delta sorts LAST on this key), then
    3. LOWEST debit per contract, then
    4. LEXICALLY smallest occ_symbol (a stable, unique final key — a total
       order, so the pick is fully determined by the chain contents).

DEPENDENCY-INJECTION / IMPORT DISCIPLINE (mirrors the generator):
  The EV estimator is INJECTED — this module carries NO import of the
  challenger/evaluator package, so the observe-only import-lock stays intact.
  The generator supplies the request shape (``SingleLegEVInputs``) and every
  gate/typed-reject helper; this module reuses them (never re-implements a
  threshold — the drift-lie guard).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Union

from packages.quantum.analytics.guardrails import (
    apply_slippage_guardrail,
    check_liquidity,
)
from packages.quantum.brokers.execution_router import SHADOW_ONLY_ROUTING
from packages.quantum.services.momentum_signals import compute_momentum_signals
from packages.quantum.strategies import single_leg_experiment as sl
from packages.quantum.strategies.single_leg_experiment import (
    SingleLegEVInputs,
    SingleLegGenerationResult,
    SingleLegRejection,
)

# ── DTE window + delta-target bounded defaults (from scanner conventions) ─────
# Scanner: SCANNER_MIN_DTE = 25 / SCANNER_MAX_DTE = 45, expiry selection centred
# on target_dte 35 (options_scanner.py). Reused verbatim as the default window;
# policy-config bounded (a policy may narrow OR widen it explicitly).
DEFAULT_MIN_DTE = 25
DEFAULT_MAX_DTE = 45
DEFAULT_TARGET_DTE = 35
# Delta target for the NEAREST-delta tie-break (magnitude). 0.50 ≈ ATM long
# option. Applied as +target for a call, −target for a put.
DEFAULT_TARGET_DELTA = 0.50

# Tie-breaker documentation string stamped on every selection (audit-legible).
TIE_BREAKER = "(-expected_value, |delta-target|, debit_per_contract, occ_symbol)"

# ── Selection-level typed rejection reason codes ────────────────────────────
# (The per-condition GATE rejections — iv_rank / VRP / earnings / etc. — are the
# generator's; these are the SELECTION-stage reasons for a symbol that never
# yields a chosen contract.)
CHAIN_UNAVAILABLE = "chain_unavailable"
NO_CONTRACT_IN_DTE_WINDOW = "no_contract_in_dte_window"
NO_VIABLE_CONTRACT = "no_viable_contract"
# Reused from the generator so the direction pre-check speaks the same vocabulary.
DIRECTIONAL_SIGNAL_UNAVAILABLE = sl.DIRECTIONAL_SIGNAL_UNAVAILABLE
NO_DIRECTIONAL_BIAS = sl.NO_DIRECTIONAL_BIAS
CONTRACT_MISSING = sl.CONTRACT_MISSING


@dataclass(frozen=True)
class SelectedContract:
    """The ONE contract selected for a symbol + the scan context handed to the
    generator + selection provenance (EV source/version/known_at, tie-break,
    considered/viable counts, chain source)."""

    symbol: str
    option_type: str            # "call" | "put"
    occ_symbol: Optional[str]
    strike: float
    expiry: Optional[str]
    dte_days: float
    debit_per_contract: float
    delta: Optional[float]
    ev_expected_value: float
    ev_pop: Optional[float]
    ev_source: Optional[str]
    ev_version: Optional[str]
    ev_known_at: str
    considered: int             # contracts on the chosen side inside the DTE window
    viable: int                 # of those, how many passed every pre-filter (ranked set)
    chain_source: Optional[str]
    tie_breaker: str = TIE_BREAKER
    # The exact mapping handed to generate_single_leg_candidates for this symbol.
    scan_context: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class SingleLegSelectionResult:
    """Typed output of select_and_generate_single_leg.

    ``generation`` is the generator's own result (the authoritative candidates +
    gate rejections on the chosen contracts). ``selections`` is the per-symbol
    chosen-contract provenance. ``selection_rejections`` are symbols that never
    reached the generator (no chain / no in-window / no viable contract)."""

    generation: SingleLegGenerationResult
    selections: List[SelectedContract] = field(default_factory=list)
    selection_rejections: List[SingleLegRejection] = field(default_factory=list)


# ── Bounded policy-config extraction (reuses the generator's _cfg_get) ───────

def _dte_window(policy_config: Optional[Mapping[str, Any]]) -> tuple[int, int]:
    """(min_dte, max_dte) for the experiment. Policy-config bounded; a reversed
    or non-positive window falls back to the scanner-convention default."""
    try:
        lo = int(sl._cfg_get(policy_config, "single_leg_min_dte", DEFAULT_MIN_DTE))
    except (TypeError, ValueError):
        lo = DEFAULT_MIN_DTE
    try:
        hi = int(sl._cfg_get(policy_config, "single_leg_max_dte", DEFAULT_MAX_DTE))
    except (TypeError, ValueError):
        hi = DEFAULT_MAX_DTE
    if lo <= 0 or hi <= 0 or hi < lo:
        return DEFAULT_MIN_DTE, DEFAULT_MAX_DTE
    return lo, hi


def _target_delta(policy_config: Optional[Mapping[str, Any]]) -> float:
    try:
        v = float(sl._cfg_get(policy_config, "single_leg_target_delta", DEFAULT_TARGET_DELTA))
    except (TypeError, ValueError):
        v = DEFAULT_TARGET_DELTA
    # A long-option delta magnitude lives in (0, 1]; clamp defensively.
    return max(0.01, min(1.0, abs(v)))


# ── Chain helpers ────────────────────────────────────────────────────────────

def _asof_date(known_at: str) -> Optional[date]:
    try:
        return datetime.fromisoformat(str(known_at).replace("Z", "+00:00")).date()
    except (ValueError, TypeError):
        return None


def _right(contract: Mapping[str, Any]) -> Optional[str]:
    """Canonical call/put from a chain contract (truth-layer 'right', or a
    C/P/call/put in 'right'/'type')."""
    for key in ("right", "type", "option_type"):
        val = contract.get(key)
        if not val:
            continue
        s = str(val).strip().lower()
        if s in ("call", "c"):
            return "call"
        if s in ("put", "p"):
            return "put"
    return None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(v):
        return float(v)
    return None


def _flatten_contract(tc: Mapping[str, Any]) -> Dict[str, Any]:
    """Map a truth-layer chain contract (nested ``quote``/``greeks``) to the FLAT
    shape the generator's ``_evaluate_symbol`` reads (bid/ask/mid/strike/expiry/
    iv/delta/occ_symbol/oi/volume). No fabrication — absent fields stay None."""
    quote = tc.get("quote") if isinstance(tc.get("quote"), Mapping) else {}
    greeks = tc.get("greeks") if isinstance(tc.get("greeks"), Mapping) else {}
    oi = _num(tc.get("oi"))
    if oi is None:
        oi = _num(tc.get("open_interest"))
    vol = _num(tc.get("volume"))
    return {
        "strike": _num(tc.get("strike")),
        "expiry": tc.get("expiry") or tc.get("expiration"),
        "iv": _num(tc.get("iv")),
        "bid": _num(quote.get("bid")) if quote else _num(tc.get("bid")),
        "ask": _num(quote.get("ask")) if quote else _num(tc.get("ask")),
        "mid": _num(quote.get("mid")) if quote else _num(tc.get("mid")),
        "delta": _num(greeks.get("delta")) if greeks else _num(tc.get("delta")),
        "occ_symbol": tc.get("contract") or tc.get("occ_symbol"),
        # Integer OI/volume for the generator's check_liquidity (None → 0 so a
        # None never TypeErrors the > comparison; a real viable contract clears
        # the floor and is numeric anyway).
        "oi": int(oi) if oi is not None else 0,
        "volume": int(vol) if vol is not None else 0,
        "source": tc.get("source"),
    }


@dataclass(frozen=True)
class _Ranked:
    flat: Mapping[str, Any]
    dte: float
    ev_val: float
    ev_pop: Optional[float]
    ev_source: Optional[str]
    ev_version: Optional[str]
    debit_per_contract: float

    @property
    def delta(self) -> Optional[float]:
        return _num(self.flat.get("delta"))

    @property
    def occ(self) -> str:
        return str(self.flat.get("occ_symbol") or "")


def _delta_dist(delta: Optional[float], target: float) -> float:
    d = _num(delta)
    return abs(d - target) if d is not None else math.inf


def _direction_for(uctx: Mapping[str, Any]) -> str:
    """Return 'call' / 'put' from the SAME momentum surface the generator uses
    (so the two can never disagree on side), or a typed rejection reason string
    prefixed with '!' for the caller to convert. run20>0 → call, <0 → put."""
    momo = uctx.get("momentum") if isinstance(uctx.get("momentum"), Mapping) else None
    run20 = momo.get("run_up_20d") if momo is not None else None
    if run20 is None:
        probe = compute_momentum_signals(list(uctx.get("closes") or []), "bullish")
        run20 = probe.get("run_up_20d")
    r = _num(run20)
    if r is None:
        return "!" + DIRECTIONAL_SIGNAL_UNAVAILABLE
    if r > 0:
        return "call"
    if r < 0:
        return "put"
    return "!" + NO_DIRECTIONAL_BIAS


# ── Per-symbol selection ─────────────────────────────────────────────────────

def select_single_leg_contract(
    uctx: Mapping[str, Any],
    policy_config: Optional[Mapping[str, Any]],
    *,
    truth_layer: Any,
    ev_estimator: Optional[sl.EvEstimator],
    known_at: Optional[str] = None,
) -> Union[SelectedContract, SingleLegRejection]:
    """Read the real chain for one symbol and pick THE contract, or reject
    (typed). Returns a SelectedContract (carrying the generator scan context) or
    a SingleLegRejection. Read-only — never mutates the chain or the DB."""
    symbol = str(uctx.get("symbol") or "").strip()
    if not symbol:
        return SingleLegRejection("<unknown>", CONTRACT_MISSING, "underlying context has no symbol")

    known_at = str(known_at or uctx.get("known_at") or datetime.now(timezone.utc).isoformat())

    # Direction from the shared momentum surface (agrees with the generator).
    side = _direction_for(uctx)
    if side.startswith("!"):
        return SingleLegRejection(symbol, side[1:], "no usable 20d directional signal")
    option_type = side

    asof = _asof_date(known_at)
    if asof is None:
        return SingleLegRejection(symbol, CONTRACT_MISSING, f"unparseable known_at {known_at!r}")
    min_dte, max_dte = _dte_window(policy_config)
    min_expiry = (asof + timedelta(days=min_dte)).isoformat()
    max_expiry = (asof + timedelta(days=max_dte)).isoformat()
    spot = _num(uctx.get("spot"))

    # CHAIN SOURCE SEAM — same call shape as the scanner. DI truth layer.
    try:
        chain = truth_layer.option_chain(
            symbol, min_expiry=min_expiry, max_expiry=max_expiry, spot=spot
        )
    except Exception as exc:  # a chain fetch fault is dark → reject (H9, never fabricate)
        return SingleLegRejection(symbol, CHAIN_UNAVAILABLE, f"option_chain raised {type(exc).__name__}: {str(exc)[:120]}")
    if not chain:
        return SingleLegRejection(symbol, CHAIN_UNAVAILABLE, "option_chain returned no contracts (dark chain)")

    chain_source = None
    # Side + precise DTE window.
    considered: List[tuple[Dict[str, Any], float]] = []
    for tc in chain:
        if not isinstance(tc, Mapping):
            continue
        if _right(tc) != option_type:
            continue
        flat = _flatten_contract(tc)
        if chain_source is None:
            chain_source = flat.get("source")
        dte = sl._dte_days(flat, known_at)
        if dte is None or not (min_dte <= dte <= max_dte):
            continue
        considered.append((flat, dte))

    if not considered:
        return SingleLegRejection(
            symbol, NO_CONTRACT_IN_DTE_WINDOW,
            f"no {option_type} contract in DTE window [{min_dte},{max_dte}]",
        )

    max_debit = sl._max_debit_per_contract(policy_config)
    ranked: List[_Ranked] = []
    for flat, dte in considered:
        bid, ask = flat.get("bid"), flat.get("ask")
        # Exact-contract liquidity — strict (no dev leniency): spread + OI/vol.
        if not (isinstance(bid, (int, float)) and isinstance(ask, (int, float)) and bid > 0 and ask > 0):
            continue
        if apply_slippage_guardrail({"symbol": symbol}, {"bid": float(bid), "ask": float(ask)}) <= 0.0:
            continue
        if not check_liquidity(symbol, {"open_interest": flat.get("oi", 0), "volume": flat.get("volume", 0)}):
            continue
        # Explicit max debit (reuse the generator's priceable-debit + ceiling).
        dps = sl._debit_per_share(flat)
        if dps is None:
            continue
        debit_per_contract = dps * 100.0
        if debit_per_contract > max_debit:
            continue
        # Independent EV/PoP via the injected estimator (H9: abstain → exclude).
        if ev_estimator is None:
            continue
        strike = _num(flat.get("strike"))
        if strike is None or strike <= 0:
            continue
        ev_inputs = SingleLegEVInputs(
            option_type=option_type,
            strike=float(strike),
            debit_per_share=float(dps),
            iv=_num(flat.get("iv")),
            spot=spot if spot is not None else _num(flat.get("spot")),
            dte_days=dte,
            known_at=known_at,
            contracts=1,
        )
        ev_result = ev_estimator(ev_inputs)
        ev_val = getattr(ev_result, "expected_value", None)
        if ev_result is None or not isinstance(ev_val, (int, float)) or not math.isfinite(ev_val):
            continue
        prov = getattr(ev_result, "provenance", None)
        ranked.append(_Ranked(
            flat=flat,
            dte=float(dte),
            ev_val=float(ev_val),
            ev_pop=(float(getattr(ev_result, "pop")) if isinstance(getattr(ev_result, "pop", None), (int, float)) else None),
            ev_source=getattr(prov, "source", None),
            ev_version=getattr(prov, "version", None),
            debit_per_contract=round(debit_per_contract, 2),
        ))

    if not ranked:
        return SingleLegRejection(
            symbol, NO_VIABLE_CONTRACT,
            f"{len(considered)} {option_type} contract(s) in window, none passed "
            f"liquidity/max-debit(${max_debit:.0f})/priceable-EV",
        )

    # Deterministic total-order tie-break.
    target = _target_delta(policy_config) * (1.0 if option_type == "call" else -1.0)
    ranked.sort(key=lambda r: (-r.ev_val, _delta_dist(r.delta, target), r.debit_per_contract, r.occ))
    best = ranked[0]

    # Build the generator scan context: chosen contract + exact-contract oi/vol
    # merged into market_data (so the generator re-confirms the SAME liquidity),
    # earnings_date preserved from the underlying context.
    market_data = dict(uctx.get("market_data") or {})
    market_data["open_interest"] = best.flat.get("oi", 0)
    market_data["volume"] = best.flat.get("volume", 0)
    scan_context: Dict[str, Any] = {
        "symbol": symbol,
        "iv_rank": uctx.get("iv_rank"),
        "iv_rv_spread": uctx.get("iv_rv_spread"),
        "closes": uctx.get("closes"),
        "momentum": uctx.get("momentum"),
        "spot": spot,
        "known_at": known_at,
        "contract": dict(best.flat),
        "market_data": market_data,
    }

    return SelectedContract(
        symbol=symbol,
        option_type=option_type,
        occ_symbol=best.occ or None,
        strike=float(_num(best.flat.get("strike")) or 0.0),
        expiry=(str(best.flat.get("expiry")) if best.flat.get("expiry") else None),
        dte_days=best.dte,
        debit_per_contract=best.debit_per_contract,
        delta=best.delta,
        ev_expected_value=best.ev_val,
        ev_pop=best.ev_pop,
        ev_source=best.ev_source,
        ev_version=best.ev_version,
        ev_known_at=known_at,
        considered=len(considered),
        viable=len(ranked),
        chain_source=chain_source,
        scan_context=scan_context,
    )


# ── Public orchestrator: SELECTION → GENERATOR (complete stageable candidate) ─

def select_and_generate_single_leg(
    underlying_contexts: List[Mapping[str, Any]],
    policy_config: Optional[Mapping[str, Any]] = None,
    *,
    routing_mode: str,
    truth_layer: Any,
    ev_estimator: Optional[sl.EvEstimator] = None,
    policy_registration_id: Optional[str] = None,
    supabase: Any = None,
    registry_epoch: Optional[str] = None,
) -> SingleLegSelectionResult:
    """Per-symbol contract SELECTION wired into the #1287 generator.

    Opt-in + shadow-only routing are the GENERATOR's authority (this module
    never relaxes either):
      * opt-in absent/false  → dark no-op (enabled=False), NO chain fetch.
      * routing != shadow_only → delegated straight to the generator (which
        emits LIVE_ROUTING_FORBIDDEN per symbol), NO chain fetch — a live-routed
        batch never even touches the chain.
      * shadow_only + enabled → each symbol's chain is read, ONE contract is
        selected (or the symbol is typed-rejected), and the chosen contracts are
        handed to the generator, which re-confirms every gate on the chosen
        contract and stamps the one-contract candidate.

    The generator remains the sole gate authority and one-contract stamper; this
    orchestrator only decides WHICH contract each symbol offers it.
    """
    if policy_registration_id is not None:
        # Versioned registry is the opt-in truth (raw jsonb; fail-closed to dark).
        policy_config = sl.load_policy_registration_config(
            supabase, policy_registration_id, epoch=registry_epoch
        )

    routing_norm = str(routing_mode or "").strip().lower()

    # DARK: opt-in absent/false → no candidates, no chain fetch, no rejection.
    if not sl.experiment_enabled(policy_config):
        return SingleLegSelectionResult(
            generation=SingleLegGenerationResult(enabled=False, routing_mode=str(routing_mode or "")),
        )

    # LIVE-POOL STRUCTURAL PROOF: a non-shadow batch is refused by the generator
    # itself — delegate with the RAW contexts (no chosen contract, no chain
    # fetch). The generator emits LIVE_ROUTING_FORBIDDEN for every symbol.
    if routing_norm != SHADOW_ONLY_ROUTING:
        gen = sl.generate_single_leg_candidates(
            list(underlying_contexts or []), policy_config,
            routing_mode=routing_mode, ev_estimator=ev_estimator,
        )
        return SingleLegSelectionResult(generation=gen)

    scan_contexts: List[Mapping[str, Any]] = []
    selections: List[SelectedContract] = []
    selection_rejections: List[SingleLegRejection] = []
    for uctx in underlying_contexts or []:
        outcome = select_single_leg_contract(
            uctx or {}, policy_config, truth_layer=truth_layer, ev_estimator=ev_estimator,
        )
        if isinstance(outcome, SelectedContract):
            selections.append(outcome)
            scan_contexts.append(outcome.scan_context)
        else:
            selection_rejections.append(outcome)

    gen = sl.generate_single_leg_candidates(
        scan_contexts, policy_config,
        routing_mode=SHADOW_ONLY_ROUTING, ev_estimator=ev_estimator,
    )
    return SingleLegSelectionResult(
        generation=gen,
        selections=selections,
        selection_rejections=selection_rejections,
    )
