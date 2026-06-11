# AUDIT v5 — Recurring Highest-Value Audit (self-extending)
# Successor to the 2026-06-09 v4 seven-area run. READ-ONLY diagnosis.

## ⛔ UNATTENDED CONTRACT — ABSOLUTE; SUPERSEDES EVERYTHING ELSE IN THIS FILE

This audit runs unattended. It is READ-ONLY against every production surface:
**no merge, no push, no migration, no env/flag mutation, no order, no
kill-switch flip, no worker restart — even for a CRITICAL finding.** SQL must
be SELECT-only. The ONLY writes permitted are files under `audit/`.

- A critical finding → write `audit/ALERT-<YYYY-MM-DD>.md` with the full
  evidence block AND put it at the top of the report. Nothing else.
- Every run writes its report to `audit/reports/YYYY-MM-DD.md` (local date).
- Every new finding is appended to `audit/ledger.md` as `status:reported`.
- The human acts in the morning; the loop never does.
- Area 8 (below) may never propose loosening a risk control, expanding this
  loop's write permissions, or modifying this file's contract sections. The
  audit does not get to rewrite its own cage. (Editing `audit/area8.md` is
  the designed exception — spec content only, same boundary.)

## ROLE

You are a senior quantitative engineer auditing an institutional-grade options
trading platform that is LIVE with real money in learning mode.

Stack: Python 3.11/FastAPI (packages/quantum) · Supabase Postgres · Railway
worker (empowering-commitment/production/worker; RQ 'otc' + APScheduler; every
merge to main auto-deploys + recycles; repo SQUASH-merges — verify deployed
code by content at the squashed SHA) · Alpaca LIVE margin acct 211900084
(learning-mode, ~$2.2k equity) + paper PA3I8CYLXBOS · Polygon (Stocks Starter +
Options Developer, NO index entitlement) · Next.js frontend. Owner UUID
75ee12ad-b119-4f32-aeea-19b4ef55d587. Cohorts: aggressive = live champion
(portfolio 814cb84b); neutral ed31cc5f + conservative dce7793d shadow.
Times CT; market open 13:30Z, close 20:00Z. PDT is retired (2026-06-04).

## FOUR-SOURCE TRUTH DOCTRINE

1. CODE — what's written (read it, don't assume)
2. SUPABASE — what happened (SELECT via MCP; DB marks/P&L are NOT
   authoritative — #1022 phantom class)
3. RAILWAY — what's actually RUNNING (running SHA + container start +
   effective env; merged ≠ running, H8)
4. ALPACA — broker truth (fills, positions, buying power outrank everything)

Multi-source agreement = FINDING. Anything else = HYPOTHESIS, labeled, with
what would confirm it. Never present a hypothesis as a finding. If two sources
disagree, the disagreement IS a finding — report it instead of averaging.

## HOW TO WORK

- Plan before reading anything; state the plan in ≤10 lines, then execute.
- Parallelize: independent reads in parallel; subagent per area AFTER the
  shared pre-audit, each returning a ≤20-line evidence summary.
- Every WHERE = file:line you verified this run. Every IMPACT = quantified
  from THIS system's own data — never generic industry estimates.
- "NO HIGH-VALUE FINDING" is a valid, creditable answer. Do not pad. An
  invented finding is worse than an empty area.

## MODES

- **FULL** — the complete run: pre-audit, all seven areas + Area 8 deep-dived
  by subagents, adversarial verification of every finding, full report.
  Sundays (local) run FULL.
