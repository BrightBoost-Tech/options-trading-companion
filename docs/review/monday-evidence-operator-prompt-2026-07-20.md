# Monday natural-evidence consolidated read — operator prompt (2026-07-20)

Run this **Monday 2026-07-20, at or after 17:45Z** (>= ~12:45 CT — after the
11:00 CT scan, 11:30 CT executor, and the first intraday monitor cycles have
run, so the day's natural-evidence sinks have accrued). It is a **read-only,
observe-only** consolidation: it places no trade, flips no flag, writes no
production row, changes no config, and touches no broker.

## Model policy (repeat)

Same policy as the build lane:

- **ORCHESTRATOR = Claude Fable 5** (`claude --model claude-fable-5`).
- **SUBAGENTS = Opus** (spawn any sub-tasks with the opus model).

Report the effective model before doing work. If the orchestrator is not Fable
5, stop with `BLOCKED_MODEL_MISMATCH` — do not silently substitute.

## What it does

`scripts/analytics/monday_evidence_reader.py` consolidates, for ONE
`cycle_date`, twelve natural-evidence sinks into a stable JSON snapshot + a
concise markdown report, cohorts kept separate, with cycle + deployment identity
(`decision_runs.git_sha`) and known-at (`as_of_ts`) stamps. The twelve sections:

1. cycle & deployment identity (git_sha / code_sha / as_of_ts)
2. H7 finals (`disposition='h7_dropped'` parent / `h7_subreason` / `sizing_outcome`)
3. candidate terminal disposition census
4. option-quote provenance (source / 429 / fallback / freshness)
5. exact-leg OI + hypothetical-floor counterfactual tallies
6. scan-time spot / IV / delta capture rates on staged opens
7. tier-taper DARK payload (current / proposed / difference / verdict)
8. greek-cap counterfactual (coverage flags + would_block)
9. TCM current vs `tcm_v2_proposal` stamp counts
10. single-leg experiment opt-in count (expected **0** — dark)
11. scorable-close count + model_review trigger state
12. writer / no-op / failure counters (disposition + provenance + quality-gate)

**Each section is typed independently:** `OK` · `HONEST-EMPTY` (the query ran,
the sink is dark this cycle — a finding, not a fault) · `FAILED-FETCH` (table
absent / not fetched — an instrument fault, never scored as zero) ·
`NOT-FETCHED` (absent from the payload). A FAILED section is never conflated
with EMPTY (H9).

Most sinks are **forward-looking**: verified read-only 2026-07-19, the
`candidate_terminal_dispositions` and `option_quote_provenance` tables exist but
hold zero rows, and no job_run yet carries `cycle_metadata.tier_taper`, a
`results[].greek_cap_counterfactual`, a `tcm.tcm_v2_proposal` stamp, a
`model_review` result, or a stage-seam `entry_underlying_spot`/leg `iv`/`delta`
capture. Expect a mostly HONEST-EMPTY report until those sinks first accrue —
that is correct, and needs no code change; the same tool shows real
distributions the moment rows land.

## Two named measurement limits (do not read past them)

- **Greek-cap HEADROOM is unavailable at this grain by construction.** The
  monitor's `_compact_greek_cf` strips headroom / cap / exposure before the
  summary reaches `job_runs`; only the coverage flags + `would_block` persist.
  The report types headroom `unavailable_by_construction`, never zero.
- **Provenance writer counters are log-only.** `rows_written` /
  `persist_failures` / `schema_absent_noops` are never copied into
  `job_runs.result`; the report counts provenance **writes** from the persisted
  rows by `cycle_date` and types the failure/no-op counters unavailable at the
  DB grain.

## How to run

The tool never opens a DB connection. `--emit-sql` prints the exact read-only
query; you run it via the Supabase MCP (read-only) or psql; then feed the JSON
back in.

```bash
# 1. Emit the read-only consolidated SQL for Monday's cycle (date baked in).
python scripts/analytics/monday_evidence_reader.py \
    --emit-sql --cycle-date 2026-07-20 > /tmp/monday_evidence.sql

# 2. Run /tmp/monday_evidence.sql READ-ONLY (Supabase MCP execute_sql / psql).
#    It returns ONE row, ONE json column ("payload"). Save that json object to
#    /tmp/monday_evidence.json  (the object itself, not the {"payload": ...}
#    wrapper — unwrap the single column).

# 3. Render the report + the stable JSON snapshot. --cycle-date here
#    cross-checks the payload's own cycle_date (a mismatch is surfaced LOUDLY;
#    the payload wins, per STEP 0 clock grounding).
python scripts/analytics/monday_evidence_reader.py \
    --rows-json /tmp/monday_evidence.json \
    --cycle-date 2026-07-20 \
    --out docs/review/monday-evidence-report-2026-07-20.md \
    --json-out docs/review/monday-evidence-2026-07-20.json
```

The reader is a **pure function** of the payload: identical rows produce
byte-identical JSON and markdown (`--json-out` is `sort_keys` indented), so a
re-run or a diff of two dated snapshots is meaningful.

## Read-only contract

Allowed: `--emit-sql`, running that SQL read-only, `--rows-json` / `--out` /
`--json-out` (which write only local report/JSON files), and documentation-only
commits on a branch. **Not** allowed in this lane: any write verb against the
DB, any migration, any Railway env / config change, any broker action, any
schedule change, any scan / model-review trigger, or merging to main. If a
section reports `FAILED-FETCH` because a table is absent, that is a schema-state
finding for the human — do not apply the migration from this lane.
