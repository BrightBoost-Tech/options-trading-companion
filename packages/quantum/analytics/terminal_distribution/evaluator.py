"""Deterministic offline/prequential evaluator for terminal-distribution models.

Runs any model (baseline or challenger) over HISTORICAL suggestion+outcome
fixtures and reports: Brier score, EV-RMSE, realized net outcome, calibration
buckets (typed-insufficient below a sample floor), coverage/abstention rate,
sample counts with explicit censoring, and per-segment identity
(strategy/regime/DTE bucket).

DESIGN RULES:
- DETERMINISTIC: records are evaluated in (known_at, record_id) order; no
  wall-clock, no randomness, no dict-order dependence. Same inputs -> byte-
  identical report.
- PREQUENTIAL: each record is scored on its own ``known_at`` inputs only; the
  evaluator never feeds an outcome back into a model.
- CENSORING IS EXPLICIT: open/unresolved outcomes are EXCLUDED from every
  metric and COUNTED (``censored``); resolved rows missing a realized field
  are excluded and counted separately (``malformed``) — never coerced to 0.
- ABSTENTION IS A RESULT: a typed ``Unavailable`` from the model is counted
  (``abstained``) and drives the coverage rate; it is never scored as a 0.5.
- RAW vs CALIBRATED ARE SEPARATE REPORTS: models emit basis="raw" only.
  ``with_production_multipliers`` wraps a model to apply a production
  calibration multiplier READ-ONLY, yielding a second, separately-labeled
  basis="calibrated" report. Nothing here writes to or imports the production
  calibration service.
- NO DB, NO JOBS: ``records_from_rows`` is a PURE row-mapping helper for rows
  an operator fetched read-only (e.g. via the Supabase MCP). This module
  imports no DB client and is imported by no job/handler — the import-lock
  test pins that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    DistributionInputs,
    EvalOutcome,
    LegSpec,
    Provenance,
    StructureSpec,
    Unavailable,
    params_hash,
)

EVALUATOR_VERSION = f"evaluator@{CONTRACT_VERSION}"

OutcomeStatus = str  # "resolved" | "open" | "unresolved"


@dataclass(frozen=True)
class OutcomeRecord:
    """Realized outcome of a historical suggestion. ``status`` other than
    "resolved" is censored (excluded + counted)."""

    status: OutcomeStatus
    realized_win: Optional[bool] = None
    realized_pnl: Optional[float] = None  # dollars per position, same units as EV


@dataclass(frozen=True)
class SegmentKey:
    strategy: str
    regime: str
    dte_bucket: str


@dataclass(frozen=True)
class EvalRecord:
    record_id: str
    structure: StructureSpec
    dist_inputs: DistributionInputs
    outcome: OutcomeRecord
    segment: SegmentKey


ModelFn = Callable[[EvalRecord], EvalOutcome]


@dataclass(frozen=True)
class PredictionRow:
    record_id: str
    scored: bool
    pop: Optional[float]
    expected_value: Optional[float]
    abstain_reason: Optional[str]
    realized_win: Optional[bool]
    realized_pnl: Optional[float]
    segment: SegmentKey


@dataclass(frozen=True)
class CalibrationBucket:
    lo: float
    hi: float
    n: int
    mean_pop: float
    realized_rate: float


@dataclass(frozen=True)
class InsufficientSamples:
    """Typed refusal to draw calibration buckets from too little data."""

    n: int
    required: int


@dataclass(frozen=True)
class SegmentMetrics:
    n_scored: int
    brier: Optional[float]
    ev_rmse: Optional[float]
    realized_net: Optional[float]


@dataclass(frozen=True)
class ModelReport:
    model_label: str
    basis: str
    evaluator_version: str
    total: int
    censored: int
    malformed: int
    eligible: int
    abstained: int
    scored: int
    coverage: Optional[float]  # scored / eligible; None when eligible == 0
    brier: Optional[float]
    ev_rmse: Optional[float]
    realized_net: Optional[float]
    calibration: Union[Tuple[CalibrationBucket, ...], InsufficientSamples]
    segments: Tuple[Tuple[SegmentKey, SegmentMetrics], ...]
    predictions: Tuple[PredictionRow, ...]


_BUCKET_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def _resolved_well_formed(outcome: OutcomeRecord) -> bool:
    return (
        outcome.status == "resolved"
        and outcome.realized_win is not None
        and outcome.realized_pnl is not None
        and isinstance(outcome.realized_pnl, (int, float))
        and math.isfinite(outcome.realized_pnl)
    )


def evaluate_model(
    model_fn: ModelFn,
    records: Sequence[EvalRecord],
    *,
    model_label: str,
    basis: str = "raw",
    min_calibration_n: int = 5,
) -> ModelReport:
    """Deterministic prequential pass of ``model_fn`` over ``records``."""
    ordered = sorted(records, key=lambda r: (r.dist_inputs.known_at, r.record_id))

    total = len(ordered)
    censored = malformed = abstained = 0
    rows: List[PredictionRow] = []

    for rec in ordered:
        if rec.outcome.status != "resolved":
            censored += 1
            continue
        if not _resolved_well_formed(rec.outcome):
            malformed += 1
            continue
        outcome = model_fn(rec)
        if isinstance(outcome, Unavailable):
            abstained += 1
            rows.append(
                PredictionRow(
                    record_id=rec.record_id,
                    scored=False,
                    pop=None,
                    expected_value=None,
                    abstain_reason=outcome.reason_code,
                    realized_win=rec.outcome.realized_win,
                    realized_pnl=rec.outcome.realized_pnl,
                    segment=rec.segment,
                )
            )
            continue
        rows.append(
            PredictionRow(
                record_id=rec.record_id,
                scored=True,
                pop=outcome.pop,
                expected_value=outcome.expected_value,
                abstain_reason=None,
                realized_win=rec.outcome.realized_win,
                realized_pnl=rec.outcome.realized_pnl,
                segment=rec.segment,
            )
        )

    scored_rows = [r for r in rows if r.scored]
    scored = len(scored_rows)
    eligible = scored + abstained
    coverage = (scored / eligible) if eligible > 0 else None

    brier = ev_rmse = realized_net = None
    if scored > 0:
        brier = sum((r.pop - (1.0 if r.realized_win else 0.0)) ** 2 for r in scored_rows) / scored
        ev_rmse = math.sqrt(
            sum((r.expected_value - r.realized_pnl) ** 2 for r in scored_rows) / scored
        )
        realized_net = sum(r.realized_pnl for r in scored_rows)

    if scored < min_calibration_n:
        calibration: Union[Tuple[CalibrationBucket, ...], InsufficientSamples] = InsufficientSamples(
            n=scored, required=min_calibration_n
        )
    else:
        buckets: List[CalibrationBucket] = []
        for lo, hi in zip(_BUCKET_EDGES[:-1], _BUCKET_EDGES[1:]):
            in_bucket = [
                r for r in scored_rows
                if (lo <= r.pop < hi) or (hi == 1.0 and r.pop == 1.0)
            ]
            if not in_bucket:
                continue
            n = len(in_bucket)
            buckets.append(
                CalibrationBucket(
                    lo=lo,
                    hi=hi,
                    n=n,
                    mean_pop=sum(r.pop for r in in_bucket) / n,
                    realized_rate=sum(1.0 for r in in_bucket if r.realized_win) / n,
                )
            )
        calibration = tuple(buckets)

    seg_map: Dict[SegmentKey, List[PredictionRow]] = {}
    for r in scored_rows:
        seg_map.setdefault(r.segment, []).append(r)
    segments: List[Tuple[SegmentKey, SegmentMetrics]] = []
    for key in sorted(seg_map, key=lambda k: (k.strategy, k.regime, k.dte_bucket)):
        seg_rows = seg_map[key]
        n = len(seg_rows)
        segments.append(
            (
                key,
                SegmentMetrics(
                    n_scored=n,
                    brier=sum((r.pop - (1.0 if r.realized_win else 0.0)) ** 2 for r in seg_rows) / n,
                    ev_rmse=math.sqrt(sum((r.expected_value - r.realized_pnl) ** 2 for r in seg_rows) / n),
                    realized_net=sum(r.realized_pnl for r in seg_rows),
                ),
            )
        )

    return ModelReport(
        model_label=model_label,
        basis=basis,
        evaluator_version=EVALUATOR_VERSION,
        total=total,
        censored=censored,
        malformed=malformed,
        eligible=eligible,
        abstained=abstained,
        scored=scored,
        coverage=coverage,
        brier=brier,
        ev_rmse=ev_rmse,
        realized_net=realized_net,
        calibration=calibration,
        segments=tuple(segments),
        predictions=tuple(rows),
    )


def with_production_multipliers(
    model_fn: ModelFn,
    *,
    pop_multiplier: float = 1.0,
    ev_multiplier: float = 1.0,
) -> ModelFn:
    """READ-ONLY application of a production calibration multiplier.

    The wrapped model's raw outputs are copied into new results labeled
    basis="calibrated" (pop clamped to [0,1] after scaling — a probability
    bound, not a laundering of the raw value: the raw result object is
    unchanged and separately reportable). The multipliers are INPUTS supplied
    by the operator from the production calibration read path; this module
    never imports or invokes the calibration service."""

    def calibrated(rec: EvalRecord) -> EvalOutcome:
        outcome = model_fn(rec)
        if isinstance(outcome, Unavailable):
            return outcome
        return replace(
            outcome,
            basis="calibrated",
            model=f"{outcome.model}+calibrated",
            pop=min(1.0, max(0.0, outcome.pop * pop_multiplier)),
            expected_value=outcome.expected_value * ev_multiplier,
            provenance=Provenance(
                source=outcome.provenance.source,
                version=outcome.provenance.version,
                params_hash=params_hash(
                    {
                        "raw": outcome.provenance.params_hash,
                        "pop_multiplier": pop_multiplier,
                        "ev_multiplier": ev_multiplier,
                    }
                ),
            ),
        )

    return calibrated


@dataclass(frozen=True)
class HeadToHead:
    """Metrics recomputed on the JOINT scored set (records both models scored)
    — the only fair basis for the charter falsifier comparison."""

    model_a: str
    model_b: str
    n_joint: int
    brier_a: Optional[float]
    brier_b: Optional[float]
    ev_rmse_a: Optional[float]
    ev_rmse_b: Optional[float]
    realized_net_joint: Optional[float]


def head_to_head(report_a: ModelReport, report_b: ModelReport) -> HeadToHead:
    rows_a = {r.record_id: r for r in report_a.predictions if r.scored}
    rows_b = {r.record_id: r for r in report_b.predictions if r.scored}
    joint_ids = sorted(set(rows_a) & set(rows_b))
    n = len(joint_ids)
    if n == 0:
        return HeadToHead(report_a.model_label, report_b.model_label, 0, None, None, None, None, None)

    def _metrics(rows: Dict[str, PredictionRow]) -> Tuple[float, float]:
        brier = sum(
            (rows[i].pop - (1.0 if rows[i].realized_win else 0.0)) ** 2 for i in joint_ids
        ) / n
        rmse = math.sqrt(
            sum((rows[i].expected_value - rows[i].realized_pnl) ** 2 for i in joint_ids) / n
        )
        return brier, rmse

    brier_a, rmse_a = _metrics(rows_a)
    brier_b, rmse_b = _metrics(rows_b)
    net = sum(rows_a[i].realized_pnl for i in joint_ids)
    return HeadToHead(
        model_a=report_a.model_label,
        model_b=report_b.model_label,
        n_joint=n,
        brier_a=brier_a,
        brier_b=brier_b,
        ev_rmse_a=rmse_a,
        ev_rmse_b=rmse_b,
        realized_net_joint=net,
    )


# ---------------------------------------------------------------------------
# Read-only row mapping. NOT a DB client, NOT called by any job — an operator
# (or an offline notebook/script) fetches rows read-only and maps them here.
# ---------------------------------------------------------------------------


def records_from_rows(
    rows: Iterable[Dict[str, Any]],
) -> Tuple[List[EvalRecord], List[Tuple[int, str]]]:
    """Map plain dict rows (historical suggestion + outcome joins) to typed
    ``EvalRecord``s. Returns (records, skipped) where ``skipped`` lists
    (row_index, reason) for every row that could not be mapped — rows are
    never silently dropped and never patched with defaults (H9).

    Expected row keys: record_id, known_at, strategy, legs (list of dicts:
    action/option_type/strike and optional iv/delta), net_premium, and
    optionally contracts (default 1), spot, dte_days, risk_free_rate
    (default 0.0), outcome_status (default "open"), realized_win,
    realized_pnl, regime (default "unknown"), dte_bucket (default "unknown").
    Optional MARKET fields may be absent (models abstain downstream); the
    IDENTITY fields listed as required must be present here.
    """
    records: List[EvalRecord] = []
    skipped: List[Tuple[int, str]] = []
    for idx, row in enumerate(rows):
        try:
            missing = [k for k in ("record_id", "known_at", "strategy", "legs", "net_premium") if row.get(k) is None]
            if missing:
                skipped.append((idx, f"missing required keys: {missing}"))
                continue
            legs = tuple(
                LegSpec(
                    action=leg["action"],
                    option_type=leg["option_type"],
                    strike=float(leg["strike"]),
                    iv=(float(leg["iv"]) if leg.get("iv") is not None else None),
                    delta=(float(leg["delta"]) if leg.get("delta") is not None else None),
                )
                for leg in row["legs"]
            )
            structure = StructureSpec(
                strategy=row["strategy"],
                legs=legs,
                net_premium=float(row["net_premium"]),
                contracts=int(row.get("contracts") or 1),
            )
            dist_inputs = DistributionInputs(
                spot=(float(row["spot"]) if row.get("spot") is not None else None),
                dte_days=(float(row["dte_days"]) if row.get("dte_days") is not None else None),
                known_at=str(row["known_at"]),
                risk_free_rate=float(row.get("risk_free_rate") or 0.0),
            )
            outcome = OutcomeRecord(
                status=str(row.get("outcome_status") or "open"),
                realized_win=row.get("realized_win"),
                realized_pnl=(float(row["realized_pnl"]) if row.get("realized_pnl") is not None else None),
            )
            segment = SegmentKey(
                strategy=row["strategy"],
                regime=str(row.get("regime") or "unknown"),
                dte_bucket=str(row.get("dte_bucket") or "unknown"),
            )
            records.append(
                EvalRecord(
                    record_id=str(row["record_id"]),
                    structure=structure,
                    dist_inputs=dist_inputs,
                    outcome=outcome,
                    segment=segment,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            skipped.append((idx, f"unmappable row: {exc!r}"))
    return records, skipped
