"""Monday natural-evidence CONSOLIDATED reader (OBSERVE-ONLY, operator-invoked,
READ-ONLY).

ONE signed CLI that, for a single ``cycle_date``, consolidates the natural
evidence a trading-day cycle accrues across twelve mostly-independent sinks into
a stable JSON snapshot + a concise markdown report. It exists so the Monday
morning operator reads ONE artifact instead of running twelve ad-hoc queries the
day the sinks first carry real rows.

WHY A READ/AGGREGATE CLI (mirrors scripts/analytics/realized_cost_study.py and
oi_floor_observe_report.py):
  - Every sink here accrues only as the Monday cycle runs. A tool that queried at
    build time would summarize empty tables (verified read-only 2026-07-19: the
    candidate_terminal_dispositions and option_quote_provenance tables exist but
    hold ZERO rows; no job_run yet carries cycle_metadata.tier_taper, a
    results[].greek_cap_counterfactual, a model_review result, a
    tcm.tcm_v2_proposal stamp, or a stage-seam entry_underlying_spot/iv/delta
    capture). The read/aggregate split lets the operator run it Monday
    >=17:45Z once the cycle has closed and the sinks have accrued.
  - This file lives OUTSIDE ``packages/quantum`` and imports NOTHING from the
    scanner/ranker/gate/executor/monitor. It opens NO database connection and
    touches NO network. ``--emit-sql`` prints the exact READ-ONLY query an
    operator runs (Supabase MCP / psql); ``--rows-json`` consumes the JSON that
    query returns; ``--out`` writes a dated markdown report; ``--json-out``
    writes the stable machine-diffable JSON snapshot. There is no live-DB code
    path to rot.

HONESTY CONTRACT (H9 both-ends — the whole point of a consolidated reader):
  - HONEST-EMPTY vs FAILED-FETCH are DISTINCT typed states PER SECTION, never
    conflated. A section that the query ran and found nothing for is EMPTY (the
    sink is dark today — expected, not a fault). A section whose table was ABSENT
    at query time, or that the operator could not fetch, is FAILED (typed
    ``fetch_status='failed'``); a section entirely absent from the payload is
    NOT_FETCHED. EMPTY is a finding ("the cycle produced no H7 drops"); FAILED is
    an instrument fault ("we could not look"). The reader never scores a FAILED
    section as zero.
  - COUNT typed states, never fabricate. Distributions are exact GROUP BY counts
    the SQL produced; the reader only interprets and renders them.
  - COHORTS ARE SEPARATE where the sink carries a cohort. Live champion
    (aggressive) vs shadow (neutral / conservative — "partly fiction" per
    docs/specs/shadow_fill_realism.md) vs unattributed are never pooled.
  - MEASUREMENT LIMITS ARE NAMED, never papered over. Two sinks are honest about
    what they do NOT persist: (1) the greek-cap counterfactual's HEADROOM /
    cap / exposure numbers are STRIPPED by the monitor's ``_compact_greek_cf``
    before they reach ``job_runs`` — only the coverage FLAGS + would_block
    survive, so headroom is typed UNAVAILABLE-BY-CONSTRUCTION at this grain, not
    reported as zero; (2) the quote-provenance writer's rows_written /
    persist_failures counters are LOG-ONLY (never copied into job_runs.result),
    so provenance "writes" are counted from the persisted ROWS by cycle_date and
    the failure/no-op counters are typed unavailable at the DB grain.
  - CLOCK GROUNDING (STEP 0 doctrine): the payload's own ``cycle_date`` wins over
    any passed ``--cycle-date``; a mismatch is surfaced LOUDLY as a caveat, never
    silently averaged.

DETERMINISM: the reader is a PURE function of the payload — no now(), no network,
every distribution rendered in sorted key order, every row list stably ordered.
Identical input rows -> byte-identical JSON and markdown (``--json-out`` is
``sort_keys=True`` indented).

The twelve sections (each typed EMPTY / OK / FAILED / NOT_FETCHED independently):
  1. cycle_identity      - decision_runs git_sha(s) + disposition/suggestion
                           code_sha(s) + as_of_ts known-at stamps for the cycle.
  2. h7_finals           - candidate_terminal_dispositions disposition='h7_dropped'
                           finals: parent/h7_subreason/sizing_outcome distribution.
  3. terminal_dispositions - candidate_terminal_dispositions disposition census.
  4. quote_provenance    - option_quote_provenance source / 429 / fallback /
                           freshness counts.
  5. oi_floor            - exact-leg OI + hypothetical-floor counterfactual tallies.
  6. scan_capture        - scan-time spot / IV / delta capture rates on staged opens.
  7. tier_taper          - DARK tier-taper current/proposed/difference/verdict.
  8. greek_cap           - greek-cap coverage flags + would_block counterfactual.
  9. tcm_stamps          - TCM current vs tcm_v2_proposal stamp counts.
 10. single_leg          - single-leg experiment opt-in count (policy_registrations).
 11. model_review        - scorable-close count + model_review_event trigger state.
 12. writer_counters     - disposition + provenance + quality-gate writer counters.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

MODEL_VERSION = "monday-evidence-reader/1.0"

# The literal an operator replaces (or the CLI substitutes via --cycle-date).
CYCLE_DATE_PLACEHOLDER = "__CYCLE_DATE__"
_CYCLE_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Ordered section identity (the render + JSON key order; deterministic).
SECTION_ORDER: Tuple[str, ...] = (
    "cycle_identity",
    "h7_finals",
    "terminal_dispositions",
    "quote_provenance",
    "oi_floor",
    "scan_capture",
    "tier_taper",
    "greek_cap",
    "tcm_stamps",
    "single_leg",
    "model_review",
    "writer_counters",
)

# Human titles for the markdown headers.
_SECTION_TITLES: Dict[str, str] = {
    "cycle_identity": "Cycle & deployment identity",
    "h7_finals": "H7 finals (parent / subreason / sizing_outcome)",
    "terminal_dispositions": "Candidate terminal dispositions",
    "quote_provenance": "Option quote provenance (source / 429 / fallback / freshness)",
    "oi_floor": "Exact-leg OI + hypothetical-floor counterfactuals",
    "scan_capture": "Scan-time spot / IV / delta capture on staged opens",
    "tier_taper": "Tier-taper DARK payload (current / proposed / difference / verdict)",
    "greek_cap": "Greek-cap counterfactual (coverage / would_block)",
    "tcm_stamps": "TCM current / v2 stamp counts",
    "single_leg": "Single-leg experiment opt-in (dark status)",
    "model_review": "Scorable-close count + model_review trigger state",
    "writer_counters": "Writer / no-op / failure counters",
}

# ═══════════════════════════════════════════════════════════════════════════
# READ-ONLY consolidated SQL. ONE statement, a single top-level SELECT building
# one JSON object with a `sections` map. STRICTLY READ-ONLY: no write verbs. Each
# table-backed section is guarded by ``to_regclass(...)`` so a missing table
# yields a TYPED per-section ``fetch_status='failed'`` instead of failing the
# whole query. Scope: DB-row sinks by their own ``cycle_date`` column; job_runs
# sinks by ``(started_at AT TIME ZONE 'UTC')::date`` (RTH cycles land same-UTC-
# date); orders/TCM by the order's suggestion ``cycle_date`` join. Replace
# ``__CYCLE_DATE__`` with the target date (the CLI does this via --cycle-date).
# ═══════════════════════════════════════════════════════════════════════════
STUDY_SQL = (
    r"""
