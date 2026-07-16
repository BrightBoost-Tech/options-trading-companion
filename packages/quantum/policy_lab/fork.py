"""
Pipeline fork — creates cohort-specific suggestions from the shared opportunity set.

After the workflow orchestrator generates scored suggestions for the default
cohort, this module clones them for each additional Policy Lab cohort with
adjusted sizing and filtering per PolicyConfig.
"""

import logging
import math
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Any

from packages.quantum.policy_lab.config import (
    PolicyConfig,
    load_cohort_configs,
    is_policy_lab_enabled,
)
from packages.quantum.policy_lab.champion import get_current_champion
from packages.quantum.policy_lab.capital import normalize_capital

logger = logging.getLogger(__name__)


def fork_suggestions_for_cohorts(
    user_id: str,
    supabase,
    source_window: str = "midday_entry",
) -> Dict[str, Any]:
    """
    After the orchestrator inserts suggestions for the default cohort,
    create cohort-specific variants for each additional Policy Lab cohort.

    The default cohort's suggestions (cohort_name IS NULL) serve as the
    source. For each other active cohort, we clone qualifying suggestions
    with adjusted quantity and tag them with cohort_name.

    Returns summary of what was created.
    """
    if not is_policy_lab_enabled():
        return {"status": "disabled"}

    configs = load_cohort_configs(user_id, supabase)
    if not configs:
        return {"status": "no_cohorts"}

    # Fetch today's untagged suggestions (the default cohort's output)
    today_str = date.today().isoformat()
    source_res = supabase.table("trade_suggestions") \
        .select("*") \
        .eq("user_id", user_id) \
        .eq("window", source_window) \
        .eq("cycle_date", today_str) \
        .is_("cohort_name", "null") \
        .in_("status", ["pending", "staged"]) \
        .order("risk_adjusted_ev", desc=True) \
        .order("ev", desc=True) \
        .execute()

    source_suggestions = source_res.data or []

    # ── E19-2 (2026-07-13): PRE-REJECTION FORK SOURCE ────────────────────
    # Candidates that pass raw eligibility but die at the CALIBRATED edge
    # floor (workflow_orchestrator: raev <= -999 → status NOT_EXECUTABLE,
    # blocked_reason='edge_below_minimum') are exactly the divergence cases
    # the raw-EV shadow experiment exists to observe — and the pending/staged
    # filter above excludes them (the SOFI class: ev_raw clears the edge, the
    # ×0.5-calibrated ev does not; 2026-07-13 live exhibit). Fetch them as a
    # SECOND source set for shadow cohorts only.
    #
    # Boundary discipline: ONLY 'edge_below_minimum' — a row with that reason
    # is fully formed (legs, priced quotes, computed EV) and failed nothing
    # but the calibrated floor. 'marketdata_quality_gate' (stale/dark/
    # unpriceable) and every scanner-level rejection (malformed, missing
    # legs, capital invalidity — those never become suggestion rows) are
    # NEVER resurrected. Keyed on the SAME revert lever as the raw-EV basis
    # (SHADOW_RAW_EV_ENABLED): lever explicitly off → this source is off.
    # A fetch failure is TYPED into the return — never a silent empty.
    # Fork-result contract accumulators (adversarial-review Blocker 1): every
    # experimental-path failure INCREMENTS errors and lands in error_details as
    # a typed entry — the handler folds `errors` into the job's counts.errors,
    # so a broken experiment can never ride a green scheduled job. The champion
    # path's own success/failure is reported separately (champion_* fields).
    fork_errors: List[Dict[str, Any]] = []
    prerej_counts: Dict[str, int] = {
        "source": 0, "eligible": 0, "created": 0, "existing": 0,
        # terminal dispositions (exactly one per source×challenger attempt):
        "accepted": 0, "refused": 0, "clone_failed": 0,
        "identity_mismatch": 0, "accepted_verdict_failed": 0,
        "cohort_binding_unavailable": 0, "cohort_identity_missing": 0,
        "cohort_portfolio_missing": 0, "cohort_capital_invalid": 0,
        # secondary / observability (NOT terminal dispositions):
        "reject_verdict_write_failed": 0, "repaired": 0,
        # honest verdict counters (B22):
        "accepted_verdicts": 0, "rejected_verdicts": 0,
        # coverage:
        "source_cohort_attempts": 0, "expected_source_cohort_attempts": 0,
    }

    prerejection_sources: List[Dict] = []
    if _is_shadow_raw_ev_enabled():
        try:
            prerej_res = supabase.table("trade_suggestions") \
                .select("*") \
                .eq("user_id", user_id) \
                .eq("window", source_window) \
                .eq("cycle_date", today_str) \
                .is_("cohort_name", "null") \
                .eq("status", "NOT_EXECUTABLE") \
                .eq("blocked_reason", "edge_below_minimum") \
                .order("ev_raw", desc=True) \
                .execute()
            prerejection_sources = prerej_res.data or []
            prerej_counts["source"] = len(prerejection_sources)
        except Exception as pr_err:
            fork_errors.append({
                "stage": "prerejection_source_select",
                "error_class": type(pr_err).__name__,
                "error": str(pr_err)[:200],
            })
            logger.warning(
                f"policy_lab_fork: pre-rejection source fetch failed (typed, "
                f"champion path unaffected): {type(pr_err).__name__}"
            )

    if not source_suggestions and not prerejection_sources:
        logger.info(f"policy_lab_fork: no source suggestions for user={user_id}")
        return _fork_result(
            "no_source_suggestions", {}, prerej_counts, fork_errors)

    # Tag source suggestions with the currently-promoted champion cohort.
    #
    # #62a-D1 (closed 2026-05-18): this site used to hardcode
    # `cohort_name = "aggressive"`. The evaluator at
    # `policy_lab/evaluator.py:537-545` writes `promoted_at` on the
    # winning cohort when its 7 promotion gates pass; nothing read
    # `promoted_at` for routing. That integration seam is now closed
    # via `get_current_champion` (see policy_lab/champion.py).
    # Defensive fallback in the helper: if no cohort is promoted
    # (transition window or fresh DB), returns "aggressive" — preserves
    # pre-PR behavior so deploy-vs-migration ordering doesn't matter.
    # See `docs/loud_error_doctrine.md` H12 — Parallel architectures
    # without integration.
    champion_name = get_current_champion(user_id, supabase)

    champion_tagged = 0
    for s in source_suggestions:
        try:
            supabase.table("trade_suggestions").update({
                "cohort_name": champion_name,
            }).eq("id", s["id"]).execute()
            champion_tagged += 1
        except Exception as tag_err:
            fork_errors.append({
                "stage": "champion_tag_failed",
                "source_suggestion_id": s.get("id"),
                "error_class": type(tag_err).__name__,
                "error": str(tag_err)[:200],
            })

    # Get cohort portfolio mapping and cohort IDs. B16: an ids-fetch
    # failure is TYPED (never an authoritative-empty {}) — downstream every
    # prerejection attempt records cohort_identity_missing and the job goes
    # partial; champion tagging above is already complete and unaffected.
    cohort_portfolios = _get_cohort_portfolios(user_id, supabase)
    try:
        cohort_ids = _get_cohort_ids(user_id, supabase)
    except Exception as ci_err:
        cohort_ids = {}
        fork_errors.append({
            "stage": "cohort_ids_fetch_failed",
            "error_class": type(ci_err).__name__,
            "error": str(ci_err)[:200],
        })

    # ── E19-2A: PRE-REJECTION RAW-ELIGIBILITY COVERAGE (B19 + B26) ───────
    # Runs HERE — after champion resolution + tagging, and BEFORE any legacy
    # normal-challenger portfolio/open-position query — so the B19 per-pair
    # accounting and count invariants are always computed and can never be
    # erased by a legacy state-read fault below. Separate from and never
    # perturbing the champion-visible normal-clone loop.
    _run_prerejection_coverage(
        supabase, user_id, prerejection_sources, champion_name,
        configs, prerej_counts, fork_errors)
    logger.info(
        f"policy_lab_fork: user={user_id[:8]} prerejection={prerej_counts}")

    created = {}
    for cohort_name, config in configs.items():
        if cohort_name == champion_name:
            created[cohort_name] = len(source_suggestions)
            continue  # Already tagged above (source suggestions ARE the champion's output)

        portfolio_id = cohort_portfolios.get(cohort_name)
        cohort_id = cohort_ids.get(cohort_name)
        if not portfolio_id:
            logger.warning(f"policy_lab_fork: no portfolio for cohort={cohort_name}")
            continue

        # B26 exception containment: a legacy state-read fault (portfolio /
        # open-position) must NOT raise out of the fork and erase the
        # already-computed B19 result. Contain it per challenger, type it,
        # and continue. This changes NOTHING about successful-path normal-clone
        # behavior — it only adds isolation of the read exceptions.
        try:
            # Get the cohort's actual capital. Missing/zero/non-finite
            # net_liq is never reinterpreted as cash or a nominal $100,000.
            port_res = supabase.table("paper_portfolios") \
                .select("cash_balance, net_liq") \
                .eq("id", portfolio_id) \
                .single() \
                .execute()
            portfolio = port_res.data
            deployable, capital_reason = normalize_capital(portfolio)
            if capital_reason is not None or deployable is None:
                raise RuntimeError(
                    f"legacy_normal_clone_capital_invalid:{capital_reason}"
                )

            # Count existing open positions for this cohort's portfolio
            open_pos_res = supabase.table("paper_positions") \
                .select("id", count="exact") \
                .eq("portfolio_id", portfolio_id) \
                .eq("status", "open") \
                .execute()
            open_count = open_pos_res.count or 0
        except Exception as _state_err:
            fork_errors.append({
                "stage": "legacy_normal_clone_state_failed",
                "cohort": cohort_name,
                "error_class": type(_state_err).__name__,
                "error": str(_state_err)[:200],
            })
            continue

        # F-A9-5: ONE canonical routing evaluation feeds BOTH the clone filter
        # and the decision log — the logger never re-derives from ev/score.
        cohort_decisions = _evaluate_cohort_policy(
            source_suggestions, config, open_count,
        )
        filtered = [d.suggestion for d in cohort_decisions if d.accepted]

        # Decision logging: log every (cohort, suggestion) decision
        _log_cohort_decisions(
            supabase, user_id, cohort_name, cohort_id, cohort_decisions,
        )

        # Clone with adjusted sizing
        cloned = 0
        for s in filtered:
            clone = None
            try:
                clone = _clone_suggestion_for_cohort(
                    s, cohort_name, config, deployable,
                )
                if clone:
                    supabase.table("trade_suggestions").insert(clone).execute()
                    cloned += 1
            except Exception as e:
                fork_errors.append({
                    "stage": "legacy_normal_clone_insert_failed",
                    "cohort": cohort_name,
                    "source_suggestion_id": s.get("id"),
                    "ticker": s.get("ticker") or s.get("symbol"),
                    "error_class": type(e).__name__,
                    "error": str(e)[:200],
                })
                logger.warning(
                    f"policy_lab_fork_clone_error: cohort={cohort_name} "
                    f"ticker={s.get('ticker')} error={e}"
                )
                # Loud-Error Doctrine v1.0 anti-pattern 4 fix (#97 Phase 1).
                # Surface the swallowed exception so the underlying root
                # cause (missing NOT NULL / unique constraint / schema
                # drift) becomes diagnosable from `risk_alerts` metadata.
                # Observability-only — no behavioral change to the loop.
                try:
                    from packages.quantum.observability.alerts import (
                        alert, _get_admin_supabase,
                    )
                    alert(
                        _get_admin_supabase(),
                        alert_type="cohort_clone_insert_failed",
                        severity="critical",
                        message=(
                            f"Cohort {cohort_name} clone insert failed: "
                            f"{type(e).__name__}"
                        ),
                        user_id=user_id,
                        metadata={
                            "cohort_name": cohort_name,
                            "source_suggestion_id": s.get("id"),
                            "ticker": s.get("ticker") or s.get("symbol"),
                            "strategy": s.get("strategy"),
                            "error_class": type(e).__name__,
                            "error_message": str(e)[:500],
                            "clone_keys": (
                                sorted(list(clone.keys()))
                                if isinstance(clone, dict)
                                else None
                            ),
                            "operator_action_required": (
                                "Inspect error_class + error_message to "
                                "determine root cause class (NOT NULL "
                                "violation / unique constraint / schema "
                                "drift). Fix to follow in PR addressing "
                                "#97."
                            ),
                        },
                    )
                except Exception:
                    # Alert-write failure → fall through. Per doctrine
                    # Valid 5 (alert-write recursion prevention).
                    logger.exception("cohort_clone_alert_write_failed")

        created[cohort_name] = cloned
        logger.info(
            f"policy_lab_fork: cohort={cohort_name} "
            f"source={len(source_suggestions)} filtered={len(filtered)} cloned={cloned}"
        )

    # Log decisions for the champion cohort too (all accepted by default —
    # source suggestions ARE the champion's output, so every one is accepted).
    champion_cohort_id = cohort_ids.get(champion_name)
    if champion_cohort_id and source_suggestions:
        # Champion: every source suggestion is accepted (its own output) — no
        # cohort filter, no routing re-derivation (F-A9-5).
        _log_cohort_decisions(
            supabase, user_id, champion_name, champion_cohort_id,
            _champion_accept_all(source_suggestions),
        )

    # (E19-2A coverage already ran ABOVE, before the legacy loop — B26.)
    return _fork_result(
        "ok", created, prerej_counts, fork_errors,
        champion_tagged=champion_tagged,
    )


