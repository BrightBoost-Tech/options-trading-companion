"""Unified counterfactual research reader (OBSERVE-ONLY, READ-ONLY).

ONE signed, deterministic CLI that consolidates the four independent research
sinks a trading-day cycle accrues into a single typed snapshot + markdown
report, so an operator reads ONE artifact instead of four ad-hoc query sets:

  (1) Terminal-distribution challenger scan scores  (Lane A —
      ``terminal_distribution_scan_scores``): coverage of the scored candidate
      population (emitted AND rejected, incl. credit spreads / condors),
      baseline-vs-challenger-vs-production head-to-head (rank swaps + EV-gate
      flips + PoP deltas on the JOINTLY-scored set), abstentions, and the honest
      executed-and-closed outcome linkage.
  (2) Regime V3 vs V4 observe comparison  (Lane B — ``regime_v4_comparisons``):
      global agreement rates, per-symbol selection deltas, typed abstentions.
  (3) Shadow-fleet policy evaluator  (Lane C — ``shadow_fleets`` /
      ``shadow_micro_accounts`` readiness + ``fleet_policy_decision_runs`` /
      ``fleet_policy_decisions``): readiness, run status, per-policy dispositions,
      and the doctrine evidence unit ``COUNT(DISTINCT decision_event_id)``.
  (4) Cohort-separated executed / outcome linkage — the "never conflated" view.

WHY A LIVE PAGINATED READER (mirrors ``single_leg_shadow_report`` +
``monday_evidence_reader`` conventions):
  - Service-role Supabase client; SELECTs only. Every evidence query PAGINATES
    explicitly (``.range()`` offset loop) with a hard row cap and TYPED
    truncation accounting, so no PostgREST default row ceiling can silently
    truncate a distribution.
  - The three lane tables are built by sibling lanes TONIGHT and may not exist
    yet. A missing relation is classified (``to_regclass``-equivalent, from the
    PostgREST/Postgres "relation absent" signatures) as a TYPED ``UNAVAILABLE``
    section, never a hard failure — so this reader merges cleanly regardless of
    lane merge order.
  - ``build_report`` is a PURE function of the fetched rows (+ an injected
    ``generated_at``); ``render_markdown`` is deterministic (every distribution
    rendered in sorted key order). Identical rows -> byte-identical output.

HONESTY CONTRACT (H9 both-ends). Every section is typed with EXACTLY ONE of six
states:
  - ``ACTUAL``         — real executed/closed outcome evidence.
  - ``COUNTERFACTUAL`` — model predictions / policy evaluations that were never
                          priced-to-fill or executed (rejected candidates, the
                          V-less regime counterfactual, the 50-policy fleet
                          evaluations). Never scored as a realized outcome.
  - ``OBSERVE_ONLY``   — observe-only telemetry (regime agreement, fleet
                          readiness).
  - ``HONEST_EMPTY``   — the query ran and the sink is dark for this scope
                          (a finding, not a fault).
  - ``UNAVAILABLE``    — the underlying table is ABSENT (sibling lane not merged
                          yet) — "we could not look because the surface does not
                          exist", distinct from empty.
  - ``FAILED_FETCH``   — a real read error (connection/permission) — instrument
                          fault, never scored as zero.
State precedence on a multi-table section: FAILED_FETCH > UNAVAILABLE >
HONEST_EMPTY > (the section's data nature).

COHORTS ARE NEVER CONFLATED. Live champion (aggressive) vs shadow
(neutral/conservative, "partly fiction" per docs/specs/shadow_fill_realism.md)
vs shadow-fleet (shadow_only) vs scan-attribution-unavailable are separate
buckets in every headline; realized aggregates are computed WITHIN a bucket
only, never pooled. ``terminal_distribution_scan_scores`` carries no cohort
column, so its outcome linkage is reported as an explicitly UN-attributed bucket
— never labelled or summed as live.

DETERMINISM: no ``now()`` inside ``build_report`` (the impure fetch layer injects
``generated_at``); no network in the pure path; sorted rendering throughout.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

MODEL_VERSION = "unified-research-reader/1.0"

# ── pagination guards ───────────────────────────────────────────────────────
# PostgREST caps a single response (commonly 1000 rows). We page explicitly so a
# large sink is fully assembled; MAX_ROWS is the hard ceiling above which we stop
# and flag TYPED truncation (counts become an explicit lower bound), never a
# silent partial read.
PAGE_SIZE = 1000
MAX_ROWS = 100_000

# ── six-state section vocabulary (EXACTLY these) ────────────────────────────
ACTUAL = "ACTUAL"
COUNTERFACTUAL = "COUNTERFACTUAL"
OBSERVE_ONLY = "OBSERVE_ONLY"
HONEST_EMPTY = "HONEST_EMPTY"
UNAVAILABLE = "UNAVAILABLE"
FAILED_FETCH = "FAILED_FETCH"

SECTION_STATES: Tuple[str, ...] = (
    ACTUAL,
    COUNTERFACTUAL,
    OBSERVE_ONLY,
    HONEST_EMPTY,
    UNAVAILABLE,
    FAILED_FETCH,
)
_NATURE_STATES = frozenset({ACTUAL, COUNTERFACTUAL, OBSERVE_ONLY})

# ── logical table keys ──────────────────────────────────────────────────────
K_SCAN = "scan_scores"
K_REGIME = "regime"
K_FLEET_RUNS = "fleet_runs"
K_FLEET_DECISIONS = "fleet_decisions"
K_FLEETS = "shadow_fleets"
K_MICRO = "micro_accounts"

# ── contract table/column/order specs (frozen sibling-lane contracts) ───────
# Ordering columns are the contract's UNIQUE idempotency tuples so pagination is
# stable+unique (no page overlap/skip); Python re-sorts for render determinism.
@dataclass(frozen=True)
class TableSpec:
    table: str
    columns: str
    order: Tuple[str, ...]


TABLE_SPECS: Dict[str, TableSpec] = {
    # Lane A — audit-A-terminal-distribution.md §7c
    K_SCAN: TableSpec(
        "terminal_distribution_scan_scores",
        ",".join(
            [
                "cycle_id", "cycle_date", "symbol", "strategy",
                "candidate_fingerprint", "challenger_model_version", "emitted",
                "reject_reason", "reject_gate",
                "baseline_pop", "baseline_ev", "baseline_model",
                "baseline_abstain_reason",
                "challenger_pop", "challenger_ev", "challenger_model",
                "challenger_abstain_reason",
                "production_pop", "production_ev",
                "suggestion_id", "realized_pnl", "realized_win", "outcome_status",
            ]
        ),
        ("cycle_id", "candidate_fingerprint", "challenger_model_version"),
    ),
    # Lane B — audit-B-regime-v4.md §3
    K_REGIME: TableSpec(
        "regime_v4_comparisons",
        ",".join(
            [
                "scope", "cycle_id", "decision_event_id", "symbol",
                "as_of_ts", "known_at", "code_sha",
                "v3_model_version", "v4_model_version",
                "v3_state", "v3_scoring_regime", "v3_global_state",
                "v4_label", "v4_scoring_regime",
                "scoring_regime_agree", "state_agree",
                "v3_effective_regime", "v4_counterfactual_effective_regime",
                "selection_delta", "sentiment", "missing_inputs", "status",
            ]
        ),
        ("cycle_id", "scope", "symbol", "code_sha"),
    ),
    # Lane C — audit-C-fleet-evaluator.md §5
    K_FLEET_RUNS: TableSpec(
        "fleet_policy_decision_runs",
        ",".join(
            [
                "run_id", "fleet_id", "fleet_epoch", "shadow_micro_account_id",
                "policy_registration_id", "source_decision_id",
                "source_code_sha", "evaluator_version", "as_of", "status",
                "counts", "created_at",
            ]
        ),
        ("source_decision_id", "shadow_micro_account_id"),
    ),
    K_FLEET_DECISIONS: TableSpec(
        "fleet_policy_decisions",
        ",".join(
            [
                "id", "run_id", "fleet_id", "fleet_epoch",
                "shadow_micro_account_id", "policy_registration_id",
                "decision_event_id", "candidate_suggestion_id", "disposition",
                "rank_at_decision", "created_at",
            ]
        ),
        ("decision_event_id", "shadow_micro_account_id"),
    ),
    # Pre-existing fleet readiness tables (columns confirmed live).
    K_FLEETS: TableSpec(
        "shadow_fleets",
        "id,epoch_name,status,micro_account_count,capital_per_account,"
        "shared_capital_enabled,effective_at,retired_at",
        ("epoch_name", "id"),
    ),
    K_MICRO: TableSpec(
        "shadow_micro_accounts",
        "fleet_id,slot_number,policy_registration_id,state",
        ("fleet_id", "slot_number"),
    ),
}


# ═══════════════════════════════════════════════════════════════════════════
# READ-ONLY existence + count cross-check SQL (to_regclass-guarded). This is the
# operator SQL-side aggregate cross-check (``--emit-sql``); the live reader uses
# the paginated client path below. STRICTLY READ-ONLY: one SELECT, no write verb.
# ═══════════════════════════════════════════════════════════════════════════
def _existence_probe(logical: str, spec: TableSpec) -> str:
    t = spec.table
    return (
        f"    '{t}', CASE WHEN to_regclass('public.{t}') IS NULL\n"
        f"      THEN json_build_object('present', false)\n"
        f"      ELSE (SELECT json_build_object('present', true, 'n', count(*)) "
        f"FROM {t}) END"
    )


STUDY_SQL = (
    "-- Unified research reader — READ-ONLY existence + row-count cross-check.\n"
    "-- to_regclass guards a not-yet-created sibling-lane table to 'present:false'\n"
    "-- (typed UNAVAILABLE in the reader), never an error. No write verbs.\n"
    "SELECT json_build_object(\n"
    + ",\n".join(_existence_probe(k, s) for k, s in TABLE_SPECS.items())
    + "\n);"
)


# ═══════════════════════════════════════════════════════════════════════════
# Fetch layer (the ONLY impure code). Paginated, table-absence classified.
# ═══════════════════════════════════════════════════════════════════════════
# PostgREST/Postgres "the relation is absent" signatures. Column-level errors
# (PGRST204/42703) deliberately do NOT match — those are real failures.
_TABLE_MISSING_MARKERS = ("pgrst205", "42p01", "could not find the table")


def _is_table_missing_error(table: str, exc: BaseException) -> bool:
    msg = str(exc).lower()
    if any(m in msg for m in _TABLE_MISSING_MARKERS):
        return True
    return "does not exist" in msg and table.lower() in msg


def _err(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:300]}"


@dataclass(frozen=True)
class FetchResult:
    table: str
    status: str  # 'ok' | 'table_absent' | 'failed'
    rows: List[Dict[str, Any]]
    truncated: bool
    n_fetched: int
    pages: int
    error: Optional[str]

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def _rows(response: Any) -> List[Dict[str, Any]]:
    data = getattr(response, "data", None)
    return [dict(r) for r in data] if isinstance(data, list) else []


def paginate(
    client: Any,
    spec: TableSpec,
    filters: Sequence[Tuple[str, Any]] = (),
    *,
    page_size: int = PAGE_SIZE,
    max_rows: int = MAX_ROWS,
) -> FetchResult:
    """Fully page a table via ``.range()`` with a hard cap.

    Pages while batches are full; stops on a short batch (genuinely exhausted,
    ``truncated=False``) OR when ``offset`` reaches ``max_rows`` (``truncated=
    True`` — a lower bound, MORE rows likely exist). A missing relation returns
    ``status='table_absent'``; any other error ``status='failed'`` — never a
    silent empty list.
    """
    rows: List[Dict[str, Any]] = []
    offset = 0
    pages = 0
    truncated = False
    try:
        while True:
            query = client.table(spec.table).select(spec.columns)
            for col, val in filters:
                query = query.eq(col, val)
            for col in spec.order:
                query = query.order(col)
            query = query.range(offset, offset + page_size - 1)
            batch = _rows(query.execute())
            pages += 1
            rows.extend(batch)
            if len(batch) < page_size:
                break  # exhausted the relation
            offset += page_size
            if offset >= max_rows:
                truncated = True  # stopped by cap; more rows likely exist
                break
        if len(rows) > max_rows:
            rows = rows[:max_rows]
            truncated = True
        return FetchResult(spec.table, "ok", rows, truncated, len(rows), pages, None)
    except Exception as exc:  # noqa: BLE001 — classified below, never swallowed
        if _is_table_missing_error(spec.table, exc):
            return FetchResult(spec.table, "table_absent", [], False, 0, pages, _err(exc))
        return FetchResult(spec.table, "failed", [], False, 0, pages, _err(exc))


def fetch_all(
    client: Any,
    *,
    cycle_date: Optional[str] = None,
    decision_id: Optional[str] = None,
    page_size: int = PAGE_SIZE,
    max_rows: int = MAX_ROWS,
) -> Dict[str, FetchResult]:
    """Fetch every sink independently (paginated). Impure; each sink's typed
    status is preserved so a downstream section abstains precisely.

    Optional scoping: ``cycle_date`` filters Lane A ``scan_scores.cycle_date``;
    ``decision_id`` filters Lane B ``regime.cycle_id`` and Lane C
    ``fleet_runs.source_decision_id`` (fleet_decisions is post-filtered by run
    membership in ``build_report`` when scoped).
    """
    scan_filters: List[Tuple[str, Any]] = []
    if cycle_date:
        scan_filters.append(("cycle_date", cycle_date))
    regime_filters: List[Tuple[str, Any]] = []
    runs_filters: List[Tuple[str, Any]] = []
    if decision_id:
        regime_filters.append(("cycle_id", decision_id))
        runs_filters.append(("source_decision_id", decision_id))

    plan = {
        K_SCAN: scan_filters,
        K_REGIME: regime_filters,
        K_FLEET_RUNS: runs_filters,
        K_FLEET_DECISIONS: [],
        K_FLEETS: [],
        K_MICRO: [],
    }
    return {
        key: paginate(
            client, TABLE_SPECS[key], filters,
            page_size=page_size, max_rows=max_rows,
        )
        for key, filters in plan.items()
    }


# ═══════════════════════════════════════════════════════════════════════════
# Small pure helpers.
# ═══════════════════════════════════════════════════════════════════════════
def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def _counts(values: Iterable[Any], *, null: str = "NULL") -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in values:
        k = null if v is None else str(v)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items()))


def _rate(a: int, b: int) -> Optional[float]:
    return (a / b) if b else None


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def _counts_line(prefix: str, d: Mapping[str, int]) -> str:
    items = sorted(d.items())
    if not items:
        return f"{prefix}: —"
    return prefix + ": " + ", ".join(f"`{k}`={v}" for k, v in items)


def _agree_rate(rows: List[Mapping[str, Any]], key: str) -> Tuple[int, int, int, Optional[float]]:
    t = sum(1 for r in rows if r.get(key) is True)
    f = sum(1 for r in rows if r.get(key) is False)
    n = sum(1 for r in rows if r.get(key) is None)
    return t, f, n, _rate(t, t + f)


# ═══════════════════════════════════════════════════════════════════════════
# Section report object + state resolution.
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class SectionReport:
    name: str
    title: str
    span: str
    state: str
    reason: Optional[str]
    truncated: bool
    summary: Dict[str, Any]
    lines: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "span": self.span,
            "reason": self.reason,
            "truncated": self.truncated,
            "summary": self.summary,
        }


def _fold_fetch_state(fetches: Sequence[FetchResult]) -> Optional[str]:
    """FAILED_FETCH > UNAVAILABLE > (None = all readable)."""
    if any(f.status == "failed" for f in fetches):
        return FAILED_FETCH
    if any(f.status == "table_absent" for f in fetches):
        return UNAVAILABLE
    return None


def _resolve_state(nature: str, primary: Sequence[FetchResult], *, empty: bool) -> str:
    folded = _fold_fetch_state(primary)
    if folded is not None:
        return folded
    return HONEST_EMPTY if empty else nature


def _reason_for(state: str, fetches: Sequence[FetchResult]) -> Optional[str]:
    if state == FAILED_FETCH:
        f = next((x for x in fetches if x.status == "failed"), None)
        return (f.error if f else "read_failed")
    if state == UNAVAILABLE:
        f = next((x for x in fetches if x.status == "table_absent"), None)
        return f"table_absent:{f.table}" if f else "table_absent"
    return None


def _mk_section(
    name: str,
    title: str,
    span: str,
    nature: str,
    primary: Sequence[FetchResult],
    *,
    empty: bool,
    summary: Dict[str, Any],
    lines: List[str],
    extra_truncation: Sequence[FetchResult] = (),
) -> SectionReport:
    state = _resolve_state(nature, primary, empty=empty)
    reason = _reason_for(state, primary)
    truncated = any(f.truncated for f in list(primary) + list(extra_truncation))
    if state in (FAILED_FETCH, UNAVAILABLE):
        summary = {}
        lines = []
    return SectionReport(name, title, span, state, reason, truncated, summary, lines)


# ═══════════════════════════════════════════════════════════════════════════
# Section builders (pure). Each returns a SectionReport.
# ═══════════════════════════════════════════════════════════════════════════
_SPAN1 = "1. Terminal-distribution challenger"
_SPAN2 = "2. Regime V3/V4 observe comparison"
_SPAN3 = "3. Shadow-fleet policy evaluator"
_SPAN4 = "4. Cohort-separated execution/outcome linkage"


def build_td_coverage(scan: FetchResult) -> SectionReport:
    rows = scan.rows
    n = len(rows)
    emitted = sum(1 for r in rows if r.get("emitted") is True)
    rejected = sum(1 for r in rows if r.get("emitted") is False)
    by_strategy = _counts(r.get("strategy") for r in rows)
    # Credit-spread / condor coverage — the population §2 credit-identity notes
    # is invisible today; count it explicitly.
    def _is(kind: str, r: Mapping[str, Any]) -> bool:
        return kind in str(r.get("strategy") or "").lower()
    n_credit = sum(1 for r in rows if _is("credit", r))
    n_condor = sum(1 for r in rows if _is("condor", r))
    n_baseline_scored = sum(1 for r in rows if _num(r.get("baseline_pop")) is not None)
    n_challenger_scored = sum(1 for r in rows if _num(r.get("challenger_pop")) is not None)
    baseline_abstain = _counts(
        r.get("baseline_abstain_reason") for r in rows
        if r.get("baseline_abstain_reason")
    )
    challenger_abstain = _counts(
        r.get("challenger_abstain_reason") for r in rows
        if r.get("challenger_abstain_reason")
    )
    by_reject_gate = _counts(
        (r.get("reject_gate") for r in rows if r.get("emitted") is False)
    )
    summary = {
        "n_candidates": n,
        "n_emitted": emitted,
        "n_rejected": rejected,
        "by_strategy": by_strategy,
        "credit_spread_coverage": n_credit,
        "condor_coverage": n_condor,
        "n_baseline_scored": n_baseline_scored,
        "n_challenger_scored": n_challenger_scored,
        "baseline_abstain_reasons": baseline_abstain,
        "challenger_abstain_reasons": challenger_abstain,
        "reject_gate_distribution": by_reject_gate,
        "basis": "per-structure-contract (contracts=1); rejected candidates are "
                 "counterfactual — never priced-to-fill",
    }
    lines = [
        f"- scored candidates: **{n}** ({emitted} emitted / {rejected} rejected)",
        f"- credit-spread coverage: **{n_credit}** · condor coverage: **{n_condor}** "
        "(the EV==0 credit-identity population, invisible pre-Lane-A)",
        f"- model scoring: baseline scored **{n_baseline_scored}** / "
        f"challenger scored **{n_challenger_scored}** of {n}",
        _counts_line("- by strategy", by_strategy),
        _counts_line("- baseline abstentions", baseline_abstain),
        _counts_line("- challenger abstentions", challenger_abstain),
        _counts_line("- reject gate (rejected only)", by_reject_gate),
    ]
    return _mk_section(
        "td_coverage", "Terminal-distribution coverage", _SPAN1,
        COUNTERFACTUAL, [scan], empty=(n == 0), summary=summary, lines=lines,
    )


def _rank_swaps(joint: List[Mapping[str, Any]]) -> Dict[str, int]:
    by_cycle: Dict[Any, List[Mapping[str, Any]]] = {}
    for r in joint:
        by_cycle.setdefault(r.get("cycle_id"), []).append(r)
    n_cycles_ranked = 0
    cycles_with_swap = 0
    total_position_changes = 0
    for cid in sorted(by_cycle, key=lambda x: str(x)):
        cands = by_cycle[cid]
        if len(cands) < 2:
            continue
        n_cycles_ranked += 1

        def _order(ev_key: str) -> List[str]:
            def key(r: Mapping[str, Any]) -> Tuple[bool, float, str]:
                ev = _num(r.get(ev_key))
                return (ev is None, -(ev if ev is not None else 0.0),
                        str(r.get("candidate_fingerprint")))
            return [str(r.get("candidate_fingerprint")) for r in sorted(cands, key=key)]

        base = {fp: i for i, fp in enumerate(_order("baseline_ev"))}
        chal = {fp: i for i, fp in enumerate(_order("challenger_ev"))}
        changed = sum(1 for fp in base if base[fp] != chal.get(fp))
        if changed:
            cycles_with_swap += 1
            total_position_changes += changed
    return {
        "n_cycles_ranked": n_cycles_ranked,
        "cycles_with_rank_swap": cycles_with_swap,
        "total_position_changes": total_position_changes,
    }


def build_td_head_to_head(scan: FetchResult) -> SectionReport:
    rows = scan.rows
    joint = [
        r for r in rows
        if _num(r.get("baseline_pop")) is not None
        and _num(r.get("challenger_pop")) is not None
    ]
    n_joint = len(joint)
    pop_deltas = [
        _num(r.get("challenger_pop")) - _num(r.get("baseline_pop")) for r in joint
    ]
    ev_gate_flips = sum(
        1 for r in joint
        if _num(r.get("baseline_ev")) is not None
        and _num(r.get("challenger_ev")) is not None
        and (_num(r.get("baseline_ev")) >= 0) != (_num(r.get("challenger_ev")) >= 0)
    )
    # baseline-abstains-but-challenger-scores divergence (and reverse).
    b_only = sum(
        1 for r in rows
        if _num(r.get("baseline_pop")) is None
        and _num(r.get("challenger_pop")) is not None
    )
    c_only = sum(
        1 for r in rows
        if _num(r.get("baseline_pop")) is not None
        and _num(r.get("challenger_pop")) is None
    )
    prod_joint = [r for r in joint if _num(r.get("production_pop")) is not None]
    swaps = _rank_swaps(joint)
    summary = {
        "n_jointly_scored": n_joint,
        "ev_gate_flips": ev_gate_flips,
        "challenger_only_scored": b_only,
        "baseline_only_scored": c_only,
        "n_with_production_comparator": len(prod_joint),
        "pop_delta_challenger_minus_baseline": {
            "mean": round(statistics.fmean(pop_deltas), 6) if pop_deltas else None,
            "median": round(statistics.median(pop_deltas), 6) if pop_deltas else None,
            "min": round(min(pop_deltas), 6) if pop_deltas else None,
            "max": round(max(pop_deltas), 6) if pop_deltas else None,
        },
        "rank_swaps": swaps,
        "note": "head-to-head only on the JOINTLY-scored set; an abstention is "
                "never scored as 0.5 (evaluator censors it)",
    }
    med = summary["pop_delta_challenger_minus_baseline"]["median"]
    lines = [
        f"- jointly-scored (both models): **{n_joint}**",
        f"- EV≥0 gate flips (baseline vs challenger): **{ev_gate_flips}**",
        f"- rank swaps: **{swaps['cycles_with_rank_swap']}** of "
        f"{swaps['n_cycles_ranked']} multi-candidate cycles "
        f"({swaps['total_position_changes']} position changes)",
        f"- PoP Δ (challenger−baseline) median: "
        f"{'—' if med is None else f'{med:+.4f}'}",
        f"- abstention divergence: challenger-only={b_only}, baseline-only={c_only} "
        f"· production comparator present on {len(prod_joint)}",
    ]
    return _mk_section(
        "td_head_to_head", "Terminal-distribution head-to-head "
        "(baseline / challenger / production)", _SPAN1,
        COUNTERFACTUAL, [scan], empty=(n_joint == 0), summary=summary, lines=lines,
    )


def build_regime_global(regime: FetchResult) -> SectionReport:
    rows = [r for r in regime.rows if r.get("scope") == "global"]
    n = len(rows)
    st_t, st_f, st_n, st_rate = _agree_rate(rows, "state_agree")
    sr_t, sr_f, sr_n, sr_rate = _agree_rate(rows, "scoring_regime_agree")
    summary = {
        "n_global_rows": n,
        "state_agree": {"true": st_t, "false": st_f, "null": st_n, "rate": st_rate},
        "scoring_regime_agree": {"true": sr_t, "false": sr_f, "null": sr_n, "rate": sr_rate},
        "v3_state_distribution": _counts(r.get("v3_global_state") or r.get("v3_state") for r in rows),
        "v4_label_distribution": _counts(r.get("v4_label") for r in rows),
        "row_status_distribution": _counts(r.get("status") for r in rows),
    }
    lines = [
        f"- global comparison rows: **{n}** (OBSERVE-ONLY; V3 stays sole live authority)",
        f"- state agreement: {_pct(st_rate)} ({st_t} agree / {st_f} disagree / {st_n} null)",
        f"- scoring-regime agreement: {_pct(sr_rate)} "
        f"({sr_t} agree / {sr_f} disagree / {sr_n} null)",
        _counts_line("- V3 global state", summary["v3_state_distribution"]),
        _counts_line("- V4 label", summary["v4_label_distribution"]),
        _counts_line("- row status", summary["row_status_distribution"]),
    ]
    return _mk_section(
        "regime_global", "Regime V3 vs V4 — global agreement", _SPAN2,
        OBSERVE_ONLY, [regime], empty=(n == 0), summary=summary, lines=lines,
    )


def build_regime_symbol(regime: FetchResult) -> SectionReport:
    rows = [r for r in regime.rows if r.get("scope") == "symbol"]
    n = len(rows)
    changed = 0
    added: Dict[str, int] = {}
    removed: Dict[str, int] = {}
    for r in rows:
        delta = r.get("selection_delta")
        if isinstance(delta, Mapping):
            if delta.get("changed") is True:
                changed += 1
            for k in delta.get("added") or []:
                added[str(k)] = added.get(str(k), 0) + 1
            for k in delta.get("removed") or []:
                removed[str(k)] = removed.get(str(k), 0) + 1
    missing: Dict[str, int] = {}
    for r in rows:
        for reason in (r.get("missing_inputs") or []):
            missing[str(reason)] = missing.get(str(reason), 0) + 1
    sr_t, sr_f, sr_n, sr_rate = _agree_rate(rows, "scoring_regime_agree")
    summary = {
        "n_symbol_rows": n,
        "n_selection_changed": changed,
        "selection_change_rate": _rate(changed, n),
        "added_strategies": dict(sorted(added.items())),
        "removed_strategies": dict(sorted(removed.items())),
        "scoring_regime_agree": {"true": sr_t, "false": sr_f, "null": sr_n, "rate": sr_rate},
        "row_status_distribution": _counts(r.get("status") for r in rows),
        "missing_inputs": dict(sorted(missing.items())),
    }
    lines = [
        f"- per-symbol counterfactual rows: **{n}**",
        f"- selection deltas (V3→V4 regime swap): **{changed}** changed "
        f"({_pct(_rate(changed, n))} of symbol rows)",
        _counts_line("- strategies added by V4", summary["added_strategies"]),
        _counts_line("- strategies removed by V4", summary["removed_strategies"]),
        f"- scoring-regime agreement (symbol): {_pct(sr_rate)}",
        _counts_line("- row status", summary["row_status_distribution"]),
        _counts_line("- typed missing inputs (never fabricated)", summary["missing_inputs"]),
    ]
    return _mk_section(
        "regime_symbol", "Regime V3 vs V4 — per-symbol selection deltas", _SPAN2,
        OBSERVE_ONLY, [regime], empty=(n == 0), summary=summary, lines=lines,
    )


def build_fleet_readiness(fleets: FetchResult, micro: FetchResult) -> SectionReport:
    fleet_rows = fleets.rows
    micro_rows = micro.rows
    status_dist = _counts(r.get("status") for r in fleet_rows)
    any_active = any(r.get("status") == "active" for r in fleet_rows)
    by_state = _counts(r.get("state") for r in micro_rows)
    n_bound = sum(1 for r in micro_rows if r.get("policy_registration_id"))
    n_active = sum(1 for r in micro_rows if r.get("state") == "active")
    n_active_bound = sum(
        1 for r in micro_rows
        if r.get("state") == "active" and r.get("policy_registration_id")
    )
    verdict = "active" if (any_active and n_active_bound > 0) else "inactive_no_op"
    summary = {
        "n_fleets": len(fleet_rows),
        "fleet_status_distribution": status_dist,
        "n_micro_accounts": len(micro_rows),
        "micro_state_distribution": by_state,
        "n_bound_to_policy": n_bound,
        "n_active": n_active,
        "n_active_and_bound": n_active_bound,
        "readiness_verdict": verdict,
    }
    empty = not fleet_rows and not micro_rows
    lines = [
        f"- readiness verdict: **{verdict}**",
        _counts_line("- fleet status", status_dist),
        f"- micro-accounts: **{len(micro_rows)}** "
        f"({n_bound} bound to a policy / {n_active} active / {n_active_bound} active+bound)",
        _counts_line("- micro-account state", by_state),
    ]
    return _mk_section(
        "fleet_readiness", "Shadow-fleet readiness", _SPAN3,
        OBSERVE_ONLY, [fleets, micro], empty=empty, summary=summary, lines=lines,
    )


def build_fleet_runs(runs: FetchResult) -> SectionReport:
    rows = runs.rows
    n = len(rows)
    by_status = _counts(r.get("status") for r in rows)
    counts_total = {
        "candidates_seen": 0, "selected": 0,
        "policy_rejected": 0, "capital_rejected": 0,
    }
    for r in rows:
        c = r.get("counts")
        if isinstance(c, Mapping):
            for k in counts_total:
                v = _num(c.get(k))
                if v is not None:
                    counts_total[k] += int(v)
    n_events = len({r.get("source_decision_id") for r in rows if r.get("source_decision_id")})
    n_policies = len(
        {r.get("policy_registration_id") for r in rows if r.get("policy_registration_id")}
    )
    summary = {
        "n_runs": n,
        "by_status": by_status,
        "counts_total": counts_total,
        "n_distinct_source_events": n_events,
        "n_distinct_policies": n_policies,
        "evaluator_versions": _counts(r.get("evaluator_version") for r in rows),
    }
    lines = [
        f"- policy-evaluation runs: **{n}** "
        f"({n_events} source events × {n_policies} policies)",
        _counts_line("- run status", by_status),
        f"- aggregate counts: seen={counts_total['candidates_seen']} "
        f"selected={counts_total['selected']} "
        f"policy_rejected={counts_total['policy_rejected']} "
        f"capital_rejected={counts_total['capital_rejected']}",
    ]
    return _mk_section(
        "fleet_runs", "Shadow-fleet policy runs", _SPAN3,
        COUNTERFACTUAL, [runs], empty=(n == 0), summary=summary, lines=lines,
    )


def build_fleet_decisions(decisions: FetchResult, scoped_run_ids: Optional[frozenset]) -> SectionReport:
    rows = decisions.rows
    if scoped_run_ids is not None:
        rows = [r for r in rows if r.get("run_id") in scoped_run_ids]
    n = len(rows)
    by_disposition = _counts(r.get("disposition") for r in rows)
    # Doctrine evidence unit — COUNT(DISTINCT decision_event_id), never row count.
    evidence_n = len({r.get("decision_event_id") for r in rows if r.get("decision_event_id")})
    n_policies = len(
        {r.get("shadow_micro_account_id") for r in rows if r.get("shadow_micro_account_id")}
    )
    summary = {
        "n_decision_rows": n,
        "evidence_n_distinct_decision_events": evidence_n,
        "by_disposition": by_disposition,
        "n_policies_with_decisions": n_policies,
        "evidence_unit": "COUNT(DISTINCT decision_event_id)",
    }
    lines = [
        f"- decision rows: **{n}** · evidence n "
        f"(DISTINCT decision_event_id): **{evidence_n}** "
        f"across {n_policies} policies",
        _counts_line("- by disposition", by_disposition),
    ]
    return _mk_section(
        "fleet_decisions", "Shadow-fleet per-candidate dispositions", _SPAN3,
        COUNTERFACTUAL, [decisions], empty=(n == 0), summary=summary, lines=lines,
    )


def build_cohort_linked(scan: FetchResult, decisions: FetchResult) -> SectionReport:
    """Cohort-separated executed/outcome linkage — the NEVER-CONFLATED view.

    Two buckets, never pooled:
      - ``scan_attribution_unavailable`` (Lane A ``terminal_distribution_scan_scores``):
        the executed-and-closed realized linkage. This surface carries NO cohort
        column, so it is reported as an explicitly UN-attributed bucket — join to
        ``learning_trade_outcomes_v3`` for the live/paper split; NEVER labelled or
        summed as the live champion.
      - ``fleet_shadow`` (Lane C ``fleet_policy_decisions``): shadow_only by
        construction; realized outcomes live in the fleet C2 lifecycle tables
        (out of this reader's scope) — while the fleet is inactive there are none.

    State is driven by the PRIMARY realized surface (scan_scores). fleet is a
    secondary cohort bucket contributing content, not the section's state.
    """
    rows = scan.rows
    by_outcome = _counts(r.get("outcome_status") for r in rows)
    resolved = [r for r in rows if r.get("outcome_status") == "resolved"]
    realized_vals = [_num(r.get("realized_pnl")) for r in resolved]
    realized_vals = [v for v in realized_vals if v is not None]
    wins = sum(1 for r in resolved if r.get("realized_win") is True)
    losses = sum(1 for r in resolved if r.get("realized_win") is False)
    n_counterfactual = sum(
        1 for r in rows if r.get("outcome_status") == "counterfactual_unmarkable"
    )
    n_open = sum(1 for r in rows if r.get("outcome_status") == "open")

    scan_bucket = {
        "cohort_label": "scan_attribution_unavailable",
        "attribution_note": "terminal_distribution_scan_scores carries no cohort "
                            "column — NOT pooled with the live champion; join to "
                            "learning_trade_outcomes_v3 for the is_paper/"
                            "execution_mode split",
        "outcome_status_distribution": by_outcome,
        "n_resolved": len(resolved),
        "n_open": n_open,
        "n_counterfactual_unmarkable": n_counterfactual,
        "realized_pnl_total": round(sum(realized_vals), 2) if realized_vals else None,
        "realized_pnl_mean": round(statistics.fmean(realized_vals), 2) if realized_vals else None,
        "win_rate_of_resolved": _rate(wins, wins + losses),
        "n_wins": wins,
        "n_losses": losses,
    }

    # Fleet-shadow bucket — typed by fleet_decisions availability, kept separate.
    if decisions.status == "table_absent":
        fleet_bucket: Dict[str, Any] = {
            "cohort_label": "fleet_shadow",
            "bucket_status": UNAVAILABLE,
            "reason": f"table_absent:{decisions.table}",
        }
        fleet_line = "- fleet-shadow cohort: UNAVAILABLE (fleet_policy_decisions absent)"
    elif decisions.status == "failed":
        fleet_bucket = {
            "cohort_label": "fleet_shadow",
            "bucket_status": FAILED_FETCH,
            "reason": decisions.error,
        }
        fleet_line = "- fleet-shadow cohort: FAILED-FETCH (fleet_policy_decisions read error)"
    else:
        n_selected = sum(1 for r in decisions.rows if r.get("disposition") == "selected")
        fleet_bucket = {
            "cohort_label": "fleet_shadow",
            "bucket_status": OBSERVE_ONLY,
            "routing": "shadow_only",
            "n_selected_would_execute": n_selected,
            "realized_note": "realized outcomes live in the fleet C2 lifecycle "
                            "tables (out of scope here); zero while fleet inactive",
        }
        fleet_line = (f"- fleet-shadow cohort (shadow_only): "
                      f"**{n_selected}** selected (would execute in C2; 0 realized while inactive)")

    summary = {
        "invariant": "cohorts NEVER pooled — realized aggregates computed WITHIN a "
                     "bucket only",
        "scan_attribution_unavailable": scan_bucket,
        "fleet_shadow": fleet_bucket,
    }
    rp_total = scan_bucket["realized_pnl_total"]
    lines = [
        "- **cohorts kept separate — never pooled**",
        f"- scan bucket (attribution unavailable): {len(resolved)} resolved, "
        f"{n_open} open, {n_counterfactual} counterfactual-unmarkable (never scored)",
        f"  - resolved realized P&L total: "
        f"{'—' if rp_total is None else f'${rp_total:.2f}'} · "
        f"win rate {_pct(scan_bucket['win_rate_of_resolved'])} "
        f"({wins}W/{losses}L)",
        fleet_line,
    ]
    # Empty only when the primary surface produced no rows AND fleet contributed
    # nothing readable-with-data.
    empty = (len(rows) == 0) and (decisions.status == "ok" and not decisions.rows)
    return _mk_section(
        "cohort_linked", "Cohort-separated execution / outcome linkage", _SPAN4,
        ACTUAL, [scan], empty=empty, summary=summary, lines=lines,
        extra_truncation=[decisions],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Report assembly (pure).
# ═══════════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class ConsolidatedReport:
    generated_at: str
    model_version: str
    cycle_date: Optional[str]
    decision_id: Optional[str]
    any_truncation: bool
    sections: List[SectionReport]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "model_version": self.model_version,
            "generated_at": self.generated_at,
            "scope": {"cycle_date": self.cycle_date, "decision_id": self.decision_id},
            "any_truncation": self.any_truncation,
            "state_summary": {
                s: sum(1 for sec in self.sections if sec.state == s)
                for s in SECTION_STATES
            },
            "sections": {sec.name: sec.as_dict() for sec in self.sections},
        }


def build_report(
    fetched: Mapping[str, FetchResult],
    *,
    generated_at: str,
    cycle_date: Optional[str] = None,
    decision_id: Optional[str] = None,
) -> ConsolidatedReport:
    """PURE: map fetched rows into typed six-state sections. Never raises on a
    partial/absent sink — a missing lane table is a typed UNAVAILABLE section."""
    scan = fetched[K_SCAN]
    regime = fetched[K_REGIME]
    runs = fetched[K_FLEET_RUNS]
    decisions = fetched[K_FLEET_DECISIONS]
    fleets = fetched[K_FLEETS]
    micro = fetched[K_MICRO]

    scoped_run_ids: Optional[frozenset] = None
    if decision_id and runs.status == "ok":
        scoped_run_ids = frozenset(
            r.get("run_id") for r in runs.rows if r.get("run_id")
        )

    sections = [
        build_td_coverage(scan),
        build_td_head_to_head(scan),
        build_regime_global(regime),
        build_regime_symbol(regime),
        build_fleet_readiness(fleets, micro),
        build_fleet_runs(runs),
        build_fleet_decisions(decisions, scoped_run_ids),
        build_cohort_linked(scan, decisions),
    ]
    any_trunc = any(f.truncated for f in fetched.values())
    return ConsolidatedReport(
        generated_at=generated_at,
        model_version=MODEL_VERSION,
        cycle_date=cycle_date,
        decision_id=decision_id,
        any_truncation=any_trunc,
        sections=sections,
    )


# ── rendering (deterministic) ────────────────────────────────────────────────
_STATE_BADGE = {
    ACTUAL: "ACTUAL",
    COUNTERFACTUAL: "COUNTERFACTUAL",
    OBSERVE_ONLY: "OBSERVE-ONLY",
    HONEST_EMPTY: "HONEST-EMPTY (sink dark this scope)",
    UNAVAILABLE: "UNAVAILABLE (table absent — sibling lane not merged)",
    FAILED_FETCH: "FAILED-FETCH (read error — not scored as zero)",
}


def render_markdown(report: ConsolidatedReport) -> str:
    L: List[str] = []
    L.append("# Unified counterfactual research reader")
    L.append("")
    L.append(f"- Generated: {report.generated_at or '—'}")
    L.append(f"- Model: `{report.model_version}`")
    scope = []
    if report.cycle_date:
        scope.append(f"cycle_date=`{report.cycle_date}`")
    if report.decision_id:
        scope.append("decision_id=`(scoped)`")
    L.append(f"- Scope: {', '.join(scope) if scope else 'ALL (unscoped — paginated + capped)'}")
    L.append(
        "- OBSERVE-ONLY, READ-ONLY. Each section is typed with EXACTLY one of "
        "**ACTUAL / COUNTERFACTUAL / OBSERVE_ONLY / HONEST_EMPTY / UNAVAILABLE / "
        "FAILED_FETCH**. HONEST-EMPTY (ran, dark) ≠ UNAVAILABLE (table absent) ≠ "
        "FAILED-FETCH (read error). Cohorts are never pooled."
    )
    counts = {s: sum(1 for sec in report.sections if sec.state == s) for s in SECTION_STATES}
    L.append(
        "- Section states: "
        + " · ".join(f"**{counts[s]}** {s}" for s in SECTION_STATES if counts[s])
    )
    if report.any_truncation:
        L.append(
            "- ⚠ **TRUNCATION**: at least one evidence query hit the "
            f"{MAX_ROWS}-row cap — the affected section's counts are a LOWER "
            "BOUND (see the section's TRUNCATED flag). Re-scope to a narrower "
            "cycle_date/decision_id for exact counts."
        )
    L.append("")

    current_span = None
    for i, sec in enumerate(report.sections, 1):
        if sec.span != current_span:
            L.append(f"# Span {sec.span}")
            L.append("")
            current_span = sec.span
        L.append(f"## {i}. {sec.title} — {_STATE_BADGE[sec.state]}")
        L.append("")
        if sec.truncated:
            L.append("> ⚠ TRUNCATED — this section consumed a capped fetch; "
                     "counts are a LOWER BOUND.")
            L.append("")
        if sec.state == FAILED_FETCH:
            L.append(f"> FAILED-FETCH: `{sec.reason}`. Not scored — could not read "
                     "(distinct from empty).")
            L.append("")
            continue
        if sec.state == UNAVAILABLE:
            L.append(f"> UNAVAILABLE: `{sec.reason}`. The sibling lane's table is "
                     "not present yet — this reader tolerates its absence and will "
                     "populate once the lane merges.")
            L.append("")
            continue
        if sec.state == HONEST_EMPTY:
            L.append("_Honest-empty: the query ran and this sink carried no rows "
                     "for the scope (expected while dark)._")
            L.append("")
        for ln in sec.lines:
            L.append(ln)
        L.append("")
    return "\n".join(L) + "\n"


# ═══════════════════════════════════════════════════════════════════════════
# CLI.
# ═══════════════════════════════════════════════════════════════════════════
def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Unified counterfactual research reader (signed, observe-only, "
                    "read-only). Consolidates terminal-distribution, regime V3/V4, "
                    "and shadow-fleet evidence into one typed snapshot.")
    ap.add_argument("--cycle-date", help="scope Lane A scan scores to this cycle "
                                         "date (YYYY-MM-DD)")
    ap.add_argument("--decision-id", help="scope Lane B/C to this source decision id")
    ap.add_argument("--json-out", help="write the deterministic JSON snapshot here")
    ap.add_argument("--markdown-out", help="write the markdown report here")
    ap.add_argument("--emit-sql", action="store_true",
                    help="print the READ-ONLY to_regclass-guarded existence/count "
                         "cross-check SQL, then exit (no DB connection)")
    ap.add_argument("--page-size", type=int, default=PAGE_SIZE,
                    help=f"pagination page size (default {PAGE_SIZE})")
    ap.add_argument("--max-rows", type=int, default=MAX_ROWS,
                    help=f"hard row cap per query (default {MAX_ROWS})")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

    if args.emit_sql:
        print(STUDY_SQL)
        return 0

    from packages.quantum.supabase_env import get_sanitized_supabase_env

    url, key = get_sanitized_supabase_env()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
    from supabase import create_client

    client = create_client(url, key)
    fetched = fetch_all(
        client,
        cycle_date=args.cycle_date,
        decision_id=args.decision_id,
        page_size=args.page_size,
        max_rows=args.max_rows,
    )
    report = build_report(
        fetched,
        generated_at=_now_iso(),
        cycle_date=args.cycle_date,
        decision_id=args.decision_id,
    )
    payload = report.as_dict()
    md = render_markdown(report)
    json_text = json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n"

    if args.json_out:
        Path(args.json_out).write_text(json_text, encoding="utf-8")
    else:
        print(json_text, end="")
    if args.markdown_out:
        Path(args.markdown_out).write_text(md, encoding="utf-8")
    elif args.json_out:
        print(md)

    # Exit non-zero if any section could not be read (FAILED-FETCH) so an
    # unattended caller notices an instrument fault; UNAVAILABLE (table absent)
    # is an expected pre-merge state and stays exit 0.
    failed = any(s.state == FAILED_FETCH for s in report.sections)
    return 2 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
