"""Calibration apply-move + score recompute (F-A1-3, Option-A 5th application) —
OBSERVE-FIRST.

Selection (SmallAccountCompounder.rank_and_select) sorts on `score`, which the
scanner FREEZES from RAW ev — so calibration applied post-sizing never reaches
selection (the L1 finding). Moving apply_calibration before ranking is only
correct if `score` is RECOMPUTED from the calibrated ev. Flag
CALIBRATION_APPLY_AT_SCORING default OFF: log [APPLY_ORDER_SHADOW] (frozen-raw
top-5 vs calibrated-recomputed top-5 + would_differ), mutate nothing; ARMED →
the apply moves + score recomputes before rank_and_select and the legacy
post-sizing apply is skipped (the _calibration_applied sentinel).

Score composition (recovered WITHOUT touching the scanner): the scanner's
final_score = max(0, clamp(base_ev − cost − regime − greek, 0,100) − soft −
earnings); conviction then MULTIPLIES it (score × w, clamped). With the
pre-conviction snapshot `_scanner_score` + the dumped `unified_score_details`
components, the calibrated score is reconstructable EXACTLY:
    inner_raw = clamp(base − cost − regime − greek, 0, 100)
    soft_earn = inner_raw − scanner_score        # additive scanner penalties
    conv_w    = post_score / scanner_score        # multiplicative conviction
    new_inner = clamp(base×ev_mult − cost − regime − greek, 0, 100)
    new_score = max(0, new_inner − soft_earn) × conv_w
The de-saturation case works: a base clamped at 100 de-saturates below 100 at
ev_mult<1, and new_score tracks it. Fail-safe throughout — never breaks a cycle.
"""
import os
import logging

logger = logging.getLogger(__name__)


def is_apply_at_scoring_enabled() -> bool:
    """Behavioral opt-in (§3): ONLY '=1' arms the move. Default OFF → observe."""
    return (os.environ.get("CALIBRATION_APPLY_AT_SCORING") or "").strip() == "1"


def snapshot_pre_conviction_scores(candidates):
    """Stamp `_scanner_score` BEFORE conviction multiplies `score`, so the
    recompute can separate the additive scanner penalties from the
    multiplicative conviction. Call immediately before
    ConvictionService.adjust_suggestion_scores. Idempotent."""
    for c in candidates or []:
        if isinstance(c, dict) and c.get("_scanner_score") is None:
            c["_scanner_score"] = c.get("score")


def _clamp(v, lo=0.0, hi=100.0):
    return max(lo, min(hi, v))


def recompute_score(candidate, ev_mult):
    """Recomputed unified score with ev scaled by ev_mult (module docstring).
    Fail-safe: returns the current score when inputs are unavailable."""
    try:
        comp = candidate.get("unified_score_details") or {}
        base = float(comp.get("ev") or 0.0)
        cost = float(comp.get("execution_cost") or 0.0)
        regime = float(comp.get("regime_penalty") or 0.0)
        greek = float(comp.get("greek_penalty") or 0.0)
        post_score = float(candidate.get("score") or 0.0)
        scanner_score = candidate.get("_scanner_score")
        scanner_score = float(scanner_score) if scanner_score is not None else post_score
        inner_raw = _clamp(base - cost - regime - greek)
        soft_earn = inner_raw - scanner_score
        conv_w = (post_score / scanner_score) if scanner_score > 0 else 1.0
        new_inner = _clamp(base * float(ev_mult) - cost - regime - greek)
        return max(0.0, new_inner - soft_earn) * conv_w
    except (TypeError, ValueError, ZeroDivisionError):
        return candidate.get("score")


def _cand_identity(c):
    """Structural identity for a candidate (W4, 2026-07-12). Ticker ALONE collides
    on same-ticker multi-structure cycles (the packet-observed QQQ ×4 case), so a
    reorder among them read as would_differ=False. Include strategy + a legs/expiry
    fingerprint + id so a structural swap is visible."""
    fp = c.get("legs_fingerprint")
    if not fp:
        legs = c.get("legs") or (c.get("order_json") or {}).get("legs") or []
        try:
            fp = "|".join(sorted(
                f"{l.get('type', l.get('right', ''))}{l.get('strike', '')}"
                f"{l.get('expiry', '')}{l.get('action', l.get('side', ''))}"
                for l in legs)) or None
        except (TypeError, AttributeError):
            fp = None
    return (c.get("ticker"), c.get("strategy"),
            c.get("suggestion_id") or c.get("id"), fp)