def _run_prerejection_coverage(
    supabase,
    user_id: str,
    prerejection_sources: List[Dict],
    champion_name: str,
    configs: Dict[str, Any],
    counts: Dict[str, int],
    errors: List[Dict[str, Any]],
) -> None:
    """B19 complete-coverage loop: every source × challenger pair increments
    source_cohort_attempts BEFORE any binding/portfolio/capital guard and
    terminates in exactly one bucket. One strict binding read (raises → every
    pair records cohort_binding_unavailable). Capital fails closed (no
    $100,000 fabrication). Runtime invariants enforced at the end."""
    challenger_names = [n for n in configs.keys() if n != champion_name]
    expected = len(prerejection_sources) * len(challenger_names)
    counts["expected_source_cohort_attempts"] = expected
    if expected == 0:
        return

    # One strict binding read for ALL challengers (B19-A). A failure is TYPED;
    # every expected pair then records cohort_binding_unavailable.
    bindings: Optional[Dict[str, Dict[str, Any]]] = None
    try:
        bindings = _get_active_cohort_bindings(user_id, supabase)
    except Exception as be:
        errors.append({
            "stage": "cohort_bindings_fetch_failed",
            "error_class": type(be).__name__, "error": str(be)[:200],
        })

    for cohort_name in challenger_names:
        config = configs.get(cohort_name) or PolicyConfig()
        for ps in prerejection_sources:
            counts["source_cohort_attempts"] += 1  # BEFORE any guard (B19-D)

            if bindings is None:
                counts["cohort_binding_unavailable"] += 1
                continue
            binding = bindings.get(cohort_name)
            if binding is None:
                counts["cohort_binding_unavailable"] += 1
                errors.append({
                    "stage": "cohort_binding_unavailable",
                    "cohort": cohort_name, "ticker": ps.get("ticker"),
                    "source_suggestion_id": ps.get("id")})
                continue
            cohort_id = binding.get("cohort_id")
            portfolio_id = binding.get("portfolio_id")
            if not cohort_id:
                counts["cohort_identity_missing"] += 1
                errors.append({
                    "stage": "cohort_identity_missing",
                    "cohort": cohort_name,
                    "source_suggestion_id": ps.get("id")})
                continue
            if not portfolio_id:
                counts["cohort_portfolio_missing"] += 1
                errors.append({
                    "stage": "cohort_portfolio_missing",
                    "cohort": cohort_name,
                    "source_suggestion_id": ps.get("id")})
                continue

            # Capital fails CLOSED (B19-I) — no $100,000 default.
            deployable, cap_reason = _normalize_capital(
                _read_portfolio_row(supabase, portfolio_id))
            if cap_reason is not None:
                counts["cohort_capital_invalid"] += 1
                errors.append({
                    "stage": "cohort_capital_invalid",
                    "cohort": cohort_name, "reason": cap_reason,
                    "source_suggestion_id": ps.get("id")})
                continue

            _process_prerejection_source(
                supabase, user_id, cohort_name, cohort_id, ps,
                config, deployable, counts, errors)

    # B19-K runtime invariants (NOT python assert — typed error, sets partial).
    terminal = (counts["accepted"] + counts["refused"] + counts["clone_failed"]
                + counts["identity_mismatch"] + counts["accepted_verdict_failed"]
                + counts["cohort_binding_unavailable"]
                + counts["cohort_identity_missing"]
                + counts["cohort_portfolio_missing"]
                + counts["cohort_capital_invalid"])
    actual = counts["source_cohort_attempts"]
    if actual != expected or actual != terminal:
        errors.append({
            "stage": "prerejection_count_invariant_failed",
            "expected_attempts": expected, "actual_attempts": actual,
            "terminal_sum": terminal,
            "buckets": {k: counts[k] for k in (
                "accepted", "refused", "clone_failed", "identity_mismatch",
                "accepted_verdict_failed", "cohort_binding_unavailable",
                "cohort_identity_missing", "cohort_portfolio_missing",
                "cohort_capital_invalid")},
        })


