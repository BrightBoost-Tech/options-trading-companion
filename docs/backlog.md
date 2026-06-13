# Backlog — tiered (rewritten 2026-06-13)

Every item: one-line context · origin · reopen/done condition. Full pre-0613
history preserved verbatim in `docs/backlog_archive_2026-06-13.md` (240k,
4075 lines) — consult it for narrative, not for current priority. Settled
items live in `audit/ledger.md` (exclusion memory) — do not re-investigate.

Tiers: **GATED** (built/known, awaiting operator go) · **P1** (next build
slots) · **P2** (real but deferred) · **RESEARCH** (open questions) ·
**RESOLVED — DO NOT REINVESTIGATE**.

---

## GATED — pre-approved/known, do not re-find (operator owns the go)

- **N1 realized-blind daily brake** (#1058) — broker `equity−last_equity`
  tightens all four envelope feeders. Wrapper omission fixed 06-12
  (`d68029c`). · origin 06-11 · done when: operator confirms live behavior
  over a losing session; reopen only on a NEW brake defect, not to re-derive.
- **N2 ops-health alert delivery** (#1059) — dual-channel to risk_alerts,
  critical-severity fix, data_stale market-hours gate. · origin 06-11 ·
  done when: operator confirms delivery cadence; do not re-find the delivery
  path.

## P1 — next build slots

- **Close-side quote check** — entry has #1038/#1052; the CLOSE path has no
  equivalent stage-time executable-quote validation independent of #1034
  observe. · origin pre-0610 · done when: a close stages only on a
  corroborated executable price or rejects loudly.
- **EXIT_EVAL_DEBUG honest print** — the debug line prints flat defaults
  while decisions are cohort-aware/time-scaled; manufactured one phantom
  incident. · origin §8 · done when: the print computes through the same
  cohort/time functions as the decision, or is removed.
- **A5 queue routing** — confirm `otc` vs `background` queue assignment per
  job; a misrouted long job can starve the q5min/q15min cadence. · origin
  06-13 audit A5 · done when: each job's queue is asserted in a test +
  documented in §6.
- **Executor cadence** — one execution shot/day (11:30 CT) is the known
  volume bottleneck; the funnel evaluates ~70 symbols/day but stages ≤1×. ·
  origin pre-0610 · done when: a second sanctioned execution window or
  event-trigger lands (NOT a loosening of gates).
- **Funnel status transitions** — suggestion `status` never reflects
  execution (morning sweep relabels all `dismissed`); `blocked_reason`
  closed the rejection half only. · origin §8 · done when: a staged/executed
  suggestion carries a truthful terminal status.

## P2 — real but deferred

- **v3 view Gates A/B** — `learning_performance_summary_v3` referenced, never
  shipped; conviction runs DEGRADED-legacy every recycle (#1043). · origin
  pre-0610 · done when: the view ships and the DEGRADED line stops.
- **Greeks validator observe-only** — promote the greeks envelope from warn
  to a tested observe→enforce path. · origin pre-0610 · reopen with data.
- **OUTPUT_FRESHNESS registry expansion** — watches ONE table
  (`calibration_adjustments`, `ops_health_service.py:79`); a silent stall of
  learning ingest or mark refresh would not alert. · origin 06-13 audit A4 ·
  done when: `learning_trade_outcomes_v3` (or `paper_positions.last_marked_at`)
  is registered with a tuned max-age.
- **ghost_position sweep excludes shadows** — the sweep selects all
  open-position users with no live-routed filter (`alpaca_order_sync.py:245`);
  73 shadow-induced ghost alerts this week bury a real desync. · origin 06-13
  audit A2 · done when: the sweep scopes to live_routed or tags shadow ghosts
  distinctly (H10 integrity).
- **is_paper live/shadow discriminator** — every learning row this week
  tagged `is_paper=true` incl. live SPY/MARA/NFLX closes; the routing
  resolver isn't distinguishing live broker fills in learning rows. · origin
  06-13 audit A3 · done when: live fills are distinguishable in
  learning_feedback_loops / outcomes_v3.
- **chain_mechanics_formula_anomaly noise** — legacy `option_spread_pct`
  formula fires >300% on deep-ITM verticals (24×/week, observability-only,
  `options_scanner.py:3528`). · origin 06-13 audit A6 · done when: the legacy
  formula handles deep-ITM legs or the print is made honest (EXIT_EVAL_DEBUG
  class).
- **Startup flag-echo** — no read-back echo of effective flags at boot;
  read-back is manual per deploy. · origin pre-0610 · done when: boot logs
  the parsed value of every registry flag.
- **Loss-limit coherence** — per-symbol envelope vs cohort stop vs vestigial
  0.50 precedence is deliberate-but-undecided at compounding capital (§5). ·
  origin pre-0610 · reopen when capital crosses a tier cliff; never ad-hoc.
- **Legacy rollups** — older aggregation paths duplicate canonical_ranker /
  close_math; consolidate. · origin pre-0610 · reopen with data.
- **Dead instrumentation** — submitted_at/latency fields and lying counters
  partially fixed (06-12 honesty pass); sweep for the remainder. · origin
  pre-0610 · done when: no counter interpolates a MAX constant as an actual.
- **Clamp review** — calibration ev_mult/pop_mult 0.5 floor clamp may mask
  signal once post-epoch data lands. · origin pre-0610 · reopen at ≥8
  post-epoch closes (~06-20).
- **FK wart** — a foreign-key/nullable mismatch noted in migrations.
  · origin pre-0610 · reopen with the next migration touching it.
- **Deploy windows** — codify the no-RTH-merge rule as a CI/branch guard (two
  06-12 deploys carried RTH timestamps). · origin 06-13 · done when: a merge
  during RTH is blocked or warns.
- **#908 live credit-mleg-close validation** — pending the next system close
  on a credit structure. · origin pre-0610 · done when: a credit close
  validates positive-limit, no Sign-incoherent raise.
- **#1035/#1036 mark fail-closed** — monitor mark-refresh fail-closed paths;
  verify both fire under partial-quote. · origin pre-0610 · reopen with a
  partial-quote incident.

## RESEARCH — open questions, no committed build

- **Vol brackets** — regime-conditioned sizing/threshold brackets beyond the
  current normal/chop split. · origin pre-0610.
- **Area-8 capture fields** — what to persist to make rejected-candidate
  counterfactuals markable: underlying-spot-at-decision + spot-at-+1d as the
  conservative proxy for DARK-leg rejects (the XLE dead-leg class is
  unmarkable on the executable side by construction). · origin 06-13 audit
  A8 · done when: rejection rows carry the proxy fields (additive, observe).

## RESOLVED — DO NOT REINVESTIGATE (cite, never re-derive)

- **PDT** — retired FINRA + Alpaca 2026-06-04; daytrade fields are
  placeholders; never flip `PDT_PROTECTION_ENABLED`.
- **Historical NBBO** — no historical option-quote endpoint from local
  tooling; counterfactuals use executable-side-at-decision or are marked
  indeterminate, never hindsight quotes.
- **External frameworks** — no ChatGPT/mixed-tool architecture decisions;
  drift risk, settled.
- **Retro-recompute** — pre-#1051 sign-flipped EVs are NOT retro-corrected;
  the epoch (`CALIBRATION_EV_EPOCH`) walls them off instead.
- **Mode-column** — execution_mode layering (alpaca_live / internal_paper /
  shadow_blocked) is settled; both ALPACA_PAPER layers must be false for
  live.
- **Backtest deferral** — no backtest harness this phase; learning-mode
  forward-only is the deliberate choice.

---

### Appended 2026-06-13 (combined run Part 2 audit) — see also audit/ledger.md
New findings folded into tiers above with origin=06-13: OUTPUT_FRESHNESS
expansion (P2/A4), ghost-sweep shadow exclusion (P2/A2), is_paper
discriminator (P2/A3), chain_mechanics anomaly (P2/A6), A5 queue routing
(P1), deploy-window guard (P2), Area-8 capture fields (RESEARCH/A8). No new
GATED or P1-build items beyond those listed; A1 EV-optimism is raw-mode
expected (no action until the ~06-20 relearn).