WITH params AS (SELECT DATE '"""
    + CYCLE_DATE_PLACEHOLDER
    + r"""' AS cd)
SELECT json_build_object(
  'schema_version', 1,
  'model_version', 'monday-evidence-reader/1.0',
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
  'cycle_date', (SELECT cd::text FROM params),
  'sections', json_build_object(

    -- 1. cycle & deployment identity ------------------------------------------
    'cycle_identity', json_build_object(
      'fetch_status', 'ok',
      'decision_runs', COALESCE((
        SELECT json_agg(json_build_object(
                 'decision_id', dr.decision_id::text,
                 'strategy_name', dr.strategy_name,
                 'git_sha', dr.git_sha,
                 'status', dr.status,
                 'tape_integrity', dr.tape_integrity,
                 'as_of_ts', to_char(dr.as_of_ts AT TIME ZONE 'UTC',
                                     'YYYY-MM-DD"T"HH24:MI:SS"Z"'))
                 ORDER BY dr.as_of_ts, dr.decision_id)
        FROM decision_runs dr
        WHERE dr.decision_id IN (
          SELECT DISTINCT ts.decision_id
          FROM trade_suggestions ts CROSS JOIN params p
          WHERE ts.cycle_date = p.cd AND ts.decision_id IS NOT NULL)
      ), '[]'::json),
      'n_suggestions', (SELECT count(*) FROM trade_suggestions ts CROSS JOIN params p
                        WHERE ts.cycle_date = p.cd),
      'suggestion_code_shas', COALESCE((
        SELECT json_agg(DISTINCT ts.code_sha)
        FROM trade_suggestions ts CROSS JOIN params p
        WHERE ts.cycle_date = p.cd AND ts.code_sha IS NOT NULL), '[]'::json),
      'disposition_code_shas', CASE
        WHEN to_regclass('public.candidate_terminal_dispositions') IS NULL THEN NULL
        ELSE COALESCE((SELECT json_agg(DISTINCT ctd.code_sha)
              FROM candidate_terminal_dispositions ctd CROSS JOIN params p
              WHERE ctd.cycle_date = p.cd AND ctd.code_sha IS NOT NULL), '[]'::json) END
    ),

    -- 2. H7 finals (disposition='h7_dropped') ---------------------------------
    'h7_finals', CASE
      WHEN to_regclass('public.candidate_terminal_dispositions') IS NULL
        THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
      ELSE json_build_object(
        'fetch_status', 'ok',
        'rows', COALESCE((SELECT json_agg(r ORDER BY r.cohort, r.h7_subreason,
                                          r.sizing_outcome) FROM (
          SELECT COALESCE(ts.cohort_name, 'unattributed') AS cohort,
                 COALESCE(ctd.detail->>'h7_subreason', 'unspecified') AS h7_subreason,
                 ctd.detail->>'sizing_outcome' AS sizing_outcome,
                 ctd.detail->>'reason' AS reason,
                 count(*) AS n
          FROM candidate_terminal_dispositions ctd CROSS JOIN params p
          LEFT JOIN trade_suggestions ts ON ts.id = ctd.suggestion_id
          WHERE ctd.cycle_date = p.cd AND ctd.disposition = 'h7_dropped' AND ctd.is_final
          GROUP BY 1, 2, 3, 4) r), '[]'::json),
        'taxonomy_violations', (SELECT count(*)
          FROM candidate_terminal_dispositions ctd CROSS JOIN params p
          WHERE ctd.cycle_date = p.cd AND ctd.disposition = 'h7_dropped'
            AND ctd.is_final AND ctd.detail->>'h7_subreason_violation' = 'true')
      ) END,

    -- 3. terminal disposition census ------------------------------------------
    'terminal_dispositions', CASE
      WHEN to_regclass('public.candidate_terminal_dispositions') IS NULL
        THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
      ELSE json_build_object(
        'fetch_status', 'ok',
        'n_total', (SELECT count(*) FROM candidate_terminal_dispositions ctd
                    CROSS JOIN params p WHERE ctd.cycle_date = p.cd),
        'n_final', (SELECT count(*) FROM candidate_terminal_dispositions ctd
                    CROSS JOIN params p WHERE ctd.cycle_date = p.cd AND ctd.is_final),
        'n_cost_reconciliation', (SELECT count(*) FROM candidate_terminal_dispositions ctd
                    CROSS JOIN params p WHERE ctd.cycle_date = p.cd
                    AND ctd.detail ? 'cost_reconciliation'),
        'rows', COALESCE((SELECT json_agg(r ORDER BY r.cohort, r.disposition) FROM (
          SELECT COALESCE(ts.cohort_name, 'unattributed') AS cohort,
                 COALESCE(ctd.disposition, 'unset') AS disposition,
                 count(*) AS n,
                 count(*) FILTER (WHERE ctd.is_final) AS n_final
          FROM candidate_terminal_dispositions ctd CROSS JOIN params p
          LEFT JOIN trade_suggestions ts ON ts.id = ctd.suggestion_id
          WHERE ctd.cycle_date = p.cd
          GROUP BY 1, 2) r), '[]'::json)
      ) END,

    -- 4. quote provenance -----------------------------------------------------
    'quote_provenance', CASE
      WHEN to_regclass('public.option_quote_provenance') IS NULL
        THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
      ELSE json_build_object(
        'fetch_status', 'ok',
        'n_rows', (SELECT count(*) FROM option_quote_provenance o CROSS JOIN params p
                   WHERE o.cycle_date = p.cd),
        'by_record_type', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT COALESCE(record_type, 'NULL') k, count(*) n
          FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd GROUP BY 1) s), '{}'::json),
        'by_source', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT COALESCE(source, 'NULL') k, count(*) n
          FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd GROUP BY 1) s), '{}'::json),
        'by_verdict', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT COALESCE(verdict, 'NULL') k, count(*) n
          FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd GROUP BY 1) s), '{}'::json),
        'by_fallback_reason', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT COALESCE(fallback_reason, 'NULL') k, count(*) n
          FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd GROUP BY 1) s), '{}'::json),
        'n_rows_with_429', (SELECT count(*) FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd AND o.http_statuses::text LIKE '%429%'),
        'freshness', json_build_object(
          'n_with_stale_age', (SELECT count(*) FROM option_quote_provenance o CROSS JOIN params p
            WHERE o.cycle_date = p.cd AND o.stale_age_ms IS NOT NULL),
          'n_stale_gt_60s', (SELECT count(*) FROM option_quote_provenance o CROSS JOIN params p
            WHERE o.cycle_date = p.cd AND o.stale_age_ms > 60000),
          'median_stale_ms', (SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY o.stale_age_ms)
            FROM option_quote_provenance o CROSS JOIN params p
            WHERE o.cycle_date = p.cd AND o.stale_age_ms IS NOT NULL))
      ) END,

    -- 5. exact-leg OI + hypothetical floors -----------------------------------
    'oi_floor', CASE
      WHEN to_regclass('public.option_quote_provenance') IS NULL
        THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
      ELSE json_build_object(
        'fetch_status', 'ok',
        'rows', COALESCE((SELECT json_agg(json_build_object(
                   'verdict', o.verdict, 'selected', o.selected, 'oi', o.details->'oi')
                   ORDER BY o.created_at, o.id)
          FROM option_quote_provenance o CROSS JOIN params p
          WHERE o.cycle_date = p.cd AND o.record_type = 'leg_set' AND o.details ? 'oi'
        ), '[]'::json)
      ) END,

    -- 6. scan-time spot/IV/delta capture on staged OPEN orders ----------------
    'scan_capture', json_build_object(
      'fetch_status', 'ok',
      'rows', COALESCE((SELECT json_agg(json_build_object(
                 'cohort', COALESCE(ts.cohort_name, 'unattributed'),
                 'spot_status', po.order_json->'entry_underlying_spot'->>'status',
                 'n_legs', (SELECT count(*) FROM jsonb_array_elements(
                              COALESCE(po.order_json->'legs', '[]'::jsonb))),
                 'n_iv_populated', (SELECT count(*) FROM jsonb_array_elements(
                              COALESCE(po.order_json->'legs', '[]'::jsonb)) l
                              WHERE l->>'iv_status' = 'populated_at_stage'),
                 'n_delta_populated', (SELECT count(*) FROM jsonb_array_elements(
                              COALESCE(po.order_json->'legs', '[]'::jsonb)) l
                              WHERE l->>'greeks_status' = 'populated_at_stage'))
                 ORDER BY po.staged_at, po.id)
        FROM paper_orders po CROSS JOIN params p
        JOIN trade_suggestions ts ON ts.id = po.suggestion_id
        WHERE po.position_id IS NULL AND ts.cycle_date = p.cd), '[]'::json)
    ),

    -- 7. tier-taper DARK payload (nested under cycle_results[]) ----------------
    'tier_taper', json_build_object(
      'fetch_status', 'ok',
      'rows', COALESCE((SELECT json_agg(cr->'cycle_metadata'->'tier_taper'
                 ORDER BY jr.started_at, jr.id)
        FROM job_runs jr CROSS JOIN params p
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(jr.result->'cycle_results',
                                                         '[]'::jsonb)) cr
        WHERE jr.job_name = 'suggestions_open'
          AND (jr.started_at AT TIME ZONE 'UTC')::date = p.cd
          AND cr->'cycle_metadata' ? 'tier_taper'), '[]'::json)
    ),

    -- 8. greek-cap counterfactual compact (headroom NOT persisted) ------------
    'greek_cap', json_build_object(
      'fetch_status', 'ok',
      'rows', COALESCE((SELECT json_agg(res->'greek_cap_counterfactual'
                 ORDER BY jr.started_at, jr.id)
        FROM job_runs jr CROSS JOIN params p
        CROSS JOIN LATERAL jsonb_array_elements(COALESCE(jr.result->'results',
                                                         '[]'::jsonb)) res
        WHERE jr.job_name = 'intraday_risk_monitor'
          AND (jr.started_at AT TIME ZONE 'UTC')::date = p.cd
          AND res ? 'greek_cap_counterfactual'), '[]'::json)
    ),

    -- 9. TCM current vs v2 stamp counts ---------------------------------------
    'tcm_stamps', json_build_object(
      'fetch_status', 'ok',
      'rows', COALESCE((SELECT json_agg(r ORDER BY r.cohort) FROM (
          SELECT COALESCE(ts.cohort_name, 'unattributed') AS cohort,
                 count(*) AS n_orders,
                 count(*) FILTER (WHERE po.tcm IS NOT NULL) AS n_tcm_current,
                 count(*) FILTER (WHERE po.tcm ? 'tcm_v2_proposal') AS n_tcm_v2
          FROM paper_orders po CROSS JOIN params p
          JOIN trade_suggestions ts ON ts.id = po.suggestion_id
          WHERE ts.cycle_date = p.cd
          GROUP BY 1) r), '[]'::json),
      'v2_by_model_version', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT po.tcm->'tcm_v2_proposal'->>'model_version' k, count(*) n
          FROM paper_orders po CROSS JOIN params p
          JOIN trade_suggestions ts ON ts.id = po.suggestion_id
          WHERE ts.cycle_date = p.cd AND po.tcm ? 'tcm_v2_proposal' GROUP BY 1) s), '{}'::json),
      'v2_by_routing', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT po.tcm->'tcm_v2_proposal'->>'routing' k, count(*) n
          FROM paper_orders po CROSS JOIN params p
          JOIN trade_suggestions ts ON ts.id = po.suggestion_id
          WHERE ts.cycle_date = p.cd AND po.tcm ? 'tcm_v2_proposal' GROUP BY 1) s), '{}'::json)
    ),

    -- 10. single-leg experiment opt-in (fleet state, not cycle-scoped) --------
    'single_leg', CASE
      WHEN to_regclass('public.policy_registrations') IS NULL
        THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
      ELSE json_build_object(
        'fetch_status', 'ok',
        'n_registrations', (SELECT count(*) FROM policy_registrations),
        'n_opt_in', (SELECT count(*) FROM policy_registrations
                     WHERE (policy_config->>'single_leg_experiment_enabled')::boolean IS TRUE),
        'by_approval_status', COALESCE((SELECT json_object_agg(k, n) FROM (
          SELECT COALESCE(approval_status, 'NULL') k, count(*) n
          FROM policy_registrations GROUP BY 1) s), '{}'::json)
      ) END,

    -- 11. scorable-close count + model_review trigger state -------------------
    'model_review', json_build_object(
      'fetch_status', 'ok',
      'rows', COALESCE((SELECT json_agg(r ORDER BY r.started_at, r.job_name) FROM (
          SELECT jr.job_name,
                 to_char(jr.started_at AT TIME ZONE 'UTC',
                         'YYYY-MM-DD"T"HH24:MI:SS"Z"') AS started_at,
                 COALESCE(jr.result->'model_review', jr.result) AS review
          FROM job_runs jr CROSS JOIN params p
          WHERE jr.job_name IN ('model_review_event', 'paper_learning_ingest')
            AND (jr.started_at AT TIME ZONE 'UTC')::date = p.cd
            AND ((jr.result ? 'model_review')
                 OR (jr.result ? 'scorable_count')
                 OR (jr.job_name = 'model_review_event'))) r), '[]'::json)
    ),

    -- 12. writer / no-op / failure counters -----------------------------------
    'writer_counters', json_build_object(
      'fetch_status', 'ok',
      'disposition', COALESCE((SELECT json_build_object(
          'attempts_recorded', COALESCE(sum((cd_c->>'attempts_recorded')::int), 0),
          'finals_recorded', COALESCE(sum((cd_c->>'finals_recorded')::int), 0),
          'write_failures', COALESCE(sum((cd_c->>'write_failures')::int), 0),
          'table_missing_noops', COALESCE(sum((cd_c->>'table_missing_noops')::int), 0),
          'writer_taxonomy_violation', COALESCE(sum((cd_c->>'writer_taxonomy_violation')::int), 0),
          'n_runs', count(*))
        FROM job_runs jr CROSS JOIN params p
        CROSS JOIN LATERAL (SELECT jr.result->'counts'->'candidate_disposition' AS cd_c) x
        WHERE jr.job_name IN ('suggestions_open', 'midday_scan')
          AND (jr.started_at AT TIME ZONE 'UTC')::date = p.cd
          AND jr.result->'counts' ? 'candidate_disposition'), NULL),
      'provenance', CASE
        WHEN to_regclass('public.option_quote_provenance') IS NULL
          THEN json_build_object('fetch_status', 'failed', 'reason', 'table_absent')
        ELSE json_build_object(
          'fetch_status', 'ok',
          'rows_persisted', (SELECT count(*) FROM option_quote_provenance o
            CROSS JOIN params p WHERE o.cycle_date = p.cd),
          'by_record_type', COALESCE((SELECT json_object_agg(k, n) FROM (
            SELECT COALESCE(record_type, 'NULL') k, count(*) n
            FROM option_quote_provenance o CROSS JOIN params p
            WHERE o.cycle_date = p.cd GROUP BY 1) s), '{}'::json),
          'counters_note', 'rows_written/persist_failures/schema_absent_noops are LOG-ONLY (not in job_runs.result) -- persisted rows counted here by cycle_date') END,
      'quality_gate', json_build_object(
        'modes', COALESCE((SELECT json_agg(DISTINCT jr.result->'debug'->>'quality_gate_mode')
          FROM job_runs jr CROSS JOIN params p
          WHERE jr.job_name IN ('suggestions_open', 'midday_scan')
            AND (jr.started_at AT TIME ZONE 'UTC')::date = p.cd
            AND jr.result->'debug' ? 'quality_gate_mode'), '[]'::json),
        'n_quality_gate_dispositions', CASE
          WHEN to_regclass('public.candidate_terminal_dispositions') IS NULL THEN NULL
          ELSE (SELECT count(*) FROM candidate_terminal_dispositions ctd CROSS JOIN params p
                WHERE ctd.cycle_date = p.cd
                  AND ctd.detail->>'sizing_outcome' = 'marketdata_quality_gate') END)
    )
  )
);
""".strip()
)