def _read_portfolio_row(supabase, portfolio_id: str) -> Optional[Dict]:
    """Read one portfolio row (net_liq, cash_balance). Returns None on any
    fault — the caller's capital normalizer fails closed on None."""
    try:
        res = supabase.table("paper_portfolios") \
            .select("cash_balance, net_liq") \
            .eq("id", portfolio_id) \
            .single() \
            .execute()
        return res.data or None
    except Exception:
        return None


def _normalize_capital(portfolio_row: Optional[Dict]) -> tuple:
    """Compatibility seam for E19 tests; authoritative logic is shared."""
    return normalize_capital(portfolio_row)


def _get_active_cohort_bindings(user_id: str, supabase) -> Dict[str, Dict[str, Any]]:
    """B19-A strict single-read binding of active cohorts. RAISES on
    query/shape failure — never returns {} as a substitute for failure.
    {cohort_name: {"cohort_id": id, "portfolio_id": pid}}."""
    res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name, portfolio_id") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    rows = res.data
    if rows is None:
        raise RuntimeError("policy_lab_cohorts binding read returned no data attr")
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        name = r.get("cohort_name")
        if name is None:
            raise RuntimeError("policy_lab_cohorts binding row missing cohort_name")
        out[name] = {"cohort_id": r.get("id"),
                     "portfolio_id": r.get("portfolio_id")}
    return out


def _fork_result(
    base_status: str,
    created: Dict[str, int],
    prerej_counts: Dict[str, int],
    fork_errors: List[Dict[str, Any]],
    champion_tagged: int = 0,
) -> Dict[str, Any]:
    """The explicit fork-result contract (Blocker 1 + contract cleanup).

    STATUS VOCABULARY (stable enum): status ∈ {ok, partial, failed} — always.
    'no_source_suggestions' is a REASON, not a status (rides the `reason`
    field). The two pre-existing early returns above this machinery
    ('disabled', 'no_cohorts') predate the contract and keep their legacy
    shapes — documented consumers: none beyond logs (verified by grep); left
    untouched deliberately. status degrades to 'partial' whenever ANY
    experimental-path failure occurred; champion outcome is separate."""
    status = "partial" if fork_errors else "ok"
    result_reason = None if base_status == "ok" else base_status
    return {
        "status": status,
        "reason": result_reason,
        "champion_status": (
            "partial"
            if any(
                e.get("stage") in {
                    "champion_tag_failed",
                    "legacy_normal_clone_insert_failed",
                    "legacy_normal_clone_state_failed",
                }
                for e in fork_errors
            )
            else "ok"
        ),
        "champion_tagged": champion_tagged,
        "created": created,
        "existing": prerej_counts.get("existing", 0),
        "refused": prerej_counts.get("refused", 0),
        "errors": len(fork_errors),
        "error_details": fork_errors[:10],
        "prerejection_source_count": prerej_counts.get("source", 0),
        "prerejection_source_rows": prerej_counts.get("source", 0),
        # B19 coverage:
        "prerejection_source_cohort_attempts": prerej_counts.get(
            "source_cohort_attempts", 0),
        "expected_source_cohort_attempts": prerej_counts.get(
            "expected_source_cohort_attempts", 0),
        "coverage_shortfall": (
            prerej_counts.get("expected_source_cohort_attempts", 0)
            - prerej_counts.get("source_cohort_attempts", 0)),
        "coverage_complete": (
            prerej_counts.get("expected_source_cohort_attempts", 0)
            == prerej_counts.get("source_cohort_attempts", 0)
            and not any(e.get("stage") == "prerejection_count_invariant_failed"
                        for e in fork_errors)),
        "prerejection_eligible_count": prerej_counts.get("eligible", 0),
        "prerejection_clone_count": (
            prerej_counts.get("created", 0) + prerej_counts.get("existing", 0)
        ),
        # B22 honest verdict counters. total = accepted + rejected.
        "prerejection_eligible_verdict_count": prerej_counts.get(
            "accepted_verdicts", 0),
        "prerejection_ineligible_verdict_count": prerej_counts.get(
            "rejected_verdicts", 0),
        "prerejection_total_verdict_count": (
            prerej_counts.get("accepted_verdicts", 0)
            + prerej_counts.get("rejected_verdicts", 0)),
        # `prerejection_verdict_count` retained as an ALIAS of the total (B22).
        "prerejection_verdict_count": (
            prerej_counts.get("accepted_verdicts", 0)
            + prerej_counts.get("rejected_verdicts", 0)),
        "prerejection_counts": dict(prerej_counts),
    }


@dataclass
class CohortPolicyDecision:
    """Canonical result of evaluating ONE source suggestion against a cohort's
    PolicyConfig. Produced ONCE by `_evaluate_cohort_policy` and consumed by
    BOTH `_filter_for_cohort` (the accepted subset) and `_log_cohort_decisions`
    (the decision rows). The logger MUST NOT re-derive routing from ev /
    risk_adjusted_ev / score / threshold — that was the F-A9-5 defect: the
    logger compared dollar `ev` against the 0-100 `min_score_threshold`, so
    `ev_below_min` fired on capacity rejections whose score PASSED, and genuine
    score rejections were logged as the generic `filtered_by_policy` (the real
    reason erased)."""
    suggestion: Dict
    suggestion_id: Optional[str]
    accepted: bool
    reason_codes: List[str]
    score_value: Optional[float]
    score_basis: str
    capacity_state: str   # within_capacity | capacity_exhausted | champion_unfiltered
    rank: int


_SCORE_BASIS = "sizing_metadata.score"


