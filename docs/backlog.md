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
  tightens all four envelope feeders; phantom-mark-safe rebuild #1071 (06-17)
  fires on realized + executable-corroborated unrealized, not the raw
  phantom-mark delta. **DEPLOYED, LIVE-UNEXERCISED** — verified origin/main
  (`b9b1781`), both workers on `5a1c8a7`. · origin 06-11 · **first live RTH
  06-18 — evaluated q15min, stayed clear** (the −675.99 loss was shadow_only,
  correctly excluded from the live brake); gate: still awaiting a losing LIVE
  session; reopen only on a NEW brake defect.
- **N2 ops-health alert delivery** (#1059) — dual-channel to risk_alerts,
  critical-severity fix, data_stale market-hours gate. · origin 06-11 ·
  done when: operator confirms delivery cadence; do not re-find the delivery
  path.
- **Close-side stage-time quote validation** (#1072) — the close path reuses
  #1034's executable estimate: corroborated → stage at achievable_close,
  uncorroborated/dark → DEFER (hold + flag + escalate; stops faster than TPs),
  returning before staging so a defer never strands a naked position.
  `CLOSE_QUOTE_VALIDATION_ENABLED` default-ON (`paper_exit_evaluator.py:660`).
  **DEPLOYED, LIVE-UNEXERCISED** — verified origin/main (`5a1c8a7`), both
  workers. · origin pre-0610 (P1) · 06-18: no live close (the only close was a
  shadow `internal_paper` stop) · gate: first live close confirming
  reprice-to-achievable / defer-flag-escalate behavior.
- **Funnel status transitions** (#1073) — execution never stamped
  `trade_suggestions.status`, so executed suggestions stayed `pending` and the
  sweep relabeled them `dismissed`. Two layers behind
  `FUNNEL_STATUS_TRUTHFUL_ENABLED` (default-ON): A stamps `executed` at the
  position-insert seam, B reconciles prior-day pending at the sweep
  (position→executed, none→dismissed). INDEPENDENT of the relearn (calibration
  never reads status). **MERGED #1073 (`d1c8d08`, 06-18), deployed default-ON.
  Layer B LIVE 06-18** (13:00Z sweep reconciled the prior-day pending →
  dismissed, none-path); **Layer A still pending a live entry**. · origin §8 ·
  separate pending: supervised
  backfill of the 32 historical `dismissed`-with-position rows
  (dry-run-then-go, not shipped).
- **#1076 live-only calibration + v3 conviction view (#1043)** — calibration now
  trains on LIVE outcomes only (`CALIBRATION_TRAIN_LIVE_ONLY` default-ON);
  shadow/internal-fill outcomes can't drive a live-applied EV/PoP multiplier (the
  06-18 LONG_PUT ×1.5 shadow-outvote, +662 outlier). + null-pop denominator-basis
  fix (flagless) + `learning_performance_summary_v3` conviction view CREATED DARK
  (is_paper-blind-match, epoch+floor wall; every bucket <20 → all-1.0). **MERGED
  #1076 (`9e6a719`, 06-18), deployed; view applied via supervised migration.** The
  served blob keeps the wrong ×1.5 until the 10:00Z relearn rewrites it live-scoped
  (5<8 → raw). · origin 06-18 incident · verify-pending: live-scoped raw blob at
  06-19 10:00Z relearn; v3 [CONVICTION] DEGRADED-log gone at 06-19 16:00Z scan.

## P1 — next build slots

- **A5 queue routing — LANDED 06-18 (#1077 + Railway edit)** — the 6-job
  post-close learning chain (learning_ingest_eod, paper_learning_ingest,
  policy_lab_eval, post_trade_learning, promotion_check, daily_progression_eval)
  now routes to `background` (off the otc trading queue) via
  `queue_name=BACKGROUND_QUEUE` at the 6 enqueue sites; full handler→queue map
  test-pinned (`test_learning_chain_queue_routing.py`, "exactly 7 background
  routes" backstop); §6 documents it. worker-background switched to SimpleWorker
  (Railway start cmd, 06-18 23:21Z, deploy `b23cb6f5`) BEFORE the 6 run — the
  forking-worker flip never reached them. **MERGED #1077 (`319b7de`, 06-18).**
  · origin 06-13 audit A5 · verify-pending: bg container logs at the 06-19
  ~21:00Z chain show the 6 ran on bg / otc's didn't (NOT `job_runs.locked_by` —
  null post-completion).
- **Executor cadence — HELD (anti-list: do NOT add capacity yet)** — one
  execution shot/day (11:30 CT) is the known volume bottleneck, but the
  one-shot cadence is PROTECTIVE while calibration is unproven — it's the
  cadence half of the equity/EV+cadence constraint and that premise isn't met
  (relearn not yet fired clean). · origin pre-0610 · trigger to build: relearn
  fired + N post-relearn clean closes + predicted-vs-realized EV tracking
  positive + #1071/#1072 have a clean live exercise → then add ONE window
  incrementally + observe (NOT a gate loosening).
## P2 — real but deferred

- **REGIME_V4_ENABLED env drift — RESOLVED 06-18** — was `worker`=`0` vs
  `worker-background`=`true`; aligned bg `true`→`0` (Railway env, recycle
  `04ac318e`) to match otc + the code default. Behaviorally inert (flag unwired —
  one reader, zero production callers, live path is v3). otc untouched.
- **v3 view Gates A/B — Gate A LANDED 06-18 (#1076)** —
  `learning_performance_summary_v3` CREATED dark (is_paper-blind-match +
  epoch+floor wall); conviction auto-flips off DEGRADED-legacy on next read (see
  the #1076 GATED entry). Gate B (wire-vs-retire / lean on v3 conviction)
  deferred until live buckets approach ≥20 (far off; dark today). · origin
  pre-0610 · verify: DEGRADED-log gone at 06-19 16:00Z scan.
- **Greeks validator observe-only** — promote the greeks envelope from warn
  to a tested observe→enforce path. · origin pre-0610 · reopen with data.
- **OUTPUT_FRESHNESS registry expansion** — watches ONE table
  (`calibration_adjustments`, `ops_health_service.py:79`); a silent stall of
  learning ingest or mark refresh would not alert. · origin 06-13 audit A4 ·
  **PARTIAL (Phase 1):** `learning_feedback_loops` (created_at, 14d via
  `OPS_LEARNING_INGEST_MAX_AGE_HOURS`) now registered. · done when: mark
  refresh (`paper_positions.last_marked_at`) is also registered with a tuned
  max-age.
- **ghost_position sweep excludes shadows** — the sweep selects all
  open-position users with no live-routed filter (`alpaca_order_sync.py:245`);
  73 shadow-induced ghost alerts this week bury a real desync. · origin 06-13
  audit A2 · done when: the sweep scopes to live_routed or tags shadow ghosts
  distinctly (H10 integrity).
- **Phantom-mark-safe brake — gate consumers (REFRAMED 06-18)** — of the 3
  `tightened_daily_pnl` consumers, only the **autopilot breaker was a real gate —
  FIXED via #1075** (`212d949`, P2#6: corroborated daily_pnl + de-phantomed
  denominator; first live RTH 06-18 clean). **MTM** (`paper_mark_to_market.py:104`)
  and **midday** (`workflow_orchestrator.py:2844`) are **warn-only** (the raw
  phantom only logs CRITICAL/FORCE_CLOSE there, no action) → low-priority log
  hygiene. · origin 06-17 incident · done when: MTM+midday feeds optionally
  swapped to corroborated (cosmetic), folded with the deeper **MTM mark-WRITE
  corroboration** item — the real MTM harm: `refresh_marks` persists the phantom
  into `current_mark`/`unrealized_pl` + `paper_eod_snapshots` (#1076 recomputes/
  bypasses but does NOT fix the persisted value).
- **signal_weight_history epoch/is_paper guard (DORMANT consumer)** — the
  per-segment multiplier writer (`post_trade_learning._update_segment_calibration`)
  queries `learning_feedback_loops` with NO epoch (`CALIBRATION_EV_EPOCH`) or
  is_paper filter; IRON_CONDOR|chop already holds 14 pre-epoch is_paper=true
  rows. Its only reader is `DynamicWeightService` (`get_weight_overrides`/
  `apply_to_score`), which has ZERO call sites — so the output is inert today.
  · origin Phase-1 scope-lock · done when: an epoch + is_paper filter is added
  to the segment query **IF/BEFORE `DynamicWeightService` is ever activated**
  (do not guard a dead reader; this is a tripwire, not a build slot).
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
- **Cohort-stop cooldown realized_loss from fill** — the writer records
  trigger-time `unrealized_pl` at force-close-submit (pre-fill), not the
  actual close fill; minor metadata inaccuracy, no current consumer. LARGELY
  OBVIATED by the 06-15 structural clamp (impossible marks can't reach the
  writer now). · origin 06-15 (Phase B commit-4 deferral) · done when: the
  reconcile path backfills realized_loss from the fill, if ever worth it.
- **config.py fail-open-looser stop (decision-path, 06-15 STEP-4)** —
  `policy_lab/config.py` DEFAULT_CONFIGS hardcode looser stops (≈0.40/0.50/
  0.65) than the live DB cohorts (0.15/0.20/0.30), so a cohort-load failure
  fails to a 2–3× LOOSER stop — make it fail-CLOSED (live-reachable on a
  cohort-load failure). · origin 06-15 · **(b) RESOLVED 06-18:**
  `agents/agents/exit_plan_agent.py:43,50` `stop_loss_pct=0.50` confirmed
  ADVISORY — it only builds candidate metadata (`agent_signals.exit_plan`,
  scored + lineage) in the midday-scan path
  (`services/workflow_orchestrator.py:3140-3186`); it does NOT gate the
  intraday_risk_monitor force-close (cohort conditions drive that). · **(a)
  open** · done when: config defaults fail-CLOSED — bundle with the
  ghost-sweep shadow-scoping fix as the higher-value risk pair.
- **Winsorize calibration shadow-outlier influence** — defense-in-depth for when
  a segment reaches ≥8 live trades: cap outlier influence on the ev/pop ratio
  (the 06-18 +662 NFLX shadow drove LONG_PUT/normal to the 1.5 rail). Only bites
  once live data matures; pairs with the clamp-review (both 06-18 blob segments
  were rail-pinned). · origin 06-18 · done when: a winsorize/cap applies at ≥8
  live/segment.
- **IRON_CONDOR/chop structural suppression (WATCH)** — the calibration ×0.5
  deflate on IC/chop is load-bearing (no structural regime gate; live IC trades
  exist, entered under raw) — live-only→raw forgoes it. If IC/chop keeps losing,
  suppress it STRUCTURALLY (`StrategyPolicy` ban / min-edge tightening), NOT via
  thin calibration. · origin 06-18 · revisit at n≈8–10 IC/chop closes.
- **Persistent job-level worker/queue tag in job_runs (observability)** —
  `job_runs.locked_by` is null post-completion, so otc-vs-bg can't be audited
  after the fact (surfaced verifying the A5 re-route; it's why the A5 proof keys
  on bg logs, not locked_by). Add a durable queue/worker tag written at job
  start. · origin 06-18 · done when: job_runs carries the executing queue/worker.
- **trade_suggestions.created_at index (minor)** — `created_at`-filtered queries
  time out (full scan); EOD sweeps use the indexed `cycle_date` as a workaround.
  · origin 06-18 · done when: a created_at index exists.
- **risk_alerts hygiene sweep (minor)** — ~350 cumulative un-acked critical/high
  alerts (force_close 354, warn 579, …) are historical noise burying a real one
  (H11). · origin 06-18 · done when: ack/resolve the backlog (+ consider
  auto-resolve TTLs) so the open critical/high count reflects only live
  actionable alerts.

## RESEARCH — open questions, no committed build

- **Vol brackets** — regime-conditioned sizing/threshold brackets beyond the
  current normal/chop split. · origin pre-0610.
- **Area-8 capture fields** — what to persist to make rejected-candidate
  counterfactuals markable: underlying-spot-at-decision + spot-at-+1d as the
  conservative proxy for DARK-leg rejects (the XLE dead-leg class is
  unmarkable on the executable side by construction). · origin 06-13 audit
  A8 · done when: rejection rows carry the proxy fields (additive, observe).
- **Executable-for-stops (OBSERVE-ONLY experiment, not a live change)** — per
  stop evaluation, log what the stop WOULD do on the executable/achievable
  side vs what it does on mid, and persist the divergence. Decision gate:
  after ~2 weeks, review whether executable-basis would have over-fired on
  noise in wide/illiquid names before considering adoption. Rationale:
  achievable is always worse than mid → fires stops earlier → more
  conservative but noise-prone. NOT today's bug (the 06-15 stop fired
  correctly on mid; the debug line was the only liar). · origin 06-15
  (Phase B commit-2 deferral).

## RESOLVED — DO NOT REINVESTIGATE (cite, never re-derive)

- **EXIT_EVAL_DEBUG honest print** — DONE (#1067, squash `ad8ce0f`, in
  origin/main; merged ~06-15, operator-confirmed live 06-16). The debug line
  reads the cohort-built `pct` keys from `conditions`
  (`paper_exit_evaluator.py:945-947`), not `_DEFAULT_*` — it prints the
  threshold the decision computes through, retiring the §8 known-liar. (Branch
  commit `2dac872` is NOT an ancestor of main; content landed via the squash.)
- **is_paper live/shadow discriminator** — COMPLETE (#1069, `efb9a3a`,
  origin/main + supervised row corrections, 06-17). Ingest derives is_paper
  from `order.execution_mode` (`_resolve_is_paper`). Verified: the 4 historical
  live-as-paper rows are now `is_paper=false` (SPY a5393e2b, NFLX 7f604f7a,
  MARA bc399a4f, QQQ 6798e58f — joined via suggestion_id); `da446325`
  `learning_ingested=true`; the 3 remaining post-epoch `is_paper=true` rows are
  genuine shadow/paper.
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
- **#71 async-dispatch migration sweep** — endpoints moved sync→202+enqueue:
  PR-1 audit (`rq_dispatch_audit_2026_05_04.md`), PR-2 (/tasks/policy-lab/eval),
  PR-3 (/tasks/validation/init-window). All shipped; traceability tokens
  retained here because migration-doc guard tests assert them in this file
  (`test_policy_lab_eval_async_migration.py`,
  `test_validation_init_window_async_migration.py`). Do not drop the tokens
  on future reorgs.

---

### Appended 2026-06-13 (combined run Part 2 audit) — see also audit/ledger.md
New findings folded into tiers above with origin=06-13: OUTPUT_FRESHNESS
expansion (P2/A4), ghost-sweep shadow exclusion (P2/A2), is_paper
discriminator (P2/A3), chain_mechanics anomaly (P2/A6), A5 queue routing
(P1), deploy-window guard (P2), Area-8 capture fields (RESEARCH/A8). No new
GATED or P1-build items beyond those listed; A1 EV-optimism is raw-mode
expected (no action until the ~06-20 relearn).