# ═══════════════════════════════════════════════════════════════════════════
# Per-section typing: HONEST-EMPTY vs FAILED-FETCH vs NOT-FETCHED vs OK.
# ═══════════════════════════════════════════════════════════════════════════
STATUS_OK = "ok"
STATUS_EMPTY = "empty"
STATUS_FAILED = "failed"
STATUS_NOT_FETCHED = "not_fetched"


def _fetch_status(raw: Any) -> Optional[str]:
    """The section's own ``fetch_status`` if present, else None."""
    if isinstance(raw, Mapping):
        fs = raw.get("fetch_status")
        if isinstance(fs, str):
            return fs
    return None


def classify_section(raw: Any, is_empty: bool) -> str:
    """Type ONE section. Precedence: an explicit ``fetch_status='failed'`` (or any
    non-ok fetch_status) is FAILED; a section absent from the payload is
    NOT_FETCHED; a section that fetched but carries no evidence is EMPTY; else
    OK. FAILED is never scored as EMPTY (H9 — "we could not look" != "nothing
    happened")."""
    if raw is None:
        return STATUS_NOT_FETCHED
    fs = _fetch_status(raw)
    if fs is not None and fs != "ok":
        return STATUS_FAILED
    if not isinstance(raw, Mapping):
        # A section that isn't an object at all is a malformed/failed fetch.
        return STATUS_FAILED
    return STATUS_EMPTY if is_empty else STATUS_OK


