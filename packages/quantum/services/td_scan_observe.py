"""⑤ Terminal-distribution score-on-scan observer — enqueue + child body.

OBSERVE-ONLY. Two seams, one module (mirrors the model_review trio):

  1. ENQUEUE (:func:`maybe_enqueue_td_scan_observe`) — a fail-soft tail step of
     ``suggestions_open`` (the same tail the single-leg shadow child rides). Only
     a scheduler-origin parent with a complete, durably-committed decision tape
     may enqueue exactly ONE ``td_scan_score_observe`` job (background queue) —
     the tape's ``source_decision_id`` is the SAME cycle_id the scan-time capture
     stamped on its envelopes, so the child scores exactly that cycle. Gated on
     the observe-only flag (default OFF). Idempotent per source decision.

  2. CHILD BODY (:func:`run_td_scan_score_observe`) — reads the cycle's captured
     envelopes, scores each (current frozen baseline vs lognormal challenger)
     via the ``scripts.analytics`` scorer, computes ranks over the identical set,
     joins outcomes read-time for the executed-and-closed subset, and upserts one
     row per candidate into ``td_scan_scores``. Fail-soft; a missing table is a
     typed no-op; one candidate's failure never erases its siblings; it never
     gates / ranks / sizes / stages / submits a live decision.

IMPORT-LOCK: this module NEVER imports or names the observe-only scoring package
— it reaches the models ONLY through ``scripts.analytics.td_scan_scorer`` (which
lives outside packages/quantum), exactly as ``model_review_event`` reaches them
through ``model_review.run_review``. Prose says "terminal-distribution" (hyphen).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

from packages.quantum.services.td_scan_capture import (
    ENVELOPE_TABLE,
    td_scan_observe_enabled,
)

logger = logging.getLogger(__name__)

JOB_NAME = "td_scan_score_observe"
SCORES_TABLE = "td_scan_scores"
NATURAL_PARENT_ORIGIN = "scheduler"

# Top-N membership window for the rank-delta counterfactual (the small-tier
# executor's per-cycle candidate cap; observe-only, tunable, never a gate).
_TOP_N = int(os.getenv("TD_SCAN_TOP_N", "4") or "4")

# Read cap on envelopes per cycle (generous; observe-only).
_MAX_ENVELOPES = int(os.getenv("TD_SCAN_MAX_ENVELOPES", "5000") or "5000")

_TABLE_MISSING_MARKERS = ("pgrst205", "42p01", "could not find the table")


def _is_table_missing_error(exc: BaseException, table: str) -> bool:
    msg = str(exc).lower()
    if any(m in msg for m in _TABLE_MISSING_MARKERS):
        return True
    return "does not exist" in msg and table in msg


def _rows(result: Any) -> List[Dict[str, Any]]:
    data = getattr(result, "data", None)
    return [dict(r) for r in data] if isinstance(data, list) else []


# ── 1. ENQUEUE (suggestions_open tail) ──────────────────────────────────────
def maybe_enqueue_td_scan_observe(
    client: Any,
    *,
    user_id: str,
    source_job_run_id: Optional[str],
    source_decision_id: Optional[str],
    source_code_sha: Optional[str],
    as_of: Optional[str],
    parent_origin: Optional[str],
    enqueue_fn: Optional[Callable[..., Dict[str, Any]]] = None,
    origin_builder: Optional[Callable[..., Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Enqueue one observe-only scoring child for a complete natural parent
    decision. The flag read happens FIRST so a dark deployment is a true no-op.
    Only the scheduler origin is admitted; a complete tape's decision_id is
    required (it is the cycle_id the capture stamped). NEVER raises."""
    try:
        if not td_scan_observe_enabled():
            return {"status": "flag_disabled", "enqueued": False, "errors": 0}
        if str(parent_origin or "") != NATURAL_PARENT_ORIGIN:
            return {"status": "non_natural_parent", "enqueued": False, "errors": 0}
        required = {
            "source_job_run_id": source_job_run_id,
            "source_decision_id": source_decision_id,
            "user_id": user_id,
            "as_of": as_of,
        }
        missing = sorted(k for k, v in required.items() if not str(v or "").strip())
        if missing:
            # No decision tape (REPLAY off) → no cycle_id to correlate envelopes;
            # a true no-op, not an error (the capture simply won't be scored).
            return {"status": "source_identity_missing", "enqueued": False,
                    "errors": 0, "missing": missing}

        if enqueue_fn is None:
            from packages.quantum.public_tasks import enqueue_job_run as enqueue_fn
        if origin_builder is None:
            from packages.quantum.jobs.origin import build_event_origin as origin_builder
        try:
            from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE
        except Exception:
            # The background queue name is a stable literal; fall back to it so
            # an unavailable rq (e.g. a fork-context-less test host) never blocks
            # this observe-only enqueue. Production imports the real constant.
            BACKGROUND_QUEUE = "background"

        payload = {
            "source_job_run_id": str(source_job_run_id),
            "source_decision_id": str(source_decision_id),
            "source_code_sha": source_code_sha,
            "source_as_of": str(as_of),
            "user_id": str(user_id),
        }
        enqueued = enqueue_fn(
            job_name=JOB_NAME,
            idempotency_key=f"{JOB_NAME}:{source_decision_id}",
            payload=payload,
            queue_name=BACKGROUND_QUEUE,
            origin=origin_builder(
                "td_scan_score_after_decision",
                parent_job_run_id=str(source_job_run_id),
            ),
        )
        result = enqueued if isinstance(enqueued, dict) else {}
        terminal_skip = bool(result.get("skipped"))
        actually_queued = bool(result.get("rq_job_id")) and not terminal_skip
        return {
            "status": result.get("status", "queued"),
            "enqueued": actually_queued,
            "errors": 0,
            "job_run_id": result.get("job_run_id"),
            "rq_job_id": result.get("rq_job_id"),
            "skipped": terminal_skip,
        }
    except Exception as exc:
        logger.exception("td-scan-observe child enqueue failed")
        return {"status": "enqueue_failed", "enqueued": False, "errors": 1,
                "error": f"{type(exc).__name__}: {str(exc)[:200]}"}