def _score_for_log(value) -> Optional[float]:
    """Best-effort numeric score for the decision RECORD only (informational —
    routing never consumes this). Never raises; missing/non-numeric → None."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _evaluate_cohort_policy(
    suggestions: List[Dict],
    config: PolicyConfig,
    open_positions: int,
) -> List["CohortPolicyDecision"]:
    """The SINGLE routing evaluation for a challenger cohort. Precedence and
    arithmetic mirror the pre-F-A9-5 inline filter EXACTLY — capacity binds
    first (the old filter `break`s), then missing score, then score < threshold
    — so the accepted set and its order are byte-identical; each rejection just
    carries a truthful typed reason. `sizing_metadata.get("score")` (0-100) is
    the routing quantity; dollar `ev` is NEVER a routing input.

    (#95 lineage: score is read from sizing_metadata, persisted at insert by
    workflow_orchestrator; the old bug read risk_adjusted_ev — 0-2 ratio —
    against min_score_threshold (0-100), filtering every non-aggressive cohort
    to zero. Missing score → rejected, safe default.)"""
    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    decisions: List[CohortPolicyDecision] = []
    accepted = 0
    for rank, s in enumerate(suggestions, start=1):
        sid = s.get("id")
        sizing_metadata = s.get("sizing_metadata") or {}
        score_value = sizing_metadata.get("score")

        # 1) Capacity binds FIRST (the inline filter `break`s here): every
        #    remaining candidate is a capacity rejection regardless of score.
        if accepted >= max_new:
            reason = (
                "max_positions_reached"
                if open_positions >= config.max_positions_open
                else "daily_limit_reached"
            )
            decisions.append(CohortPolicyDecision(
                s, sid, False, [reason], _score_for_log(score_value),
                _SCORE_BASIS, "capacity_exhausted", rank))
            continue

        # 2) Missing predicate evidence → typed unavailable, never fabricated.
        if score_value is None:
            decisions.append(CohortPolicyDecision(
                s, sid, False, ["routing_decision_unavailable"], None,
                _SCORE_BASIS, "within_capacity", rank))
            continue

        # 3) Score below the cohort bar (0-100 vs 0-100). `float()` mirrors the
        #    inline filter's comparison exactly (identical raise on non-numeric).
        if float(score_value) < config.min_score_threshold:
            decisions.append(CohortPolicyDecision(
                s, sid, False, ["score_below_min"], float(score_value),
                _SCORE_BASIS, "within_capacity", rank))
            continue

        accepted += 1
        decisions.append(CohortPolicyDecision(
            s, sid, True, [], float(score_value),
            _SCORE_BASIS, "within_capacity", rank))

    return decisions


def _champion_accept_all(
    suggestions: List[Dict],
) -> List["CohortPolicyDecision"]:
    """Champion decisions: the source suggestions ARE the champion's output, so
    every one is accepted with no reason (the champion never runs the cohort
    filter). No routing re-derivation — preserves the pre-F-A9-5 champion
    contract (all accepted, empty reason_codes, rank in source order)."""
    return [
        CohortPolicyDecision(
            s, s.get("id"), True, [],
            _score_for_log((s.get("sizing_metadata") or {}).get("score")),
            _SCORE_BASIS, "champion_unfiltered", rank)
        for rank, s in enumerate(suggestions, start=1)
    ]


def _filter_for_cohort(
    suggestions: List[Dict],
    config: PolicyConfig,
    open_positions: int,
) -> List[Dict]:
    """The accepted subset per the canonical `_evaluate_cohort_policy` — the
    routing side of the single evaluation the logger also consumes (F-A9-5).
    Byte-identical accepted set + order to the pre-F-A9-5 inline filter."""
    return [
        d.suggestion
        for d in _evaluate_cohort_policy(suggestions, config, open_positions)
        if d.accepted
    ]


def _is_shadow_raw_ev_enabled() -> bool:
    """D② (2026-07-12): shadow cohorts (neutral/conservative — every clone; the
    champion is tagged in place, never cloned) score on RAW ev (source.ev_raw), not
    the champion's calibrated ev, so the experiment layer breathes on unclamped EV.
    The honest cross-cohort comparison lives at OUTCOMES (closes, thesis accuracy,
    per-contract-normalized promotion gates), which are basis-independent — not at
    entry EV. DECIDED design; SHADOW_RAW_EV_ENABLED is a REVERT lever (default ON:
    empty/unset → ON; explicit 0/false/no/off → inherit calibrated). Shadows are
    simulated — no live money — so this is a lever, not an observe gate."""
    raw = os.environ.get("SHADOW_RAW_EV_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def _clone_suggestion_for_cohort(
    source: Dict,
    cohort_name: str,
    config: PolicyConfig,
    deployable_capital: float,
) -> Optional[Dict]:
    """
    Clone a suggestion with cohort-specific sizing.

    Adjusts contract quantity based on cohort's risk parameters while
    preserving the original suggestion's legs, strategy, and scores.
    """
    order_json = source.get("order_json") or {}
    sizing_meta = source.get("sizing_metadata") or {}

    original_contracts = int(order_json.get("contracts") or 1)
    max_loss = float(sizing_meta.get("max_loss_total") or 0)
    max_loss_per = max_loss / max(original_contracts, 1)

    # Compute cohort-specific contract count
    if max_loss_per > 0:
        budget = deployable_capital * config.budget_cap_pct
        max_risk = deployable_capital * config.max_risk_pct_per_trade * config.risk_multiplier
        effective_risk = min(budget, max_risk)
        contracts = max(1, int(math.floor(effective_risk / max_loss_per)))
    else:
        # Fallback: scale proportionally from aggressive defaults
        scale = config.max_risk_pct_per_trade / 0.05
        contracts = max(1, int(round(original_contracts * scale)))

    # E14 (2026-07-12): rescale the honest risk to the CLONE's contracts and emit
    # it as BOTH the typed top-level total AND consistent JSON provenance. Pre-fix
    # the clone copied the SOURCE's max_loss_total unchanged (mis-scaled) into
    # sizing_metadata and omitted the top-level column (→ NULL) — so fill/orphan
    # consumers read a NULL while the JSON lied. UNKNOWN stays EXPLICIT (None):
    # never a fabricated 0, never a stale JSON total next to a NULL typed column.
    # max_loss_per is the source per-contract truth (source_total/source_contracts).
    if max_loss_per > 0:
        clone_max_loss_total = round(max_loss_per * contracts, 2)
        _max_loss_basis = "rescaled_from_source_per_contract"
    else:
        clone_max_loss_total = None
        _max_loss_basis = "unknown_source_no_max_loss_total"

    # Build cloned order_json with new quantity.
    #
    # #3 convention (full-count): each leg's quantity must equal the clone's OWN
    # contract count, not the champion's. Pre-fix, `{**order_json}` copied the
    # champion's legs verbatim — so a 26ct neutral clone carried the champion's
    # 5ct legs (PR #990's F-row check observed legs.quantity=5 across the 5/12/26
    # cohort rows). Rescale every leg's quantity to `contracts` here so cohort
    # suggestion rows are convention-correct at emission.
    cloned_legs = [
        {**leg, "quantity": contracts}
        for leg in (order_json.get("legs") or [])
        if isinstance(leg, dict)
    ]
    cloned_order = {**order_json, "contracts": contracts, "legs": cloned_legs}

    # Build cloned sizing_metadata
    cloned_sizing = {
        **sizing_meta,
        "contracts": contracts,
        "cohort_name": cohort_name,
        "original_contracts": original_contracts,
        "policy_max_risk_pct": config.max_risk_pct_per_trade,
        # E14: the clone's OWN rescaled total (or explicit None), never the source's.
        "max_loss_total": clone_max_loss_total,
        "max_loss_total_basis": _max_loss_basis,
    }

    now_iso = datetime.now(timezone.utc).isoformat()

    # Use unique fingerprint to avoid unique constraint violation
    source_fp = source.get("legs_fingerprint") or ""
    cohort_fp = f"{source_fp}_{cohort_name}" if source_fp else cohort_name

    # D② (2026-07-12): shadow cohorts score on RAW ev, not the champion's calibrated
    # ev. Fallback to calibrated when ev_raw is absent (older rows) or the revert
    # flag is off. (risk_adjusted_ev inheritance unchanged — the decided basis
    # change is the entry EV; outcome-side comparisons are basis-independent.)
    # E19-2 (2026-07-13): the basis is now EXPLICIT on every clone — ev_basis
    # states which number `ev` carries, raev_basis states where
    # risk_adjusted_ev came from, and the typed ev_raw column is persisted
    # (pre-fix clones carried ev=RAW beside ev_raw=NULL and an inherited
    # CALIBRATED risk_adjusted_ev — the 2026-07-13 926fd7e2 incoherence
    # exhibit). Never inferred downstream; never silently defaulted.
    _clone_ev = source.get("ev")
    _ev_basis = "calibrated_inherited"
    if _is_shadow_raw_ev_enabled():
        _raw_ev = source.get("ev_raw")
        if _raw_ev is not None:
            _clone_ev = _raw_ev
            _ev_basis = "raw"

    cloned_sizing["ev_basis"] = _ev_basis
    cloned_sizing["raev_basis"] = "inherited_calibrated_source"

    return {
        "user_id": source["user_id"],
        "window": source.get("window"),
        "ticker": source.get("ticker"),
        "strategy": source.get("strategy"),
        "direction": source.get("direction"),
        "status": "pending",
        "ev": _clone_ev,
        "ev_raw": source.get("ev_raw"),
        "risk_adjusted_ev": source.get("risk_adjusted_ev"),
        # E14: typed top-level risk — rescaled to THIS clone's contracts, or an
        # explicit NULL (never fabricated) — so fill/orphan consumers stop reading
        # a NULL beside a lying JSON total.
        "max_loss_total": clone_max_loss_total,
        "order_json": cloned_order,
        "sizing_metadata": cloned_sizing,
        "cohort_name": cohort_name,
        "cycle_date": source.get("cycle_date"),
        "legs_fingerprint": cohort_fp,
        # #97 Phase 2 fix: trace_id is row-unique per
        # idx_trade_suggestions_trace_id_unique (partial unique on
        # non-null). Inheriting source's trace_id collided across
        # cohort clones — first INSERT took the trace_id, second
        # failed with PostgreSQL 23505 unique violation. Generate
        # fresh per clone. Lineage tracking is intentionally retained
        # via decision_lineage / lineage_hash / lineage_sig /
        # lineage_version (those ARE inherited correctly below).
        "trace_id": str(uuid.uuid4()),
        "model_version": source.get("model_version"),
        "features_hash": source.get("features_hash"),
        "regime": source.get("regime"),
        "decision_lineage": source.get("decision_lineage"),
        "lineage_hash": source.get("lineage_hash"),
        "agent_signals": source.get("agent_signals"),
        "agent_summary": source.get("agent_summary"),
        "created_at": now_iso,
    }


# E19-2 experiment identity. The clone fingerprint embeds this version, so a
# future v2 produces DISTINCT clone rows. HONEST NARROWING (Blocker 8): the
# policy_decisions verdict conflicts on UNIQUE(cohort_id, suggestion_id) —
# verified live schema — which is VERSION-BLIND; the stored verdict therefore
# represents the LATEST experiment version only. Making verdict history
# version-aware would require a migration (operator adjudication required —
# not taken here).
EXPERIMENT_VERSION = "e19_prerejection_v1"

# Raw-gate typed reject reasons (Blocker 4 + B12).
_REJECT_MISSING_BASIS = "missing_ev_basis"
_REJECT_RAW_EDGE = "raw_edge_below_minimum"
_REJECT_RAW_RECOMPUTE = "raw_raev_recompute_failed"
_REJECT_RAW_INVALID = "raw_raev_invalid"
_REJECT_RAW_EV_INVALID = "raw_ev_invalid"
_REJECT_MAX_LOSS_NOT_NORMALIZABLE = "max_loss_not_normalizable"
_REJECT_CONTRACT_COUNT_MISMATCH = "contract_count_basis_mismatch"

# B12 — the EXACT canonical cost assumption the eligibility computation
# inherits from canonical_ranker at one contract: fees = 0.65 × 1 × 2 (open +
# close, LEG-BLIND — the ranker does not scale by leg count; the multi-basis
# unification is its own backlog item) + slippage floor = 5% of |ev| when no
# TCM estimate exists. Stamped on every verdict so nobody later assumes
# leg-aware costs were applied.
_ELIGIBILITY_COST_BASIS = "leg_blind_fee_0.65_per_contract_x2_plus_5pct_ev_slippage"

# B13 — tolerant numeric comparison bound for persisted-clone identity checks.
# Values round-trip Python float → JSONB → Python; 1e-6 absolute covers that
# representation noise while catching any real basis drift (the quantities
# compared are dollars/ratios ≥ 0.01 in magnitude).
_IDENTITY_NUM_TOL = 1e-6


def _finite_num(value):
    """B25 strict finite-number normalizer. Returns (float, True) only for a
    real finite number; (None, False) for bool / NaN / ±inf / non-numeric.
    Booleans are rejected explicitly (bool is an int subclass)."""
    if isinstance(value, bool):
        return None, False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None, False
    if not math.isfinite(f):
        return None, False
    return f, True


def _num_neq_strict(actual, expected) -> bool:
    """B25 — MISMATCH iff either side is non-finite (fail closed: a NaN can
    never 'pass') OR |actual − expected| > tol."""
    a, aok = _finite_num(actual)
    e, eok = _finite_num(expected)
    if not aok or not eok:
        return True
    return abs(a - e) > _IDENTITY_NUM_TOL


def _pos_int(value):
    """B25 strict positive-integer normalizer for contract quantities.
    Returns (int, True) only for a finite, >0, integer-valued number
    (accepts 1, 1.0, "1", "1.0"); (None, False) for bool / 0 / negative /
    1.9 / NaN / inf / non-numeric."""
    if isinstance(value, bool):
        return None, False
    f, ok = _finite_num(value)
    if not ok or f <= 0 or not float(f).is_integer():
        return None, False
    return int(f), True


def build_raw_eligibility_view(row: Dict) -> tuple:
    """B12 — the EV QUANTITY-UNIT CONTRACT for E19 raw eligibility.

    The scanner's ev/ev_raw is the economics of ONE structure-contract
    (options_scanner computes total_ev from a single-structure combo and the
    orchestrator never multiplies it by sized contracts), while
    canonical_ranker subtracts fees × sizing_metadata.contracts × 2. Feeding a
    resized clone into the ranker therefore mixes per-contract EV with
    quantity-scaled costs — eligibility would depend on clone size.

    E19-2A is RAW-CANDIDATE-ELIGIBILITY-ONLY, so eligibility is decided on an
    explicit ONE-CONTRACT NORMALIZED VIEW:

        ev              = per-contract ev_raw          (as stored)
        contracts       = 1
        max_loss_total  = row max_loss_total / row contracts   (per contract)
        costs           = _ELIGIBILITY_COST_BASIS at contracts=1

    Leg/order quantity CANNOT influence the decision. Returns (view, None) or
    (None, typed_reason): non-finite/zero ev_raw → raw_ev_invalid;
    missing/zero/non-finite normalized max loss → max_loss_not_normalizable —
    never inferred, never silently defaulted.
    """
    raw_ev = row.get("ev_raw")
    if raw_ev is None:
        return None, _REJECT_MISSING_BASIS
    try:
        raw_ev_f = float(raw_ev)
    except (TypeError, ValueError):
        return None, _REJECT_RAW_EV_INVALID
    if not math.isfinite(raw_ev_f) or raw_ev_f == 0.0:
        return None, _REJECT_RAW_EV_INVALID

    sizing = row.get("sizing_metadata") or {}
    order_json = row.get("order_json") or {}
    sizing_ct = sizing.get("contracts")
    order_ct = order_json.get("contracts")
    if sizing_ct is not None and order_ct is not None:
        try:
            if int(sizing_ct) != int(order_ct):
                # B17: two disagreeing canonical contract counts — never
                # choose silently.
                return None, _REJECT_CONTRACT_COUNT_MISMATCH
        except (TypeError, ValueError):
            return None, _REJECT_MAX_LOSS_NOT_NORMALIZABLE
    contracts_raw = sizing_ct
    if contracts_raw is None:  # explicit 0 must NOT fall through (typed refusal)
        contracts_raw = order_ct
    try:
        contracts = int(contracts_raw)
    except (TypeError, ValueError):
        return None, _REJECT_MAX_LOSS_NOT_NORMALIZABLE
    mlt = sizing.get("max_loss_total")
    if mlt is None:
        mlt = row.get("max_loss_total")
    try:
        mlt_f = float(mlt)
    except (TypeError, ValueError):
        return None, _REJECT_MAX_LOSS_NOT_NORMALIZABLE
    if contracts <= 0 or not math.isfinite(mlt_f) or mlt_f <= 0.0:
        return None, _REJECT_MAX_LOSS_NOT_NORMALIZABLE
    per_contract_max_loss = round(mlt_f / contracts, 6)
    if not math.isfinite(per_contract_max_loss) or per_contract_max_loss <= 0:
        return None, _REJECT_MAX_LOSS_NOT_NORMALIZABLE

    view = {
        "ev": raw_ev_f,
        "ticker": row.get("ticker"),
        "sizing_metadata": {
            "contracts": 1,
            "max_loss_total": per_contract_max_loss,
        },
    }
    return view, None


def _process_prerejection_source(
    supabase,
    user_id: str,
    cohort_name: str,
    cohort_id: Optional[str],
    source: Dict,
    config: PolicyConfig,
    deployable_capital: float,
    counts: Dict[str, int],
    errors: List[Dict[str, Any]],
) -> None:
    """One calibrated-rejected source through the RECOVERABLE order
    (Blocker 2): validate -> build+raw-gate clone -> fail-closed lookup ->
    insert (race-reconciled) -> read back the persisted row -> verdict FROM
    the persisted clone. Failures are typed into ``errors``; a clone that
    exists without a verdict is REPAIRED on re-run; nothing here can raise
    out (the champion path is never at risk)."""
    ticker = source.get("ticker")
    # NOTE (B19): source_cohort_attempts + the binding/portfolio/capital guards
    # are owned by _run_prerejection_coverage; this function is only reached for
    # a fully-bound, capital-valid pair and owns the remaining terminal buckets
    # (accepted / refused / clone_failed / identity_mismatch /
    # accepted_verdict_failed).

    def _err(stage: str, e: Exception) -> None:
        errors.append({
            "stage": stage, "cohort": cohort_name, "ticker": ticker,
            "source_suggestion_id": source.get("id"),
            "error_class": type(e).__name__, "error": str(e)[:200],
        })

    try:
        # 1. Raw basis present? (typed refusal, never a silent default)
        if source.get("ev_raw") is None:
            counts["refused"] += 1
            _write_prerejection_reject(
                supabase, user_id, cohort_id, source,
                _REJECT_MISSING_BASIS, counts, errors)
            return

        # 2. Cohort policy (score) filter — a typed POLICY refusal (counted
        #    in `refused` exactly once, like every economic/policy refusal).
        sizing_md = source.get("sizing_metadata") or {}
        score_value = sizing_md.get("score")
        if score_value is None or float(score_value) < config.min_score_threshold:
            counts["refused"] += 1
            _write_prerejection_reject(
                supabase, user_id, cohort_id, source,
                "filtered_by_policy", counts, errors)
            return

        # 3. Build the sized raw-basis clone + RAW ELIGIBILITY GATE
        #    (Blocker 4): the divergence claim requires raw to GENUINELY
        #    pass the canonical edge semantics, not merely exist.
        clone, reject_reason = _build_prerejection_clone(
            source, cohort_name, config, deployable_capital)
        if reject_reason is not None:
            counts["refused"] += 1
            _write_prerejection_reject(
                supabase, user_id, cohort_id, source,
                reject_reason, counts, errors)
            return
        counts["eligible"] += 1

        # 4. Fail-CLOSED idempotency lookup (Blocker 10): "could not prove
        #    absence" must never become "insert another row".
        try:
            existing = _find_existing_clone(supabase, clone)
        except Exception as le:
            counts["clone_failed"] += 1
            _err("clone_lookup_failed", le)
            return

        persisted: Optional[Dict] = None
        was_existing = existing is not None
        if was_existing:
            counts["existing"] += 1
            persisted = existing
        else:
            # 5. Insert; a uniqueness race is reconciled by re-lookup and
            #    counted as existing, never as success-by-assumption.
            try:
                supabase.table("trade_suggestions").insert(clone).execute()
            except Exception as ie:
                msg = str(ie).lower()
                if "duplicate" in msg or "unique" in msg:
                    try:
                        persisted = _find_existing_clone(supabase, clone)
                    except Exception as re_le:
                        counts["clone_failed"] += 1
                        _err("clone_race_relookup_failed", re_le)
                        return
                    if persisted is None:
                        counts["clone_failed"] += 1
                        _err("clone_race_unreconciled", ie)
                        return
                    counts["existing"] += 1
                    was_existing = True
                else:
                    counts["clone_failed"] += 1
                    _err("clone_insert_failed", ie)
                    return

        # 6. READ BACK the persisted clone — the verdict is built from what
        #    the database actually holds (Blocker 3), never from in-memory
        #    intent.
        if persisted is None:
            try:
                persisted = _find_existing_clone(supabase, clone)
            except Exception as rb:
                counts["clone_failed"] += 1
                _err("clone_readback_failed", rb)
                return
            if persisted is None:
                counts["clone_failed"] += 1
                _err("clone_readback_missing",
                     RuntimeError("insert reported success but read-back is empty"))
                return
            counts["created"] += 1

        # 7. B13 — PERSISTED CLONE IDENTITY + BASIS VALIDATION. The verdict
        #    of record may only be written from a persisted row PROVEN to be
        #    the expected clone: identity fields exact, numeric basis fields
        #    within _IDENTITY_NUM_TOL. Any mismatch → typed error, NO
        #    accepted verdict, job goes partial, champion untouched.
        mismatch_kind, mismatch_field = _validate_persisted_clone(
            persisted, clone, source)
        if mismatch_kind is not None:
            counts["identity_mismatch"] += 1
            _err(mismatch_kind,
                 RuntimeError(f"persisted clone field {mismatch_field!r} "
                              f"does not match expected"))
            return

        already_verdicted = False
        try:
            already_verdicted = _verdict_exists(
                supabase, cohort_id, source.get("id"))
        except Exception:
            already_verdicted = False  # the upsert below is idempotent anyway

        try:
            _write_prerejection_verdict(
                supabase, user_id, cohort_id, source, persisted)
            counts["accepted"] += 1          # terminal disposition
            counts["accepted_verdicts"] += 1  # B22 honest verdict counter
            if was_existing and not already_verdicted:
                counts["repaired"] += 1
        except Exception as ve:
            counts["accepted_verdict_failed"] += 1
            _err("verdict_upsert_failed", ve)
            # The clone persists; identity (fingerprint + source id) is
            # sufficient for the next run to repair the missing verdict.
            return

    except Exception as ue:  # belt-and-braces: nothing may escape per-source
        counts["clone_failed"] += 1
        _err("prerejection_unexpected", ue)


def _build_prerejection_clone(
    source: Dict,
    cohort_name: str,
    config: PolicyConfig,
    deployable_capital: float,
) -> tuple:
    """Build the sized raw-basis observational clone, applying the RAW
    ELIGIBILITY GATE on the ONE-CONTRACT NORMALIZED VIEW (Blockers 4 + 12).

    B12 unit contract: eligibility is decided on build_raw_eligibility_view —
    per-contract ev_raw against contracts=1 costs and per-contract max loss —
    so the decision and the normalized raw RAeV are IDENTICAL at every clone
    quantity. The OBSERVATIONAL clone itself keeps its cohort-sized quantity
    and honestly rescaled risk fields; only eligibility is normalized.

    Gate: canonical compute_risk_adjusted_ev(view, [], 0.0) — portfolio-blind,
    concentration penalty 1.0, the exact leg-blind canonical cost assumption
    (_ELIGIBILITY_COST_BASIS). -999 sentinel -> raw fails the edge too;
    exception -> typed recompute failure; None/non-finite -> typed invalid;
    non-normalizable inputs -> typed refusal. No clone, no accepted verdict,
    for any of those.
    """
    view, view_reason = build_raw_eligibility_view(source)
    if view_reason is not None:
        return None, view_reason
    raw_ev = view["ev"]

    from packages.quantum.analytics.canonical_ranker import compute_risk_adjusted_ev
    try:
        raw_raev = compute_risk_adjusted_ev(view, [], 0.0)
    except Exception:
        return None, _REJECT_RAW_RECOMPUTE
    if raw_raev is None or not isinstance(raw_raev, (int, float)) \
            or not math.isfinite(float(raw_raev)):
        return None, _REJECT_RAW_INVALID
    raw_raev = round(float(raw_raev), 6)
    if raw_raev <= -999.0:
        return None, _REJECT_RAW_EDGE

    base = _clone_suggestion_for_cohort(
        source, cohort_name, config, deployable_capital)
    if not base:
        return None, _REJECT_RAW_INVALID

    sizing = dict(base.get("sizing_metadata") or {})
    clone_contracts = int((base.get("order_json") or {}).get("contracts") or 1)
    sizing.update({
        # EV provenance triple: the basis is explicit; execution is described
        # by what ACTUALLY happened (nothing).
        "ev_basis": "raw",
        "raev_basis": "raw_per_contract_normalized",
        # B12 stamps — the unit contract of the eligibility decision:
        "eligibility_ev_unit": "per_contract",
        "eligibility_contracts": 1,
        "clone_contracts": clone_contracts,
        "eligibility_cost_basis": _ELIGIBILITY_COST_BASIS,
        "ev_calibrated": source.get("ev"),
        # B20 — TRUTHFUL provenance: source.model_version is populated from
        # APP_VERSION, NOT from the calibration_adjustments blob that actually
        # scaled ev. It is therefore NOT a calibration identity. We carry the
        # source's model_version verbatim and mark that no calibration
        # identity is persisted on the source.
        "source_model_version": source.get("model_version"),
        "calibration_provenance_status": "not_persisted_on_source",
        # B23 — NARROW CLAIM: this is candidate-level raw eligibility, NOT
        # entry selection (no capacity / joint-rank / slot accounting).
        "observation_scope": "raw_candidate_eligibility_only",
        "decision_semantics": "raw_candidate_eligibility",
        "selected_for_entry": False,
        "capacity_evaluated": False,
        "joint_rank_evaluated": False,
        "routing_intent": "shadow_only",
        "execution_state": "not_executed",
        "execution_intent": "internal_paper_only",
        "prerejection_fork": True,
        "experiment_version": EXPERIMENT_VERSION,
        "champion_blocked_reason": source.get("blocked_reason"),
        "source_suggestion_id": source.get("id"),
        "source_trace_id": source.get("trace_id"),
        "source_lineage_hash": source.get("lineage_hash"),
    })
    base.update({
        "status": "NOT_EXECUTABLE",
        "blocked_reason": "shadow_prerejection_fork",
        "blocked_detail": (
            f"champion rejected: {source.get('blocked_reason')}; "
            f"raw-candidate-eligibility observation only"
        ),
        "ev": raw_ev,
        "ev_raw": raw_ev,
        "risk_adjusted_ev": raw_raev,
        "sizing_metadata": sizing,
        # Version-aware clone identity (Blocker 8): a v2 experiment mints
        # distinct rows instead of silently overwriting v1 evidence.
        "legs_fingerprint": (
            f"{source.get('legs_fingerprint') or ''}"
            f"_prerej_{EXPERIMENT_VERSION}_{cohort_name}"
        ),
    })
    return base, None


def _validate_persisted_clone(persisted: Dict, expected: Dict, source: Dict) -> tuple:
    """B13 — prove the persisted row IS the expected clone before any
    accepted verdict is written or repaired. Returns (None, None) on match,
    else (typed_kind, field): identity fields → 'clone_identity_mismatch';
    EV/basis fields → 'clone_basis_mismatch'. Numeric comparisons use
    _IDENTITY_NUM_TOL (1e-6 absolute — float→JSONB→float representation
    noise; all compared magnitudes ≥ 0.01)."""
    p_sz = persisted.get("sizing_metadata") or {}
    e_sz = expected.get("sizing_metadata") or {}
    p_order = persisted.get("order_json") or {}
    e_order = expected.get("order_json") or {}

    # B21 — COMPLETE consumer-driven binding. EVERY field the verdict emits
    # (identity, provenance, economics, AND the legs) is validated before an
    # accepted verdict is written. Strings/enums exact; numerics at tolerance.
    identity_checks = [
        ("user_id", persisted.get("user_id"), expected.get("user_id")),
        ("source_suggestion_id", p_sz.get("source_suggestion_id"), source.get("id")),
        ("cohort_name", persisted.get("cohort_name"), expected.get("cohort_name")),
        ("ticker", persisted.get("ticker"), expected.get("ticker")),
        ("strategy", persisted.get("strategy"), expected.get("strategy")),
        ("window", persisted.get("window"), expected.get("window")),
        ("cycle_date", persisted.get("cycle_date"), expected.get("cycle_date")),
        ("experiment_version", p_sz.get("experiment_version"), EXPERIMENT_VERSION),
        ("legs_fingerprint", persisted.get("legs_fingerprint"),
         expected.get("legs_fingerprint")),
        ("status", persisted.get("status"), "NOT_EXECUTABLE"),
        ("blocked_reason", persisted.get("blocked_reason"),
         "shadow_prerejection_fork"),
        ("observation_scope", p_sz.get("observation_scope"),
         "raw_candidate_eligibility_only"),
        ("decision_semantics", p_sz.get("decision_semantics"),
         "raw_candidate_eligibility"),
        ("selected_for_entry", p_sz.get("selected_for_entry"), False),
        # B24 — the narrow-scope no-selection markers are IDENTITY-bound:
        ("capacity_evaluated", p_sz.get("capacity_evaluated"), False),
        ("joint_rank_evaluated", p_sz.get("joint_rank_evaluated"), False),
        ("execution_state", p_sz.get("execution_state"), "not_executed"),
        ("execution_intent", p_sz.get("execution_intent"), "internal_paper_only"),
        ("routing_intent", p_sz.get("routing_intent"), "shadow_only"),
        ("source_model_version", p_sz.get("source_model_version"),
         e_sz.get("source_model_version")),
        ("calibration_provenance_status",
         p_sz.get("calibration_provenance_status"),
         "not_persisted_on_source"),
        ("champion_blocked_reason", p_sz.get("champion_blocked_reason"),
         e_sz.get("champion_blocked_reason")),
        # source provenance (retained on the verdict snapshot):
        ("source_trace_id", p_sz.get("source_trace_id"),
         e_sz.get("source_trace_id")),
        ("source_lineage_hash", p_sz.get("source_lineage_hash"),
         e_sz.get("source_lineage_hash")),
    ]
    for field, got, want in identity_checks:
        if got != want:
            return "clone_identity_mismatch", field

    # basis/eligibility enums exact.
    basis_enum_checks = [
        ("ev_basis", p_sz.get("ev_basis"), "raw"),
        ("raev_basis", p_sz.get("raev_basis"), e_sz.get("raev_basis")),
        ("eligibility_ev_unit", p_sz.get("eligibility_ev_unit"), "per_contract"),
        ("eligibility_contracts", p_sz.get("eligibility_contracts"), 1),
        ("eligibility_cost_basis", p_sz.get("eligibility_cost_basis"),
         _ELIGIBILITY_COST_BASIS),
    ]
    for field, got, want in basis_enum_checks:
        if got != want:
            return "clone_basis_mismatch", field

    # B25 — economic coherence, FAIL CLOSED. _num_neq_strict flags a mismatch
    # if EITHER side is non-finite (NaN/inf) — a NaN can never "pass".
    if _num_neq_strict(persisted.get("ev_raw"), expected.get("ev_raw")):
        return "clone_basis_mismatch", "ev_raw"
    if _num_neq_strict(persisted.get("ev"), persisted.get("ev_raw")):
        return "clone_basis_mismatch", "ev_equals_ev_raw"
    if _num_neq_strict(p_sz.get("ev_calibrated"), e_sz.get("ev_calibrated")):
        return "clone_basis_mismatch", "ev_calibrated"
    if _num_neq_strict(persisted.get("risk_adjusted_ev"),
                       expected.get("risk_adjusted_ev")):
        return "clone_basis_mismatch", "risk_adjusted_ev"
    # contract-count coherence: EXACT positive integers (B25 — 1.9 must NOT
    # truncate-match). sizing.contracts == sizing.clone_contracts ==
    # order_json.contracts == expected clone qty.
    p_sizing_ct, ok1 = _pos_int(p_sz.get("contracts"))
    p_clone_ct, ok2 = _pos_int(p_sz.get("clone_contracts"))
    p_order_ct, ok3 = _pos_int(p_order.get("contracts"))
    e_clone_ct, ok4 = _pos_int(e_order.get("contracts"))
    if not (ok1 and ok2 and ok3 and ok4):
        return "clone_basis_mismatch", "clone_contracts"
    if not (p_sizing_ct == p_clone_ct == p_order_ct == e_clone_ct):
        return "clone_basis_mismatch", "clone_contracts"
    # both max-loss locations the verdict may read, both validated:
    if _num_neq_strict(persisted.get("max_loss_total"),
                       expected.get("max_loss_total")):
        return "clone_basis_mismatch", "max_loss_total"
    if _num_neq_strict(p_sz.get("max_loss_total"),
                       expected.get("max_loss_total")):
        return "clone_basis_mismatch", "sizing_max_loss_total"
    # limit_price is OPTIONAL: both-None is a legitimate match (a shadow clone
    # carries no limit); exactly-one-None or differing/non-finite is a mismatch.
    p_lp, e_lp = p_order.get("limit_price"), e_order.get("limit_price")
    if p_lp is None or e_lp is None:
        if p_lp is not e_lp:  # one None, one not
            return "clone_basis_mismatch", "limit_price"
    elif _num_neq_strict(p_lp, e_lp):
        return "clone_basis_mismatch", "limit_price"
    # legs: canonicalized per-leg comparison (symbol/side/type/strike/expiry/qty)
    if _canon_legs(p_order.get("legs")) != _canon_legs(e_order.get("legs")):
        return "clone_basis_mismatch", "order_legs"
    return None, None


def _canon_legs(legs) -> list:
    """Canonicalize order legs for exact comparison (B21-F): sort by a stable
    key and bind symbol/side|action/type|right/strike/expiry/quantity."""
    if not isinstance(legs, list):
        return []
    canon = []
    for leg in legs:
        if not isinstance(leg, dict):
            canon.append(("__nonleg__", str(leg)))
            continue
        canon.append((
            str(leg.get("symbol")),
            str(leg.get("side") if leg.get("side") is not None else leg.get("action")),
            str(leg.get("type") if leg.get("type") is not None else leg.get("right")),
            str(leg.get("strike")),
            str(leg.get("expiry")),
            str(leg.get("quantity")),
        ))
    return sorted(canon)


def _find_existing_clone(supabase, clone: Dict) -> Optional[Dict]:
    """Idempotency lookup for the EXACT ACTIVE prerejection-clone shape
    (B14): the unique-index key (user, window, cycle_date, ticker, strategy,
    fingerprint — unique_suggestion_per_cycle_v3, which ignores dismissed/
    cancelled) PLUS status='NOT_EXECUTABLE' AND
    blocked_reason='shadow_prerejection_fork'. An ARCHIVED (dismissed/
    cancelled) twin or an active row wearing a foreign status/reason is NOT
    this clone and must never receive its verdict. Standard chained
    PostgREST .eq() filters (the same verified syntax every other query in
    this module uses). RAISES on lookup failure — the caller fails CLOSED
    (Blocker 10)."""
    res = supabase.table("trade_suggestions") \
        .select("*") \
        .eq("user_id", clone.get("user_id")) \
        .eq("window", clone.get("window")) \
        .eq("cycle_date", clone.get("cycle_date")) \
        .eq("ticker", clone.get("ticker")) \
        .eq("strategy", clone.get("strategy")) \
        .eq("legs_fingerprint", clone.get("legs_fingerprint")) \
        .eq("status", "NOT_EXECUTABLE") \
        .eq("blocked_reason", "shadow_prerejection_fork") \
        .limit(1) \
        .execute()
    rows = res.data or []
    return rows[0] if rows else None


def _verdict_exists(supabase, cohort_id: Optional[str], suggestion_id) -> bool:
    if not cohort_id or not suggestion_id:
        return False
    res = supabase.table("policy_decisions") \
        .select("id") \
        .eq("cohort_id", cohort_id) \
        .eq("suggestion_id", suggestion_id) \
        .limit(1) \
        .execute()
    return bool(res.data)


def _write_prerejection_verdict(
    supabase,
    user_id: str,
    cohort_id: Optional[str],
    source: Dict,
    persisted_clone: Dict,
) -> None:
    """The ACCEPTED verdict of record — built from the PERSISTED clone
    (Blocker 3). Raises on failure (the caller types it)."""
    if not cohort_id:
        raise RuntimeError("no cohort_id for verdict")
    p_sizing = persisted_clone.get("sizing_metadata") or {}
    p_order = persisted_clone.get("order_json") or {}
    row = {
        "cohort_id": cohort_id,
        "suggestion_id": source.get("id"),
        "user_id": user_id,
        "decision": "accepted",
        # B24 — NULL is the truthful value: no ranking occurred.
        "rank_at_decision": None,
        "reason_codes": ["raw_candidate_eligible_observation"],
        "features_snapshot": {
            "source_suggestion_id": source.get("id"),
            "clone_suggestion_id": persisted_clone.get("id"),
            "source_trace_id": source.get("trace_id"),
            "source_lineage_hash": source.get("lineage_hash"),
            "ev": persisted_clone.get("ev"),
            "ev_raw": persisted_clone.get("ev_raw"),
            "ev_calibrated": p_sizing.get("ev_calibrated"),
            "ev_basis": p_sizing.get("ev_basis"),
            "risk_adjusted_ev": persisted_clone.get("risk_adjusted_ev"),
            "raev_basis": p_sizing.get("raev_basis"),
            "champion_blocked_reason": p_sizing.get("champion_blocked_reason"),
            "routing_intent": p_sizing.get("routing_intent"),
            "execution_state": p_sizing.get("execution_state"),
            # B24 — complete no-execution / no-selection contract on the verdict:
            "execution_intent": p_sizing.get("execution_intent"),
            "capacity_evaluated": p_sizing.get("capacity_evaluated"),
            "joint_rank_evaluated": p_sizing.get("joint_rank_evaluated"),
            # B20 — TRUTHFUL provenance (no false calibration identity):
            "source_model_version": p_sizing.get("source_model_version"),
            "calibration_provenance_status":
                p_sizing.get("calibration_provenance_status"),
            "experiment_version": p_sizing.get("experiment_version"),
            # B23 — narrow-claim semantics:
            "observation_scope": p_sizing.get("observation_scope"),
            "decision_semantics": p_sizing.get("decision_semantics"),
            "selected_for_entry": p_sizing.get("selected_for_entry"),
            # B12 — the eligibility unit contract, from the PERSISTED row:
            "eligibility_ev_unit": p_sizing.get("eligibility_ev_unit"),
            "eligibility_contracts": p_sizing.get("eligibility_contracts"),
            "clone_contracts": p_sizing.get("clone_contracts"),
            "eligibility_cost_basis": p_sizing.get("eligibility_cost_basis"),
            "cohort_name": persisted_clone.get("cohort_name"),
            "clone_fingerprint": persisted_clone.get("legs_fingerprint"),
            "strategy": persisted_clone.get("strategy"),
            "ticker": persisted_clone.get("ticker"),
            "window": persisted_clone.get("window"),
        },
        # simulated_fill describes the CLONE's own sizing, from VALIDATED
        # values (B21-C): prefer the validated top-level max_loss_total over
        # the JSON duplicate.
        "simulated_fill": {
            "contracts": p_order.get("contracts"),
            "limit_price": p_order.get("limit_price"),
            "max_loss_total": persisted_clone.get("max_loss_total"),
            "expected_fill_price": None,
            "expected_slippage": None,
            "spread_width": None,
        },
    }
    supabase.table("policy_decisions").upsert(
        [row], on_conflict="cohort_id,suggestion_id"
    ).execute()


def _write_prerejection_reject(
    supabase,
    user_id: str,
    cohort_id: Optional[str],
    source: Dict,
    reason: str,
    counts: Dict[str, int],
    errors: List[Dict[str, Any]],
) -> None:
    """Typed REJECTED verdict for a pre-rejection source that did not clone.
    A write failure increments reject_verdict_write_failed AND errors — a
    SECONDARY error on an already-refused attempt (B15): the terminal
    disposition remains the refusal and is never double-counted."""
    if not cohort_id:
        return
    try:
        supabase.table("policy_decisions").upsert([{
            "cohort_id": cohort_id,
            "suggestion_id": source.get("id"),
            "user_id": user_id,
            "decision": "rejected",
            # B24 — NULL rank: no ranking occurred.
            "rank_at_decision": None,
            "reason_codes": [reason],   # the specific typed refusal reason
            "features_snapshot": {
                **_build_features_snapshot(source),
                # B24 — the ineligible verdict has NO clone, so it constructs
                # the SAME narrow-scope + provenance contract directly from the
                # source + constants.
                "observation_scope": "raw_candidate_eligibility_only",
                "decision_semantics": "raw_candidate_eligibility",
                "selected_for_entry": False,
                "capacity_evaluated": False,
                "joint_rank_evaluated": False,
                "execution_state": "not_executed",
                "execution_intent": "internal_paper_only",
                "routing_intent": "shadow_only",
                "source_model_version": source.get("model_version"),
                "calibration_provenance_status": "not_persisted_on_source",
                "experiment_version": EXPERIMENT_VERSION,
            },
            "simulated_fill": _build_simulated_fill(source),
        }], on_conflict="cohort_id,suggestion_id").execute()
        counts["rejected_verdicts"] += 1   # B22 successful rejected verdict
    except Exception as e:
        counts["reject_verdict_write_failed"] += 1
        errors.append({
            "stage": "reject_verdict_upsert_failed",
            "ticker": source.get("ticker"),
            "source_suggestion_id": source.get("id"),
            "error_class": type(e).__name__, "error": str(e)[:200],
        })


def _get_cohort_portfolios(user_id: str, supabase) -> Dict[str, str]:
    """Map cohort_name → portfolio_id from policy_lab_cohorts."""
    try:
        res = supabase.table("policy_lab_cohorts") \
            .select("cohort_name, portfolio_id") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .execute()
        return {r["cohort_name"]: r["portfolio_id"] for r in (res.data or [])}
    except Exception:
        return {}


def _get_cohort_ids(user_id: str, supabase) -> Dict[str, str]:
    """Map cohort_name → cohort id (UUID) from policy_lab_cohorts.

    B16: RAISES on query failure — a fetch failure must stay distinguishable
    from a legitimately empty mapping; the caller types it into fork_errors
    so every prerejection attempt lands cohort_identity_missing (non-green)
    instead of silently reading an authoritative-empty {}."""
    res = supabase.table("policy_lab_cohorts") \
        .select("id, cohort_name") \
        .eq("user_id", user_id) \
        .eq("is_active", True) \
        .execute()
    return {r["cohort_name"]: r["id"] for r in (res.data or [])}


def _build_features_snapshot(suggestion: Dict) -> Dict:
    """Extract a features snapshot from a suggestion for decision logging.

    E19-2: carries EV PROVENANCE — ev_raw, the basis of the ev field, and
    the champion's rejection reason (when the row was calibrated-rejected) —
    so a stored verdict is interpretable without re-deriving which basis it
    was decided on."""
    sizing = suggestion.get("sizing_metadata") or {}
    return {
        "ev": suggestion.get("ev"),
        "ev_raw": suggestion.get("ev_raw"),
        "ev_basis": sizing.get("ev_basis"),
        "blocked_reason": suggestion.get("blocked_reason"),
        "probability_of_profit": suggestion.get("probability_of_profit"),
        "regime": suggestion.get("regime"),
        "model_version": suggestion.get("model_version"),
        "features_hash": suggestion.get("features_hash"),
        "strategy": suggestion.get("strategy"),
        "ticker": suggestion.get("ticker"),
        "window": suggestion.get("window"),
    }


def _build_simulated_fill(suggestion: Dict) -> Dict:
    """Extract simulated fill data from suggestion's TCM estimates."""
    tcm = suggestion.get("tcm") or {}
    order_json = suggestion.get("order_json") or {}
    sizing = suggestion.get("sizing_metadata") or {}
    return {
        "expected_fill_price": tcm.get("expected_fill_price"),
        "expected_slippage": tcm.get("expected_slippage"),
        "spread_width": tcm.get("spread_width"),
        "limit_price": order_json.get("limit_price"),
        "contracts": order_json.get("contracts"),
        "max_loss_total": sizing.get("max_loss_total"),
    }


