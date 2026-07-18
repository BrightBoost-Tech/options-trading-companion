"""Observe-only cost-reconciliation artifact for candidate dispositions.

Multi-basis cost model phase-2 — CONSUMER #1 (Lane 2C). Assembles the typed
multi-basis cost view for ONE candidate at the disposition-write seam and
returns it as a plain, JSON-serializable dict destined for the
``candidate_terminal_dispositions.detail`` jsonb (``detail.cost_reconciliation``).

OBSERVE-ONLY / NON-DECISIONAL. This module:
  - is imported by the OBSERVE-ONLY disposition recorder only
    (``packages/quantum/services/candidate_disposition.py``);
  - writes nothing itself (pure dict/dataclass out);
  - never mutates the candidate it reads;
  - is the ONE module the ``cost_basis`` import-lock allowlists
    (``test_cost_basis_import_lock.py``) — every gate / ranker / scanner /
    executor stays locked out of ``cost_basis``.
Nothing in the decision path reads ``candidate_terminal_dispositions`` (verified
zero code readers repo-wide, 2026-07-18), so this artifact can never feed a
rank or a gate. The existing cost formulas remain the sole decision authority;
this is a side-by-side reconciliation of their divergent bases.

BASES RECONSTRUCTABLE AT THE DISPOSITION SEAM (from the candidate dict alone —
no network, no DB, no mutation):

  - ``ranker_model``           canonical_ranker fees (round-trip, 2 sides) +
                               slippage proxy, TOTAL usd — the number the
                               ranker subtracts from EV. Always attempted
                               (needs only the candidate mapping).
  - ``stage_executable_cross`` the executable round-trip cross
                               ``(ask - bid) * 100 * contracts``, entry + exit,
                               via the REAL
                               ``exit_mark_corroboration.executable_roundtrip_cost``
                               — TOTAL + per-structure-contract + per-leg.
                               Present when the candidate legs carry two-sided
                               quotes; typed UNAVAILABLE otherwise.
  - ``ev_basis`` flag          calibrated vs raw EV, read from the candidate's
                               ``_ev_raw_true`` / ``_calibration_applied``
                               markers.

BASES THAT LIVE UPSTREAM of this seam (scanner drag/unified, both
TransactionCostModels, the realized close) are typed UNAVAILABLE with an
explicit reason: their inputs (``combo_width_share``, a live execution ticket,
a broker fill) are not carried on the disposition candidate. A missing basis
is TYPED, never zero (H9 both ends).

SHARED COMPONENTS — the bases are alternative MEASUREMENTS of the same round
trip; COMPARE them, never SUM them. The ``shared_components`` block in the
artifact documents the overlaps so a reader cannot double-count (e.g. the
ranker slippage proxy and the executable cross are two estimates of ONE
slippage, not two costs; scanner commission is one-side while ranker fees are
round-trip).

FAIL-SOFT: any exception in assembly returns ``None`` (the writer then simply
omits the artifact — a disposition row is never lost to a cost-artifact
failure). No exception escapes ``build_cost_reconciliation``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# Version of THIS artifact envelope (distinct from the cost_basis model
# version it wraps). Bump when the artifact's own shape changes.
ARTIFACT_VERSION = "cost-recon-artifact/1.0"

# Canonical basis keys, matching cost_basis.reconcile_cost_bases' normalized
# keys. Every key gets a typed availability status in the artifact, so an
# absent basis is visible and reasoned — never silently dropped.
CANONICAL_BASES: Tuple[str, ...] = (
    "scanner_estimate",
    "scanner_unified_final",
    "ranker_model",
    "stage_executable_cross",
    "tcm",
    "tcm_legacy",
    "realized",
)

# Why the upstream-only bases cannot be reconstructed from a disposition
# candidate. Typed reasons, not zeros.
_SEAM_UNAVAILABLE_REASON: Dict[str, str] = {
    "scanner_estimate": "scanner_drag_inputs_not_carried_to_disposition_seam",
    "scanner_unified_final": "scanner_scoring_not_rerun_at_disposition_seam",
    "tcm": "no_execution_ticket_at_disposition_seam",
    "tcm_legacy": "no_execution_ticket_at_disposition_seam",
    "realized": "no_broker_fill_pre_execution",
}

# Documentation of overlapping components so a reader never sums two bases
# that measure the same thing. Text only — carries no numbers, no thresholds.
SHARED_COMPONENTS: Dict[str, str] = {
    "note": (
        "bases are alternative measurements of the SAME round trip — COMPARE, "
        "never SUM"
    ),
    "ranker_model.fees_plus_slippage": (
        "round_trip_fees (0.65 * contracts * legs * 2 sides) + expected_slippage;"
        " the slippage term is a PROXY (tcm/sizing/5%-of-EV floor), NOT the "
        "executable cross"
    ),
    "stage_executable_cross.round_trip_total": (
        "executable (ask-bid)*100*contracts over the full round trip — a "
        "DIFFERENT slippage basis than ranker expected_slippage; the "
        "slippage_executable_cross_vs_ranker_proxy delta COMPARES them"
    ),
    "commission_double_count_guard": (
        "scanner_estimate embeds commission ONE side only; ranker fees are "
        "round-trip (x2). Never add scanner + ranker fees"
    ),
    "quantity": (
        "TOTAL = per_structure_contract * contracts — the SAME cost at two "
        "scales (the quantity_scaling delta surfaces the legacy-gate unit pun "
        "at qty>1), not additive"
    ),
}


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _resolve_quantity(
    cand: Mapping[str, Any], quantity: Optional[float]
) -> Optional[float]:
    """Contract count for this candidate, honestly None when unknown.

    Never fabricates a 1-lot at the reconcile level: an unknown quantity keeps
    the TOTAL/per-contract conversions typed UNAVAILABLE rather than inventing
    a scale. (Individual extractors still apply their OWN production default
    where production would — e.g. the ranker fee formula.)"""
    q = _coerce_float(quantity)
    if q is not None:
        return abs(q)
    for parent_key, child_key in (
        ("sizing_metadata", "contracts"),
        ("sizing", "contracts"),
    ):
        parent = cand.get(parent_key)
        if isinstance(parent, Mapping):
            q = _coerce_float(parent.get(child_key))
            if q is not None:
                return abs(q)
    q = _coerce_float(cand.get("contracts"))
    if q is not None:
        return abs(q)
    return None


def _uniform_leg_quantity(
    legs: List[Mapping[str, Any]]
) -> Optional[float]:
    """The single per-leg contract count when every leg shares one (or None
    when legs disagree / are empty). Used only to detect the scanner's 1-lot
    placeholder so it can be lifted to the structure size — a genuine ratio /
    multi-lot structure (legs disagreeing) is preserved untouched."""
    seen = {_coerce_float(leg.get("quantity")) for leg in legs}
    if len(seen) == 1:
        return next(iter(seen))
    return None


def _stage_legs(
    legs: List[Mapping[str, Any]], stage_qty: Optional[float]
) -> List[Dict[str, Any]]:
    """Copy the candidate legs, lifting ONLY placeholder (missing / 1-lot)
    per-leg quantities to ``stage_qty`` so the executable round-trip TOTAL
    reflects the intended trade size — the structure genuinely trades at
    ``stage_qty`` uniform lots; the scanner's ``quantity: 1`` is a placeholder.
    A real non-1 per-leg quantity (ratio structure) is preserved verbatim.
    Never mutates the input legs."""
    out: List[Dict[str, Any]] = []
    for leg in legs:
        d = dict(leg)
        lq = _coerce_float(d.get("quantity"))
        if stage_qty is not None and (lq is None or lq == 1.0):
            d["quantity"] = stage_qty
        out.append(d)
    return out


def _leg_quotes_from_legs(
    legs: List[Mapping[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """Build the OCC-keyed quote map ``executable_roundtrip_cost`` expects from
    the candidate legs' OWN bid/ask (occ = occ_symbol or symbol, matching
    ``exit_mark_corroboration._leg_occ``). A leg missing bid/ask contributes a
    one-sided quote — the extractor then types the round trip UNAVAILABLE
    (all-or-nothing), never a fabricated partial cross."""
    quotes: Dict[str, Dict[str, Any]] = {}
    for leg in legs:
        if not isinstance(leg, Mapping):
            continue
        occ = leg.get("occ_symbol") or leg.get("symbol")
        if not occ:
            continue
        quotes[str(occ)] = {
            "bid": leg.get("bid"),
            "ask": leg.get("ask"),
            "last": leg.get("last") if leg.get("last") is not None
            else leg.get("mid"),
        }
    return quotes


def _ev_bases(cand: Mapping[str, Any]) -> Tuple[
    Optional[float], Optional[float], Optional[str]
]:
    """Return (raw_ev, calibrated_ev, ranker_ev_basis_label).

    When the apply-at-scoring move armed, the candidate carries the TRUE raw in
    ``_ev_raw_true`` and its ``ev`` is already calibrated. Absent that marker
    (and any ``_calibration_applied`` sentinel), ``ev`` is the raw EV and no
    calibrated basis is known."""
    ev = _coerce_float(cand.get("ev"))
    raw = _coerce_float(cand.get("_ev_raw_true"))
    if raw is None:
        raw = ev
    calibrated_present = (
        "_ev_raw_true" in cand or bool(cand.get("_calibration_applied"))
    )
    calibrated = ev if calibrated_present else None
    if calibrated is not None:
        label = "calibrated"
    elif raw is not None:
        label = "raw"
    else:
        label = None
    return raw, calibrated, label


def build_cost_reconciliation(
    cand: Optional[Mapping[str, Any]],
    *,
    quantity: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Assemble the observe-only cost-reconciliation artifact for ``cand``.

    Returns a plain JSON-serializable dict for ``detail.cost_reconciliation``,
    or ``None`` when nothing could be reconstructed or on ANY failure (the
    caller then omits the artifact — the disposition write is never blocked).
    Never mutates ``cand``; never touches the network or DB.
    """
    try:
        if not isinstance(cand, Mapping):
            return None

        # Lazy import keeps this module (and the disposition writer that imports
        # it) free of a module-level cost_basis dependency, and cost_basis'
        # own production imports stay lazy inside its extractors.
        from packages.quantum.analytics import cost_basis as cb

        legs_raw = cand.get("legs") or []
        legs = [leg for leg in legs_raw if isinstance(leg, Mapping)]
        qty = _resolve_quantity(cand, quantity)
        raw_ev, calibrated_ev, ev_basis_label = _ev_bases(cand)

        built: Dict[str, Any] = {}

        # ── ranker_model — fees(round-trip) + slippage proxy ────────────────
        # A disposition candidate carries legs but no order_json (built later,
        # at persist). Surface the candidate's OWN legs as order_json so the
        # ranker fee basis is the REAL per-leg-per-structure-contract round trip
        # (leg_count from the structure), not the legacy single-leg fallback;
        # and thread the resolved structure size as sizing_metadata.contracts.
        # Both derive purely from the candidate — extract_ranker_costs deep-
        # copies, so cand is never mutated.
        ranker_view = dict(cand)
        if legs and not ranker_view.get("order_json"):
            ranker_view["order_json"] = {"legs": [dict(leg) for leg in legs]}
        if qty is not None:
            _sm = dict(ranker_view.get("sizing_metadata") or {})
            if not _sm.get("contracts"):
                _sm["contracts"] = qty
                ranker_view["sizing_metadata"] = _sm
        ranker_bd = None
        try:
            ranker_bd = cb.extract_ranker_costs(
                ranker_view, ev_basis=ev_basis_label, quantity=qty,
            )
        except Exception as exc:  # never let one basis sink the artifact
            logger.debug(
                "[COST_RECON] ranker basis skipped: %s", exc,
            )
        if ranker_bd is not None:
            built["ranker_model"] = ranker_bd

        # ── stage_executable_cross — the executable round-trip cross ────────
        # The structure trades at `stage_qty` uniform lots. When unsized (qty
        # unknown), fall back to the legs' own uniform lot (the 1-lot
        # placeholder) so the TOTAL and per-contract stay a consistent, honest
        # 1-lot basis rather than a mislabeled scale.
        stage_bd = None
        # Dynamic unavailability reasons for the two reconstructable bases (the
        # upstream-only bases use the static _SEAM_UNAVAILABLE_REASON map).
        not_built_reason: Dict[str, str] = {}
        if not legs:
            not_built_reason["stage_executable_cross"] = "no_candidate_legs"
        else:
            if qty is not None:
                stage_qty: Optional[float] = qty
            else:
                _uq = _uniform_leg_quantity(legs)
                stage_qty = _uq if _uq else 1.0
            try:
                stage_bd = cb.extract_stage_executable_cross(
                    legs=_stage_legs(legs, stage_qty),
                    leg_quotes=_leg_quotes_from_legs(legs),
                    quantity=stage_qty,
                )
            except Exception as exc:
                logger.debug(
                    "[COST_RECON] stage basis skipped: %s", exc,
                )
                not_built_reason["stage_executable_cross"] = "stage_extract_error"
        if stage_bd is not None:
            built["stage_executable_cross"] = stage_bd
        if ranker_bd is None:
            not_built_reason["ranker_model"] = "ranker_extract_error"

        # Nothing reconstructable -> no artifact (rather than an all-empty one).
        if not built:
            return None

        recon = cb.reconcile_cost_bases(
            quantity=qty,
            gross_ev=raw_ev,
            calibrated_ev=calibrated_ev,
            ranker=built.get("ranker_model"),
            stage=built.get("stage_executable_cross"),
        )
        artifact: Dict[str, Any] = dict(recon.as_dict())

        # Typed availability for EVERY canonical basis — absent bases are
        # reasoned, never silently dropped (H9).
        bases_status: Dict[str, Dict[str, Any]] = {}
        for name in CANONICAL_BASES:
            bd = built.get(name)
            if bd is not None:
                primary = bd.primary_component
                bases_status[name] = {
                    "available": bool(primary.available),
                    "primary": bd.primary,
                    "reason": (
                        None if primary.available
                        else primary.unavailable_reason
                    ),
                }
            else:
                bases_status[name] = {
                    "available": False,
                    "primary": None,
                    "reason": (
                        not_built_reason.get(name)
                        or _SEAM_UNAVAILABLE_REASON.get(
                            name, "not_reconstructed_at_disposition_seam"
                        )
                    ),
                }

        artifact["observe_only"] = True
        artifact["decisional"] = False
        artifact["artifact_version"] = ARTIFACT_VERSION
        artifact["bases_status"] = bases_status
        artifact["shared_components"] = dict(SHARED_COMPONENTS)
        return artifact
    except Exception as exc:  # absolute fail-soft
        logger.debug(
            "[COST_RECON] artifact assembly failed (non-fatal, omitted): %s",
            exc,
        )
        return None
