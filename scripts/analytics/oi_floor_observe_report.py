"""Exact-leg OPEN-INTEREST (OI) floor observation — Lane H OBSERVE-FIRST report.

OBSERVE-ONLY, operator-invoked, READ-ONLY. Summarizes the exact-leg OI evidence
the quote-provenance recorder now stamps into
``option_quote_provenance.details->'oi'`` (leg_set rows): the per-leg OI
distribution and the hypothetical-floor counterfactuals (would_pass / would_fail
/ indeterminate) computed at write time. It answers ONE question, before any
enforcing floor ever ships: **if a floor of N had been applied, what fraction of
the leg sets the scanner actually evaluated would it have failed — and how many
are INDETERMINATE because OI was dark?**

WHY A READ-ONLY CLI (not a live consumer):
  - There is NO live OI gate. ``ENABLE_LIVE_OI_FLOOR`` is a separate, unbuilt
    control; this lane records only. The counterfactuals are already persisted
    at write time by ``compute_oi_counterfactuals`` — this report AGGREGATES
    them, it does not re-decide anything.
  - The natural rows accrue only as scan cycles run. A report that queried at
    build time would summarize an empty table, so the read/aggregate split
    (mirrors scripts/analytics/realized_cost_study.py) lets an operator run it
    whenever cycles have accrued.

HONESTY CONTRACT (H9 both-ends — the whole point of this lane):
  - OI 0 is a REAL value (a listed-but-untraded contract). It is AVAILABLE and
    it FAILS a positive floor. It is COUNTED in the value distribution and never
    conflated with "unavailable".
  - Missing / dark OI is typed UNAVAILABLE and COUNTED, never scored as zero. A
    leg set with ANY unavailable OI is INDETERMINATE at every floor — reported
    as its own bucket, never folded into pass or fail.
  - The floor pass/fail RATES are computed over the EVALUABLE (fully-priced)
    leg sets only; the indeterminate count is reported alongside so the reader
    sees the denominator honestly (a would-fail rate over a tiny evaluable set
    is flagged, not hidden).

OPERATION (mirrors scripts/analytics/realized_cost_study.py):
  - This file lives OUTSIDE ``packages/quantum`` and imports NOTHING from the
    scanner/ranker/gate/executor. It opens NO database connection and touches NO
    network. ``--emit-sql`` prints the exact READ-ONLY query an operator runs
    (Supabase MCP / psql); ``--rows-json`` consumes the JSON that query returns;
    ``--out`` writes a dated markdown report. There is no live-DB code path to
    rot.
"""

from __future__ import annotations

import argparse
import json
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

MODEL_VERSION = "oi-floor-observe/lane-h-1.0"

# Read-only query an operator runs (Supabase MCP / psql) to regenerate the
# --rows-json payload. ONE row per persisted leg_set that carries the Lane H OI
# observation (``details ? 'oi'``). Emits the whole ``details->'oi'`` object
# (per-leg OI + the write-time counterfactuals) plus the row's identity/verdict
# so the aggregation can partition by rejected/passed/selected. STRICTLY
# READ-ONLY: a single SELECT, no write verbs.
STUDY_SQL = r"""
SELECT json_build_object(
  'schema_version', 1,
  'model_version', 'oi-floor-observe/lane-h-1.0',
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
  'source', 'option_quote_provenance leg_set rows with details->oi',
  'rows', COALESCE(json_agg(row_to_json(x)
            ORDER BY x.created_at, x.record_id), '[]'::json)
)
FROM (
  SELECT
    oqp.id::text                                           AS record_id,
    to_char(oqp.created_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"')                  AS created_at,
    oqp.cycle_date::text                                   AS cycle_date,
    oqp.symbol                                             AS symbol,
    oqp.strategy_key                                       AS strategy_key,
    oqp.verdict                                            AS verdict,
    oqp.reject_reason                                      AS reject_reason,
    oqp.selected                                           AS selected,
    oqp.leg_fingerprint                                    AS leg_fingerprint,
    oqp.details->'oi'                                      AS oi
  FROM option_quote_provenance oqp
  WHERE oqp.record_type = 'leg_set'
    AND oqp.details ? 'oi'
) x;
""".strip()


# --- small helpers ----------------------------------------------------------
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


# --- per-row parse (pure; never raises on a partial row) --------------------
@dataclass(frozen=True)
class LegSetOI:
    record_id: str
    symbol: str
    strategy_key: str
    verdict: str            # rejected | passed | (unknown)
    selected: bool
    legs_total: int
    legs_available: int
    legs_unavailable: int
    any_unavailable: bool
    min_leg_oi: Optional[int]
    available_leg_ois: Tuple[int, ...]   # per-leg OI values (0 included)
    # floor -> verdict (pass | fail | indeterminate), from the persisted
    # counterfactuals (never recomputed here).
    floor_verdicts: Mapping[int, str]