# --- cohort classification (mirrors realized_cost_study) --------------------
_SHADOW_COHORTS = frozenset({"neutral", "conservative"})


def cohort_class(cohort_name: Optional[str]) -> str:
    """live | shadow | unattributed — the comparability partition. Shadow
    magnitudes never pool into live (docs/specs/shadow_fill_realism.md)."""
    name = (cohort_name or "").strip().lower()
    if name == "aggressive":
        return "live"
    if name in _SHADOW_COHORTS:
        return "shadow"
    return "unattributed"


# --- small helpers -----------------------------------------------------------
def _coerce_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(raw: Any) -> List[Any]:
    if isinstance(raw, Mapping):
        r = raw.get("rows")
        if isinstance(r, list):
            return r
    return []


# ═══════════════════════════════════════════════════════════════════════════
# Section builders. Each returns (summary_dict, is_empty, markdown_body_lines).
# Pure functions of the section payload; never raise on a partial/dark section.
# ═══════════════════════════════════════════════════════════════════════════
SectionBuild = Tuple[Dict[str, Any], bool, List[str]]


def _sorted_counts(d: Any) -> List[Tuple[str, int]]:
    if not isinstance(d, Mapping):
        return []
    return sorted(((str(k), _coerce_int(v) or 0) for k, v in d.items()), key=lambda t: t[0])


def _counts_line(prefix: str, d: Any) -> str:
    items = _sorted_counts(d)
    if not items:
        return f"{prefix}: —"
    return prefix + ": " + ", ".join(f"`{k}`={v}" for k, v in items)


def build_cycle_identity(raw: Any) -> SectionBuild:
    drs = raw.get("decision_runs") if isinstance(raw, Mapping) else None
    drs = drs if isinstance(drs, list) else []
    git_shas = sorted({str(d.get("git_sha")) for d in drs
                       if isinstance(d, Mapping) and d.get("git_sha")})
    statuses = sorted({str(d.get("status")) for d in drs
                       if isinstance(d, Mapping) and d.get("status")})
    tape = sorted({str(d.get("tape_integrity")) for d in drs
                   if isinstance(d, Mapping) and d.get("tape_integrity")})
    as_ofs = sorted(str(d.get("as_of_ts")) for d in drs
                    if isinstance(d, Mapping) and d.get("as_of_ts"))
    sug_shas = raw.get("suggestion_code_shas") if isinstance(raw, Mapping) else None
    disp_shas = raw.get("disposition_code_shas") if isinstance(raw, Mapping) else None
    sug_shas = sorted(str(s) for s in sug_shas) if isinstance(sug_shas, list) else []
    disp_shas = sorted(str(s) for s in disp_shas) if isinstance(disp_shas, list) else []
    n_sug = _coerce_int(raw.get("n_suggestions")) if isinstance(raw, Mapping) else 0
    n_sug = n_sug or 0

    summary = {
        "n_decision_runs": len(drs),
        "n_suggestions": n_sug,
        "git_shas": git_shas,
        "decision_run_statuses": statuses,
        "tape_integrity": tape,
        "as_of_ts_range": ([as_ofs[0], as_ofs[-1]] if as_ofs else []),
        "suggestion_code_shas": sug_shas,
        "disposition_code_shas": disp_shas,
    }
    is_empty = not drs and n_sug == 0 and not sug_shas and not disp_shas
    lines = [
        f"- decision_runs: **{len(drs)}** · suggestions: **{n_sug}**",
        f"- deploy git_sha(s): {', '.join(f'`{s[:12]}…`' for s in git_shas) or '—'}"
        + (" **MULTIPLE SHAs in one cycle — possible mid-cycle deploy**"
           if len(git_shas) > 1 else ""),
        f"- decision_run status: {', '.join(f'`{s}`' for s in statuses) or '—'}"
        f" · tape_integrity: {', '.join(f'`{s}`' for s in tape) or '—'}",
        f"- suggestion code_sha(s): {', '.join(f'`{s}`' for s in sug_shas) or '—'}"
        f" · disposition code_sha(s): {', '.join(f'`{s}`' for s in disp_shas) or '—'}",
        f"- as_of_ts (known-at) range: "
        + (f"{as_ofs[0]} → {as_ofs[-1]}" if as_ofs else "—"),
    ]
    return summary, is_empty, lines


def build_h7_finals(raw: Any) -> SectionBuild:
    rows = _rows(raw)
    by_cohort_sub: Dict[str, Dict[str, int]] = {}
    by_sizing: Dict[str, int] = {}
    total = 0
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        n = _coerce_int(r.get("n")) or 0
        total += n
        cohort = cohort_class(r.get("cohort"))
        sub = str(r.get("h7_subreason") or "unspecified")
        by_cohort_sub.setdefault(cohort, {}).setdefault(sub, 0)
        by_cohort_sub[cohort][sub] += n
        so = r.get("sizing_outcome")
        if so:
            by_sizing[str(so)] = by_sizing.get(str(so), 0) + n
    taxviol = _coerce_int(raw.get("taxonomy_violations")) if isinstance(raw, Mapping) else 0
    summary = {
        "n_h7_finals": total,
        "by_cohort_subreason": {c: dict(sorted(v.items())) for c, v in sorted(by_cohort_sub.items())},
        "by_sizing_outcome": dict(sorted(by_sizing.items())),
        "taxonomy_violations": taxviol or 0,
    }
    is_empty = total == 0
    lines = [f"- H7 finals (`disposition='h7_dropped'`): **{total}**"]
    for cohort in sorted(by_cohort_sub):
        lines.append(f"  - {cohort}: "
                     + ", ".join(f"`{k}`={v}" for k, v in sorted(by_cohort_sub[cohort].items())))
    lines.append(_counts_line("- sizing_outcome", by_sizing))
    if taxviol:
        lines.append(f"- ⚠ writer taxonomy violations (h7_dropped missing subreason): **{taxviol}**")
    return summary, is_empty, lines


