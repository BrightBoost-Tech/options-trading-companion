"""Greek-cap ALERT-ONLY counterfactual — would-block frequency study
(OBSERVE-ONLY, operator-invoked, read-only).

Owner items 9 + 11 (Lane E). The live seam
(``risk_envelope.compute_greek_cap_counterfactual``, wired into
``check_all_envelopes``) computes, per q15min monitor cycle and per reference
tightness row (tight/medium/loose), whether the book WOULD breach a documented
greek cap — WITHOUT arming any cap. The monitor stamps a COMPACT summary of that
counterfactual into its ``job_runs.result.results[]`` (``_compact_greek_cf``).
This CLI reads those accrued summaries and reports would-block FREQUENCIES so the
owner can decide, from this system's OWN data, whether a real greek cap is worth
arming and at what tightness.

WHY A job_runs CLI (not a live-DB consumer): the counterfactual field is
observe-only telemetry; no decision reads it, and there is no bespoke table.
job_runs.result already durably accrues the monitor's per-user return every
cycle, so the frequency study needs no new persistence.

HONESTY CONTRACT (same H9 discipline as scripts/analytics/realized_cost_study.py):
  - COUNT typed states, never fabricate. Each reference row's would_block is one
    of True / False / None (typed UNAVAILABLE — dark, partial, sign-mismatched, or
    uncorroborated greeks). UNAVAILABLE cycles are COUNTED as unavailable, NEVER
    scored as "would not block". §8 double-dormancy: production legs carry no
    greeks today, so EVERY row reads unavailable until #1259's stage-time greek
    population accrues — the report will honestly show ~100% unavailable now and
    real frequencies later, with NO code change.
  - OBSERVE-ONLY end to end: this file arms no cap, changes no config, feeds no
    decision. It opens NO database connection and touches NO network — ``--emit-sql``
    prints the exact READ-ONLY query an operator runs (Supabase MCP / psql),
    ``--rows-json`` consumes the JSON that query returns, ``--out`` writes a dated
    markdown report. There is no live-DB code path to rot.
  - The reference caps and their derivation are OWNED by risk_envelope (never
    re-derived here) — this CLI only tallies the states risk_envelope produced.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

MODEL_VERSION = "greek-cap-counterfactual-report/1.0"

# Read-only query an operator runs (Supabase MCP / psql) to regenerate the
# --rows-json payload. ONE row per (job_run, per-user result) that carries a
# greek_cap_counterfactual summary. STRICTLY READ-ONLY: a single SELECT, no write
# verbs. The monitor's per-user return lands under result->'results'; we unnest it
# and keep only elements that carry the observe-only counterfactual summary.
STUDY_SQL = r"""
SELECT json_build_object(
  'schema_version', 1,
  'model_version', 'greek-cap-counterfactual-report/1.0',
  'generated_at', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD'),
  'source', 'job_runs.result->results[]->greek_cap_counterfactual (intraday_risk_monitor)',
  'rows', COALESCE(json_agg(row_to_json(x) ORDER BY x.started_at), '[]'::json)
)
FROM (
  SELECT
    jr.id::text                                             AS job_run_id,
    to_char(jr.started_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS"Z"')                   AS started_at,
    (res->>'user_id')                                       AS user_id,
    (res->'greek_cap_counterfactual')                       AS greek_cap_counterfactual
  FROM job_runs jr
  CROSS JOIN LATERAL jsonb_array_elements(
      COALESCE(jr.result->'results', '[]'::jsonb)) AS res
  WHERE jr.job_name = 'intraday_risk_monitor'
    AND res ? 'greek_cap_counterfactual'
    AND jr.started_at > now() - interval '30 days'
) x;
""".strip()


# --- aggregation -------------------------------------------------------------
@dataclass
class RowTally:
    """would_block frequency for ONE reference row across all cycles."""
    name: str
    n_block: int = 0
    n_no_block: int = 0
    n_unavailable: int = 0
    blocking_greeks: Counter = field(default_factory=Counter)

    @property
    def n_total(self) -> int:
        return self.n_block + self.n_no_block + self.n_unavailable

    @property
    def n_evaluable(self) -> int:
        return self.n_block + self.n_no_block

    @property
    def block_rate_of_evaluable(self) -> Optional[float]:
        return (self.n_block / self.n_evaluable) if self.n_evaluable else None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "n_total": self.n_total,
            "n_would_block": self.n_block,
            "n_would_not_block": self.n_no_block,
            "n_unavailable": self.n_unavailable,
            "block_rate_of_evaluable": self.block_rate_of_evaluable,
            "blocking_greeks": dict(self.blocking_greeks),
        }


@dataclass
class Study:
    generated_at: str
    source: str
    model_version: str
    n_cycles: int
    n_available_cycles: int
    n_unavailable_cycles: int
    rows: List[RowTally]


_ROW_ORDER = ("tight", "medium", "loose")


def build_study(payload: Mapping[str, Any]) -> Study:
    """Tally would_block states across the accrued monitor summaries. Pure; a
    partial / malformed element is counted, never crashes the study."""
    tallies: Dict[str, RowTally] = {n: RowTally(n) for n in _ROW_ORDER}
    n_cycles = 0
    n_available = 0
    n_unavailable = 0

    for row in payload.get("rows") or []:
        cf = row.get("greek_cap_counterfactual")
        if not isinstance(cf, Mapping):
            continue
        n_cycles += 1
        if not cf.get("available"):
            # The whole cycle's greeks were unavailable (dark/partial/etc.): every
            # reference row is unavailable this cycle. Counted, never scored.
            n_unavailable += 1
            for name in _ROW_ORDER:
                tallies.setdefault(name, RowTally(name)).n_unavailable += 1
            continue
        n_available += 1
        for r in cf.get("rows") or []:
            name = r.get("name")
            if name not in tallies:
                tallies[name] = RowTally(str(name))
            t = tallies[name]
            wb = r.get("would_block")
            if wb is True:
                t.n_block += 1
                for g in r.get("blocking_greeks") or []:
                    t.blocking_greeks[g] += 1
            elif wb is False:
                t.n_no_block += 1
            else:  # None → typed unavailable
                t.n_unavailable += 1

    ordered = [tallies[n] for n in _ROW_ORDER if n in tallies]
    ordered += [tallies[n] for n in sorted(tallies) if n not in _ROW_ORDER]
    return Study(
        generated_at=str(payload.get("generated_at", "")),
        source=str(payload.get("source", "")),
        model_version=str(payload.get("model_version", MODEL_VERSION)),
        n_cycles=n_cycles,
        n_available_cycles=n_available,
        n_unavailable_cycles=n_unavailable,
        rows=ordered,
    )


# --- rendering ---------------------------------------------------------------
def _fmt_rate(x: Optional[float]) -> str:
    return "—" if x is None else f"{x:.1%}"


def render_markdown(study: Study) -> str:
    L: List[str] = []
    L.append(f"# Greek-Cap Counterfactual — would-block frequencies — {study.generated_at}")
    L.append("")
    L.append(f"- Source: {study.source}")
    L.append(f"- Model: `{study.model_version}`")
    L.append(f"- Monitor cycles with a counterfactual summary: **{study.n_cycles}** "
             f"({study.n_available_cycles} greeks-available / "
             f"{study.n_unavailable_cycles} greeks-unavailable)")
    L.append("- OBSERVE-ONLY. The greek caps are DORMANT (default 0); this is a "
             "counterfactual of what a reference cap WOULD do — it arms nothing, "
             "rejects nothing, sizes nothing.")
    L.append("- Reference caps are DERIVED (see `risk_envelope.compute_greek_cap_"
             "counterfactual`): tight/medium/loose = per-symbol / daily / weekly "
             "loss fraction × equity, translated into each greek's unit via the "
             "envelope's own stress moves. UNAVAILABLE cycles are COUNTED, never "
             "scored as 'would not block' (H9).")
    if study.n_available_cycles == 0 and study.n_cycles > 0:
        L.append("")
        L.append("> **All cycles greeks-UNAVAILABLE.** Expected while production "
                 "legs carry no greeks (§8 double-dormancy). Real frequencies will "
                 "appear once stage-time greek population (#1259) accrues — no code "
                 "change needed.")
    L.append("")
    L.append("| reference row | cycles | would-block | would-not-block | "
             "unavailable | block-rate (of evaluable) | blocking greeks |")
    L.append("|---|---|---|---|---|---|---|")
    for r in study.rows:
        L.append(
            f"| {r.name} | {r.n_total} | {r.n_block} | {r.n_no_block} | "
            f"{r.n_unavailable} | {_fmt_rate(r.block_rate_of_evaluable)} | "
            f"`{dict(r.blocking_greeks) or '{}'}` |")
    L.append("")
    if not study.rows:
        L.append("_No counterfactual summaries in the payload._")
        L.append("")
    return "\n".join(L) + "\n"


# --- CLI --------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Greek-cap counterfactual would-block frequency study "
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
    study = build_study(payload)
    md = render_markdown(study)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"wrote {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