def _log_cohort_decisions(
    supabase,
    user_id: str,
    cohort_name: str,
    cohort_id: Optional[str],
    decisions: List["CohortPolicyDecision"],
) -> None:
    """
    Persist one `policy_decisions` row per cohort decision.

    Consumes the CANONICAL evaluation (challengers: `_evaluate_cohort_policy`;
    champion: `_champion_accept_all`). It NEVER recomputes routing from ev /
    risk_adjusted_ev / score / thresholds — that was the F-A9-5 defect. The
    `reason_codes`, decision, and rank come straight from the evaluation.
    """
    if not cohort_id:
        logger.debug(f"policy_decision_log_skip: no cohort_id for {cohort_name}")
        return

    rows = []
    for d in decisions:
        rows.append({
            "cohort_id": cohort_id,
            "suggestion_id": d.suggestion_id,
            "user_id": user_id,
            "decision": "accepted" if d.accepted else "rejected",
            "rank_at_decision": d.rank,
            "reason_codes": list(d.reason_codes),
            "features_snapshot": _build_features_snapshot(d.suggestion),
            "simulated_fill": _build_simulated_fill(d.suggestion),
        })

    if not rows:
        return

    try:
        # Batch upsert — on_conflict handles re-runs on the same day
        supabase.table("policy_decisions").upsert(
            rows, on_conflict="cohort_id,suggestion_id"
        ).execute()
        logger.info(
            f"policy_decision_log: cohort={cohort_name} "
            f"total={len(rows)} accepted={sum(1 for r in rows if r['decision'] == 'accepted')} "
            f"rejected={sum(1 for r in rows if r['decision'] == 'rejected')}"
        )
    except Exception as e:
        logger.error(f"policy_decision_log_error: cohort={cohort_name} error={e}")