# ── 2. CHILD BODY (background handler delegates here) ────────────────────────
def _read_envelopes(client: Any, cycle_id: str) -> List[Dict[str, Any]]:
    """Read the cycle's captured envelopes. Read-only. A missing table raises to
    the caller (classified table_missing → typed no-op)."""
    res = (
        client.table(ENVELOPE_TABLE)
        .select("cycle_id, cycle_date, user_id, symbol, strategy, strategy_key, "
                "candidate_fingerprint, emitted, reject_reason, reject_gate, "
                "known_at, envelope")
        .eq("cycle_id", cycle_id)
        .limit(_MAX_ENVELOPES)
        .execute()
    )
    return _rows(res)


def _link_outcome(client: Any, fingerprint: str) -> Dict[str, Any]:
    """Read-time outcome linkage (§6): fingerprint == trade_suggestions.
    legs_fingerprint → suggestion_id → learning_trade_outcomes_v3.pnl_realized,
    cohort-split by is_paper. Real label ONLY for an executed-and-closed
    candidate; a persisted-not-closed one is 'open'; everything else stays
    'counterfactual_unmarkable' with realized fields NULL — never fabricated.
    Fail-soft: any read error returns the unmarkable default (never conflates)."""
    default = {"outcome_status": "counterfactual_unmarkable", "suggestion_id": None,
               "realized_pnl": None, "realized_win": None, "is_paper": None,
               "execution_mode": None}
    try:
        sug = (
            client.table("trade_suggestions")
            .select("id, execution_mode")
            .eq("legs_fingerprint", fingerprint)
            .limit(1)
            .execute()
        )
        srows = _rows(sug)
        if not srows:
            return default
        sid = srows[0].get("id")
        execution_mode = srows[0].get("execution_mode")
        v3 = (
            client.table("learning_trade_outcomes_v3")
            .select("suggestion_id, pnl_realized, is_paper, closed_at")
            .eq("suggestion_id", sid)
            .order("closed_at", desc=True)
            .limit(1)
            .execute()
        )
        vrows = _rows(v3)
        if not vrows:
            # Persisted (suggestion exists) but no closed outcome yet.
            return {**default, "outcome_status": "open", "suggestion_id": sid,
                    "execution_mode": execution_mode}
        row = vrows[0]
        pnl = row.get("pnl_realized")
        realized_win = (float(pnl) > 0.0) if pnl is not None else None
        return {
            "outcome_status": "resolved",
            "suggestion_id": sid,
            "realized_pnl": (float(pnl) if pnl is not None else None),
            "realized_win": realized_win,
            "is_paper": row.get("is_paper"),
            "execution_mode": execution_mode,
        }
    except Exception as exc:
        logger.debug("[TD_SCAN_OBSERVE] outcome linkage skipped (non-fatal): %s", exc)
        return default