def build_terminal_dispositions(raw: Any) -> SectionBuild:
    rows = _rows(raw)
    by_cohort_disp: Dict[str, Dict[str, int]] = {}
    by_disp: Dict[str, int] = {}
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        n = _coerce_int(r.get("n")) or 0
        cohort = cohort_class(r.get("cohort"))
        disp = str(r.get("disposition") or "unset")
        by_cohort_disp.setdefault(cohort, {}).setdefault(disp, 0)
        by_cohort_disp[cohort][disp] += n
        by_disp[disp] = by_disp.get(disp, 0) + n
    n_total = _coerce_int(raw.get("n_total")) if isinstance(raw, Mapping) else 0
    n_final = _coerce_int(raw.get("n_final")) if isinstance(raw, Mapping) else 0
    n_cr = _coerce_int(raw.get("n_cost_reconciliation")) if isinstance(raw, Mapping) else 0
    summary = {
        "n_total": n_total or 0,
        "n_final": n_final or 0,
        "n_cost_reconciliation": n_cr or 0,
        "by_disposition": dict(sorted(by_disp.items())),
        "by_cohort_disposition": {c: dict(sorted(v.items())) for c, v in sorted(by_cohort_disp.items())},
    }
    is_empty = (n_total or 0) == 0
    lines = [
        f"- rows: **{n_total or 0}** ({n_final or 0} final; "
        f"{n_cr or 0} carry cost_reconciliation)",
        _counts_line("- by disposition", by_disp),
    ]
    for cohort in sorted(by_cohort_disp):
        lines.append(f"  - {cohort}: "
                     + ", ".join(f"`{k}`={v}" for k, v in sorted(by_cohort_disp[cohort].items())))
    return summary, is_empty, lines


def build_quote_provenance(raw: Any) -> SectionBuild:
    n_rows = _coerce_int(raw.get("n_rows")) if isinstance(raw, Mapping) else 0
    n_rows = n_rows or 0
    fresh = raw.get("freshness") if isinstance(raw, Mapping) else {}
    fresh = fresh if isinstance(fresh, Mapping) else {}
    summary = {
        "n_rows": n_rows,
        "by_record_type": dict(_sorted_counts(raw.get("by_record_type") if isinstance(raw, Mapping) else {})),
        "by_source": dict(_sorted_counts(raw.get("by_source") if isinstance(raw, Mapping) else {})),
        "by_verdict": dict(_sorted_counts(raw.get("by_verdict") if isinstance(raw, Mapping) else {})),
        "by_fallback_reason": dict(_sorted_counts(raw.get("by_fallback_reason") if isinstance(raw, Mapping) else {})),
        "n_rows_with_429": _coerce_int(raw.get("n_rows_with_429")) if isinstance(raw, Mapping) else 0,
        "freshness": {
            "n_with_stale_age": _coerce_int(fresh.get("n_with_stale_age")) or 0,
            "n_stale_gt_60s": _coerce_int(fresh.get("n_stale_gt_60s")) or 0,
            "median_stale_ms": _coerce_float(fresh.get("median_stale_ms")),
        },
    }
    is_empty = n_rows == 0
    med = summary["freshness"]["median_stale_ms"]
    lines = [
        f"- provenance rows: **{n_rows}**",
        _counts_line("- by record_type", summary["by_record_type"]),
        _counts_line("- by source", summary["by_source"]),
        _counts_line("- by verdict", summary["by_verdict"]),
        _counts_line("- by fallback_reason", summary["by_fallback_reason"]),
        f"- rows touching a 429 status: **{summary['n_rows_with_429']}**",
        f"- freshness: {summary['freshness']['n_with_stale_age']} with stale_age, "
        f"{summary['freshness']['n_stale_gt_60s']} > 60s stale, "
        f"median stale={'—' if med is None else f'{med:.0f}ms'}",
    ]
    return summary, is_empty, lines


def _oi_floor_tally(rows: List[Any]) -> Tuple[Dict[int, Dict[str, int]], Dict[str, Any]]:
    """Per-floor pass/fail/indeterminate tally + OI value distribution, from the
    persisted ``details->oi`` objects (verdicts never recomputed here)."""
    floors: Dict[int, Dict[str, int]] = {}
    oi_values: List[int] = []
    n_zero = 0
    n_leg_sets = 0
    n_any_dark = 0
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        oi = r.get("oi")
        if not isinstance(oi, Mapping):
            continue
        n_leg_sets += 1
        if oi.get("any_oi_unavailable"):
            n_any_dark += 1
        for leg in (oi.get("legs") or []):
            if isinstance(leg, Mapping) and leg.get("oi_available"):
                v = _coerce_int(leg.get("oi"))
                if v is not None:
                    oi_values.append(v)
                    if v == 0:
                        n_zero += 1
        for cf in (oi.get("counterfactuals") or []):
            if not isinstance(cf, Mapping):
                continue
            fl = _coerce_int(cf.get("floor"))
            if fl is None:
                continue
            verdict = str(cf.get("verdict") or "unknown")
            bucket = floors.setdefault(fl, {"pass": 0, "fail": 0, "indeterminate": 0})
            if verdict in bucket:
                bucket[verdict] += 1
    dist: Dict[str, Any] = {
        "n_leg_sets": n_leg_sets,
        "n_any_dark": n_any_dark,
        "n_leg_values": len(oi_values),
        "n_zero_oi_legs": n_zero,
        "min_oi": (min(oi_values) if oi_values else None),
        "median_oi": (round(statistics.median(oi_values), 2) if oi_values else None),
        "max_oi": (max(oi_values) if oi_values else None),
    }
    return floors, dist


def build_oi_floor(raw: Any) -> SectionBuild:
    rows = _rows(raw)
    floors, dist = _oi_floor_tally(rows)
    floor_summary = {}
    for fl in sorted(floors):
        b = floors[fl]
        evaluable = b["pass"] + b["fail"]
        floor_summary[str(fl)] = {
            "pass": b["pass"], "fail": b["fail"],
            "indeterminate": b["indeterminate"], "n_evaluable": evaluable,
            "would_fail_rate_of_evaluable": (b["fail"] / evaluable) if evaluable else None,
        }
    summary = {"distribution": dist, "floors": floor_summary}
    is_empty = dist["n_leg_sets"] == 0
    lines = [
        f"- leg sets with OI observation: **{dist['n_leg_sets']}** "
        f"({dist['n_any_dark']} with >=1 dark leg)",
        f"- per-leg OI: n={dist['n_leg_values']}, zero-OI legs={dist['n_zero_oi_legs']}, "
        f"min={dist['min_oi']}, median={dist['median_oi']}, max={dist['max_oi']}",
    ]
    for fl in sorted(floors):
        b = floors[fl]
        ev = b["pass"] + b["fail"]
        rate = f"{(b['fail'] / ev):.1%}" if ev else "—"
        lines.append(f"  - floor {fl}: pass={b['pass']} fail={b['fail']} "
                     f"indeterminate={b['indeterminate']} (would-fail rate of evaluable={rate})")
    return summary, is_empty, lines


