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
from datetime import datetime, timezone, date
from typing import Dict, List, Optional, Any

from packages.quantum.policy_lab.config import (
    PolicyConfig,
    load_cohort_configs,
    is_policy_lab_enabled,
)
from packages.quantum.policy_lab.champion import get_current_champion

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
        "refused": 0, "clone_failed": 0, "verdict_failed": 0,
        "repaired": 0, "verdicts": 0,
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

    for s in source_suggestions:
        try:
            supabase.table("trade_suggestions").update({
                "cohort_name": champion_name,
            }).eq("id", s["id"]).execute()
        except Exception:
            pass  # Non-critical

    # Get cohort portfolio mapping and cohort IDs
    cohort_portfolios = _get_cohort_portfolios(user_id, supabase)
    cohort_ids = _get_cohort_ids(user_id, supabase)

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

        # Get cohort's current portfolio for capital-aware sizing
        port_res = supabase.table("paper_portfolios") \
            .select("cash_balance, net_liq") \
            .eq("id", portfolio_id) \
            .single() \
            .execute()
        portfolio = port_res.data or {}
        deployable = float(portfolio.get("net_liq") or portfolio.get("cash_balance") or 100000)

        # Count existing open positions for this cohort's portfolio
        open_pos_res = supabase.table("paper_positions") \
            .select("id", count="exact") \
            .eq("portfolio_id", portfolio_id) \
            .eq("status", "open") \
            .execute()
        open_count = open_pos_res.count or 0

        # Filter source suggestions by cohort policy
        filtered = _filter_for_cohort(source_suggestions, config, open_count)
        filtered_ids = {s["id"] for s in filtered}

        # Decision logging: log every (cohort, suggestion) decision
        _log_cohort_decisions(
            supabase, user_id, cohort_name, cohort_id,
            source_suggestions, filtered_ids, config, open_count,
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

        # ── E19-2: PRE-REJECTION PIPELINE (per source, recoverable order —
        # Blockers 2/3/4/10). For each calibrated-rejected source:
        # validate raw basis → build + raw-gate the clone → fail-CLOSED
        # lookup → insert (race-reconciled) → READ BACK the persisted row →
        # only then write the accepted verdict FROM the persisted clone.
        # Every failure is typed into fork_errors; a verdict-less clone is
        # repaired on the next run.
        for ps in prerejection_sources:
            _process_prerejection_source(
                supabase, user_id, cohort_name, cohort_id, ps,
                config, deployable, prerej_counts, fork_errors,
            )

        created[cohort_name] = cloned
        logger.info(
            f"policy_lab_fork: cohort={cohort_name} "
            f"source={len(source_suggestions)} filtered={len(filtered)} cloned={cloned} "
            f"prerejection={prerej_counts}"
        )

    # Log decisions for the champion cohort too (all accepted by default —
    # source suggestions ARE the champion's output, so every one is accepted).
    champion_cohort_id = cohort_ids.get(champion_name)
    if champion_cohort_id and source_suggestions:
        all_ids = {s["id"] for s in source_suggestions}
        _log_cohort_decisions(
            supabase, user_id, champion_name, champion_cohort_id,
            source_suggestions, all_ids,
            configs.get(champion_name, PolicyConfig()),
            0,  # champion doesn't filter by open positions at fork time
        )

    return _fork_result("ok", created, prerej_counts, fork_errors,
                        champion_tagged=len(source_suggestions))


def _fork_result(
    base_status: str,
    created: Dict[str, int],
    prerej_counts: Dict[str, int],
    fork_errors: List[Dict[str, Any]],
    champion_tagged: int = 0,
) -> Dict[str, Any]:
    """The explicit fork-result contract (Blocker 1). status degrades to
    'partial' whenever ANY experimental-path failure occurred — the champion
    outcome is reported separately so a green champion + broken experiment is
    visible as exactly that, never as 'ok'."""
    status = base_status
    if fork_errors and base_status == "ok":
        status = "partial"
    elif fork_errors and base_status == "no_source_suggestions":
        status = "partial"
    return {
        "status": status,
        "champion_status": base_status if base_status != "partial" else "ok",
        "champion_tagged": champion_tagged,
        "created": created,
        "existing": prerej_counts.get("existing", 0),
        "refused": prerej_counts.get("refused", 0),
        "errors": len(fork_errors),
        "error_details": fork_errors[:10],
        "prerejection_source_count": prerej_counts.get("source", 0),
        "prerejection_eligible_count": prerej_counts.get("eligible", 0),
        "prerejection_clone_count": (
            prerej_counts.get("created", 0) + prerej_counts.get("existing", 0)
        ),
        "prerejection_verdict_count": prerej_counts.get("verdicts", 0),
        "prerejection_counts": dict(prerej_counts),
    }


def _filter_for_cohort(
    suggestions: List[Dict],
    config: PolicyConfig,
    open_positions: int,
) -> List[Dict]:
    """Filter source suggestions by cohort's PolicyConfig."""
    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    filtered = []
    for s in suggestions:
        if len(filtered) >= max_new:
            break
        # #95 fix: read score (0-100 scale) from sizing_metadata, where it's
        # persisted at insert time by workflow_orchestrator.py. Was previously
        # reading risk_adjusted_ev (0-2 dollar-EV-per-dollar-risk ratio)
        # against min_score_threshold (0-100), a semantic mismatch that
        # filtered every non-aggressive cohort to zero clones across all
        # DB history. Missing-score → filtered out (safe default).
        sizing_metadata = s.get("sizing_metadata") or {}
        score_value = sizing_metadata.get("score")
        if score_value is None:
            continue
        if float(score_value) < config.min_score_threshold:
            continue
        filtered.append(s)

    return filtered


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

# Raw-gate typed reject reasons (Blocker 4).
_REJECT_MISSING_BASIS = "missing_ev_basis"
_REJECT_RAW_EDGE = "raw_edge_below_minimum"
_REJECT_RAW_RECOMPUTE = "raw_raev_recompute_failed"
_REJECT_RAW_INVALID = "raw_raev_invalid"


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
                _REJECT_MISSING_BASIS, errors)
            return

        # 2. Cohort policy (score) filter — not a divergence candidate for
        #    this cohort; typed rejected verdict, not an error.
        sizing_md = source.get("sizing_metadata") or {}
        score_value = sizing_md.get("score")
        if score_value is None or float(score_value) < config.min_score_threshold:
            _write_prerejection_reject(
                supabase, user_id, cohort_id, source,
                "filtered_by_policy", errors)
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
                reject_reason, errors)
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

        # 7. Verdict FROM the persisted clone. An accepted verdict with a
        #    missing or incompatible basis is forbidden.
        p_sizing = persisted.get("sizing_metadata") or {}
        if p_sizing.get("ev_basis") != "raw" or persisted.get("ev_raw") is None:
            counts["verdict_failed"] += 1
            _err("verdict_basis_incompatible",
                 RuntimeError(f"persisted basis={p_sizing.get('ev_basis')!r}"))
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
            counts["verdicts"] += 1
            if was_existing and not already_verdicted:
                counts["repaired"] += 1
        except Exception as ve:
            counts["verdict_failed"] += 1
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
    ELIGIBILITY GATE (Blocker 4). Returns (clone, None) on pass or
    (None, typed_reject_reason) on refusal.

    Raw gate: canonical compute_risk_adjusted_ev on the clone's OWN sized
    view with ev = ev_raw (the same cost/edge semantics as the champion
    ranker, portfolio-blind: positions=[], budget=0.0 -> concentration
    penalty 1.0). -999 sentinel -> raw fails the edge too (NOT a divergence
    case); exception -> typed recompute failure; None/non-finite -> typed
    invalid. No clone and no accepted verdict for any of those.
    """
    raw_ev = source.get("ev_raw")
    if raw_ev is None:
        return None, _REJECT_MISSING_BASIS

    base = _clone_suggestion_for_cohort(
        source, cohort_name, config, deployable_capital)
    if not base:
        return None, _REJECT_RAW_INVALID

    from packages.quantum.analytics.canonical_ranker import compute_risk_adjusted_ev
    raev_view = {**base, "ev": raw_ev}
    try:
        raw_raev = compute_risk_adjusted_ev(raev_view, [], 0.0)
    except Exception:
        return None, _REJECT_RAW_RECOMPUTE
    if raw_raev is None or not isinstance(raw_raev, (int, float)) \
            or not math.isfinite(float(raw_raev)):
        return None, _REJECT_RAW_INVALID
    raw_raev = round(float(raw_raev), 6)
    if raw_raev <= -999.0:
        return None, _REJECT_RAW_EDGE

    sizing = dict(base.get("sizing_metadata") or {})
    sizing.update({
        # EV provenance triple + identities (Blockers 3/5A): the basis is
        # explicit; execution is described by what ACTUALLY happened
        # (nothing) — never a claim about an intended event. The 07-13
        # cohort-semantics lesson: execution_mode is the broker-truth
        # discriminator, so this artifact does not carry one at all.
        "ev_basis": "raw",
        "raev_basis": "raw_portfolio_blind",
        "ev_calibrated": source.get("ev"),
        "calibration_identity": source.get("model_version"),
        "routing_intent": "shadow_only",
        "execution_state": "not_executed",
        "execution_intent": "internal_paper_only",
        "observation_scope": "entry_selection_only",
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
            f"raw-basis entry-selection observation only"
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


def _find_existing_clone(supabase, clone: Dict) -> Optional[Dict]:
    """Idempotency lookup mirroring the REAL active-row unique index
    (unique_suggestion_per_cycle_v3: user_id, window, cycle_date, ticker,
    strategy, legs_fingerprint WHERE status NOT IN dismissed/cancelled).
    RAISES on lookup failure — the caller fails CLOSED (Blocker 10)."""
    res = supabase.table("trade_suggestions") \
        .select("*") \
        .eq("user_id", clone.get("user_id")) \
        .eq("window", clone.get("window")) \
        .eq("cycle_date", clone.get("cycle_date")) \
        .eq("ticker", clone.get("ticker")) \
        .eq("strategy", clone.get("strategy")) \
        .eq("legs_fingerprint", clone.get("legs_fingerprint")) \
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
        "rank_at_decision": 1,
        "reason_codes": ["prerejection_shadow_observation"],
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
            "calibration_identity": p_sizing.get("calibration_identity"),
            "experiment_version": p_sizing.get("experiment_version"),
            "cohort_name": persisted_clone.get("cohort_name"),
            "clone_fingerprint": persisted_clone.get("legs_fingerprint"),
            "strategy": persisted_clone.get("strategy"),
            "ticker": persisted_clone.get("ticker"),
            "window": persisted_clone.get("window"),
        },
        # simulated_fill describes the CLONE's own sizing, never the source's
        "simulated_fill": {
            "contracts": p_order.get("contracts"),
            "limit_price": p_order.get("limit_price"),
            "max_loss_total": p_sizing.get("max_loss_total"),
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
    errors: List[Dict[str, Any]],
) -> None:
    """Typed REJECTED verdict for a pre-rejection source that did not clone.
    Write failure is typed into errors (never silent)."""
    if not cohort_id:
        return
    try:
        supabase.table("policy_decisions").upsert([{
            "cohort_id": cohort_id,
            "suggestion_id": source.get("id"),
            "user_id": user_id,
            "decision": "rejected",
            "rank_at_decision": 1,
            "reason_codes": [reason],
            "features_snapshot": _build_features_snapshot(source),
            "simulated_fill": _build_simulated_fill(source),
        }], on_conflict="cohort_id,suggestion_id").execute()
    except Exception as e:
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
    """Map cohort_name → cohort id (UUID) from policy_lab_cohorts."""
    try:
        res = supabase.table("policy_lab_cohorts") \
            .select("id, cohort_name") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .execute()
        return {r["cohort_name"]: r["id"] for r in (res.data or [])}
    except Exception:
        return {}


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
    all_suggestions: List[Dict],
    accepted_ids: set,
    config: PolicyConfig,
    open_positions: int,
) -> None:
    """
    Log a decision record for every (cohort, suggestion) pair.

    Called once per cohort during fork. Records whether each suggestion
    was accepted or rejected, with reason codes explaining why.
    """
    if not cohort_id:
        logger.debug(f"policy_decision_log_skip: no cohort_id for {cohort_name}")
        return

    available_slots = max(0, config.max_positions_open - open_positions)
    max_new = min(config.max_suggestions_per_day, available_slots)

    rows = []
    accepted_so_far = 0

    for rank, s in enumerate(all_suggestions, start=1):
        sid = s.get("id")
        ev = float(s.get("ev") or 0)

        # Determine decision and reasons
        if sid in accepted_ids:
            decision = "accepted"
            reason_codes = []
            accepted_so_far += 1
        else:
            # Figure out WHY it was rejected
            reason_codes = []
            if ev < config.min_score_threshold:
                reason_codes.append("ev_below_min")
            if accepted_so_far >= max_new:
                if open_positions >= config.max_positions_open:
                    reason_codes.append("max_positions_reached")
                else:
                    reason_codes.append("daily_limit_reached")
            if not reason_codes:
                reason_codes.append("filtered_by_policy")
            decision = "rejected"

        rows.append({
            "cohort_id": cohort_id,
            "suggestion_id": sid,
            "user_id": user_id,
            "decision": decision,
            "rank_at_decision": rank,
            "reason_codes": reason_codes,
            "features_snapshot": _build_features_snapshot(s),
            "simulated_fill": _build_simulated_fill(s),
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
