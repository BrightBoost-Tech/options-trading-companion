"""⑤ Scan-time research-candidate scorer (OBSERVE-ONLY, pure, no I/O).

Scores ONE research-candidate envelope (captured at scan time by
``packages.quantum.services.td_scan_capture`` for EVERY fully-constructed
candidate — emitted AND rejected) against BOTH models the offline study grades:

  1. the FROZEN production-math baseline adapter (``baseline_credit_vertical`` /
     ``baseline_debit_vertical`` / ``baseline_condor``), and
  2. the ``lognormal_v1`` CHALLENGER (``challenger_lognormal_evaluate`` /
     ``evaluate_single_leg`` for a long single leg).

IMPORT-LOCK (Lane-B-of-#1287 / model_review trio pattern): this module lives
OUTSIDE ``packages/quantum`` so it is invisible to the terminal-distribution
import-lock sweep — it is the ONE place the observe-only package is named. The
background job handler and its service reach these models ONLY through this
module (exactly as ``model_review.py`` reaches them through
``challenger_study.py``), so no ``packages/quantum`` module ever names the
package.

PURITY / H9: ``score_envelope`` opens no DB/broker/provider connection and never
fabricates an input. A missing spot / per-leg IV / per-leg delta produces a
typed abstention (``Unavailable``) that is COUNTED, never scored as a 0.5 or a
default-IV guess. Emits ``basis="raw"`` only — no calibration here.

BASIS: ``contracts = 1`` (per structure-contract) — sizing is downstream of the
scan seam; the score matches the scanner's own per-contract ``ev``/``pop``.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

# The ONE import site of the observe-only package (outside packages/quantum).
from packages.quantum.analytics.terminal_distribution import (
    CONTRACT_VERSION,
    DistributionInputs,
    LegSpec,
    StrategyEvaluation,
    StructureSpec,
    Unavailable,
    baseline_condor,
    baseline_credit_vertical,
    baseline_debit_vertical,
    challenger_lognormal_evaluate,
    evaluate_single_leg,
)

# Frozen model-SET version — pinned to CONTRACT_VERSION so a model/contract
# change yields a NEW version string, disambiguating a re-score in the
# td_scan_scores idempotency key (cycle_id, fingerprint, challenger_model_version).
# Kept 1:1 with challenger_study.MODEL_SET_VERSION (the offline study's authority)
# so the two consumers never drift.
MODEL_SET_VERSION = f"td-baseline+lognormal_v1@{CONTRACT_VERSION}"

# Condor baseline model. The frozen adapter never reads CONDOR_EV_MODEL (observe-
# only, no hidden coupling to deploy state — baselines.py doctrine); we score the
# deterministic "strict" model and stamp it in provenance. The production
# as-emitted comparator (``production_ev`` on the envelope) already carries the
# deployed model's number.
_CONDOR_MODEL = "strict"

# DB strategy vocabulary -> foundation contract strategy (1:1 with
# challenger_study.STRATEGY_MAP).
STRATEGY_MAP: Dict[str, str] = {
    "IRON_CONDOR": "iron_condor",
    "LONG_CALL_DEBIT_SPREAD": "debit_vertical",
    "LONG_PUT_DEBIT_SPREAD": "debit_vertical",
    "CREDIT_CALL_SPREAD": "credit_vertical",
    "CREDIT_PUT_SPREAD": "credit_vertical",
    "LONG_CALL": "long_call",
    "LONG_PUT": "long_put",
}


def _finite(x: Any) -> Optional[float]:
    if isinstance(x, bool):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _norm_action(side: Any) -> Optional[str]:
    s = str(side or "").strip().lower()
    if s in ("buy", "long", "b"):
        return "buy"
    if s in ("sell", "short", "s"):
        return "sell"
    return None


def _norm_option_type(ot: Any) -> Optional[str]:
    s = str(ot or "").strip().lower()
    if s in ("call", "c"):
        return "call"
    if s in ("put", "p"):
        return "put"
    return None


def resolve_strategy(envelope: Dict[str, Any]) -> Optional[str]:
    """Map the envelope's DB-vocab strategy to a contract strategy, falling back
    to leg-geometry inference (leg count + premium_direction) so the scorer is
    robust to the scanner's exact naming. Returns None when unresolvable — the
    caller records a typed unmapped abstention (never a default)."""
    db = str(envelope.get("strategy") or "").strip().upper()
    if db in STRATEGY_MAP:
        return STRATEGY_MAP[db]
    legs = envelope.get("legs") or []
    n = len(legs)
    if n == 4:
        return "iron_condor"
    if n == 2:
        return "credit_vertical" if envelope.get("premium_direction") == "credit" else "debit_vertical"
    if n == 1:
        ot = _norm_option_type((legs[0] or {}).get("option_type") or (legs[0] or {}).get("type"))
        if ot == "call":
            return "long_call"
        if ot == "put":
            return "long_put"
    return None


def build_structure(envelope: Dict[str, Any], strategy: str) -> Optional[StructureSpec]:
    """Build a typed StructureSpec from envelope legs. net_premium is POSITIVE
    (production convention); its meaning follows the strategy. Returns None on a
    malformed leg (missing strike / unresolved side or type) so the caller
    abstains — never a defaulted geometry."""
    legs_out: List[LegSpec] = []
    for leg in envelope.get("legs") or []:
        if not isinstance(leg, dict):
            return None
        action = _norm_action(leg.get("side") or leg.get("action"))
        option_type = _norm_option_type(leg.get("option_type") or leg.get("type"))
        strike = _finite(leg.get("strike"))
        if action is None or option_type is None or strike is None:
            return None
        legs_out.append(
            LegSpec(
                action=action,
                option_type=option_type,
                strike=strike,
                iv=_finite(leg.get("iv")),
                delta=_finite(leg.get("delta")),
            )
        )
    if not legs_out:
        return None
    net_premium = _finite(envelope.get("net_premium"))
    if net_premium is None:
        return None
    contracts = 1  # basis: per structure-contract (§4)
    return StructureSpec(
        strategy=strategy,  # type: ignore[arg-type]
        legs=tuple(legs_out),
        net_premium=abs(net_premium),
        contracts=contracts,
    )


def build_inputs(envelope: Dict[str, Any]) -> DistributionInputs:
    """Build DistributionInputs from the envelope. A missing/typed-unavailable
    spot maps to None → the challenger abstains missing_spot (never a fabricated
    spot). known_at is the provider snapshot ts (deterministic)."""
    return DistributionInputs(
        spot=_finite(envelope.get("spot")),
        dte_days=_finite(envelope.get("dte_days")),
        known_at=str(envelope.get("known_at") or ""),
        risk_free_rate=_finite(envelope.get("risk_free_rate")) or 0.0,
    )


def _model_dict(outcome: Any) -> Dict[str, Any]:
    """Serialize a StrategyEvaluation / Unavailable into a compact typed dict.
    Abstention is EXPLICIT (pop/ev None + abstain_reason), never a 0.5."""
    if isinstance(outcome, Unavailable):
        return {
            "pop": None,
            "ev": None,
            "model": outcome.source,
            "abstain_reason": outcome.reason_code,
            "abstain_detail": outcome.detail[:200],
        }
    if isinstance(outcome, StrategyEvaluation):
        return {
            "pop": outcome.pop,
            "ev": (outcome.expected_value if math.isfinite(outcome.expected_value) else None),
            "model": outcome.model,
            "basis": outcome.basis,
            "max_gain": (outcome.max_gain if math.isfinite(outcome.max_gain) else None),
            "max_loss": (outcome.max_loss if math.isfinite(outcome.max_loss) else None),
            "known_defects": list(outcome.known_defects),
            "abstain_reason": None,
        }
    return {"pop": None, "ev": None, "model": "unknown", "abstain_reason": "non_typed_outcome"}


def _score_baseline(structure: StructureSpec, inputs: DistributionInputs) -> Any:
    strat = structure.strategy
    if strat == "credit_vertical":
        return baseline_credit_vertical(structure, inputs)
    if strat == "debit_vertical":
        return baseline_debit_vertical(structure, inputs)
    if strat == "iron_condor":
        return baseline_condor(structure, inputs, model=_CONDOR_MODEL)
    # No frozen single-leg baseline exists — the challenger owns long single legs.
    return Unavailable("no_baseline_for_strategy", strat, "td_scan_scorer.baseline")


def _score_challenger(structure: StructureSpec, inputs: DistributionInputs) -> Any:
    if structure.strategy in ("long_call", "long_put"):
        return evaluate_single_leg(structure, inputs)
    return challenger_lognormal_evaluate(structure, inputs)


def _gate_counterfactuals(
    envelope: Dict[str, Any], challenger: Dict[str, Any]
) -> Dict[str, Any]:
    """Gate counterfactuals at UNCHANGED production thresholds. Every gate is
    labeled current_actual_gate (what the scanner did) / challenger_would_gate /
    not_evaluable. Only the EV-sign gate is evaluable from the scan-seam envelope
    (execution-cost / round-trip-cost / score-floor / min-edge gates need
    downstream numbers the scan seam does not capture — they are typed
    not_evaluable, never fabricated H9)."""
    ch_ev = challenger.get("ev")
    ch_abstained = challenger.get("abstain_reason") is not None
    out: Dict[str, Any] = {
        "current_actual_gate": {
            "emitted": bool(envelope.get("emitted")),
            "reject_reason": envelope.get("reject_reason"),
            "reject_gate": envelope.get("reject_gate"),
        },
        # Only what the scan-seam envelope can honestly evaluate:
        "ev_positive": (
            "not_evaluable" if ch_abstained or ch_ev is None
            else ("challenger_would_pass" if ch_ev > 0 else "challenger_would_gate")
        ),
        # Downstream production gates need post-EV numbers absent at this seam:
        "execution_cost_gate": "not_evaluable",
        "roundtrip_cost_gate": "not_evaluable",
        "score_floor_gate": "not_evaluable",
        "min_edge_gate": "not_evaluable",
        "note": "scan-seam envelope precedes cost/score/rank gates; cost/score "
                "counterfactuals require downstream numbers not captured here.",
    }
    return out


def score_envelope(envelope: Dict[str, Any]) -> Dict[str, Any]:
    """Score ONE research-candidate envelope. Pure — no I/O, no fabrication.

    Returns a compact typed dict with BOTH models named + abstentions explicit,
    the production as-emitted comparator, gate counterfactuals, and provenance.
    One candidate's failure never affects a sibling (the caller loops)."""
    result: Dict[str, Any] = {
        "candidate_fingerprint": envelope.get("candidate_fingerprint"),
        "symbol": envelope.get("symbol"),
        "strategy": envelope.get("strategy"),
        "challenger_model_version": MODEL_SET_VERSION,
        "basis": "raw",
        "contracts_basis": 1,
        "emitted": bool(envelope.get("emitted")),
        "reject_reason": envelope.get("reject_reason"),
        "reject_gate": envelope.get("reject_gate"),
        "production_ev": _finite(envelope.get("production_ev")),
        "production_pop": _finite(envelope.get("production_pop")),
    }

    strategy = resolve_strategy(envelope)
    if strategy is None:
        abstain = {"pop": None, "ev": None, "model": "unresolved",
                   "abstain_reason": "unmapped_strategy"}
        result["baseline"] = dict(abstain)
        result["challenger"] = dict(abstain)
        result["gate_counterfactuals"] = _gate_counterfactuals(envelope, abstain)
        result["provenance"] = {"model_set_version": MODEL_SET_VERSION,
                                "contract_version": CONTRACT_VERSION,
                                "condor_model": _CONDOR_MODEL,
                                "scored": False, "reason": "unmapped_strategy"}
        return result

    structure = build_structure(envelope, strategy)
    if structure is None:
        abstain = {"pop": None, "ev": None, "model": strategy,
                   "abstain_reason": "malformed_geometry"}
        result["baseline"] = dict(abstain)
        result["challenger"] = dict(abstain)
        result["gate_counterfactuals"] = _gate_counterfactuals(envelope, abstain)
        result["provenance"] = {"model_set_version": MODEL_SET_VERSION,
                                "contract_version": CONTRACT_VERSION,
                                "condor_model": _CONDOR_MODEL,
                                "scored": False, "reason": "malformed_geometry"}
        return result

    inputs = build_inputs(envelope)
    baseline = _model_dict(_score_baseline(structure, inputs))
    challenger = _model_dict(_score_challenger(structure, inputs))

    result["baseline"] = baseline
    result["challenger"] = challenger
    result["gate_counterfactuals"] = _gate_counterfactuals(envelope, challenger)
    result["provenance"] = {
        "model_set_version": MODEL_SET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "condor_model": _CONDOR_MODEL,
        "resolved_strategy": strategy,
        "scored": True,
    }
    return result