def _score_row(env_row: Dict[str, Any], scored: Dict[str, Any]) -> Dict[str, Any]:
    """Assemble ONE td_scan_scores row from an envelope row + its scoring dict."""
    baseline = scored.get("baseline") or {}
    challenger = scored.get("challenger") or {}
    return {
        "cycle_id": env_row.get("cycle_id"),
        "cycle_date": env_row.get("cycle_date"),
        "user_id": env_row.get("user_id"),
        "symbol": env_row.get("symbol"),
        "strategy": env_row.get("strategy"),
        "candidate_fingerprint": env_row.get("candidate_fingerprint"),
        "challenger_model_version": scored.get("challenger_model_version"),
        "emitted": bool(env_row.get("emitted")),
        "reject_reason": env_row.get("reject_reason"),
        "reject_gate": env_row.get("reject_gate"),
        "basis": scored.get("basis", "raw"),
        "contracts_basis": scored.get("contracts_basis", 1),
        "envelope": env_row.get("envelope"),
        "baseline_pop": baseline.get("pop"),
        "baseline_ev": baseline.get("ev"),
        "baseline_model": baseline.get("model"),
        "baseline_abstain_reason": baseline.get("abstain_reason"),
        "challenger_pop": challenger.get("pop"),
        "challenger_ev": challenger.get("ev"),
        "challenger_model": challenger.get("model"),
        "challenger_abstain_reason": challenger.get("abstain_reason"),
        "production_pop": scored.get("production_pop"),
        "production_ev": scored.get("production_ev"),
        "current_rank": scored.get("current_rank"),
        "challenger_rank": scored.get("challenger_rank"),
        "rank_delta": scored.get("rank_delta"),
        "current_topn": scored.get("current_topn"),
        "challenger_topn": scored.get("challenger_topn"),
        "topn_delta": scored.get("topn_delta"),
        "gate_counterfactuals": scored.get("gate_counterfactuals"),
        "provenance": scored.get("provenance"),
    }