def build_scan_capture(raw: Any) -> SectionBuild:
    rows = _rows(raw)
    by_cohort: Dict[str, Dict[str, int]] = {}
    n_orders = 0
    n_spot = 0
    n_legs = 0
    n_iv = 0
    n_delta = 0
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        n_orders += 1
        cohort = cohort_class(r.get("cohort"))
        c = by_cohort.setdefault(cohort, {"orders": 0, "spot_populated": 0,
                                          "legs": 0, "iv_populated": 0, "delta_populated": 0})
        c["orders"] += 1
        if r.get("spot_status") == "populated_at_stage":
            n_spot += 1
            c["spot_populated"] += 1
        lg = _coerce_int(r.get("n_legs")) or 0
        iv = _coerce_int(r.get("n_iv_populated")) or 0
        dl = _coerce_int(r.get("n_delta_populated")) or 0
        n_legs += lg
        n_iv += iv
        n_delta += dl
        c["legs"] += lg
        c["iv_populated"] += iv
        c["delta_populated"] += dl

    def _rate(a: int, b: int) -> Optional[float]:
        return (a / b) if b else None

    summary = {
        "n_open_orders": n_orders,
        "spot_capture_rate": _rate(n_spot, n_orders),
        "iv_capture_rate": _rate(n_iv, n_legs),
        "delta_capture_rate": _rate(n_delta, n_legs),
        "n_legs": n_legs,
        "by_cohort": {c: dict(sorted(v.items())) for c, v in sorted(by_cohort.items())},
    }
    is_empty = n_orders == 0

    def _pct(x: Optional[float]) -> str:
        return "—" if x is None else f"{x:.1%}"

    lines = [
        f"- staged OPEN orders: **{n_orders}** ({n_legs} legs)",
        f"- capture rates: spot={_pct(summary['spot_capture_rate'])} (of orders), "
        f"IV={_pct(summary['iv_capture_rate'])} (of legs), "
        f"delta={_pct(summary['delta_capture_rate'])} (of legs)",
    ]
    for cohort in sorted(by_cohort):
        c = by_cohort[cohort]
        lines.append(f"  - {cohort}: orders={c['orders']} spot={c['spot_populated']} "
                     f"legs={c['legs']} iv={c['iv_populated']} delta={c['delta_populated']}")
    return summary, is_empty, lines


def build_tier_taper(raw: Any) -> SectionBuild:
    # The taper engine version bump (tier_taper.v1 [900,1100] → v2 [800,1000])
    # partitions the observe evidence: v1-era and v2-era samples have different
    # band/state semantics and MUST NOT be pooled. This reader tags every
    # observation with its engine_version and reports verdict tallies PER
    # version (by_engine_version is authoritative); the top-level by_verdict is
    # a pooled convenience only, valid solely when a single version is present.
    rows = [r for r in _rows(raw) if isinstance(r, Mapping)]
    verdicts: Dict[str, int] = {}
    by_version: Dict[str, Dict[str, Any]] = {}
    parsed = []
    for r in rows:
        verdict = str(r.get("verdict") or "unknown")
        version = str(r.get("engine_version") or "unknown")
        verdicts[verdict] = verdicts.get(verdict, 0) + 1
        bucket = by_version.setdefault(
            version, {"n_observations": 0, "by_verdict": {}})
        bucket["n_observations"] += 1
        bucket["by_verdict"][verdict] = bucket["by_verdict"].get(verdict, 0) + 1
        cur = r.get("current") if isinstance(r.get("current"), Mapping) else None
        prop = r.get("proposed") if isinstance(r.get("proposed"), Mapping) else None
        diff = r.get("difference") if isinstance(r.get("difference"), Mapping) else None
        parsed.append({
            "engine_version": version,
            "verdict": verdict,
            "effective_tier_state": r.get("effective_tier_state"),
            "raw_tier": r.get("raw_tier"),
            "current_tier": (cur or {}).get("tier"),
            "proposed_tier": (prop or {}).get("tier"),
            "difference_envelope_pct": (diff or {}).get("envelope_pct"),
            "difference_per_trade_ceiling_pct": (diff or {}).get("per_trade_ceiling_pct"),
        })
    by_engine_version = {
        v: {"n_observations": by_version[v]["n_observations"],
            "by_verdict": dict(sorted(by_version[v]["by_verdict"].items()))}
        for v in sorted(by_version)
    }
    engine_versions = sorted(by_version)
    summary = {"n_observations": len(rows),
               "engine_versions": engine_versions,
               "by_engine_version": by_engine_version,
               "by_verdict": dict(sorted(verdicts.items())),
               "observations": parsed}
    is_empty = len(rows) == 0
    lines = [f"- tier-taper observations (DARK, observe-only): **{len(rows)}**"]
    if len(engine_versions) > 1:
        lines.append("- ⚠ MULTIPLE engine versions present — reported "
                     "separately; NEVER pooled (v1/v2 band semantics differ):")
    for v in engine_versions:
        bv = by_engine_version[v]
        lines.append(_counts_line(f"  - `{v}` (n={bv['n_observations']}) verdicts",
                                  bv["by_verdict"]))
    for o in parsed:
        lines.append(f"  - [`{o['engine_version']}`] verdict=`{o['verdict']}` "
                     f"tier `{o['current_tier']}`→`{o['proposed_tier']}` "
                     f"(effective=`{o['effective_tier_state']}`) "
                     f"Δenvelope_pct={o['difference_envelope_pct']}")
    return summary, is_empty, lines


def build_greek_cap(raw: Any) -> SectionBuild:
    rows = [r for r in _rows(raw) if isinstance(r, Mapping)]
    n_cycles = 0
    n_available = 0
    n_unavailable = 0
    by_ref: Dict[str, Dict[str, int]] = {}
    for cf in rows:
        n_cycles += 1
        if not cf.get("available"):
            n_unavailable += 1
            continue
        n_available += 1
        for rr in (cf.get("rows") or []):
            if not isinstance(rr, Mapping):
                continue
            name = str(rr.get("name") or "unknown")
            b = by_ref.setdefault(name, {"would_block": 0, "would_not_block": 0, "unavailable": 0})
            wb = rr.get("would_block")
            if wb is True:
                b["would_block"] += 1
            elif wb is False:
                b["would_not_block"] += 1
            else:
                b["unavailable"] += 1
    summary = {
        "n_cycles": n_cycles,
        "n_available_cycles": n_available,
        "n_unavailable_cycles": n_unavailable,
        "by_reference_row": {k: dict(sorted(v.items())) for k, v in sorted(by_ref.items())},
        "headroom_status": "unavailable_by_construction",
        "headroom_note": ("HEADROOM / cap / exposure numbers are stripped by the monitor's "
                          "_compact_greek_cf before reaching job_runs; only coverage flags + "
                          "would_block persist at this grain"),
    }
    is_empty = n_cycles == 0
    lines = [
        f"- monitor cycles with a greek-cap counterfactual: **{n_cycles}** "
        f"({n_available} greeks-available / {n_unavailable} unavailable)",
        "- HEADROOM is UNAVAILABLE-BY-CONSTRUCTION here (stripped before job_runs); "
        "coverage-flags + would_block only.",
    ]
    for name in sorted(by_ref):
        b = by_ref[name]
        lines.append(f"  - `{name}`: would_block={b['would_block']} "
                     f"would_not_block={b['would_not_block']} unavailable={b['unavailable']}")
    return summary, is_empty, lines


def build_tcm_stamps(raw: Any) -> SectionBuild:
    rows = _rows(raw)
    by_cohort: Dict[str, Dict[str, int]] = {}
    n_orders = 0
    n_current = 0
    n_v2 = 0
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        o = _coerce_int(r.get("n_orders")) or 0
        cur = _coerce_int(r.get("n_tcm_current")) or 0
        v2 = _coerce_int(r.get("n_tcm_v2")) or 0
        n_orders += o
        n_current += cur
        n_v2 += v2
        cohort = cohort_class(r.get("cohort"))
        by_cohort[cohort] = {"n_orders": o, "n_tcm_current": cur, "n_tcm_v2": v2}
    summary = {
        "n_orders": n_orders,
        "n_tcm_current": n_current,
        "n_tcm_v2": n_v2,
        "v2_by_model_version": dict(_sorted_counts(raw.get("v2_by_model_version") if isinstance(raw, Mapping) else {})),
        "v2_by_routing": dict(_sorted_counts(raw.get("v2_by_routing") if isinstance(raw, Mapping) else {})),
        "by_cohort": {c: v for c, v in sorted(by_cohort.items())},
    }
    is_empty = n_orders == 0
    lines = [
        f"- cycle orders: **{n_orders}** · current TCM stamp: **{n_current}** · "
        f"tcm_v2_proposal stamp: **{n_v2}**",
        _counts_line("- v2 by model_version", summary["v2_by_model_version"]),
        _counts_line("- v2 by routing", summary["v2_by_routing"]),
    ]
    for cohort in sorted(by_cohort):
        c = by_cohort[cohort]
        lines.append(f"  - {cohort}: orders={c['n_orders']} current={c['n_tcm_current']} v2={c['n_tcm_v2']}")
    return summary, is_empty, lines