def rank_scored_set(
    scored: List[Dict[str, Any]], *, top_n: int
) -> None:
    """Assign current_rank / challenger_rank + top-N membership over the IDENTICAL
    scored set, in place. Ranks are ordinal (1 = best) by EV desc; a candidate
    whose model abstained (ev None) is UNRANKED (rank None) — never sorted as 0.
    rank_delta / topn_delta are challenger - current (positive = challenger ranks
    it worse). This is the only cross-candidate computation; it is pure."""

    def _assign(key_ev: str, rank_field: str, topn_field: str) -> None:
        rankable = [s for s in scored if _finite(s.get(key_ev)) is not None]
        rankable.sort(key=lambda s: (-float(s[key_ev]), str(s.get("candidate_fingerprint") or "")))
        for idx, s in enumerate(rankable, start=1):
            s[rank_field] = idx
            s[topn_field] = idx <= top_n
        for s in scored:
            s.setdefault(rank_field, None)
            s.setdefault(topn_field, None)

    for s in scored:
        s["_current_ev"] = s.get("production_ev")
        ch = s.get("challenger") or {}
        s["_challenger_ev"] = ch.get("ev")

    _assign("_current_ev", "current_rank", "current_topn")
    _assign("_challenger_ev", "challenger_rank", "challenger_topn")

    for s in scored:
        cr, chr_ = s.get("current_rank"), s.get("challenger_rank")
        s["rank_delta"] = (chr_ - cr) if (cr is not None and chr_ is not None) else None
        ct, cht = s.get("current_topn"), s.get("challenger_topn")
        s["topn_delta"] = (int(bool(cht)) - int(bool(ct))) if (ct is not None and cht is not None) else None
        s.pop("_current_ev", None)
        s.pop("_challenger_ev", None)