def run_td_scan_score_observe(
    client: Any,
    payload: Dict[str, Any],
    *,
    scorer: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
    ranker: Optional[Callable[..., None]] = None,
) -> Dict[str, Any]:
    """CHILD BODY. Read the cycle's envelopes, score each vs the frozen baseline
    + lognormal challenger, rank over the identical set, link outcomes, and
    upsert the scores. OBSERVE-ONLY, fail-soft, one-failure-isolated. Returns a
    compact typed result; counts.errors>0 marks the run 'partial'."""
    payload = payload or {}
    cycle_id = str(payload.get("source_decision_id") or "").strip()
    counts = {"envelopes": 0, "scored": 0, "written": 0,
              "resolved": 0, "counterfactual": 0, "errors": 0,
              "table_missing_noops": 0}
    base = {"ok": False, "observe_only": True, "job": JOB_NAME,
            "cycle_id": cycle_id, "counts": counts}

    if not cycle_id:
        counts["errors"] = 1
        base["status"] = "source_decision_missing"
        return base

    if scorer is None:
        # Kept OUTSIDE packages/quantum so the observe-only import lock stays
        # one-way (the handler/service never name the package).
        from scripts.analytics.td_scan_scorer import score_envelope as scorer
    if ranker is None:
        from scripts.analytics.td_scan_scorer import rank_scored_set as ranker

    try:
        env_rows = _read_envelopes(client, cycle_id)
    except Exception as exc:
        if _is_table_missing_error(exc, ENVELOPE_TABLE):
            counts["table_missing_noops"] += 1
            base["ok"] = True
            base["status"] = "envelope_table_missing"
            return base
        counts["errors"] = 1
        base["status"] = "envelope_read_failed"
        base["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        return base

    counts["envelopes"] = len(env_rows)
    if not env_rows:
        base["ok"] = True
        base["status"] = "no_envelopes"
        return base

    # Score each candidate (one failure never erases siblings).
    scored_list: List[Dict[str, Any]] = []
    per_env: List[Dict[str, Any]] = []
    for env_row in env_rows:
        try:
            env = env_row.get("envelope") or {}
            # carry the durable disposition onto the scorable envelope
            env = {**env, "emitted": env_row.get("emitted"),
                   "reject_reason": env_row.get("reject_reason"),
                   "reject_gate": env_row.get("reject_gate")}
            scored = scorer(env)
            scored_list.append(scored)
            per_env.append(env_row)
            counts["scored"] += 1
        except Exception as exc:
            counts["errors"] += 1
            logger.warning("[TD_SCAN_OBSERVE] scoring a candidate failed "
                           "(non-fatal, siblings continue): %s", exc)
            continue

    if not scored_list:
        base["status"] = "nothing_scored"
        return base

    # Ranks over the identical scored set (pure, cross-candidate).
    try:
        ranker(scored_list, top_n=_TOP_N)
    except Exception as exc:
        counts["errors"] += 1
        logger.warning("[TD_SCAN_OBSERVE] ranking failed (non-fatal): %s", exc)

    # Assemble rows + read-time outcome linkage; upsert one per candidate.
    written = 0
    for env_row, scored in zip(per_env, scored_list):
        try:
            row = _score_row(env_row, scored)
            outcome = _link_outcome(client, str(env_row.get("candidate_fingerprint")))
            row.update(outcome)
            if outcome.get("outcome_status") == "resolved":
                counts["resolved"] += 1
            else:
                counts["counterfactual"] += 1
            try:
                (
                    client.table(SCORES_TABLE)
                    .upsert(row, on_conflict="cycle_id,candidate_fingerprint,challenger_model_version")
                    .execute()
                )
                written += 1
            except Exception as wexc:
                if _is_table_missing_error(wexc, SCORES_TABLE):
                    counts["table_missing_noops"] += 1
                    base["ok"] = True
                    base["status"] = "scores_table_missing"
                    base["counts"]["written"] = written
                    return base
                counts["errors"] += 1
                logger.warning("[TD_SCAN_OBSERVE] score upsert failed "
                               "(non-fatal): %s", wexc)
        except Exception as exc:
            counts["errors"] += 1
            logger.warning("[TD_SCAN_OBSERVE] row assembly failed (non-fatal): %s", exc)
            continue

    counts["written"] = written
    base["ok"] = counts["errors"] == 0
    base["status"] = "scored"
    base["model_version"] = scored_list[0].get("challenger_model_version") if scored_list else None
    base["top_n"] = _TOP_N
    return base