def parse_row(row: Mapping[str, Any]) -> Optional[LegSetOI]:
    """Map ONE db row's ``details->oi`` object into a typed LegSetOI. Returns
    None when the oi object is missing/malformed (counted as skipped by the
    caller — never fabricated)."""
    oi = row.get("oi")
    if not isinstance(oi, Mapping):
        return None
    legs = oi.get("legs") if isinstance(oi.get("legs"), list) else []
    available_ois: List[int] = []
    for leg in legs:
        if not isinstance(leg, Mapping):
            continue
        if leg.get("oi_available"):
            v = _coerce_int(leg.get("oi"))
            if v is not None:
                available_ois.append(v)
    floor_verdicts: Dict[int, str] = {}
    for cf in (oi.get("counterfactuals") or []):
        if not isinstance(cf, Mapping):
            continue
        fl = _coerce_int(cf.get("floor"))
        if fl is None:
            continue
        floor_verdicts[fl] = str(cf.get("verdict") or "unknown")
    return LegSetOI(
        record_id=str(row.get("record_id") or ""),
        symbol=str(row.get("symbol") or "unknown"),
        strategy_key=str(row.get("strategy_key") or "unknown"),
        verdict=str(row.get("verdict") or "unknown"),
        selected=bool(row.get("selected")),
        legs_total=_coerce_int(oi.get("legs_total")) or len(legs),
        legs_available=_coerce_int(oi.get("legs_oi_available")) or len(available_ois),
        legs_unavailable=_coerce_int(oi.get("legs_oi_unavailable")) or 0,
        any_unavailable=bool(oi.get("any_oi_unavailable")),
        min_leg_oi=_coerce_int(oi.get("min_leg_oi")),
        available_leg_ois=tuple(available_ois),
        floor_verdicts=floor_verdicts,
    )


# --- floor aggregation ------------------------------------------------------
@dataclass(frozen=True)
class FloorStat:
    """Leg-set-level counterfactual outcome for ONE floor. Rates are over the
    EVALUABLE (fully-priced) leg sets only; indeterminate is its own bucket."""
    floor: int
    n_pass: int
    n_fail: int
    n_indeterminate: int

    @property
    def n_evaluable(self) -> int:
        return self.n_pass + self.n_fail

    @property
    def would_fail_rate(self) -> Optional[float]:
        return (self.n_fail / self.n_evaluable) if self.n_evaluable else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "floor": self.floor,
            "n_pass": self.n_pass,
            "n_fail": self.n_fail,
            "n_indeterminate": self.n_indeterminate,
            "n_evaluable": self.n_evaluable,
            "would_fail_rate_over_evaluable": self.would_fail_rate,
        }


@dataclass(frozen=True)
class OIDistribution:
    n_leg_values: int         # count of per-leg AVAILABLE OI values
    n_zero: int               # legs whose OI is exactly 0 (real, not missing)
    min_oi: Optional[int]
    median_oi: Optional[float]
    p25_oi: Optional[float]
    p75_oi: Optional[float]
    max_oi: Optional[int]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "n_leg_values": self.n_leg_values,
            "n_zero_oi_legs": self.n_zero,
            "min_oi": self.min_oi,
            "p25_oi": self.p25_oi,
            "median_oi": self.median_oi,
            "p75_oi": self.p75_oi,
            "max_oi": self.max_oi,
        }


@dataclass(frozen=True)
class Segment:
    name: str
    n_leg_sets: int
    n_fully_available: int
    n_any_unavailable: int
    distribution: OIDistribution
    floors: Tuple[FloorStat, ...]


@dataclass(frozen=True)
class OIReport:
    generated_at: str
    source: str
    model_version: str
    total_rows: int
    n_parsed: int
    n_skipped_malformed: int
    segments: Tuple[Segment, ...]


def _percentile(values: List[int], q: float) -> Optional[float]:
    """Linear-interpolated percentile (q in [0,1]); None on empty. statistics
    has no percentile in 3.11 stdlib, so compute it directly."""
    if not values:
        return None
    s = sorted(values)
    if len(s) == 1:
        return float(s[0])
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return round(s[lo] + (s[hi] - s[lo]) * frac, 2)


def _build_distribution(rows: List[LegSetOI]) -> OIDistribution:
    vals: List[int] = []
    for r in rows:
        vals.extend(r.available_leg_ois)
    return OIDistribution(
        n_leg_values=len(vals),
        n_zero=sum(1 for v in vals if v == 0),
        min_oi=(min(vals) if vals else None),
        median_oi=(round(statistics.median(vals), 2) if vals else None),
        p25_oi=_percentile(vals, 0.25),
        p75_oi=_percentile(vals, 0.75),
        max_oi=(max(vals) if vals else None),
    )


def _build_floor_stats(rows: List[LegSetOI]) -> Tuple[FloorStat, ...]:
    # Union of every floor observed across the rows (floors are env-config, so
    # a payload could mix floor sets across cycles — union keeps them all).
    floors = sorted({fl for r in rows for fl in r.floor_verdicts})
    stats: List[FloorStat] = []
    for fl in floors:
        n_pass = n_fail = n_ind = 0
        for r in rows:
            v = r.floor_verdicts.get(fl)
            if v == "pass":
                n_pass += 1
            elif v == "fail":
                n_fail += 1
            elif v == "indeterminate":
                n_ind += 1
        stats.append(FloorStat(floor=fl, n_pass=n_pass, n_fail=n_fail,
                               n_indeterminate=n_ind))
    return tuple(stats)