def _top_n(candidates, score_of, n=5):
    """Ranked full-tuple identities (ticker, strategy, id, fp, score) — the score
    is carried for magnitude but is NOT part of the ordering-comparison key (frozen
    vs calibrated scores differ by construction; _order_key drops it)."""
    ranked = sorted(candidates, key=lambda c: -(score_of(c) if score_of(c) is not None else -1e9))
    out = []
    for c in ranked[:n]:
        s = score_of(c)
        out.append(_cand_identity(c) + (round(float(s), 4) if s is not None else None,))
    return out


def _order_key(ranked_tuples):
    """The structural ordering, score dropped — a same-ticker STRUCTURE swap
    changes this even though the ticker list is unchanged (the W4 fix)."""
    return [t[:-1] for t in ranked_tuples]


def apply_calibration_at_scoring(candidates, cal_adj_cache, regime, *,
                                 apply_calibration, classify_dte, cal_enabled):
    """ARMED (flag on): calibrate ev/pop + recompute score IN PLACE + set the
    `_calibration_applied` sentinel + stamp the TRUE raw (`_ev_raw_true`/
    `_pop_raw_true`). OBSERVE (off): compute the calibrated ordering on the side
    + log [APPLY_ORDER_SHADOW], mutate NOTHING. Fail-safe per candidate; a
    failure of the whole seam must never break the cycle (caller wraps too)."""
    # Heartbeat FIRST — fires every scan even when this seam no-ops (empty cache /
    # 0 candidates / disabled), so [APPLY_ORDER_SHADOW] silence is diagnosable.
    try:
        from packages.quantum.services.risk_basis_shadow import log_shadow_heartbeat
        log_shadow_heartbeat("APPLY_ORDER", len(candidates or []),
                             armed=is_apply_at_scoring_enabled(),
                             cache=bool(cal_adj_cache), enabled=bool(cal_enabled))
    except Exception:
        pass
    if not cal_enabled or not cal_adj_cache or not candidates:
        return candidates
    armed = is_apply_at_scoring_enabled()
    recomputed = {}
    for c in candidates:
        try:
            raw_ev = float(c.get("ev") or 0.0)
            raw_pop = c.get("probability_of_profit")
            dte_bucket = classify_dte({"dte_at_entry": c.get("dte") or 30})
            cal_ev, cal_pop = apply_calibration(
                raw_ev, raw_pop, c.get("strategy") or "", regime or "",
                cal_adj_cache, dte_bucket=dte_bucket)
            ev_mult = (cal_ev / raw_ev) if raw_ev else 1.0
            new_score = recompute_score(c, ev_mult)
            recomputed[id(c)] = new_score
            if armed:
                c["_ev_raw_true"] = raw_ev
                c["_pop_raw_true"] = raw_pop
                c["ev"] = cal_ev
                c["probability_of_profit"] = cal_pop
                c["score"] = new_score
                c["_calibration_applied"] = True
        except Exception as e:
            logger.warning("[APPLY_ORDER] candidate calibration failed (%s): %s",
                           (c.get("ticker") if isinstance(c, dict) else "?"), e)
            recomputed[id(c)] = c.get("score") if isinstance(c, dict) else None
    if not armed:
        try:
            frozen = _top_n(candidates, lambda c: c.get("score"))
            cal = _top_n(candidates, lambda c: recomputed.get(id(c)))
            # W4: compare STRUCTURAL ordering (ticker+strategy+id+fp), not the
            # ticker-only list — a same-ticker structure swap now flips would_differ.
            would_differ = _order_key(frozen) != _order_key(cal)
            logger.info(
                "[APPLY_ORDER_SHADOW] n=%d frozen_top5=%s calibrated_top5=%s would_differ=%s",
                len(candidates), frozen, cal, would_differ)
        except Exception as e:
            logger.warning("[APPLY_ORDER_SHADOW] log failed: %s", e)
    return candidates