def build_single_leg(raw: Any) -> SectionBuild:
    n_reg = _coerce_int(raw.get("n_registrations")) if isinstance(raw, Mapping) else 0
    n_opt = _coerce_int(raw.get("n_opt_in")) if isinstance(raw, Mapping) else 0
    n_reg = n_reg or 0
    n_opt = n_opt or 0
    by_status = dict(_sorted_counts(raw.get("by_approval_status") if isinstance(raw, Mapping) else {}))
    summary = {
        "n_registrations": n_reg,
        "n_opt_in": n_opt,
        "opt_in_key": "single_leg_experiment_enabled",
        "by_approval_status": by_status,
    }
    # Fleet-state, not cycle-scoped: EMPTY only when the registry itself is empty
    # (0 registrations). 0 opt-ins with a populated registry is the EXPECTED dark
    # status, not empty.
    is_empty = n_reg == 0
    lines = [
        f"- policy_registrations: **{n_reg}** · single-leg opt-ins "
        f"(`single_leg_experiment_enabled=true`): **{n_opt}** (expected 0 — dark)",
        _counts_line("- by approval_status", by_status),
    ]
    return summary, is_empty, lines


def build_model_review(raw: Any) -> SectionBuild:
    rows = [r for r in _rows(raw) if isinstance(r, Mapping)]
    parsed = []
    max_scorable = None
    latest_status = None
    for r in rows:
        review = r.get("review") if isinstance(r.get("review"), Mapping) else {}
        sc = _coerce_int(review.get("scorable_count"))
        if sc is not None:
            max_scorable = sc if max_scorable is None else max(max_scorable, sc)
        latest_status = review.get("status") or latest_status
        parsed.append({
            "job_name": r.get("job_name"),
            "started_at": r.get("started_at"),
            "scorable_count": sc,
            "status": review.get("status"),
            "boundary_crossed": review.get("boundary_crossed"),
            "ok": review.get("ok"),
        })
    summary = {
        "n_review_events": len(rows),
        "max_scorable_count": max_scorable,
        "latest_status": latest_status,
        "events": parsed,
    }
    is_empty = len(rows) == 0
    lines = [
        f"- model_review job results this cycle: **{len(rows)}**",
        f"- scorable-close count (max seen): "
        f"{'—' if max_scorable is None else max_scorable}"
        f" · latest trigger state: `{latest_status or '—'}`",
    ]
    for e in parsed:
        lines.append(f"  - `{e['job_name']}` @ {e['started_at']}: "
                     f"scorable={e['scorable_count']} status=`{e['status']}` "
                     f"boundary_crossed={e['boundary_crossed']}")
    return summary, is_empty, lines


def build_writer_counters(raw: Any) -> SectionBuild:
    disp = raw.get("disposition") if isinstance(raw, Mapping) else None
    prov = raw.get("provenance") if isinstance(raw, Mapping) else None
    qg = raw.get("quality_gate") if isinstance(raw, Mapping) else None
    disp = disp if isinstance(disp, Mapping) else None
    prov = prov if isinstance(prov, Mapping) else {}
    qg = qg if isinstance(qg, Mapping) else {}

    disp_summary = None
    if disp is not None:
        disp_summary = {
            "attempts_recorded": _coerce_int(disp.get("attempts_recorded")) or 0,
            "finals_recorded": _coerce_int(disp.get("finals_recorded")) or 0,
            "write_failures": _coerce_int(disp.get("write_failures")) or 0,
            "table_missing_noops": _coerce_int(disp.get("table_missing_noops")) or 0,
            "writer_taxonomy_violation": _coerce_int(disp.get("writer_taxonomy_violation")) or 0,
            "n_runs": _coerce_int(disp.get("n_runs")) or 0,
        }
    prov_failed = _fetch_status(prov) == "failed"
    prov_rows = _coerce_int(prov.get("rows_persisted")) if isinstance(prov, Mapping) else None
    modes = qg.get("modes") if isinstance(qg, Mapping) else None
    modes = sorted(str(m) for m in modes) if isinstance(modes, list) else []
    n_qg_disp = _coerce_int(qg.get("n_quality_gate_dispositions")) if isinstance(qg, Mapping) else None

    summary = {
        "disposition": disp_summary,
        "provenance": {
            "fetch_status": ("failed" if prov_failed else "ok"),
            "rows_persisted": prov_rows,
            "by_record_type": dict(_sorted_counts(prov.get("by_record_type") if isinstance(prov, Mapping) else {})),
            "counters_note": (prov.get("counters_note") if isinstance(prov, Mapping) else None),
        },
        "quality_gate": {
            "modes": modes,
            "n_quality_gate_dispositions": n_qg_disp,
        },
    }
    # The disposition sub-query aggregates with no GROUP BY, so it returns an
    # all-zero object (never NULL) even when zero runs matched — key emptiness
    # off n_runs, not object-presence.
    disp_has_data = disp_summary is not None and disp_summary["n_runs"] > 0
    # Empty only when NOTHING was captured: no disposition counter runs, no
    # provenance rows, no quality-gate mode/dispositions.
    is_empty = (
        not disp_has_data
        and not prov_failed
        and (prov_rows or 0) == 0
        and not modes
        and (n_qg_disp or 0) == 0
    )
    if not disp_has_data:
        disp_line = "- disposition writer: no counter-bearing runs this cycle"
    else:
        disp_line = (
            f"- disposition writer: finals={disp_summary['finals_recorded']} "
            f"attempts={disp_summary['attempts_recorded']} "
            f"write_failures={disp_summary['write_failures']} "
            f"table_missing_noops={disp_summary['table_missing_noops']} "
            f"taxonomy_violations={disp_summary['writer_taxonomy_violation']} "
            f"(n_runs={disp_summary['n_runs']})")
    prov_line = (
        "- provenance writer: FAILED FETCH (table absent)" if prov_failed
        else f"- provenance writer: {prov_rows if prov_rows is not None else '—'} rows persisted "
             f"(rows_written/persist_failures are LOG-ONLY — unavailable at DB grain)")
    lines = [
        disp_line,
        prov_line,
        f"- quality gate: modes={modes or '—'}, "
        f"quality-gate dispositions={'—' if n_qg_disp is None else n_qg_disp}",
    ]
    return summary, is_empty, lines


_SECTION_BUILDERS = {
    "cycle_identity": build_cycle_identity,
    "h7_finals": build_h7_finals,
    "terminal_dispositions": build_terminal_dispositions,
    "quote_provenance": build_quote_provenance,
    "oi_floor": build_oi_floor,
    "scan_capture": build_scan_capture,
    "tier_taper": build_tier_taper,
    "greek_cap": build_greek_cap,
    "tcm_stamps": build_tcm_stamps,
    "single_leg": build_single_leg,
    "model_review": build_model_review,
    "writer_counters": build_writer_counters,
}


# ═══════════════════════════════════════════════════════════════════════════
# Consolidated report assembly.
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class SectionReport:
    name: str
    title: str
    status: str            # ok | empty | failed | not_fetched
    reason: Optional[str]  # the section's own failure reason when FAILED
    summary: Dict[str, Any]
    lines: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "summary": self.summary}