def _build_segment(name: str, rows: List[LegSetOI]) -> Segment:
    return Segment(
        name=name,
        n_leg_sets=len(rows),
        n_fully_available=sum(1 for r in rows if not r.any_unavailable),
        n_any_unavailable=sum(1 for r in rows if r.any_unavailable),
        distribution=_build_distribution(rows),
        floors=_build_floor_stats(rows),
    )


# Deterministic segment order in the report.
_SEGMENT_ORDER = ("all", "rejected", "passed", "selected")


def build_report(payload: Mapping[str, Any]) -> OIReport:
    raw_rows = payload.get("rows") or []
    parsed: List[LegSetOI] = []
    skipped = 0
    for r in raw_rows:
        p = parse_row(r) if isinstance(r, Mapping) else None
        if p is None:
            skipped += 1
        else:
            parsed.append(p)

    by_segment: Dict[str, List[LegSetOI]] = {
        "all": list(parsed),
        "rejected": [r for r in parsed if r.verdict == "rejected"],
        "passed": [r for r in parsed if r.verdict == "passed"],
        "selected": [r for r in parsed if r.selected],
    }
    segments = tuple(
        _build_segment(name, by_segment[name])
        for name in _SEGMENT_ORDER if by_segment.get(name)
    )
    return OIReport(
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", "")),
        model_version=str(payload.get("model_version", MODEL_VERSION)),
        total_rows=len(raw_rows),
        n_parsed=len(parsed),
        n_skipped_malformed=skipped,
        segments=segments,
    )


# --- rendering --------------------------------------------------------------
def _fmt(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def _pct(x: Optional[float]) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def render_markdown(report: OIReport) -> str:
    L: List[str] = []
    L.append(f"# Exact-leg OI floor observation — Lane H — {report.generated_at}")
    L.append("")
    L.append(f"- Source: {report.source}")
    L.append(f"- Model: `{report.model_version}`")
    L.append(f"- Leg-set rows with OI observation: **{report.n_parsed}** "
             f"(of {report.total_rows}; {report.n_skipped_malformed} skipped malformed)")
    L.append("- OBSERVE-ONLY. There is NO live OI gate. The floors below are "
             "HYPOTHETICAL counterfactuals recorded at write time; nothing here "
             "gated, ranked, or sized any candidate.")
    L.append("")
    L.append("### Honesty legend")
    L.append("- **OI 0 is a real value** (listed-but-untraded) — it is AVAILABLE "
             "and it FAILS a positive floor; it is counted in the distribution "
             "(`n_zero_oi_legs`), never as missing.")
    L.append("- **Dark / missing OI is UNAVAILABLE** — a leg set with any "
             "unavailable OI is **INDETERMINATE** at every floor (its own "
             "bucket), never folded into pass/fail. Floor would-fail rates are "
             "over the EVALUABLE (fully-priced) leg sets only.")
    L.append("")
    if not report.segments:
        L.append("_No OI-observed leg sets in the payload (natural rows accrue "
                 "as scan cycles run)._")
        L.append("")
        return "\n".join(L) + "\n"

    for seg in report.segments:
        L.append(f"## Segment: {seg.name.upper()}")
        L.append("")
        L.append(f"- Leg sets: **{seg.n_leg_sets}** "
                 f"({seg.n_fully_available} fully-priced OI / "
                 f"{seg.n_any_unavailable} with >=1 dark leg)")
        d = seg.distribution
        L.append(f"- Per-leg OI (available legs): n={d.n_leg_values}, "
                 f"zero-OI legs={d.n_zero}, min={d.min_oi}, "
                 f"p25={_fmt(d.p25_oi)}, median={_fmt(d.median_oi)}, "
                 f"p75={_fmt(d.p75_oi)}, max={d.max_oi}")
        L.append("")
        L.append("| hypothetical floor | pass | fail | indeterminate | "
                 "evaluable | would-fail rate (evaluable) |")
        L.append("|---|---|---|---|---|---|")
        for f in seg.floors:
            L.append(
                f"| {f.floor} | {f.n_pass} | {f.n_fail} | {f.n_indeterminate} "
                f"| {f.n_evaluable} | {_pct(f.would_fail_rate)} |")
        if not seg.floors:
            L.append("| _(no floors recorded)_ | — | — | — | — | — |")
        L.append("")
    return "\n".join(L) + "\n"


# --- CLI --------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Lane H exact-leg OI floor observation report "
                    "(observe-only, read-only)")
    ap.add_argument("--rows-json", help="path to the JSON payload emitted by --emit-sql")
    ap.add_argument("--emit-sql", action="store_true",
                    help="print the read-only SQL to regenerate the payload, then exit")
    ap.add_argument("--out", help="write the markdown report to this path (default: stdout)")
    args = ap.parse_args(argv)

    if args.emit_sql:
        print(STUDY_SQL)
        return 0
    if not args.rows_json:
        ap.error("--rows-json is required (or use --emit-sql)")

    with open(args.rows_json, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    report = build_report(payload)
    md = render_markdown(report)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
