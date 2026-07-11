"""Risk-basis shadow (P0-B book-scaling, 2026-07-11) — OBSERVE-ONLY.

The risk stack costs the open book / a candidate on a PREMIUM / null-blind
basis: the allocator and RiskBudgetEngine see the open book as ~$0 (no
cost_basis persisted) and the utilization gate costs a candidate at premium,
not defined-risk max loss. The HONEST basis is max_loss_total (now persisted on
paper_positions, reused from trade_suggestions.max_loss_total).

This module computes BOTH bases at each consumer and logs [RISK_BASIS_SHADOW];
the honest basis becomes DECISIVE only when RISK_BASIS_MAX_LOSS_ENABLED=1
(default OFF — decisions stay on the current basis, byte-identical). Third
application of the Option-A observe→enforce pattern (after #1034 exit-mark
corroboration and #1116 mark-write corroboration).

⚠ UNITS: max_loss_total is a POSITION-LEVEL TOTAL (already × contracts × 100).
Never multiply it by qty again (the RBE double-scaling trap).
"""
import os
import logging

logger = logging.getLogger(__name__)


def is_max_loss_basis_enabled() -> bool:
    """Behavioral opt-in (§3): ONLY '=1' makes the honest max_loss basis
    DECISIVE. Absent / empty / any other value → current basis (observe-only),
    so an env regression fails SAFE to today's behavior."""
    return (os.environ.get("RISK_BASIS_MAX_LOSS_ENABLED") or "").strip() == "1"


def log_risk_basis_shadow(consumer, current_usd, honest_usd, *,
                          context=None, threshold_usd=None):
    """One [RISK_BASIS_SHADOW] line per consumer decision: both bases + whether
    the honest basis WOULD flip the decision against a threshold. honest_usd
    None → NULL-basis (legacy / unpopulated max_loss_total), logged as such with
    no divergence claim. Observe-only; NEVER raises."""
    try:
        cur = float(current_usd or 0.0)
        if honest_usd is None:
            logger.info(
                "[RISK_BASIS_SHADOW] consumer=%s current=%.2f honest=NULL "
                "basis=null_legacy context=%s", consumer, cur, context or {})
            return
        hon = float(honest_usd)
        would_flip = None
        if threshold_usd is not None:
            t = float(threshold_usd)
            # the decision flips iff the two bases fall on opposite sides of t
            would_flip = (cur <= t < hon) or (hon <= t < cur)
        logger.info(
            "[RISK_BASIS_SHADOW] consumer=%s current=%.2f honest=%.2f delta=%.2f "
            "would_flip=%s context=%s",
            consumer, cur, hon, hon - cur, would_flip, context or {})
    except Exception as e:  # observe-only must never break a decision
        logger.warning("[RISK_BASIS_SHADOW] log failed consumer=%s: %s", consumer, e)


def choose_basis(current_usd, honest_usd):
    """Return the value the DECISION should use: the honest basis when the flag
    is ARMED and honest is a usable positive number, else the current basis.
    Flag OFF → returns current_usd unchanged (byte-identical)."""
    if is_max_loss_basis_enabled():
        try:
            if honest_usd is not None and float(honest_usd) > 0:
                return float(honest_usd)
        except (TypeError, ValueError):
            pass
    return current_usd


def honest_position_risk(pos):
    """The honest per-position risk = max_loss_total, a POSITION-LEVEL TOTAL.
    Returns None when absent. ⚠ NEVER multiplies by qty — max_loss_total is
    already × contracts × 100; the RBE legacy path keys max_loss PER-CONTRACT
    and × qty, so re-scaling a _total would double-count. This helper IS the
    units-trap guard (unit-tested: a qty-4 position returns its total as-is)."""
    ml = pos.get("max_loss_total") if isinstance(pos, dict) else getattr(pos, "max_loss_total", None)
    try:
        return abs(float(ml)) if ml is not None else None
    except (TypeError, ValueError):
        return None


def compute_position_risk_basis(entry_premium_abs, qty,
                                suggestion_max_loss_total, suggestion_contracts):
    """(cost_basis_total, max_loss_total) for a newly-created position — WRITE
    side. cost_basis_total = |premium| × 100 × |qty| (premium basis, always
    available). max_loss_total = the suggestion's defined-risk TOTAL scaled to
    ACTUAL filled contracts; None (H9) when the suggestion carries no
    max_loss_total or an unusable contract count — never fabricated."""
    q = abs(int(qty or 0))
    try:
        cb = round(abs(float(entry_premium_abs or 0.0)) * 100.0 * q, 2)
        cost_basis_total = cb if cb > 0 else None
    except (TypeError, ValueError):
        cost_basis_total = None
    max_loss_total = None
    try:
        if suggestion_max_loss_total is not None:
            sc = int(suggestion_contracts or 0)
            if sc > 0 and q > 0:
                max_loss_total = round(float(suggestion_max_loss_total) * q / sc, 2)
    except (TypeError, ValueError):
        max_loss_total = None
    return cost_basis_total, max_loss_total
