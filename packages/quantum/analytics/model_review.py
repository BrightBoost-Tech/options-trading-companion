"""Event-driven model-review lane (Lane J) — OBSERVE-ONLY.

When a NEW SCORABLE close is persisted (or a versioned sample boundary is
crossed), run the signed/read-only terminal-distribution comparison the ⑤
offline study runs — but EVENT-DRIVEN, not on any calendar cadence, and with
NO selector / ranker / gate / calibration mutation of any kind. The review's
only output surface is ``job_runs.result`` (written by the runner from the
handler's return); this module writes NOTHING else.

TWO SEAMS, ONE MODULE:
  1. DETECTOR (:func:`evaluate_and_maybe_enqueue_review`) — a fail-soft tail
     step of ``paper_learning_ingest`` (the same seam the streak breaker runs
     in): it enumerates the current SCORABLE population, fingerprints it, and
     enqueues exactly ONE ``model_review_event`` job (background queue, origin
     ``event`` / ``new_scorable_close``) — suppressed when a same-fingerprint
     review already ran. It NEVER raises: an error returns a structured status.
  2. REVIEW HANDLER BODY (:func:`run_review`) — invoked by
     ``jobs/handlers/model_review_event.py``: re-fetches the scorable rows for
     the fingerprint's authoritative id-set and runs ``build_study`` (live vs
     shadow cohorts SEPARATE), serializing a compact truth surface into the
     return dict.

SCORABILITY (reuse the study's marker-gated linkage semantics, no drift): a
closed outcome is SCORABLE iff its OPENING order carried the ⑤ stage-seam
capture — ``entry_underlying_spot`` POPULATED **and** every geometry leg has a
captured per-leg IV **and** a captured per-leg delta. We do not re-implement
that gate: we run the study's own ``to_foundation_row`` mapper and read back
the fields it emits (``spot`` set, and every leg carrying ``iv`` + ``delta``),
so "scorable" here is defined EXACTLY as the frozen adapter (needs delta) and
the lognormal challenger (needs spot + IV) consume it. Historical rows have no
captured markers → not scorable → never trigger a review (H9: never
backfilled/defaulted).

IMPORT-LOCK NOTE: the terminal-distribution package is observe-only and the
full-tree import-lock forbids any production module under packages/quantum from
naming it. This module therefore reaches the models ONLY through
``scripts.analytics.challenger_study`` (which lives outside packages/quantum and
is the canonical study assembly) — never the package directly. The string that
names the package must not appear in this file.

DEDUP (smallest honest key, NO new table): the scorable-set CONTENT fingerprint
(sorted record ids + frozen model-set version, mirroring #1119's content
fingerprint). It is durable three ways: (a) it is the enqueue idempotency key,
so ``enqueue_job_run``'s ``create_or_get`` dedups a re-enqueue; (b) the detector
pre-checks recent ``model_review_event`` ``job_runs.result``/``payload`` for the
fingerprint and suppresses; (c) a NEW scorable close changes the id-set → a new
fingerprint → a fresh review (edge-triggered). Repeated ingests with no new
scorable close re-compute the SAME fingerprint → suppressed, never a job storm.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.analytics.learning_read_filter import partition_trusted_rows

logger = logging.getLogger(__name__)

MODEL_REVIEW_JOB_NAME = "model_review_event"

# Read-cap on the v3 outcome scan. Observe-only + current scale is ~100 rows;
# generous so the dedup-by-suggestion never silently truncates the population.
_MAX_OUTCOMES = int(os.getenv("MODEL_REVIEW_MAX_OUTCOMES", "5000"))

# How many recent model_review_event job_runs the detector scans for the
# fingerprint pre-check + the prior scorable-count (for boundary crossing).
_PRIOR_REVIEW_SCAN = int(os.getenv("MODEL_REVIEW_PRIOR_SCAN", "200"))

# The stage-seam capture marker that identifies an OPENING order (written
# EXCLUSIVELY on the OPEN path; closes are capture-exempt). Same key the study
# SQL gates on (``order_json ? 'entry_underlying_spot'``).
_OPEN_CAPTURE_MARKER = "entry_underlying_spot"

# F-CREDIT-SIGN correction marker on the LFL row (mirrors STUDY_SQL's LATERAL).
_CORRECTED_MARKER = "f_credit_sign_correction"


def _sample_boundaries() -> Tuple[int, ...]:
    """Versioned scorable-count boundaries at which a review stamps a crossing.
    Parameterized off EXISTING conventions — NOT invented: the 8th-live-close
    convergence (#1051 raw-mode exit + clamp/winsorize review) and the Phase-3
    10-15-fills gate. Env override ``MODEL_REVIEW_SAMPLE_BOUNDARIES``."""
    raw = os.getenv("MODEL_REVIEW_SAMPLE_BOUNDARIES", "8,10,15")
    out: List[int] = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(sorted(set(out)))


def _model_set_version() -> str:
    from scripts.analytics.challenger_study import MODEL_SET_VERSION
    return MODEL_SET_VERSION


# ── row fetch: STUDY_SQL mirrored through the supabase client ──────────────
# STUDY_SQL (scripts/analytics/challenger_study.py) is the canonical read, but
# it is raw SQL an operator runs; the worker has only the PostgREST client, so
# the linkage is mirrored here. Kept structurally 1:1 with STUDY_SQL (dedup by
# suggestion / latest close · suggestion legs are the geometry authority · the
# OPEN-order marker gate for captured inputs · the corrected LATERAL) and pinned
# by test_model_review_event. READ-ONLY: only .select() calls, no writes.
def _fmt_known_at(ts: Any) -> str:
    """Format a v3 timestamp to the study's known_at shape. to_foundation_row
    only consumes the date (known_at[:10]); we still emit full ISO-Z when we
    can parse it, and pass strings through untouched otherwise."""
    if ts is None:
        return ""
    if isinstance(ts, datetime):
        return ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(ts)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return s


def _num(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _staged_key(order: Dict[str, Any]) -> str:
    # earliest-staged wins (STUDY_SQL: ORDER BY staged_at ASC NULLS LAST).
    return str(order.get("staged_at") or "~")  # '~' sorts after real ISO stamps


def fetch_study_rows(client: Any, *, max_outcomes: int = _MAX_OUTCOMES) -> Dict[str, Dict[str, Any]]:
    """Build the STUDY_SQL-shaped row set keyed by record_id (suggestion id).
    Read-only. Returns {} on an empty population. Faithful mirror of STUDY_SQL."""
    # 1. v3 outcomes → dedup by suggestion_id keeping the latest close.
    v3 = (
        client.table("learning_trade_outcomes_v3")
        .select(
            "suggestion_id, is_paper, strategy, regime, entry_ts, closed_at, "
            "pnl_realized, pop_predicted, ev_predicted"
        )
        .order("closed_at", desc=True)
        .limit(max_outcomes)
        .execute()
    )
    ded: Dict[str, Dict[str, Any]] = {}
    for r in (getattr(v3, "data", None) or []):
        sid = r.get("suggestion_id")
        if sid and sid not in ded:  # desc order → first seen is latest close
            ded[sid] = r
    sids = list(ded.keys())
    if not sids:
        return {}

    # 2. trade_suggestions → geometry legs (authority), premium, contracts.
    ts_rows = (
        client.table("trade_suggestions")
        .select("id, order_json, created_at")
        .in_("id", sids)
        .execute()
    )
    ts_by_id = {t["id"]: t for t in (getattr(ts_rows, "data", None) or [])}

    # 3. OPENING orders carrying the stage-seam capture marker → captured inputs.
    po_rows = (
        client.table("paper_orders")
        .select("suggestion_id, order_json, staged_at")
        .in_("suggestion_id", sids)
        .execute()
    )
    open_by_sid: Dict[str, Dict[str, Any]] = {}
    for po in (getattr(po_rows, "data", None) or []):
        oj = po.get("order_json") or {}
        if _OPEN_CAPTURE_MARKER not in oj:  # marker gate == OPEN by construction
            continue
        sid = po.get("suggestion_id")
        if not sid:
            continue
        prev = open_by_sid.get(sid)
        if prev is None or _staged_key(po) < _staged_key(prev):
            open_by_sid[sid] = po

    # 4. F-CREDIT-SIGN corrected flag (LATERAL EXISTS mirror). Routed through the
    #    #1042 learning quarantine (partition_trusted_rows): the credit-sign
    #    correction marker rides on the REAL trade_closed / individual_trade
    #    outcome row, so a synthetic / historical (historical_win / aggregate)
    #    row must never set a live/paper study outcome's `corrected` display
    #    flag. Fail-closed allowlist (semantically correct, not mere compliance);
    #    it also logs the excluded-row count. Selecting outcome_type so the
    #    partition can see it.
    corrected_sids: set = set()
    lfl = (
        client.table("learning_feedback_loops")
        .select("suggestion_id, outcome_type, details_json")
        .in_("suggestion_id", sids)
        .execute()
    )
    lfl_trusted = partition_trusted_rows(
        getattr(lfl, "data", None) or [],
        reader="model_review.corrected_flag",
    )
    for r in lfl_trusted:
        dj = r.get("details_json") or {}
        sid = r.get("suggestion_id")
        if sid and isinstance(dj, dict) and _CORRECTED_MARKER in dj:
            corrected_sids.add(sid)

    out: Dict[str, Dict[str, Any]] = {}
    for sid, d in ded.items():
        ts = ts_by_id.get(sid)
        if not ts:  # INNER JOIN trade_suggestions semantics
            continue
        oj = ts.get("order_json") or {}
        legs = oj.get("legs")
        if not legs:  # no geometry → unmappable by construction
            continue
        open_oj = (open_by_sid.get(sid) or {}).get("order_json") or {}
        rid = str(sid)
        out[rid] = {
            "record_id": rid,
            "is_paper": d.get("is_paper"),
            "strategy": d.get("strategy"),
            "regime": d.get("regime") or "unknown",
            "known_at": _fmt_known_at(d.get("entry_ts") or ts.get("created_at")),
            "realized_pnl": _num(d.get("pnl_realized")),
            "pop_pred": _num(d.get("pop_predicted")),
            "ev_pred": _num(d.get("ev_predicted")),
            "net_premium": _num(oj.get("limit_price")),
            "contracts": int(oj.get("contracts") or 1),
            "corrected": sid in corrected_sids,
            "legs": legs,
            "captured_legs": open_oj.get("legs"),
            "entry_underlying_spot": open_oj.get(_OPEN_CAPTURE_MARKER),
        }
    return out


def is_scorable_row(db_row: Dict[str, Any]) -> bool:
    """Scorable iff BOTH models can score: spot present AND every geometry leg
    carries a captured iv AND delta. Defined via the study's own mapper so the
    predicate never drifts from what the models consume. A structurally
    unmappable row (bad OCC / unknown strategy / missing premium) is NOT
    scorable — exactly as build_study would skip it."""
    try:
        from scripts.analytics.challenger_study import to_foundation_row
        frow, _preds = to_foundation_row(db_row)
    except Exception:
        return False
    if frow.get("spot") is None:
        return False
    legs = frow.get("legs") or []
    if not legs:
        return False
    return all(("iv" in leg and "delta" in leg) for leg in legs)


def scorable_record_ids(rows_by_id: Dict[str, Dict[str, Any]]) -> List[str]:
    return sorted(rid for rid, row in rows_by_id.items() if is_scorable_row(row))


def scorable_fingerprint(record_ids: List[str], model_version: str) -> str:
    """Content fingerprint of the scorable SET (sorted ids ⊕ model version).
    A stable identity: same set + same models → same fingerprint (suppressed);
    a new scorable close changes the set → a new fingerprint (fresh review)."""
    h = hashlib.sha256()
    h.update(model_version.encode("utf-8"))
    for rid in sorted(record_ids):
        h.update(b"\x00")
        h.update(str(rid).encode("utf-8"))
    return h.hexdigest()


def _prior_reviews(client: Any) -> Tuple[set, int]:
    """Scan recent model_review_event job_runs for (a) already-seen fingerprints
    (from result AND payload — covers completed AND still-pending reviews) and
    (b) the max prior scorable_count (for boundary-crossing detection).
    Read-only; a query error fails toward NOT-suppressing (the enqueue
    idempotency key is the durable backstop)."""
    seen: set = set()
    max_prior = 0
    try:
        res = (
            client.table("job_runs")
            .select("payload, result, status")
            .eq("job_name", MODEL_REVIEW_JOB_NAME)
            .order("created_at", desc=True)
            .limit(_PRIOR_REVIEW_SCAN)
            .execute()
        )
        for row in (getattr(res, "data", None) or []):
            for blob_key in ("result", "payload"):
                blob = row.get(blob_key)
                if not isinstance(blob, dict):
                    continue
                fp = blob.get("fingerprint")
                if isinstance(fp, str) and fp:
                    seen.add(fp)
                cnt = blob.get("scorable_count")
                try:
                    if cnt is not None and int(cnt) > max_prior:
                        max_prior = int(cnt)
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        logger.info("[MODEL_REVIEW] prior-review scan failed (non-fatal): %s", e)
    return seen, max_prior


def _boundaries_crossed(prior_count: int, current_count: int) -> List[int]:
    """Versioned sample boundaries newly crossed on this event: b in
    (prior_count, current_count]. Empty when no boundary is between the two."""
    return [b for b in _sample_boundaries() if prior_count < b <= current_count]


def evaluate_and_maybe_enqueue_review(client: Any) -> Dict[str, Any]:
    """DETECTOR (learning-ingest tail step). Enumerate the scorable population,
    fingerprint it, and enqueue exactly ONE observe-only review — suppressed on
    a same-fingerprint prior review. NEVER raises: any failure returns a
    structured status so the ingest job's result always carries model_review.
    Enqueues at most ONCE per call (no job storm)."""
    try:
        rows_by_id = fetch_study_rows(client)
        ids = scorable_record_ids(rows_by_id)
        if not ids:
            return {"status": "no_scorable_closes", "enqueued": False,
                    "scorable_count": 0}

        model_version = _model_set_version()
        fingerprint = scorable_fingerprint(ids, model_version)

        seen, prior_count = _prior_reviews(client)
        crossed = _boundaries_crossed(prior_count, len(ids))

        if fingerprint in seen:
            return {"status": "suppressed_duplicate", "enqueued": False,
                    "scorable_count": len(ids), "fingerprint": fingerprint}

        payload = {
            "fingerprint": fingerprint,
            "model_version": model_version,
            "scorable_record_ids": ids,
            "scorable_count": len(ids),
            "prior_scorable_count": prior_count,
            "boundary_crossed": crossed,
        }
        try:
            from packages.quantum.public_tasks import enqueue_job_run
            from packages.quantum.jobs.rq_enqueue import BACKGROUND_QUEUE
            from packages.quantum.jobs.origin import build_event_origin

            enq = enqueue_job_run(
                job_name=MODEL_REVIEW_JOB_NAME,
                idempotency_key=f"model_review-{fingerprint}",
                payload=payload,
                queue_name=BACKGROUND_QUEUE,
                origin=build_event_origin("new_scorable_close"),
            )
        except Exception as e:
            logger.error("[MODEL_REVIEW] enqueue failed (non-fatal): %s", e)
            return {"status": "enqueue_failed", "enqueued": False,
                    "scorable_count": len(ids), "fingerprint": fingerprint,
                    "error": str(e)[:200]}

        return {
            "status": enq.get("status", "queued") if isinstance(enq, dict) else "queued",
            "enqueued": True,
            "scorable_count": len(ids),
            "fingerprint": fingerprint,
            "boundary_crossed": crossed,
            "job_run_id": enq.get("job_run_id") if isinstance(enq, dict) else None,
            "queue": BACKGROUND_QUEUE,
        }
    except Exception as e:  # detector is fail-soft — never breaks the ingest
        logger.error("[MODEL_REVIEW] detector failure (non-fatal): %s", e)
        return {"status": "error", "enqueued": False, "error": str(e)[:200]}


# ── review handler body ────────────────────────────────────────────────────
def _abstain(report: Any) -> Dict[str, int]:
    from scripts.analytics.challenger_study import _abstain_hist
    return _abstain_hist(report)


def _model_metrics(r: Any) -> Dict[str, Any]:
    return {
        "scored": r.scored,
        "eligible": r.eligible,
        "abstained": r.abstained,
        "coverage": r.coverage,
        "brier": r.brier,
        "ev_rmse": r.ev_rmse,
        "realized_net": r.realized_net,
        "censored": r.censored,
        "malformed": r.malformed,
        "abstain_reasons": _abstain(r),
    }


def _h2h(x: Any) -> Dict[str, Any]:
    return {
        "n_joint": x.n_joint,
        "brier_a": x.brier_a,
        "brier_b": x.brier_b,
        "ev_rmse_a": x.ev_rmse_a,
        "ev_rmse_b": x.ev_rmse_b,
    }


def _compact_cohort(c: Any) -> Dict[str, Any]:
    return {
        "cohort": c.cohort,
        "is_paper": c.is_paper,
        "n_rows": c.n_rows,
        "n_corrected": c.n_corrected,
        "n_unmappable_skips": len(c.skipped),
        "models": {
            "baseline_stored": _model_metrics(c.baseline),
            "frozen_adapter": _model_metrics(c.adapter),
            "lognormal_challenger": _model_metrics(c.challenger),
        },
        "head_to_head": {
            "baseline_vs_challenger": _h2h(c.h2h_baseline_challenger),
            "adapter_vs_challenger": _h2h(c.h2h_adapter_challenger),
        },
    }


def run_review(client: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    """REVIEW HANDLER BODY. Re-fetch the scorable rows for the fingerprint's
    authoritative id-set (payload.scorable_record_ids), run the study
    (live vs shadow SEPARATE), and return the compact truth surface. OBSERVE-
    ONLY: this writes nothing — the runner persists the RETURN into
    job_runs.result. A fetch/study error returns counts.errors>0 so the runner
    classifies the run 'partial' (visible, terminal — never a mutation, never a
    retry storm)."""
    payload = payload or {}
    fingerprint = payload.get("fingerprint")
    model_version = payload.get("model_version") or _model_set_version()
    record_ids = list(payload.get("scorable_record_ids") or [])
    base = {
        "ok": False,
        "observe_only": True,
        "fingerprint": fingerprint,
        "model_version": model_version,
        "boundary_crossed": payload.get("boundary_crossed") or [],
        "counts": {"errors": 0},
    }

    try:
        rows_by_id = fetch_study_rows(client)
    except Exception as e:
        logger.error("[MODEL_REVIEW] handler fetch failed: %s", e)
        base["counts"]["errors"] = 1
        base["error"] = f"fetch_failed: {str(e)[:200]}"
        return base

    if record_ids:
        # Authoritative set = exactly the fingerprint's ids (so the review
        # covers the set the fingerprint was computed over, even if the
        # population shifted between enqueue and run).
        rows = [rows_by_id[r] for r in record_ids if r in rows_by_id]
    else:
        rows = [rows_by_id[r] for r in scorable_record_ids(rows_by_id)]

    scorable_count = len(rows)
    try:
        from scripts.analytics.challenger_study import build_study, render_markdown
        study_payload = {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "source": "event:new_scorable_close (Lane J observe-only review)",
            "rows": rows,
        }
        study = build_study(study_payload)
        markdown = render_markdown(study)
    except Exception as e:
        logger.error("[MODEL_REVIEW] handler study failed: %s", e)
        base["counts"]["errors"] = 1
        base["error"] = f"study_failed: {str(e)[:200]}"
        base["scorable_count"] = scorable_count
        return base

    return {
        "ok": True,
        "observe_only": True,
        "fingerprint": fingerprint,
        "model_version": model_version,
        "scorable_count": scorable_count,
        "scorable_record_ids": record_ids,
        "boundary_crossed": payload.get("boundary_crossed") or [],
        "sample_boundaries": list(_sample_boundaries()),
        "total_rows": study.total_rows,
        "cohorts": [_compact_cohort(c) for c in study.cohorts],
        "report_markdown": markdown,
        "counts": {"errors": 0},
    }