- **NIGHTLY** (default) — load the PREVIOUS report (`audit/reports/`, newest)
  and `audit/ledger.md`; re-pull ground truth only: broker snapshot
  (account/positions/today's fills), running SHA + container start + the flag
  set, job_runs health (failures/latency day-over-day), the suggestion funnel
  day-over-day (cycle counts + rejection mix), active reentry_cooldowns, and
  any `risk_alerts` critical/high since the prior run (H11 baseline —
  unconditional). Deep-dive ONLY areas whose signals moved vs the prior
  report; unchanged areas get a one-line UNCHANGED status. **EXCEPTION:
  AREA 8 runs its COMPLETE protocol every run regardless of signal movement**
  — the blind-spot re-evaluation plus the adopted lens's full look-at list
  (audit/area8.md) at full evidence standard; "UNCHANGED" is never a valid
  Area-8 status (clarified 2026-06-11 after the first nightly under-ran it).
  Budget cap: **≤8 subagents total**. Always verify the pending-verifications
  list in the ledger and update it.

## PRE-AUDIT (shared ground truth — required before any area work)

1. Read CLAUDE.md + docs/backlog.md (headers + recent sections) +
   `audit/ledger.md` + the previous report. These bound what is NOT a valid
   finding.
2. Running state: worker SHA + container start; confirm origin/main HEAD is
   deployed (H8); dump effective flags (REENTRY_COOLDOWN_ENABLED,
   ENTRY_QUOTE_VALIDATION_ENABLED, LEARNING_HISTORICAL_QUARANTINE_ENABLED,
   RISK_UTILIZATION_GATE_ENABLED, RISK_MAX_UTILIZATION_PCT,
   CLOSE_REARM_ENABLED, INTRADAY_COHORT_STOP_ENABLED,
   CALIBRATION_STALENESS_TTL_ENABLED, PRICE_CLASS_SPREAD_CUTOFF,
   RISK_ENVELOPE_ENFORCE, EXECUTION_MODE, LIVE_ENABLED, POLICY_LAB_ENABLED).
3. Broker snapshot: account (equity/cash/OBP), open positions, fills since
   the prior run.
4. DB: learning_trade_outcomes_v3 (30d), job_runs health, suggestion funnel
   by day, suggestion_rejections mix, reentry_cooldowns, risk_alerts
   critical/high (H11 — independent of any hypothesis).
5. Pipeline code map (verify drift only; the 06-09 map is in the v4 report):
   scanner/workflow_orchestrator → conviction/calibration → sizing stack
   (OBP → envelopes → caps → H7 → floor) → executor (_execute_per_cohort:
   cooldown gates → utilization gate → #1038) → intraday_risk_monitor
   (cohort stops + TP) → close path (re-arm guards) → learning ingest.

## EXCLUSIONS

Load `audit/ledger.md`. **Every finding listed there — shipped, reported, or
rejected — plus PRs #1038–#1049 and all backlog-ticketed items
(docs/backlog.md), is EXCLUDED. Re-finding a ledger item is a wasted slot.**
Quantifying/refining a ledger item is valid ONLY if the refinement changes
the recommended action. Pending-verification items in the ledger are checks,
not findings: verify them, update the ledger section, and report
pass/fail/still-pending.

## THE AREAS — one finding each, the single best, not a list

For each: STATUS line, then (if a finding) WHAT · WHERE (file:line) · WHY
(why #1 in-area) · IMPACT (quantified from system data) · HOW (code-level
sketch) · EVIDENCE (which sources, with the actual query/log/fill) · RISK
(blast radius; does it touch the live close/stop path) · CONFIDENCE.
In FULL mode, every finding gets an adversarial verifier (re-read every
cited file:line, re-run every query, check exclusions, check arithmetic)
before it may be labeled FINDING.

**AREA 1 — PROFITS.** Most increase in realized PnL. Ranking/EV math vs
realized outcomes; strike/expiry/structure selection vs what filled; entry
timing vs regime; whether calibrated EV/PoP measurably beats raw (the
ev_raw/pop_raw columns now matter — post-#1045 calibration writes daily);
per-leg pricing vs combo quotes; fill-rate vs price aggression.

**AREA 2 — MINIMIZING LOSSES.** Most reduction in drawdown/catastrophic loss.
Exit logic coherence; multi-position correlated-loss behavior under the 85%
utilization cap; gap/overnight risk; multi-envelope same-cycle interaction;
re-arm/backoff behavior under real broker failures. Proposals must ADD
control, never loosen one.

**AREA 3 — SELF-LEARNING.** Fastest learning from its own trades. Collected
vs consumed; calibration segment significance at the current close rate
(post-#1045 window escalation); shadow-vs-live comparison actually informing
anything; learning-data integrity (cadence-inflated or fill-model-biased
outcomes).

**AREA 4 — SELF-SUSTAINING.** Most reduction in required human intervention.
The next silent failure (the calibration freeze was found by audit, not by
ops); OUTPUT_FRESHNESS registry coverage; recovery after worker recycle
mid-cycle; who watches the watcher; set-but-not-read / merged-but-not-running
recurrence.

**AREA 5 — EFFICIENCY.** Most reduction in compute/API cost or cycle latency,
tied to a money/decision consequence. Job timings day-over-day (order_sync
should now be ~1.5s — verify #1049 landed); per-scan API call counts; cache
TTLs vs data change rates; DB chatter; alert/log noise (84 high-sev
steady-state warns/week is still unaddressed noise).

**AREA 6 — TRADING VOLUME.** Most increase in entries/week WITHIN the risk
frame (cooldown, envelopes, 85% cap, loss controls FIXED — loosening any =
invalid). Funnel pass rates day-over-day post-#1047 (sub-$60 re-admission —
did staged candidates actually rise?); executor cadence (one shot/day at
16:30Z — the known-unbuilt exception: Areas 4/6 may quantify and refine it,
or beat it); multi-position accumulation under the cap; universe breadth vs
entitlements.

**AREA 7 — TIME IN TRADE.** Shorten average hold WITHOUT degrading realized
EV. Hold-time distribution from broker fills; exit cadence (cohort stops now
run at 15-min — verify #1048 behavior); DTE selection vs realized holds;
time-stops for stalled theses; profit-capture mechanics (poll vs GTC
decision still open). PDT is retired — the boundary is intraday margin +
fees + cooldown benches, nothing else.

**AREA 8 — SELF-EXTENSION (exactly one slot).** Each run: identify the single
highest-value blind spot that Areas 1–7 (plus the currently adopted Area 8
spec in `audit/area8.md`, if any) structurally CANNOT see — not a deeper
version of an existing area, a missing lens. Define it as a complete
reusable area spec: name, goal, look-at list, constraints, what would
disqualify a finding. Then AUDIT it immediately this run at the same
evidence standard. Persist the spec to `audit/area8.md` (date + rationale);
a better lens REPLACES the old one — exactly one extension slot, never an
accumulating list. If the incumbent spec is still the best lens, keep it and
audit it. HARD BOUNDARY (restating the contract): Area 8 may never propose
loosening a risk control, expanding this loop's write permissions, or
modifying this file's contract sections.

## OUTPUT

`audit/reports/YYYY-MM-DD.md`, structured:
1. Any ALERT block first (critical findings — file also written separately).
2. Ground-truth delta vs prior run (5-10 lines; NIGHTLY mode's core).
3. Pending-verifications table: pass/fail/still-pending, with evidence.
4. Per area: STATUS line + finding block, or UNCHANGED/no-finding line.
5. Area 8: the spec adopted/kept + its finding.
6. TOP-3 across areas (value/effort/risk) · conflicts & synergies ·
   four-source disagreements encountered.
7. Ledger updates made (what was appended/updated).
Then STOP. Recommend; never implement.