@dataclass(frozen=True)
class ConsolidatedReport:
    generated_at: str
    model_version: str
    cycle_date: str
    cycle_date_requested: Optional[str]
    cycle_date_mismatch: bool
    sections: List[SectionReport]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "model_version": self.model_version,
            "generated_at": self.generated_at,
            "cycle_date": self.cycle_date,
            "cycle_date_requested": self.cycle_date_requested,
            "cycle_date_mismatch": self.cycle_date_mismatch,
            "status_summary": {
                s: sum(1 for sec in self.sections if sec.status == s)
                for s in (STATUS_OK, STATUS_EMPTY, STATUS_FAILED, STATUS_NOT_FETCHED)
            },
            "sections": {sec.name: sec.as_dict() for sec in self.sections},
        }


def build_report(payload: Mapping[str, Any],
                 cycle_date_requested: Optional[str] = None) -> ConsolidatedReport:
    """Pure: map ONE consolidated payload into the typed report. Each section is
    independently typed OK / EMPTY / FAILED / NOT_FETCHED — a dark section is
    EMPTY, a table-absent section is FAILED, never confused. Never raises on a
    partial section."""
    sections_raw = payload.get("sections")
    sections_raw = sections_raw if isinstance(sections_raw, Mapping) else {}
    cycle_date = str(payload.get("cycle_date") or "")
    mismatch = bool(cycle_date_requested and cycle_date and cycle_date_requested != cycle_date)

    reports: List[SectionReport] = []
    for name in SECTION_ORDER:
        raw = sections_raw.get(name)
        builder = _SECTION_BUILDERS[name]
        if raw is None:
            reports.append(SectionReport(name, _SECTION_TITLES[name],
                                         STATUS_NOT_FETCHED, "section_absent_from_payload",
                                         {}, []))
            continue
        fs = _fetch_status(raw)
        if fs is not None and fs != "ok":
            reason = raw.get("reason") if isinstance(raw, Mapping) else None
            reports.append(SectionReport(name, _SECTION_TITLES[name],
                                         STATUS_FAILED, str(reason or "fetch_failed"),
                                         {}, []))
            continue
        if not isinstance(raw, Mapping):
            reports.append(SectionReport(name, _SECTION_TITLES[name],
                                         STATUS_FAILED, "malformed_section", {}, []))
            continue
        summary, is_empty, lines = builder(raw)
        status = STATUS_EMPTY if is_empty else STATUS_OK
        reports.append(SectionReport(name, _SECTION_TITLES[name], status, None, summary, lines))

    return ConsolidatedReport(
        generated_at=str(payload.get("generated_at", "")),
        model_version=str(payload.get("model_version", MODEL_VERSION)),
        cycle_date=cycle_date,
        cycle_date_requested=cycle_date_requested,
        cycle_date_mismatch=mismatch,
        sections=reports,
    )


# --- rendering ---------------------------------------------------------------
_STATUS_BADGE = {
    STATUS_OK: "OK",
    STATUS_EMPTY: "HONEST-EMPTY (sink dark this cycle)",
    STATUS_FAILED: "FAILED-FETCH",
    STATUS_NOT_FETCHED: "NOT-FETCHED (absent from payload)",
}


def render_markdown(report: ConsolidatedReport) -> str:
    L: List[str] = []
    L.append(f"# Monday natural-evidence consolidated reader — cycle {report.cycle_date or '(unknown)'}")
    L.append("")
    L.append(f"- Generated: {report.generated_at or '—'}")
    L.append(f"- Model: `{report.model_version}`")
    L.append("- OBSERVE-ONLY, READ-ONLY. Consolidates twelve natural-evidence "
             "sinks for one cycle. Each section is typed independently: "
             "**HONEST-EMPTY** (the query ran, the sink is dark) is a finding; "
             "**FAILED-FETCH** (table absent / not fetched) is an instrument "
             "fault — never scored as zero (H9).")
    if report.cycle_date_mismatch:
        L.append(f"- ⚠ **CLOCK MISMATCH**: requested `--cycle-date "
                 f"{report.cycle_date_requested}` but the payload is for "
                 f"`{report.cycle_date}`. The PAYLOAD wins (STEP 0 clock "
                 f"grounding); correct the premise before trusting counts.")
    counts = {s: sum(1 for sec in report.sections if sec.status == s)
              for s in (STATUS_OK, STATUS_EMPTY, STATUS_FAILED, STATUS_NOT_FETCHED)}
    L.append(f"- Section status: **{counts[STATUS_OK]} ok · "
             f"{counts[STATUS_EMPTY]} honest-empty · {counts[STATUS_FAILED]} failed · "
             f"{counts[STATUS_NOT_FETCHED]} not-fetched**")
    L.append("")
    for i, sec in enumerate(report.sections, 1):
        L.append(f"## {i}. {sec.title} — {_STATUS_BADGE[sec.status]}")
        L.append("")
        if sec.status == STATUS_FAILED:
            L.append(f"> FAILED FETCH: `{sec.reason}`. Not scored — this section "
                     "could not be read, which is distinct from empty.")
            L.append("")
            continue
        if sec.status == STATUS_NOT_FETCHED:
            L.append("> NOT FETCHED: this section was absent from the payload. "
                     "Re-run the consolidated query, or fetch this section, then "
                     "re-run the reader.")
            L.append("")
            continue
        if sec.status == STATUS_EMPTY:
            L.append("_Honest-empty: the query ran and this sink carried no rows "
                     "for the cycle (expected while the sink is dark)._")
            L.append("")
        for ln in sec.lines:
            L.append(ln)
        L.append("")
    return "\n".join(L) + "\n"


# --- CLI ---------------------------------------------------------------------
def _emit_sql(cycle_date: Optional[str]) -> str:
    """Return STUDY_SQL with the cycle-date literal substituted when provided,
    else the placeholder (with an inline instruction) left in place."""
    if cycle_date:
        if not _CYCLE_DATE_RE.match(cycle_date):
            raise ValueError(f"--cycle-date must be YYYY-MM-DD, got {cycle_date!r}")
        return STUDY_SQL.replace(CYCLE_DATE_PLACEHOLDER, cycle_date)
    return ("-- Replace " + CYCLE_DATE_PLACEHOLDER + " with the target cycle date "
            "(YYYY-MM-DD), or pass --cycle-date to have this CLI substitute it.\n"
            + STUDY_SQL)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Monday natural-evidence consolidated reader "
                    "(signed, observe-only, read-only)")
    ap.add_argument("--rows-json", help="path to the consolidated JSON payload emitted by --emit-sql")
    ap.add_argument("--emit-sql", action="store_true",
                    help="print the read-only consolidated SQL, then exit")
    ap.add_argument("--cycle-date",
                    help="cycle date YYYY-MM-DD; with --emit-sql substitutes the "
                         "literal, with --rows-json cross-checks the payload's cycle_date")
    ap.add_argument("--out", help="write the markdown report to this path (default: stdout)")
    ap.add_argument("--json-out",
                    help="also write the stable machine-diffable JSON snapshot to this path "
                         "(deterministic, sort_keys)")
    args = ap.parse_args(argv)

    # Emit UTF-8 to the console even on a legacy Windows code page (the report
    # uses em-dashes / arrows). File writes are already utf-8; this only fixes
    # stdout. No-op / harmless where stdout isn't reconfigurable (e.g. captured).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

    if args.emit_sql:
        print(_emit_sql(args.cycle_date))
        return 0
    if not args.rows_json:
        ap.error("--rows-json is required (or use --emit-sql)")

    with open(args.rows_json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    report = build_report(payload, cycle_date_requested=args.cycle_date)
    md = render_markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out}")
    else:
        print(md)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(report.as_dict(), fh, indent=2, sort_keys=True)
        print(f"wrote {args.json_out}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
