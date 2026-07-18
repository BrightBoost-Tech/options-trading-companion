"""FROZEN baseline adapters — CURRENT production math, wrapped verbatim.

These adapters are the BASELINE AUTHORITY for the ⑤ prequential comparison.
They call the production functions in ``packages.quantum.ev_calculator``
READ-ONLY (coupling direction: terminal_distribution -> ev_calculator, never
the reverse; the production->ev_calculator wiring is untouched). They do NOT
reimplement the math — parity with production is by construction, pinned by
tests.

KNOWN BASELINE DEFECT — KEPT VISIBLE, NEVER SILENTLY FIXED (charter):
    Production credit-vertical PoP is the payoff-implied fair-odds identity
    PoP = max_loss/(max_gain+max_loss) = 1 - credit/width
    (ev_calculator.calculate_pop:66-80). Substituting into
    EV = PoP*max_gain - (1-PoP)*max_loss (calculate_ev:282) gives raw credit
    EV == $0 for EVERY credit vertical, algebraically. This is why the credit
    cohort produced 0 suggestions in 120d (backlog ⑤). The adapter REPRODUCES
    the zero exactly and stamps ``CREDIT_IDENTITY_DEFECT`` into the result's
    ``known_defects`` so no report can quote the baseline number without the
    defect label. Fixing it here would destroy the baseline's authority as the
    thing challengers must beat.

Model selection for the condor is EXPLICIT (``model="strict"|"tail"``) —
production selects via the CONDOR_EV_MODEL env at options_scanner.py:214 and
~:1808-1830; this package never reads that env (observe-only, no hidden
coupling to deploy state). Tail constants default to the production code
defaults (options_scanner.py:215-216).
"""

from __future__ import annotations

from typing import Literal, Optional

# Read-only wrap of production math. This is the ONLY permitted coupling
# between this package and the live economics path.
from packages.quantum import ev_calculator
from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    DistributionInputs,
    EvalOutcome,
    Provenance,
    StrategyEvaluation,
    StructureSpec,
    Unavailable,
    params_hash,
    structure_params,
    validate_condor,
    validate_vertical,
)

BASELINE_SOURCE = "ev_calculator"
BASELINE_VERSION = f"frozen@{CONTRACT_VERSION}"

CREDIT_IDENTITY_DEFECT = (
    "credit_identity_ev_zero: production PoP = 1 - credit/width is the "
    "payoff-implied fair-odds ratio, so raw credit-vertical EV == $0 by "
    "algebraic identity (ev_calculator.calculate_pop:66-80 + calculate_ev:282). "
    "KNOWN baseline defect — kept visible, never silently fixed here."
)

# Production condor tail-model code defaults (options_scanner.py:215-216).
DEFAULT_TAIL_LOSS_SEVERITY = 0.50
DEFAULT_TAIL_PROB_MULT = 1.00

CondorModel = Literal["strict", "tail"]


def _provenance(model: str, structure: StructureSpec, extra: Optional[dict] = None) -> Provenance:
    params = structure_params(structure)
    if extra:
        params["model_params"] = extra
    return Provenance(
        source=BASELINE_SOURCE,
        version=f"{model}:{BASELINE_VERSION}",
        params_hash=params_hash(params),
    )


def baseline_credit_vertical(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs] = None,  # unused: delta/identity math needs no market snapshot
) -> EvalOutcome:
    """Frozen credit-vertical baseline: production ``calculate_ev`` verbatim.

    For every validated credit vertical (0 < credit < width) production takes
    the credit-identity branch, so ``expected_value`` is EXACTLY 0.0 — see
    ``CREDIT_IDENTITY_DEFECT`` (stamped on the result)."""
    source = "baseline_credit_vertical"
    geom = validate_vertical(structure, source)
    if isinstance(geom, Unavailable):
        return geom
    if structure.strategy != "credit_vertical":
        return Unavailable("wrong_strategy", f"expected credit_vertical, got {structure.strategy}", source)

    credit = structure.net_premium
    legs_payload = [{"action": l.action, "delta": l.delta} for l in structure.legs]
    result = ev_calculator.calculate_ev(
        premium=credit,
        strike=geom.short_leg.strike,
        current_price=(inputs.spot if inputs and inputs.spot is not None else 0.0),
        delta=(geom.short_leg.delta if geom.short_leg.delta is not None else 0.0),
        strategy="credit_spread",
        width=geom.width,
        contracts=structure.contracts,
        legs=legs_payload,
    )
    breakeven = (
        geom.short_leg.strike + credit
        if geom.option_type == "call"
        else geom.short_leg.strike - credit
    )
    return StrategyEvaluation(
        strategy="credit_vertical",
        model="baseline_credit_identity",
        pop=result.win_probability,
        expected_value=result.expected_value,
        basis="raw",
        max_gain=result.max_gain,
        max_loss=result.max_loss,
        breakevens=(breakeven,),
        provenance=_provenance("baseline_credit_identity", structure),
        known_defects=(CREDIT_IDENTITY_DEFECT,),
    )


def baseline_debit_vertical(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs] = None,  # unused: delta interpolation needs no market snapshot
) -> EvalOutcome:
    """Frozen debit-vertical baseline: production ``calculate_ev`` verbatim.

    Production PoP is the breakeven interpolation between long/short deltas
    weighted by premium/width (ev_calculator.calculate_pop:92-108, reachable
    because calculate_ev passes credit=premium for debit — the v5-A1 fix).
    Both leg deltas are REQUIRED here: without them production would silently
    degrade to its delta fallback, which is not the interpolation baseline —
    we abstain instead (H9)."""
    source = "baseline_debit_vertical"
    geom = validate_vertical(structure, source)
    if isinstance(geom, Unavailable):
        return geom
    if structure.strategy != "debit_vertical":
        return Unavailable("wrong_strategy", f"expected debit_vertical, got {structure.strategy}", source)
    if geom.long_leg.delta is None or geom.short_leg.delta is None:
        return Unavailable(
            "missing_delta",
            "debit interpolation baseline requires both leg deltas; production would "
            "silently fall back off the interpolation branch without them",
            source,
        )

    debit = structure.net_premium
    legs_payload = [{"action": l.action, "delta": l.delta} for l in structure.legs]
    result = ev_calculator.calculate_ev(
        premium=debit,
        strike=geom.long_leg.strike,
        current_price=(inputs.spot if inputs and inputs.spot is not None else 0.0),
        delta=geom.long_leg.delta,
        strategy="debit_spread",
        width=geom.width,
        contracts=structure.contracts,
        legs=legs_payload,
    )
    breakeven = (
        geom.long_leg.strike + debit
        if geom.option_type == "call"
        else geom.long_leg.strike - debit
    )
    return StrategyEvaluation(
        strategy="debit_vertical",
        model="baseline_debit_interp",
        pop=result.win_probability,
        expected_value=result.expected_value,
        basis="raw",
        max_gain=result.max_gain,
        max_loss=result.max_loss,
        breakevens=(breakeven,),
        provenance=_provenance("baseline_debit_interp", structure),
    )


def baseline_condor(
    structure: StructureSpec,
    inputs: Optional[DistributionInputs] = None,  # unused: delta-tail math needs no market snapshot
    *,
    model: CondorModel,
    tail_loss_severity: float = DEFAULT_TAIL_LOSS_SEVERITY,
    tail_prob_mult: float = DEFAULT_TAIL_PROB_MULT,
) -> EvalOutcome:
    """Frozen iron-condor baseline. ``model`` is EXPLICIT and required:

    - "strict": production ``calculate_condor_ev`` (short deltas only,
      disjoint-tail; ev_calculator.py:568-629).
    - "tail": production ``calculate_condor_ev_tail`` (short=breach,
      long=max-loss, severity-weighted partial region; :632-734). Requires
      long-leg deltas too; absent -> abstain.

    Production units are dollars PER CONTRACT (x100, no contracts multiply in
    calculate_condor_ev*); the adapter multiplies by ``structure.contracts``
    to match the per-position units of ``StrategyEvaluation`` (documented
    bookkeeping, not a math change — parity tests pin contracts=1 equality)."""
    source = "baseline_condor"
    geom = validate_condor(structure, source)
    if isinstance(geom, Unavailable):
        return geom
    if structure.strategy != "iron_condor":
        return Unavailable("wrong_strategy", f"expected iron_condor, got {structure.strategy}", source)
    if model not in ("strict", "tail"):
        return Unavailable("invalid_model", f"condor model must be 'strict' or 'tail', got {model!r}", source)
    if geom.short_put.delta is None or geom.short_call.delta is None:
        return Unavailable("missing_delta", "condor baseline requires short put/call deltas", source)

    credit = structure.net_premium
    if model == "tail":
        if geom.long_put.delta is None or geom.long_call.delta is None:
            return Unavailable("missing_delta", "tail condor baseline requires long put/call deltas", source)
        result = ev_calculator.calculate_condor_ev_tail(
            credit=credit,
            width_put=geom.width_put,
            width_call=geom.width_call,
            delta_short_put=abs(geom.short_put.delta),
            delta_short_call=abs(geom.short_call.delta),
            delta_long_put=abs(geom.long_put.delta),
            delta_long_call=abs(geom.long_call.delta),
            tail_loss_severity=tail_loss_severity,
            tail_prob_mult=tail_prob_mult,
        )
        model_name = "baseline_condor_tail"
        extra = {
            "model": model,
            "tail_loss_severity": tail_loss_severity,
            "tail_prob_mult": tail_prob_mult,
        }
    else:
        result = ev_calculator.calculate_condor_ev(
            credit=credit,
            width_put=geom.width_put,
            width_call=geom.width_call,
            delta_short_put=abs(geom.short_put.delta),
            delta_short_call=abs(geom.short_call.delta),
        )
        model_name = "baseline_condor_strict"
        extra = {"model": model}

    n = structure.contracts
    return StrategyEvaluation(
        strategy="iron_condor",
        model=model_name,
        pop=result.win_probability,
        expected_value=result.expected_value * n,
        basis="raw",
        max_gain=result.max_gain * n,
        max_loss=result.max_loss * n,
        breakevens=(geom.short_put.strike - credit, geom.short_call.strike + credit),
        provenance=_provenance(model_name, structure, extra),
    )
