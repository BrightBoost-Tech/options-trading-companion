# Audit Ledger — findings already found

Every finding listed here is EXCLUDED from future audit runs. Re-finding a
ledger item is a wasted slot. Runs append new findings as `status:reported`;
the human flips them to `status:shipped` (with PR#) or `status:rejected`.

## 2026-07-12 (Sun ~06:3x CT) — FULL-REPORT TRIAGE + OWNER DECISIONS PRESENTED (awaiting operator confirmation before any build)

STEP-0: DB `11:31Z` = Sunday `06:31 CT` / broker `07:31 ET` = `06:31 CT`, agree to
the second; NO UTC-roll bite (both are 07-12). Market CLOSED.

**PART 1 — the FULL ran correctly.** cron.log: 07-12 `start 0:00:18 → end (exit 0)
0:17:51 → ping sent (curl exit 0)` = scheduled ✅ FULL mode ✅ (header "three
passes per area") all 11 areas ✅ ping GREEN ✅. Expected-state handling WORKED:
breaker 2nd designed suppression, flat book (0 positions), four-source agreement
everywhere — the inverted block is functioning. The FULL respected the v1.3
exclusion floor: **E8/E12/E14/E16/W2-W5/F-A2-1 CONVERGED (cited, NOT re-found)** →
the ①-④ queue owns them.

**TRIAGE TABLE (NEW findings only; CONVERGED = above):**
| Finding | Sev | Path | Decision |
|---|---|---|---|
| F-A9-THESIS-BASIS — thesis_tracker `_underlying_at_expiry` (thesis_tracker.py:55-57) grades a ≤7d-stale fallback bar as the expiry price + persists a TERMINAL hit/miss with NO price-basis field; thesis_basis prints it as expiry price while claiming "NEVER fabricated H9" (thesis_scoring.py:20,88-121) | MED | Evidence — the standing thesis-hit metric the owner steers by; NOT live capital; 0 rows yet | **FIX-TODAY (recommend), PENDING OWNER GO** — time-sensitive: first authoritative fill Mon 17:00 CT; 1 field + 1 line, observe-only, born-honest if shipped first; same 2 files as F-A9-1. NOT in the ①-④ queue → a PR-⓪ insertion candidate. |
| F-A4-SLEEP-DEATH — 07-11 nightly machine-sleep kill (start-no-end; end-marker unconditional so external kill); 4th weekend (06-14·06-20·06-30·07-11); WakeToRun holds no wake-lock | — | Evidence-integrity (audit coverage); NO repo code | **ESCALATE (operator)** — (1) confirm the 07-11 healthchecks DOWN email ARRIVED (else dead-man unarmed); (2) ES_SYSTEM_REQUIRED sleep-hold or mid-run-safe schedule. |
| A5 observability noise — 07-10 14:02Z 5-row loss (#1104 residual, 2nd occ, 11 cumulative) re-egressed hourly ×9; `ops_output_stale` ×10 flat-book false HIGH | MED | Alert-hygiene | **FILE (already filed) — ⚠ slipped THREE build days** (07-08→07-12); the only found item not converging. Owner: give it a slot (fold iv_daily_refresh EXPECTED_JOBS half). |
| `bucket_exposure_would_block` severity='warning' → no egress/relay despite the "#1139-class alarm" comment (paper_autopilot_service.py:1063-64) | LOW-MED | Evidence (observe-week relies on it) | **FILE** — fold into the composed observe→enforce packet (D③); owner READs logs meanwhile. |

**A11 FULL-FORMAT DEBUT — GRADE: STRONG, well-formed (all 4 components present).**
Proposed lens = **SECURITY & CREDENTIAL HYGIENE** (secret scanning · git-history
exposure · key rotation · RLS/permission surfaces · MCP/tool allow-lists).
Examines: credential/permission-surface drift nothing else owns. Ten miss: the
incumbent watches TIME boundaries only. Concrete finding-shaped example: F-FREE-1
checked-in Supabase keys (found by an UN-lensed free look, not a charter) + its 2
operator tails (history cleanup + secret-scanning) still OPEN/unaudited + the
nightly's own allow/deny list is a growing security surface with no reviewer.
Replace-vs-queue: argues the incumbent "completed its headline (winter-close),
look-list in maintenance, marginal yield falling." **My grade:** a genuinely
uncovered surface + a real finding-example → QUEUE-worthy. BUT the replace half is
WEAK — F-A10-1 (summer warm-up blind, HIGH) shows Calendar & Clock is STILL
finding, and A10 still guards DST 11-01. Not a clean retirement. → feeds D①.

**A7 COUNTER RECONCILIATION (corrects the prompt's "9/10"):** two different
counters — all-time live closes = 9 (v1.3's "9/10") vs the #1102-instrumented
close-fill-gap counter = **3/10-15** (the meaningful A7-reinstatement gate, needs
the fill-quality instrumentation). By the correct counter A7 is FAR from
reinstatement (3/10-15), NOT near. The causal close-quality charter reshape
happened in v1.3, not tonight (tonight A7 = one dormant line). PASS-3: all EARNING
except A5 SLIPPING; NO area at 6, NO retirement proposed. **Anti-drift:** Saturday's
FIX-TODAYs all shipped (#1174-#1182, ledgered); the ONE item pending >2 days = the
3-in-1 observability PR (07-08→07-12).

**PART 2 — FOUR OWNER DECISIONS PRESENTED (my recommendations; AWAITING operator
confirmation — NOTHING built until the GOs are recorded):**
- **D① A10 ROTATION.** REC: **KEEP Calendar & Clock one more cycle** (F-A10-1 HIGH
  proves it's still earning; A10 counter=4 not 6; DST 11-01 still to guard) +
  **QUEUE the SECURITY lens** (A11's proposal, strong) for the next rotation.
  Owner's call.
- **D② SHADOW UN-MUTING.** REC: **un-mute at queue-④'s SHA** (after the clone
  normalizer) — until then new shadow evidence is born risk-contaminated (E14
  census 33/33 non-champion typed-null). Promotion-comparison caveat, owner picks:
  shared calibration = honest cross-cohort comparison; split = the experiment
  breathes.
- **D③ THE COMPOSED ARM (W2+W3).** RESHAPE: clocks are RESET → NO arm this week
  regardless. Decision = **GO on the arm-evidence-repair PACKAGE (queue ②) + the
  W3 double-polarity fix as its precondition**; clocks restart at that SHA. GO on
  the package, not the arm.
- **D④ 2-LEG CREDIT COHORT.** RESHAPE: GATED on the credit-probability source
  (queue ⑤; E12 algebra means un-muting cannot produce a qualifying entry).
  Decision = **approve queue-⑤'s spec** (independent terminal/breakeven
  probability source, production-route test asserting NONZERO EV + unchanged
  gates, observe/replay-only start; ~1-2 evenings + observation) as next week's
  strategy build. GO on the spec.

**STOP for operator confirmation. Part 3 (PR-① E8 seam → PR-② arm-evidence → PR-③
replay terminal → PR-④ clone normalizer, + the possible PR-⓪ thesis-basis) builds
ONLY on the recorded GOs. ①② are the must-lands if the day runs long; ③④ hold to
Monday post-close at no cost (capture completeness already known-defective).**

## 2026-07-12 (Sun 00:01 CT) — FULL NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-12.md

STEP-0: DB 05:01:47Z = Sunday 00:01 CT / broker 01:02 ET — agree to the minute; FULL mode.
Broker READ (not blind): equity=cash=OBP $2,067.86, book FLAT. H8: all 3 services @ `a120c5f`
= origin/main; run-START = run-END SHA (first run under the run-boundary pin). H11: 0 critical.
Budgets: 15 SQL · 2 broker · 6 Railway · 6 subagents.

**NEW FINDINGS (status:reported):**
- **F-A9-THESIS-BASIS (MED, observe-only surface, TIME-SENSITIVE for Mon 17:00 CT):**
  thesis_tracker `_underlying_at_expiry` silently falls back to the last bar ≤7d before expiry
  (thesis_tracker.py:55-57) and persists a TERMINAL hit/miss (never re-scored, :84-88/:117) with
  NO price-source/date field; thesis_basis prints the price as the expiry price
  (thesis_scoring.py:88-121) while the module claims "NEVER fabricated (H9)" (:20). Table still
  0 rows — first authoritative fill Mon 17:00 CT. Fix: persist price_basis(_date) + surface in
  thesis_basis (or strict-mode: unknown when no exact-expiry bar). Born-honest if shipped first.
- **F-A4-SLEEP-DEATH (operator-side, no repo code):** the 07-11 nightly start-with-no-end is
  PROVEN external kill — run-nightly.cmd's end marker is UNCONDITIONAL (fires even on claude
  errors, cf. cron.log 06-13), so the cmd process died: machine re-slept moments after the
  00:00:02 start. 4th occurrence, ALL weekends (06-14 · 06-20 · 06-30 · 07-11). WakeToRun wakes
  to START but holds no wake-lock for the run; ping-after-file is positive-only and never ran.
  Operator: (1) confirm the healthchecks DOWN email for the missed 07-11 ping ARRIVED (if not,
  the nightly dead-man is unarmed); (2) add a sleep-hold (ES_SYSTEM_REQUIRED wrapper) or
  equivalent.
- Shared A2/A9 one-liner: `bucket_exposure_would_block` writes severity='warning' → unpaged
  (paper_autopilot_service.py:1063-1064) though the comment says "#1139-class alarm" — fold the
  severity choice into the composed observe→enforce owner decision, not a separate PR.

**VERIFICATIONS CLOSED:**
- ★ **First calibrated PRODUCTION ev — PROVEN + persisted:** 07-10 16:00Z QQQ IC
  `ev 18.73 = ev_raw 37.46 × 0.5000` (+ SOFI 14:02Z ×0.5), blocked ev_below_roundtrip_cost /
  edge_below_minimum. F-A1-3 re-scope honored (persisted ev + final gate only; selection RAW).
  **The composed floor×gate ZERO-ENTRY regime is live-exercised** — the A1 clamp-review exhibit
  now has a production data point (QQQ-IC missed by ~2.1 EV pts). 16:00Z scan LOSSLESS.
- Breaker suppression #2 (07-10 21:20Z): `suppressed_standing_window:true` on unchanged
  fingerprint; entries stayed armed. Designed case-3, second live proof.
- Weekend-PR content verification (subagent reads @ a120c5f): #1178 all-10-branch terminal
  clamp + no double-clamp + zero forecast_ev_pop refs · #1171 seam order (utilization→bucket),
  strict =1 parse, reservation-per-cohort, no unit mix · #1174 flag-off path mutates NOTHING
  (byte-identical claim holds; legacy :3601 single-apply guarded) · #1172 winter-close ET
  wall-clock VERIFIED + repo-wide sweep: NO remaining winter-blind arithmetic (heartbeat crons
  CHICAGO_TZ) — **2026-11-01 trigger retired** · all 6 new flags CALL-TIME reads (no import-time
  growth) · #1164 Monday wiring complete (17:00 CT → background queue → EXPECTED_JOBS → typed
  PARTIAL contract) · E12 / E6-edge (submit_and_track discard :2245) / W2 / W3 / W4 all
  UNCHANGED (cited, clocks stay reset) · zero stale `hit_rate` readers post-F-A9-1.
- A5 continuation counts: 07-10 14:02Z scan lost 5 rejection rows (#1104 residual, 2nd
  occurrence, 11 cumulative) → 9 hourly phone egresses for the one condition; ops_output_stale
  ×10 flat-book HIGHs. **3-in-1(+1) observability PR slipped a 3rd build day** — TOP-2.
- M4 quarantine held: all 168 micro_tier rejects confined to excluded 07-06; zero recurrence.

**PROMPT-STATE CORRECTIONS for v5.6 (movers = 07-11 builds; loop does not edit the prompt):**
(1) iv_daily_refresh ok-on-all-missing FIXED (iv_daily_refresh.py:170-173) — EXPECTED_JOBS half
still open, ride the 3-in-1 PR; (2) watchdog now watches real paper_learning_ingest
(ops_health_service.py:117) — stub-watch claim stale; (3) P0-B BUILD half COMPLETE
(#1166+#1171 observe-off) — enforcement is a composed owner decision on ~1wk of shadow logs.

**A11 FULL-form proposal (owner-gated):** rotate A10 → SECURITY & CREDENTIAL HYGIENE lens
(incumbent's headline shipped+verified; F-FREE-1 tails unaudited; the nightly allow-list is
itself an unreviewed security surface). Decision remains the owner's.

**PENDING (Mon 07-13):** 16:00Z replay capture rows-EXIST + timing (E16 re-scope: completeness
known-defective) · first [APPLY_ORDER_SHADOW]/[GATE_QTY]/[RISK_BASIS_SHADOW]/[BUCKET_SHADOW]
clean lines · 17:00 CT first thesis run (0 rows tonight — ledger's 16-row table was preview) ·
native [CLOSE_FILL_GAP] + last_marked_at stamp still gated on a live close · healthchecks DOWN
confirm (above). Retirement counters: A1/A3/A6/A10 at 4 · A8 3 · A2/A5 2 · A4/A9 reset 0.

## 2026-07-12 (Sat ~21:3x CT) — ADJUDICATED: external full audit v1.3 (4th engagement) — READ-ONLY, doc writes only

STEP-0: DB `02:35Z` (America/Chicago `21:35`, Sat) / broker `22:35 ET` = `21:35
CT`, agree to the second; `dow=0` is the UTC date (rolled to Sun) — CT wall-clock
is SATURDAY 07-11. Market CLOSED. Report swept to
`docs/review/external-full-audit-v1.3-2026-07-12.md` (was dropped to Downloads,
not docs/review — noted). Build NOTHING; verdicts + census + backlog diff only.

**SCORECARD — v1.3 is the strongest engagement yet** (their self-grade, verified
sound): A1 A+ (killed the 2-leg profit premise + 2 corrupt arm notebooks) · A4 A+
(2nd E8 false-green seam + replay-not-decision-grade) · A6 A+ (credit-zero
identity is underlying-independent) · A2/A8/A9/A10 A · A3 A− · A5 B+ · A7 dormant
9/10. Free-look produced the headline (the E8 per-user seam). Audited against the
correct HEADs (start `17f84d9`; runtime code `1b8217b`; E18 PASS at final HEAD).

**PROMOTED EXCLUSION FAILs — all VERIFIED against code + this DB:**
- **E8 (F-A4-E8, CRITICAL, promoted FAIL).** `intraday_risk_monitor.execute()`
  catches every `_check_user` exception → appends `{user_id,error}` to `results`
  → returns hardcoded `ok:true,status:completed` with NO users_failed/counts.errors
  (`intraday_risk_monitor.py:198-216`); `run()` raises only on an OUTER exception
  (the F-A4-1 #1153 fix), so a PER-USER failure never propagates. The runner's
  `_classify_handler_return` only reads top-level keys → classifies `succeeded`
  (faithful, not a runner bug). On the ONE-user account a `_check_user` throw masks
  a COMPLETE protection-cycle failure as green. The E8 test
  (`test_typed_job_outcome.py:60-67`) is a SOURCE-STRING pin of the outer raise —
  the #1126 costume in test form, one layer up from the bug. **CENSUS: 671
  succeeded rows / 30d, 0 with a nested `results[].error`** → structural-unexercised,
  STILL CRITICAL (bounded/latent, exactly F-A4-1's 0-instance posture). F-A4-1 closed
  only the outer seam. → queue ①.
- **E12 (F-A1/A6-E12, HIGH, promoted FAIL).** Credit-spread EV is IDENTICALLY $0,
  dispositive algebra (no runtime): `calculate_pop` returns the fair-odds
  `win_prob=1−c/w`; `calculate_ev` (`ev_calculator.py:282`) then computes
  `win_prob·(c·100) − (1−win_prob)·((w−c)·100)` = `100·[(c−c²/w)−(c−c²/w)]` ≡ 0 for
  ALL c,w (payoff-circular). Their pinned $1.49/$5 case: p=0.702, gain 149, loss
  351, both terms 104.598, EV=$0, misses the $15 floor by $15. #1169 fixed the PoP
  LABEL only; the cohort is NOT evaluable. **CLOSURE CLAIM CORRECTED**: "#1169
  cleared the 2-leg credit gate" → FALSE (label fixed; EV payoff-circular).
  **CENSUS: 0 credit verticals stored in 120d** (only debit spreads + condors) →
  CONFIRMED-but-LATENT. → queue ⑤; **GATES decision ④** (2-leg cohort experiment).
- **E14 (F-A9-E14, HIGH, PARTIAL-FAIL promoted).** Policy-Lab fork copies source
  `sizing_metadata.max_loss_total` unchanged even when clone contracts differ, and
  omits top-level `max_loss_total`; fill/orphan consumers read only the typed
  field (`policy_lab/fork.py:254-333`). **CENSUS (their exact predicate):
  non-champion clones typed-null-but-JSON-present = neutral 23/23 + conservative
  10/10 = 33 rows, 100%.** The shadow cohorts that feed W2/W3 evidence are entirely
  typed-risk-blind → W2/W3 evidence contaminated. Champion path unaffected. →
  queue ④ (PRECONDITION of trusting W2/W3).
- **E16 (F-A4-E16, HIGH, promoted FAIL) — includes a fair critique of my own PR-2
  (#1175).** Four replay seams: (1) `run_midday_cycle` no-trade early return
  (`:3771-3826`) precedes my `__decision__/ranked_candidates` capture → a ZERO-
  suggestion cycle (the dominant near-zero funnel) has NO output; (2) my capture
  serializes only the accepted `suggestions` list, NOT the rejected `continue`d
  tail — my PR framing "accepted + rejected+reason" was aspirational, the code
  captures accepted only; (3) cache-hit inputs omitted (chain cache returns before
  record, `market_data_truth_layer.py:1434-1438`); (4) commit failure swallowed,
  no manifest/health. OWNED: PR-2 shipped a partial capture. → queue ③; **Monday's
  capture pin RE-SCOPED to "rows exist + timing OK" ONLY — completeness is
  KNOWN-DEFECTIVE until the terminal-manifest PR ships.**
- **E18 PASS at final HEAD** (clamp `aca743a` + dead-forecast delete `1b8217b`).

**P0 CUSTODY (verified):**
- **F-A2-1 (HIGH).** Partial multileg closes don't reconcile residual into
  `paper_positions` (closure runs only on parent `filled`); a later cancel/expiry
  → 30-min re-arm can stage the FULL stale DB qty (`alpaca_order_handler.py:795-
  924`). Plus: parent-filled-but-legs-disagree → `_close_position_on_fill` alerts +
  returns without closing (`:580-601`) yet caller logs "Position closed" +
  increments fills (`:1002-1010`). **CENSUS: 0 orders with filled_qty<requested_qty**
  → structural/latent. → queue ⑥ (HARD TRIGGER before routine qty>1 credit OR any
  position ≤~10 DTE).
- **F-A8/E6-edge (MED-HIGH).** `submit_and_track` return is DISCARDED
  (`paper_exit_evaluator.py:2245`, not assigned) → unconditional
  `routed_to:'alpaca',Fill pending` (`:2255-2260`); a `needs_manual_review` RETURN
  (terminal submit failure, not a raise) is costumed as routed success → monitor
  emits "Force-closed", increments counts, may write cooldown, suppresses same-
  cycle retry. E6's narrow no-phantom-fill invariant still holds. → rides the E8 PR
  territory.

**BROKER/DB GROUNDING (ALPACA authoritative):** live book is FLAT — Alpaca
`get_all_positions`=[], DB `paper_positions` 0 open. The "6 Aug-21 ICs" are
thesis-tracker rows (CLOSED positions tracked to expiry, I5/#1164), NOT open
custody exposure — a framing correction to F-A2-1's DTE trigger (nothing open to
trigger on today; the trigger is a standing guard for when qty>1 credit or a
near-DTE position returns).

**OBSERVE-WINDOW VERDICTS (W1 PASS, W2–W5 FAIL) + CLOCK RESET:**
- W1 (live gate qty basis) — **PASS in code**, runtime pending (all gate lines
  carry both bases + floor + applied basis + suggestion id). ITS CLOCK STANDS.
- W2 (max-loss risk basis) — **FAIL/not-armable.** All 3 callers
  (`utilization_gate.py:349`, `portfolio_allocator.py:163`,
  `risk_budget_engine.py:400`) omit `threshold_usd` → `would_flip` ALWAYS None
  (`risk_basis_shadow.py:45-49`); context lacks suggestion/cohort/decision id. The
  ledger's "each consumer logs would_flip" DISAGREES with code.
- W3 (bucket enforcement) — **FAIL/not-armable, TWO fail-open preconditions.**
  `_risk_from_fields` returns `(0,true)` when both totals unknown; `evaluate_bucket`
  adds zero + sets the caveat only when `v>0` → the log HIDES unknown open
  exposure; armed caller sees `would_block=false` and proceeds
  (`paper_autopilot_service.py:1038-1056`). This is the SECOND precondition on top
  of last night's L3 unreadable-equity polarity.
- W4 (calibration at scoring) — **FAIL/not-armable.** `_top_n` serializes ticker
  only (`calibration_apply_ordering.py:72-74`) → same-ticker structure swaps log
  `would_differ=False`; line omits strategy/expiry/id/scores/magnitude. (My own
  #1174 code.)
- W5 (composed W2+W3) — **FAIL** (both components defective).
- **⚠ LEDGER THE CLOCK RESET: W2/W3/W4/W5 arm decisions RESTART from the
  arm-evidence-repair SHA; THIS WEEK'S shadow logs are EVIDENCE-DEFECTIVE for those
  decisions. W1 alone passed — its clock stands.**

**DOCTRINE SHARPENING (adopted, extends the "drive the production route"
NEVER-DO):** "drive the production route" means the FULL route to the FAILURE
SEAM — an outer-layer test of an inner-layer bug (E8: source-pinning `run()`'s
raise while the bug is in `execute()`'s per-user loop) is the source-pin costume
one level down. A route-driving test must exercise the entrypoint END-TO-END to
the seam and assert on the OUTPUT.

**10 PACKET/LEDGER/CODE DISAGREEMENTS (move-don't-lose, annotated):** (1) E8
closure overstates the route [→①] · (2) E12 "cohort evaluable" false [→⑤] · (3)
E16 "output+linkage shipped" incomplete [→③, own PR-2] · (4) E14 persistence
path-dependent [→④] · (5) ledger "W2 logs would_flip" vs code None [→②] · (6) W4
ticker-lists aren't structure identities [→②] · (7) E6 invariant true but
close-state narrative too strong [→ E8 territory] · (8) E15 winter closed but
summer-open health still wrong [→ P2 F-A10-1] · (9) no matched 3-structure same-
underlying example — refused to fabricate; credit-zero proof is universal instead
[accepted] · (10) HEAD moved during audit (17f84d9→aca743a→1b8217b→b761a3f), E18
closed at final HEAD [accepted].

**REFUTED / NOT-PROMOTED (cite, don't re-derive):** direction='long' liar
(`workflow_orchestrator.py:3633`) — evidentiary, no proved live-decision consumer
(typed-column-lies inventory member #4, A9 hunt) · quarantined ~61 legacy rows —
no cleanup justified · no new credential instance in the current tree.

## 2026-07-11 (Sat ~21:1x CT) — BUILT: PoP census PR-0 terminal clamp (#1178) + PR-1 delete #7 (#1179)

STEP-0: DB `02:03Z` (America/Chicago `21:03`, Sat) / broker `22:03 ET` = `21:03
CT`, agree to the second; market CLOSED. Sunday FULL nightly at 00:00 CT — PR-0
H8 landed ~21:12 CT, PR-1 H8 ~21:19 CT, both clear of the ~23:00 CT hold gate
(margin ~2h40m). Sequential, H8 between.

**PR-0 — terminal [0,1] clamp in calculate_pop `aca743a` MERGED + H8 VERIFIED**
(BE `70f3f755` / worker `19307182` / worker-background `7f02521d`, all @
`aca743a`, created 02:09:15–16Z). calculate_pop clamped [0,1] on the CREDIT
branch ONLY (`ev_calculator.py:49`); every other branch (debit interp/midpoint/
long-only, short/long single-leg, raw-delta + neutral fallbacks) returned
UNCLAMPED and the `calculate_ev` consumer (`:176`→win_prob) fed them into EV
math. Fix: ONE clamp at the exit (`_clamp_pop`), every branch returns THROUGH it
(credit's inline clamp folds in — no double-clamp); LOG on engagement
(`[POP_BOUND_ENGAGED]` raw+branch+strategy, #1147 pattern) so an out-of-range
value is caught AND observable; non-finite → 0.5 neutral + logged. NO LIVE CHANGE
(max(0,min(1,x))==x for x∈[0,1]; in-range byte-identical, the clamp never engages
on the live book). Tests 15/15 (11 in-range cases bounded + assertNoLogs = the
no-op proof; clamp binds+logs on >1/<0/non-finite; end-to-end |delta|=1.3 → 1.0
long / 0.0 short + branch-tagged). **SATISFIES the PoP-unification "bound-assert
at the compute site" backlog line — the single terminal clamp IS the home; do
NOT scatter per-site clamps.**

**PR-1 — delete dead #7 `forecast_ev_pop` `1b8217b` MERGED + H8 VERIFIED**
(BE `242f7668` / worker `97b71557` / worker-background `285ab979`, all @
`1b8217b`, created 02:16:28–29Z). Zero-caller RE-VERIFIED at HEAD (`aca743a`, NOT
the census): only the def (`forecast_interface.py:129`) + test_forecast.py
(import + 2 tests); no prod caller, no re-export (`forecast/__init__.py` bare
docstring), no getattr/registry indirection. Deleted the function + orphaned test
import + the TestForecastEvPop class; no imports orphaned. Inert.
test_forecast.py 30 passed (was 32). Zero residual refs in packages/.

**PoP 7-way census — UPDATED MAP (canonical = calculate_pop, now terminally
clamped):**
- **#1 `calculate_pop`** (`ev_calculator.py:8`) = CANONICAL; PR-0 added the single
  terminal [0,1] clamp (the bound-assert home).
- **#7 `forecast_ev_pop`** = **DELETED** (#1179).
- **#6 `_calculate_ev_pop`** (`opportunity_scorer.py:316`) = **CLUSTER-RETIRE
  FILED** — NOT a trivial delete (caller `OpportunityScorer.score()` exercised by
  4 test files; dead-in-prod only transitively via the never-called
  `enrich_trade_suggestions`, `trade_builder.py:14`). Own PR: retire
  score/_calculate_ev_pop/_calculate_liquidity_penalty + enrich_trade_suggestions
  + the `optimizer.py:24` dead import + the 4 scorer test files together.
- **#3 `calculate_condor_ev` p_win** + **#5 `_condor_pop_from_legs`** (dup) =
  **FOLD into a calculate_pop condor branch** — the NEXT PoP PRs, boundary-only
  (observe-first; #5 clamps [0.01,0.99] vs canonical [0,1]), Option-A not a silent
  swap.
- **#4 score-sigmoid fallback** (`options_scanner.py:2134`) + **#2 exit-metrics
  abs-delta** (`ev_calculator.py:405`, live exit path) = **KEEP** (#4 narrow-only;
  #2 stays — folding touches the live take-profit path).
- **2-leg credit cohort's remaining PoP gate = the fold PRs** (#3/#5), sequenced
  after the #6 cluster-retire.

Untouched: everything else. Night ends here.

## 2026-07-11 (Sat ~20:3x ET) — BUILT: calibration apply-move PR-1 (#1174) + replay gap-(c) PR-2 (#1175) + prequential validator PR-3 (#1176)

STEP-0 (premise correction): the prompt/summary said "Sunday"; DB `01:21Z`
(America/Chicago `20:21`, Sat) + broker `21:21 ET` agree to the second → it is
**Saturday 2026-07-11**, market CLOSED, next open Mon 07-13 09:30 ET. The Sunday
FULL nightly fires 00:00 CT tonight — all three recycles landed by ~20:40 CT,
clear of it. Builds STRICTLY SEQUENTIAL, H8 between each.

**PR-1 — calibration apply-move + score recompute, observe-first `6f6a549`
MERGED + H8 VERIFIED** (BE `45eabc07` / worker `f1bb2c68` / worker-background
`8c98b9b9`, all @ `6f6a549`). Closes the L1-flagged real cost: SELECTION sorts on
`score` (frozen from RAW ev inside the scanner), so moving `apply_calibration`
earlier is INERT unless `score` is RECOMPUTED from calibrated ev. New
`analytics/calibration_apply_ordering.py`: `snapshot_pre_conviction_scores`
stamps `_scanner_score` before conviction → EXACT recompute (`soft_earn =
inner_raw − scanner_score` additive penalties; `conv_w = post_score /
scanner_score` multiplicative conviction; `new_score = max(0, clamp(base×ev_mult
− cost − regime − greek) − soft_earn) × conv_w`; de-saturation correct). TO-seam
`workflow_orchestrator.py:2441` (after conviction, before rank). Flag
`CALIBRATION_APPLY_AT_SCORING` default OFF → compute both orderings, log
`[APPLY_ORDER_SHADOW] … would_differ=`, mutate NOTHING (flag-off byte-identical);
armed → apply+recompute + `_calibration_applied` sentinel (the `:3564` legacy
post-sizing apply skips it → SINGLE application) + `_ev_raw_true` stamped.
Fail-safe per candidate + caller-wrapped. Tests 11/11.

**PR-2 — replay decision-output + `decision_id` linkage `057e11a` MERGED + H8
VERIFIED** (BE `a63bc95d` / worker `04f36525` / worker-background `24fd31c6`, all
@ `057e11a`, created 01:25:43–44Z; prior `6f6a549` → REMOVED confirms
supersession). **Replay Phase-1 gap-(c) — the unconditional blocker — CLOSED.**
Migration `20260712011627` `trade_suggestions.decision_id uuid` (nullable,
forward-only; in DROPPABLE_SUGGESTION_COLUMNS → code-before-migration = no-op
drop) applied + tracked + read-back (`col_uuid=1, mig_tracked=1`).
`run_midday_cycle`: fetch the active decision_id once, stamp each suggestion
(linkage); after the insert loop capture the ranked set (accepted +
rejected+reason, sorted by risk_adjusted_ev) as
`record_feature("__decision__","ranked_candidates")` — the decision OUTPUT a
byte-compare replay diffs against. BOTH blocks fail-soft
(`get_current_decision_context()` None when replay off → both no-op → replay-off
byte-identical; capture failure swallowed; `logger` is a module global so the
except branch is safe). Tests 3/3.

**PR-3 — prequential (out-of-sample) validator = the FALSIFIER `d554904` MERGED +
H8 VERIFIED** (BE `9dec42d1` / worker `2a348058` / worker-background `7399ad18`,
all @ `d554904`, created 01:38:00–01Z). Backward calibration-error is circular
(scores the fit on its own fit rows). This scores prequentially: for each live
close k (closed_at order, k≥warmup) fit on PREFIX [0..k-1], apply to close k's
RAW ev_predicted, compare calibrated-vs-raw. `calibration_service`: extracted
`build_adjustments_from_outcomes(outcomes, min_trades)` — a PURE fit (list→blob,
no DB round-trip); `compute_calibration_adjustments` delegates (byte-identical
for the prod default; `min_trades` is a study knob prod never passes; uses no
self.client → fits on `CalibrationService(None)`). New
`analytics/prequential_validator.py`: reuses prod math EXACTLY, reports raw-vs-cal
EV-RMSE/MAE + Brier; HEADLINE `ev_rmse_improvement = raw_rmse − cal_rmse` (≤0
with calibration having fired → FALSIFIED_CALIBRATION_DOES_NOT_HELP; never-fired
→ INCONCLUSIVE; >0 → HELPS); prefix-invariance checked (fit = function of the
SET, not order — order dependence = leakage); zero-row/too-short →
insufficient_data, never raises; `main()` on-demand only (schedules nothing,
changes no live behavior). Non-circular as of #1167 (ev_predicted =
COALESCE(ev_raw, ev) = RAW). Tests 10/10; existing calibration suite 58/58
(extraction backward-compatible).

**Lane deliverables (READ-ONLY, filed):**
- **L1 PoP census → 5-PR map — ⚠ CORRECTS the 07-11 census above (`:64`):** #6
  `_calculate_ev_pop` is NOT a trivial zero-caller delete — its caller is
  `OpportunityScorer.score()` (`opportunity_scorer.py:174`), dead-in-prod only
  transitively (its sole prod caller `enrich_trade_suggestions`,
  `trade_builder.py:14`, has ZERO call sites) yet exercised by 4 test files → a
  CLUSTER retire, not a one-liner. Only **#7 `forecast_ev_pop`**
  (`forecast/forecast_interface.py:129`) is a clean zero-caller delete (tests
  only; no re-export). **PR-0 terminal `[0,1]` clamp STILL NEEDED** — only the
  credit branch clamps (`ev_calculator.py:49`); every other branch + the
  `calculate_ev` consumer (`:176`→`:251`) is unclamped. Map: PR-0 clamp (inert)
  · PR-1 delete #7 (trivial) · PR-2 retire #6 CLUSTER (inert-to-live, medium
  blast) · PR-3 condor fold #3+#5 (boundary, observe) · PR-4 fallback narrow #4
  (observe). #2 STAYS (live exit path `workflow_orchestrator.py:1404`).
- **L2 replay retention TTL spec:** blob table is `data_blobs` (not
  decision_data_blobs); 4 tables in migration `20260120000000`. Growth ≈
  **70 MB/mo ≈ 0.85 GB/yr**, dominated by `data_blobs.payload` (option-chain
  blobs; 2–5× if chains carry per-contract greeks). Recommend **14-day**
  retention + daily fail-open `replay_reaper` ~03:00 CT: (1) `DELETE FROM
  decision_runs WHERE created_at < now()-'14 days'` (cascades inputs+features)
  then (2) orphan-blob anti-join delete (blobs are content-addressed/deduped →
  a pure age-delete would FK-violate). Flags: `trade_suggestions.decision_id`
  has NO FK → dangling after reap (expected; the window must exceed the
  replay-lookback need); `REPLAY_MAX_BLOB_BYTES` 2 MB cap is NOT enforced (warns
  only, still stores); no standalone `decision_runs.created_at` index (tiny
  table → low-pri; it's a migration, out of scope).
- **L3 bucket-control layering check (operator: confirm + flag, DON'T fix):**
  ordering CONFIRMED — utilization gate (`paper_autopilot_service.py:1021`,
  fail-CLOSED on unreadable input) precedes the bucket check (`:1039`). BUT the
  equity-unreadable backstop is CONDITIONAL: the bucket's cap-0-never-blocks
  (equity unreadable → would_block=False, by design at evaluate_bucket) is only
  caught upstream when `_ug_on` (RISK_UTILIZATION_GATE_ENABLED=1). **With that
  flag unset AND BUCKET_CONTROL_ENFORCE=1, an equity-unreadable read makes the
  bucket cap silently never-block — UNBACKSTOPPED.** Deferred polarity fix
  filed: bucket_control fail-CLOSED on equity-unreadable when enforce armed
  (independent of the utilization flag). NOT fixed tonight (per operator).

**Deferred (filed, not built):** L1 PoP 5-PR sequence (PR-1 delete #7 = clean
tomorrow-post-close candidate; #6 is a cluster, re-scope) · L2 `replay_reaper`
job + 14-day TTL (+ optional `decision_runs.created_at` index) · L3
bucket-control equity-unreadable fail-closed polarity.

## 2026-07-11 (Sat ~19:4x ET) — BUILT: B1/B2 bucket control PR-1 (#1171) + winter-close PR-2 (#1172)

STEP-0: DB 00:27Z (dow=0) / broker 20:27 ET — consistent, market CLOSED.

**PR-1 — B1/B2 one-beta bucket control + same-run reservation `d86a270` MERGED +
H8 VERIFIED** (BE `b6e0324e` / worker `ab1c8e0e` / worker-background `2c28a8e1`,
all @ `d86a270`, created 00:39:36–37Z > merge 00:39:34Z). **Completes the BUILD
half of the book-scaling epic** (persist+observe = #1166). `risk/bucket_control.py`:
buckets as DATA ({SPY,DIA,QQQ,IWM}=us_equity_beta, else own). Wired into
`_execute_per_cohort`'s staging loop (after the utilization gate): exposure =
Σ max_loss_total of in-bucket open positions (+ same-run reservations + the
candidate) vs BUCKET_MAX_PCT × equity; honest basis, legacy-NULL at premium WITH
caveat (H9), equity-unreadable → cap 0 → never blocks. **Observe-first** (flag
`BUCKET_CONTROL_ENFORCE` default OFF): log [BUCKET_SHADOW] + fire the #1139-class
alarm (`bucket_exposure_would_block`) on a would-block that PROCEEDS; armed →
reject with a `bucket_exposure_cap` stamp. Same-run reservation accumulates as
each candidate stages (byte-identical for a ≤1-candidate cycle). Tests 14/14
(exposure per basis + NULL-never-fabricated · reservation · fail-safe · polarity
· executor 2-candidate off/armed + ≤1 byte-identical + cross-bucket).
- **⭐ BUCKET_MAX_PCT arithmetic (owner-tunes):** at $2,068, one IC ≈$372 = 18%,
  so **0.25** allows one IC + nothing same-bucket; 0.40 allows two. **Recommend
  0.25.** **ENFORCEMENT = ONE composed owner decision after ~1 week of
  [RISK_BASIS_SHADOW] + [BUCKET_SHADOW] logs: arm `RISK_BASIS_MAX_LOSS_ENABLED=1`
  + `BUCKET_CONTROL_ENFORCE=1` together.** #1139 tripwire is the armed guard
  meanwhile. **The book-scaling epic's BUILD is done; enforcement is a decision,
  not a build.** backlog.md updated (weekend-ships block + P0-B status).

**PR-2 — winter-close blind hour `bd6046a` MERGED + H8 VERIFIED** (BE `12f104e6`
/ worker `ce2764d2` / worker-background `90d918a5`, all @ `bd6046a`, created
00:45:00–01Z > merge 00:44:58Z). `is_us_market_hours` (ops_health_service.py:42)
hardcoded UTC 13:30–20:00 = ONLY the EDT session → in EST the 20:00–21:00Z hour
read CLOSED all winter (data_stale suppressed + `_rth_job_status` ok = the A10
blind hour). Fix: ET wall-clock (9:30–16:00 America/New_York) via zoneinfo,
mirroring `intraday_risk_monitor._fallback_is_market_open_et` (reuse). BYTE-
IDENTICAL for EDT (existing June assertions pass). Winter tests: Nov 20:30/20:59Z
now OPEN, 21:00Z=close. **Retires the 2026-10-01 hard trigger ~3 months early.**

**Lane deliverables (READ-ONLY, filed):**
- **L1 calibration-apply-ordering:** ⚠ **SELECTION sorts on `score`, NOT `ev`** —
  and `score` is frozen from RAW ev INSIDE the scanner (`options_scanner.py:3751,
  3919`). So moving `apply_calibration` earlier is insufficient; the fix MUST
  RECOMPUTE `score` from calibrated ev (the real cost). TO-seam = after
  conviction at `workflow_orchestrator.py:2441` (before rank :2495); DELETE the
  midday :3562-3569 apply (move-not-add → else ev×mult²) + idempotency sentinel;
  hash `ev_raw` for features_hash continuity. Effort ~M (half-full day). Raw-basis
  prereq already closed by PR-B #1167. Filed in backlog's calibration item.
- **L2 replay Phase-1 gaps:** (a) config blob — write at suggestions_open.py:141 /
  close:135, `record_input(snapshot_type="config")`, PARTIAL blocker (code pinned
  by git_sha). (b) applied calibration+conviction — capture at
  `workflow_orchestrator.py:2441`+`:2898`, YES-blocker but LATENT (raw-mode ×1.0
  captures trivially match; breaks the day multipliers turn non-trivial). (c)
  decision OUTPUT + `decision_id` linkage — the UNCONDITIONAL blocker + the only
  gap needing a MIGRATION (`trade_suggestions.decision_id`); ranked-list via
  `record_feature("__decision__","ranked_candidates")`. Sequence: (c) critical
  path → (a) → (b before the 8th live close). ~4–6 evenings on Monday's captures.
- **L3 PoP census (7→canonical):** FOLD #3 (`calculate_condor_ev` p_win) + #5
  (`_condor_pop_from_legs`, dup) into a new `calculate_pop` condor branch; DELETE
  #6 (`_calculate_ev_pop`, dead — enrich_trade_suggestions uncalled) + #7
  (`forecast_ev_pop`, dead — tests only); #4 (score-sigmoid fallback) + #2
  (exit-metrics abs-delta) STAY. **Bound-assert [0,1] home = a single terminal
  clamp in `calculate_pop`** (today only the credit branch clamps). Migration
  order: PR-0 terminal clamp (no live change) · PR-1 dead-code delete · PR-2
  condor fold (boundary-only, observe-first) · PR-3 fallback narrow (observe) ·
  PR-4 exit fold (observe). Live-number-change flags: #5 boundary, #4 fallback,
  #2 short-legs → Option-A, not silent swap.

## 2026-07-11 (Sat ~19:0x ET) — BUILT: PoP inversion fix PR-0 (#1169) + REPLAY_ENABLE Phase-0

STEP-0: DB 00:01Z (dow=0) / broker 20:01 ET — consistent (UTC rolled to Sunday),
market CLOSED, weekend premise holds.

**PART 1 — PoP inversion `aaa8431` MERGED + H8 VERIFIED** (BE `61c01ea7` /
worker `e52b8ae2` / worker-background `c02bd0bd`, all @ `aaa8431`, created
00:08:32–33Z > merge 00:08:30Z). `ev_calculator.py:42` one-token swap
`max_gain`→`max_loss`: credit PoP was `max_gain/(max_gain+max_loss)` =
`credit/width` = **P(LOSS)** (inverted → credit-vertical EV negative → −999
MIN_EDGE gate → 2-leg credit cohort silently blocked). Now
`max_loss/(max_gain+max_loss)` = `1 − credit/width` = **P(WIN)** + terminal
`[0,1]` clamp (H9 bound-assert; width-bound recommended over delta — H9-robust).
Arithmetic: credit 1.49/width 5 → **0.298 → 0.702**. **Byte-identical for the
live book:** only the 5 credit-vertical types hit that branch; ICs RAISE in
calculate_ev (:187 → calculate_condor_ev), debits take the delta branch — both
pinned untouched. Book = ICs + debits today → NO live score change; unblocks the
latent credit cohort. Tests (new RUNNING file — legacy test_calculate_pop.py is
#775-skipped): 12 + the updated test_honest_pop pin (130/200). **The 2-leg
credit cohort PoP gate is CLEARED**; the 7-way PoP census consolidation stays
its own filed item.

**PART 2 — REPLAY_ENABLE Phase-0 (supervised env flip, AFTER Part-1 H8).**
**PRE-FLIGHT CLEAN (the load-bearing check):** `is_replay_enabled()` reads
`REPLAY_ENABLE` at RUNTIME (decision_context.py:34-45); record_input/feature
STAGE in memory and `commit()` flushes ONCE at cycle-end (atomic RPC) — NOT
per-symbol-synchronous in the scan hot path. **AND commit() is FAIL-SAFE**:
wraps everything in try/except (`:297/:366`) that logs + marks-failed +
RETURNS stats WITHOUT re-raising, so `ctx.commit()` at
suggestions_open.py:144 CANNOT break the suggestions cycle (a capture failure
writes a failed decision_run, nothing more). Capture tables were 0/0/0/0 (never
run). **FLIP DONE:** `REPLAY_ENABLE=1` set on BOTH RQ workers (worker
`9b0ffca8` + worker-background `ec49427f`; the otc worker runs
suggestions_open/close), recycled to SUCCESS (worker `816bfaac` / worker-bg
`bfe26936`, same SHA aaa8431, env-only). Env value NOT read back via
list_variables (secrets-hygiene) — the set-success + recycle + Monday capture
rows are the read-back chain.
- **⏳ VALIDATION PENDING (Mon 07-13 11:00 CT scan):** capture rows written
  (decision_runs header + inputs/config/clock/SHA per the replay contract) +
  scan timing not degraded + the job green under the F-A4-1 typed contract. I
  cannot sign a manual weekend scan trigger, and Monday's 11:00 CT
  suggestions_open is the first capture either way, so flipping tonight only
  pre-positions the flag. Replay Phase-1 (the byte-compare runner —
  ReplayTruthLayer.from_decision_id exists) now has data ACCUMULATING from
  Monday; ~4–6-evening estimate stands (writer was already built + wired, per
  the L2 recon).
- **⚠ RETENTION LINE FILED (item 7):** ~2 wrapped cycles/day (suggestions_open
  11:00 + suggestions_close 08:00 CT), each ~a few hundred decision_inputs +
  features + deduped blobs (2 MB soft cap per blob — a full multi-expiry chain
  is the volume risk). Modest rows/day but UNBOUNDED — file an N-day TTL /
  archive before this becomes the next unbounded table. **NEW P2 backlog line.**

## 2026-07-11 (Sat ~18:4x ET) — BUILT: P0-B book-scaling PR-A (#1166) + COALESCE restore PR-B (#1167)

STEP-0: DB 23:26:51Z / broker 23:26:51Z, dow=6, is_open=false — Saturday
CLOSED. Two sequential PRs (PR-A H8 before PR-B started).

**PR-A — book-scaling readiness `6044c77` MERGED + H8 VERIFIED** (BE `1af4ef75`
/ worker `e8f315b6` / worker-background `f1f79ab6`, all @ `6044c77`, created
23:41:18–19Z > merge 23:41:16Z). Migration `20260711233113`: paper_positions
+cost_basis_total +max_loss_total (TOTALS, nullable, forward-only, legacy NULL =
H9). **⚠ units-trap** guarded (column comment + `honest_position_risk()` reads
the total, never ×qty). Write sites (`_commit_fill` + orphan-repair) reuse
`trade_suggestions.max_loss_total` scaled to filled contracts. **Observe-only
shadow** (`services/risk_basis_shadow.py`, flag `RISK_BASIS_MAX_LOSS_ENABLED`
default OFF — third Option-A observe→enforce): RBE / allocator / utilization each
compute BOTH bases, DECIDE current, log `[RISK_BASIS_SHADOW]` + would_flip;
`choose_basis()` swaps to honest only when armed (byte-identical off). Tests
17/17 incl. the units-trap (qty-4 → total as-is).
- **⭐ WORKED EXAMPLE (owner-decision input) at $2,068 equity, real recent QQQ
  IC:** premium basis ~$149 (7.2% of book) vs honest max-loss ~$372 (**18%**).
  The 85% utilization gate + 36% allocator ceiling bind on NEITHER at this
  equity → the honest basis flips NO single-trade decision today. BUT it reveals
  each IC risks 18% of equity (not 7%), and **2 concurrent = 36%** ($744 honest
  vs $298 premium) — the real magnitude the #1139 tripwire alarms on. A
  per-trade cap anywhere in 8–18% would block honest / pass premium. **THE FLIP
  IS THE OWNER'S DECISION on a week of `[RISK_BASIS_SHADOW]` logs.** #1139
  remains the interim guard. B1/B2 bucket control + same-run reservation = the
  epic's NEXT PR, now unblocked by the persisted fields.

**PR-B — COALESCE restore `c069f56` MERGED + H8 VERIFIED** (BE `13413919` /
worker `97f519e5` / worker-background `b08de991`, all @ `c069f56`, created
23:47:43–44Z > merge 23:47:41Z). Migration `20260711234336`:
`learning_trade_outcomes_v3.ev_predicted` → `COALESCE(ts.ev_raw, ts.ev)` (+
pop_raw). The guard was added 04-11 and **silently reverted 06-23**
(20260623010000) → the validator/calibrator would train on their own calibrated
output (circular), masked only by raw mode. **CONTAMINATION VERDICT (verified,
not assumed): NO row annotation needed** — 40 diverged rows all have ev_raw to
fall back to (healed); 175 NULL-ev_raw rows were raw-mode (ev==raw, coalesce→ev
correct); 8 live training rows already clean (0 diverged). Fix is PREVENTIVE for
when calibration leaves raw mode; pre-epoch rows walled off by the epoch +
live-only filter. **Drift guard** (`test_ev_raw_coalesce_drift_guard.py`): a DB
view has no Python route in DB-less CI, so it asserts the LATEST committed
migration coalesces ev_raw — a 4th silent revert (3rd occurrence of this bug)
fails loudly. **Prequential-validator prereq CLOSED.**

**Lane deliverables (READ-ONLY, filed):**
- **L1 PoP-semantics spec:** the inversion is at `ev_calculator.py:42` — one-token
  swap `max_gain`→`max_loss` (= `1 − credit/width` = P(win)); recommend the
  width-bound over delta (H9-robust, minimal diff); add a terminal
  `max(0,min(1,pop))` clamp (the canonical [0,1] bound-assert home). 7-way census:
  fold #5 (`_condor_pop_from_legs`, dup of #3), #2/#3/#6 into canonical
  `calculate_pop`; #7 (forecast) + #4 (score-sigmoid fallback) stay. Ship PR-0
  (inversion + clamp + un-pin the 2 bug-pinning tests) ALONE, non-RTH. Gates the
  2-leg credit cohort.
- **L2 replay capture-write:** **PREMISE CORRECTED — the writer is fully BUILT +
  WIRED, just `REPLAY_ENABLE=0`-gated** (`decision_context.py:34-45`; entrypoints
  suggestions_open/close). Phase-0 = flip the flag env-first + validate (NO code);
  Phase-1 = 3 gaps (config blob · applied-multiplier feature · decision-output +
  decision_id linkage); Phase-2 = the byte-compare runner (ReplayTruthLayer
  exists). ~4–6 evenings, not the ~6–10 backlogged. Suggestion-decision only;
  execution-decision (equity/OBP/positions) is a separate 2nd hook.
- **L3 winter-close:** `ops_health_service.py:56` hardcodes `20*60` (20:00Z)
  close. Fix = ET wall-clock via zoneinfo, mirroring
  `intraday_risk_monitor.py:132-141` (`ZoneInfo("America/New_York")`); do NOT
  wire broker get_clock (network). ~2–4 hrs. Calendar trigger 2026-10-01.

## 2026-07-11 (Sat ~18:0x ET) — BUILT: shadow-to-expiry THESIS TRACKER (I5) + F-A9-1 (#1164)

STEP-0: DB 22:35:56Z / broker 22:35:57Z, dow=6, is_open=false — Saturday
CLOSED. **#1164 `8ffc214` MERGED + H8 VERIFIED** (BE `bdee5e44` / worker
`68103dff` / worker-background `b4ddeb4a`, all @ `8ffc214`, created 23:05:45–46Z
> merge 23:05:43Z). **"The #1 missing measurement."** OBSERVE-ONLY (own table,
alerts nothing, modulates nothing).

**RECON (no surprise):** underlying-at-expiry = `truth_layer.daily_bars`
(Polygon historical → Alpaca fallback), covers all expiries. Storage = OWN
table `position_thesis_outcomes` (migration `20260711224226`, keyed on the
position PK) — only 13/83 closes carry a joinable position_id on their LFL row,
so riding LFL would strand 70. Structure split: 42 two-leg + 41 four-leg.

**Build:** `analytics/thesis_scoring.py` (pure classify + score; strict
inequalities, AT-a-strike = MISS; IC HIT=inside the SHORT strikes, credit
vertical HIT=short not breached, debit vertical HIT=ITM through the LONG strike,
directional=ITM held side, unknown=unresolvable/H9) · `thesis_tracker.py` daily
job (idempotent: terminal never re-scored; in_progress+unknown re-scored;
**FIRST job under the F-A4-1 typed contract** — unscorable → counts.errors →
PARTIAL) · endpoint `/internal/tasks/thesis/score` (background) + SCHEDULES
17:00 CT + EXPECTED_JOBS + the 8th-background-route pin. **F-A9-1** (migration
`20260711225359`): `signal_accuracy_rolling.hit_rate → realized_trade_win_rate`
(it counts pnl>0, NOT thesis — the 12.5%-vs-~78% confusion DIES; thesis accuracy
is now its own measure). Tests: scoring per structure + handler contract, 33+.

**⭐ THE HEADLINE — first honest thesis table (16 post-epoch closes; legacy-paper
era ~61 quarantined; 6 Aug-21 ICs = IN_PROGRESS). PREVIEW basis: Alpaca daily
closes (SIP Jun / iex Jul — SIP blocks recent dates, same reason daily_bars uses
Polygon primary); the job's authoritative Polygon backfill lands Mon 17:00 CT.
None of the 16 sat near a strike boundary, so the source choice flips no
verdict.**

| symbol/exp | fill | structure | close_reason | P&L | thesis |
|---|---|---|---|---|---|
| BAC 06-05 | live-broker | debit call ≥51 | manual | −82 | **HIT** |
| CSX 06-05 | live-broker | debit call ≥43 | manual | −161 | **HIT** |
| F 06-26 | live-broker | debit call ≥15.5 | manual | +105 | miss |
| NFLX 07-02 | live-broker | debit put ≤85 | reconciler | −84 | **HIT** |
| MARA 07-10 | live-broker | debit call ≥13.5 | reconciler | −28 | miss |
| NFLX 07-10 | live-broker | debit put ≤86 | reconciler | +48 | **HIT** |
| QQQ 07-10 | live-broker | IC [645,750] | reconciler | −73 | **HIT** |
| BAC 06-05 | live-internal | debit call ≥51 | envelope | 0 | **HIT** |
| CSX 06-18 | shadow | debit call ≥44 | envelope | 0 | **HIT** |
| BAC 06-26 | shadow | debit call ≥49 | target_profit | +192 | **HIT** |
| NFLX 07-02 | shadow | debit put ≤85 | stop_loss | −273 | **HIT** |
| NFLX 07-02 | shadow | debit put ≤85 | stop_loss | −546 | **HIT** |
| MARA 07-10 | shadow | debit call ≥13.5 | stop_loss | −675.99 | miss |
| NFLX 07-10 | shadow | debit put ≤86 | target_profit | +133.35 | **HIT** |
| NFLX 07-10 | shadow | debit put ≤86 | target_profit | +662.10 | **HIT** |
| QQQ 07-10 | shadow | IC [645,750] | envelope | −234.78 | **HIT** |

**THESIS HIT-RATE = 13/16 = 81%** (LIVE broker fills 5/7 = 71% · shadow/internal
8/9 = 89%) — the formalized B1 ~78%, now a standing metric. **THE FINDING that
justifies the whole build: of the 13 thesis HITs, only 4 were profitable — SEVEN
were losses or force-flat.** The signal was right 81% of the time; execution +
stops converted most right-theses into losses. Exhibits: QQQ 07-10 finished
725.6 INSIDE [645,750] (thesis dead-on) yet stopped −73/−234; NFLX 07-02 expired
77.59 BELOW the 78/79 short puts = MAX PROFIT at expiry, yet the shadows were
stopped −273/−546 on an intraday spike. **The loss is DOWNSTREAM of the signal,
not in it** — the exact thing the tracker exists to measure. (Note: this is a
PREVIEW I computed via the scorer; `position_thesis_outcomes` is populated by
the job's own first run Mon 17:00 CT — I did NOT hand-write the table, so
Monday's authoritative rows are idempotent-clean.)

**⏳ PENDING PINS (Mon 07-13):** thesis_tracker first run 17:00 CT populates the
table + lands the 6 Aug-21 ICs in_progress + the job records `partial` iff any
close is unscorable (F-A4-1 contract's first live exercise on this job).

**Lane deliverables (READ-ONLY):**
- **L1 calibration-ordering prereqs:** (a) training pool LIVE-ONLY CONFIRMED &
  WIRED (`calibration_service.py:336-337`, flag `CALIBRATION_TRAIN_LIVE_ONLY`;
  8 live vs 91 paper excluded). (b) **CIRCULAR-RISK:** `ev_predicted` maps to
  the CALIBRATED `ts.ev` (view def), and the `COALESCE(ev_raw,…)` guard was
  **REVERTED 06-23** (`20260623010000:58-59`, undoing `20260411000000`). Masked
  ONLY by raw mode — the instant calibration leaves raw mode the prequential
  validator trains on its own output. **Epic's #1 remaining task: restore the
  `COALESCE(ev_raw,ev)` view + a drift-guard test (2nd regression).**
- **L2 F-A1a trigger distance:** **PARKED** — both challengers (neutral,
  conservative) at 0 closed round-trips in the trailing-7d Gate-2 window
  (`evaluator.py:318,408`); structurally can't approach 8 at ~1 close/wk. No
  queue jump; cheap standing re-check before each build session.
- **L3 book-scaling spec (P0-B):** **max_loss ALREADY EXISTS** at
  `trade_suggestions.max_loss_total` (from `_compute_risk_primitives_usd`,
  options_scanner.py:2042 — reuse, don't reconstruct). Write sites:
  `paper_endpoints.py` `_commit_fill` (:2525-2546) + orphan-repair (:2070-2090),
  enrich the existing suggestion SELECT (+max_loss_total, /contracts × filled).
  Migration: +cost_basis +max_loss NUMERIC (nullable, no backfill/H9).
  Consumers: PortfolioAllocator :133-135, RBE :160 (**⚠ UNITS TRAP — RBE keys
  max_loss PER-CONTRACT ×qty; persist a TOTAL and it double-scales**),
  utilization candidate-side :330 (separable). Effort ~0.5-1d. Filed for P0-B.

## 2026-07-11 (Sat ~11:1x ET) — BUILT: F-A3-1 Part B close_reason persistence — QUEUE ⑤ COMPLETE (#1162)

STEP-0: DB 14:53:35Z / broker 14:53:35Z, dow=6, is_open=false — Saturday
CLOSED. **#1162 `a5cabd3` MERGED + H8 VERIFIED** (BE `7bb2c9a3` / worker
`3e30bf87` / worker-background `6bbe69a4`, all @ `a5cabd3`, created 15:14:49–50Z
> merge 15:14:47Z). **NO migration** (rides existing JSONB — order_json +
details_json). The thesis-tracker (I5) prerequisite.

**Three deaths fixed FORWARD-ONLY:**
- **Death B** (LIVE closes lost the reason): the exit evaluator stamps the
  mapped close_reason + granular detail onto the close order's `order_json` at
  stage time (`_close_position`, beside the CLOSE_FILL_GAP stamp); the
  reconciler `_close_position_on_fill` READS it back with a
  `_VALID_CLOSE_REASONS` fallback — replacing the hardcoded
  `alpaca_fill_reconciler_standard`. Coarse ∈ the 9-value
  `check_close_reason_enum`; unmappable → left unset → safe fallback.
- **Death A** (monitor collapsed all to envelope_force_close): 5a maps
  stop_loss / expiration via `_STAGE5A_REASON_MAP` (monitor stop ==
  scheduled stop = `stop_loss_hit`); 5b threads `violation.envelope` →
  `reason_detail`; new `_close_reason_detail()` → thesis enum. New OPTIONAL
  `reason_detail` param on `_close_position` + `_execute_force_close`
  (additive; existing callers unchanged).
- **Death C/D** (ingest never carried it): `+close_reason` in the SELECT
  (fixes `policy_decisions.exit_reason` always-"") + `details_json.close_reason`
  + `close_reason_detail` (from the closing order's order_json), mirroring how
  `symbol` rides.

**Thesis enum** (JSONB-only `close_reason_detail`, UNCOUPLED from the 9-value
CHECK): take_profit, stop_loss, symbol_envelope, daily_brake, weekly_brake,
concentration, stress, dte_threshold, expiration_day, manual, orphan_repair,
reconciler_unknown. Entry gates (streak_breaker, reentry_cooldown) EXCLUDED —
they never close a position.

**Backfill (SUPERVISED — shown SQL + read-back):** true count is **100
trade_closed / 0 had close_reason** (CORRECTS the ledger's stale "~71"). 5
annotate-if-derivable via `details_json->>'position_id'` → semantic
`paper_positions.close_reason` (2 target_profit_hit + 2 envelope_force_close +
1 stop_loss_hit) — stamped `close_reason_provenance=backfilled_from_position_row`.
95 stay HONESTLY BLANK (87 no join key, 8 lost at Death B). Read-back: 5 filled
/ 95 blank / 5 provenance-stamped.

Tests T1–T6 (production routes — reconciler + ingest record builder + the real
mapping fns/constant): 13 pass. Regression 285 pass / 54 skip. Two existing
fakes updated for the new `reason_detail` param (contract).

**⭐ I5 THESIS TRACKER UNBLOCKED** — its charter now reads
`details_json.close_reason` (coarse) + `close_reason_detail` (granular) going
forward.

**⏳ NEW PENDING PIN (Mon 07-13):** the FIRST close after #1162 carries an
honest close_reason END-TO-END (`paper_positions.close_reason` semantic +
`details_json.close_reason`/`_detail` populated) — the single pin that proves
all three deaths fixed at once.

**QUEUE ⑤ COMPLETE — the adjudication queue is EMPTY except LATENTS** (all
filed with triggers): F-A4-2 (retry re-enqueue + reaper, one package) ·
F-A10-1 (999-DTE fabrication + equity-assignment filter — CONFIRMED-but-inert,
`docs/backlog.md:149-154`) · F-A2-1 (GTC pilot scope — CLEAN; audit GTC via
order_json/broker, not the `time_in_force` typed column). Monday pins:
PR2 first-submit (otc1-* accepted) · E7 first-ordering (≥2 survivors) · L5
partial watchlist · F-A3-1 first-honest-close.

## 2026-07-11 (Sat ~10:4x ET) — BUILT: PR2 client_order_id + targeted reconcile (P0-A COMPLETE, #1160)

STEP-0: DB 14:24:13Z / broker 14:24:14Z, dow=6, is_open=false — Saturday
CLOSED. **#1160 `2dc5b0d` MERGED + H8 VERIFIED** (BE `6c5f95cc` / worker
`c7df25bb` / worker-background `bfa6544a`, all @ `2dc5b0d`, created 14:42:52–53Z
> merge 14:42:50Z).

**Migration FIRST (order-of-ops honored):** `20260711143151
paper_orders_client_order_id` — `client_order_id text` + PARTIAL UNIQUE index —
applied + TRACKED + read-back (type=text, unique partial index confirmed)
BEFORE the code merge. Repo file mirrors the tracked version by name.

**P0-A COMPLETE.** PR1 = the invariant (a LIVE submit that raises never
internally fills — holds OPEN in needs_manual_review). PR2 = the targeted
resolution: **the response-lost edge now auto-resolves; operator-manual is the
FALLBACK, not the mechanism.**
- **ATTACH** (additive, one funnel): `deterministic_client_order_id =
  otc1-<l|p>-<paper_orders.id>` (~43 chars, [a-z0-9-]). Persisted at insert
  (paper_endpoints; id is DB-generated → written post-insert) + recomputed from
  the PK in `build_alpaca_order_request` as a bulletproof fallback → threaded
  into `submit_option_order`'s LimitOrderRequest (exclude_none → absent =
  byte-identical). Entry + close + resting-TP GTC through the one
  `submit_and_track` funnel. STABLE across in-function retries (dedup), FRESH on
  re-stage (new row → new PK).
- **DUPLICATE-422 CLASSIFIER** (`submit_and_track`): `client_order_id must be
  unique` → `get_order_by_client_id` → backfill → return submitted; NEVER
  needs_manual_review (kills the false-critical-on-every-legitimate-retry).
- **RECONCILER STEP 1.5** (`alpaca_order_sync`, flag
  `CLIENT_ORDER_ID_RECONCILE_ENABLED` default-ON): NULL alpaca_order_id +
  non-NULL client_order_id → FOUND backfill; 404 → re-arm to `'cancelled'`
  (`_TERMINAL_FAILED_STATUS`, paper_exit_evaluator.py:559 → #1046 re-arms a
  fresh close for closes; dedup-exclusion re-executes for entries). Legacy NULL
  rows excluded by the query → inert until ids exist.

Tests T1–T6 (production paths, no real SDK dep): 14 pass. Regression across
every touched module: 147+4 pass, all compile.

**⚠ DEVIATION (surfaced, not silent):** the ATTACH is UNGATED per the L1 spec
(harmless-additive; exclude_none). Blast radius is every live order, but a
broken attach fails **LOUD + SAFE** (needs_manual_review + critical, no phantom
fill, P0-A holds) and reverts by code. Followed the spec over adding a second
kill-switch; the operator can request `CLIENT_ORDER_ID_ENABLED` if preferred.
**⏳ PENDING PIN — first live submit Mon 07-13:** verify the first live
entry/close carries `otc1-*` AND Alpaca accepts it. If it 422s the
`client_order_id` param → revert #1160.

**⚠ SDK verification gap:** `get_order_by_client_id` (TradingClient) +
`client_order_id` (OrderRequest field) verified by RECON against the installed
SDK source, NOT locally runnable (alpaca absent local + CI; tests mock the
client). Standard long-standing alpaca-py API — high confidence, but Monday's
first submit is the empirical proof.

**PR1 integration-test debt (RESTATED with trigger, not paid here):** the
deferred `_close_position` P0-A hold integration test (drive a LIVE-submit
raise → assert the position is HELD OPEN, needs_manual_review, no internal
fill, then Step 1.5 resolves it) is NOT paid in PR2 — PR2's tests cover the
attach/classifier/reconcile SEAMS, not the `_close_position` hold end-to-end.
**TRIGGER:** pay it the next time `_close_position`'s LIVE-submit branch is
touched, OR on the first real response-lost event (whichever first).

Carried forward: L4 `time_in_force` typed-column caveat (audit GTC via
order_json/broker, not the column) · L5 Monday-partial watchlist
(paper_learning_ingest / iv_daily_refresh all-missing / intraday_risk_monitor) ·
E7 first-ordering-effect pin (Mon scan with ≥2 survivors). Queue after ④:
⑤ F-A3-1 close_reason (L2 spec ready) · latents F-A4-2 / F-A10-1 / F-A2-1.

## 2026-07-11 (Sat ~09:5x ET) — BUILT: E7 viability re-wire on the ACTIVE route (#1158)

STEP-0: DB 13:39:06Z / broker 13:39:11Z, dow=6, is_open=false — Saturday
CLOSED. **#1158 `723f9f5` MERGED + H8 VERIFIED** (BE `b8ed41d7` / worker
`b0513f93` / worker-background `bf3a13dd`, all SUCCESS @ `723f9f5`, created
13:50:49–50Z > merge 13:50:47Z). **Third #1126 instance — closed HONESTLY.**

**What was wrong.** M4 item-0b (07-06) wired the viability bias into
`get_executable_suggestions` — but policy-lab mode returns `_execute_per_cohort`
at the `is_policy_lab_enabled()` early-return (paper_autopilot_service.py:452),
BEFORE that method (:506). With `UNIVERSE_VIABILITY_BIAS_ENABLED=1` armed on the
workers since 07-06, **the bias steered NOTHING 07-06→07-11** (the M4 wiring was
INERT). My M4 tests pinned the orphan — the #1126 class in test form.

**Fix (bias re-wired at the ACTIVE route).** In `_execute_per_cohort`'s
per-cohort fetch: re-rank the pending set with `_viability_rank_key` when armed
(sort-KEY only, positive scores only, stored raev untouched; flag-off
byte-identical). **⚠ SEAM disposition:** `.limit(max_suggestions_per_day)`
MOVED off the DB query to a post-re-rank Python slice — a server-side LIMIT
truncated by RAW EV BEFORE the re-rank, which would strand a biased winner
(SPY ×1.30) below the cut (a 4th #1126 in the fix's clothes). Fetch now: full
pending set ordered raw-EV-desc → Python re-rank → slice to cap. Also corrected
the now-false "executor's real candidacy ordering" comment in the dead
`get_executable_suggestions` (retained for the legacy non-policy-lab path only).

**Route-driving test (first CLAUDE.md §9 application).**
`test_e7_viability_rewire_executor_route.py` DRIVES `_execute_per_cohort`
end-to-end (fake Supabase, assert staged ORDER): armed → [SPY, BAC]
(SPY 20×1.30=26 > BAC 25); flag-off → [BAC, SPY]; seam pin → cap=1 armed stages
the RE-RANKED winner (SPY) AND the DB query is never `.limit()`'d. **RETIRED**
the two M4 source-pin tests: `test_executor_sort_applies_bias_when_armed`
(reimplemented the sort in-test) + `test_production_call_path_is_wired`
(`inspect.getsource` string-pin) — both green while the active route bypassed
the wired method. Kept `test_new_tier_members_present` (real data assertion).

**⏳ PENDING PIN (first-live-observation — NOT shipped-proven):** the flag is
armed AND now wired, so the first REAL ordering effect lands on the next live
scan where ≥2 positive-score candidates survive to the executor — earliest
Mon 07-13 (11:00 CT scan → 11:30 executor). Given the current
1/84-clears-roundtrip reality (SPY only), a ≥2-survivor cohort is itself
uncommon — the pin may not fire for days. Verify then; do not claim proven.

docs: I6 one-liner correction applied to the v1.2 report (rides this PR).

**Latents verified this session (READ-ONLY lanes — filed backlog lines STAND):**
- **F-A10-1 CONFIRMED-but-INERT:** 999-DTE fabricate-on-missing at
  `paper_exit_evaluator.py:158` (0/83 positions carry it; `nearest_expiry`
  typed-date always populated; legs fallback always resolves) · option-only
  sync filter at `alpaca_client.py:540` (broker: 0 equity positions ever, 0
  OPASN/OPEXC/JNLS events). Neither needs more than `docs/backlog.md:149-154`.
  H9 fix (reject/flag unpriceable expiry vs `return 999`) stays correct-to-do,
  no signal demanding it.
- **F-A2-1 CLEAN:** 6 GTC orders EVER, 100% on the live-routed promoted
  champion (QQQ×3 / MARA / SOFI), 0 on any shadow cohort. ⚠ data-fidelity
  caveat filed: `paper_orders.time_in_force` typed column reads `DAY` for all 6
  (broker + `order_json->>'time_in_force'` say `gtc`) — future GTC audits query
  `order_json`/broker, NOT the typed column.

**HYGIENE MISS (self-logged):** confirmed the flag via `list_variables` (full
var dump incl. secrets into the transcript) — the 07-06 ledger already recorded
it armed; should have trusted that record. env-check-secrets-hygiene STANDS;
this MCP has no single-var read → do NOT call `list_variables` for one flag.

Queue after ③: ④ PR2 client_order_id (L1 spec ready) · ⑤ F-A3-1 part-B
close_reason (L2 spec ready) · latents F-A4-2 / F-A10-1 / F-A2-1 (filed).

## 2026-06-15 — Phase B (structural mark-validity) shipped + QQQ phantom-stop saga

- **Phase B MERGED #1067 → main `ad8ce0f`**, live both services (worker
  `2c8fca1d`, worker-background `b5c05eb1`) container start 20:55:06–07Z, CI
  green (run 27575798526). Two commits: (1) structural mark clamp
  (`risk/mark_validity.py` + exit-eval-seam wiring in
  intraday_risk_monitor + paper_exit_evaluator) — rejects |mark|>wing OR
  implied_loss>max_loss, fail-closed, NEVER suppresses a real stop; (2)
  EXIT_EVAL_DEBUG honesty (prints the cohort tp/sl/dte the decision uses, not
  `_DEFAULT_*`). +18 tests; full-suite zero Phase-B regression (31 pre-existing
  local fails == baseline). Commit 3 (resting-TP pre-cancel) DROPPED MOOT
  (broker cancel-ack 14:15:08.884Z before stop submit). Commit-2 executable-
  rewire DECLINED (false premise: decision is stateless/mid and fired
  correctly; the −80.5-vs-48.3 was the debug line interpolating
  `_DEFAULT_STOP_LOSS_PCT` 0.50 vs the cohort 0.30).
- **QQQ saga (book `6798e58f`, aggressive condor 5-wide/1.61cr/max-loss $339):**
  13:30Z monitor force-closed on a PHANTOM stop, mark −7.305 / implied
  −$569.50 (impossible). The 7.30 close order was BROKER-REJECTED → **zero
  loss booked** (luck, not a control — the new clamp is the control).
  CLOSE_REARM deferred re-close; mark recovered; QQQ genuinely rallied →
  **legit corroborated stop filled 14:15 at 2.34 / −$73** (corroboration
  14:15:07Z divergence_frac 0.089; single broker submission `1bcc6e83`).
- **Data correction (supervised, operator-GO, like prior corrections):**
  reentry_cooldowns `3d8a5820` realized_loss **−569.5 → −73.00** (1 row,
  guarded `AND realized_loss=-569.5`). The bench (QQQ → 06-16 13:30Z) was
  always correct; only the metadata carried the phantom.
- **STEP-4 audit (decision-path candidates flagged, NOT auto-fixed → backlog
  P2):** config.py DEFAULT_CONFIGS stops looser than live DB (fail-open looser
  on cohort-load failure); `exit_plan_agent.py:43,50` hardcodes 0.50 wired via
  workflow_orchestrator:3142. CLAUDE.md §5 stop references are ACCURATE (no doc
  fix). Two deferrals filed: executable-for-stops (observe-only) + cooldown
  realized_loss-from-fill (low, obviated by the clamp).
- **PENDING (do not act tonight):** 21:20Z ingest lands the −$73 QQQ close;
  expect `is_paper=true` (wrong) — the known Phase-1 A3 item, caught by the
  supervised historical correction, not a surprise. Post-epoch closes 5 → 6
  after tonight (relearn at ≥8).

## status:shipped — 2026-06-09 v4 seven-area run (PRs #1044–#1049, all live on worker 4bd5779)

- **[#1044] Pre-entry concentration BLOCK froze sequential accumulation** — share-of-book
  `concentration_symbol` check on a 1-position book = 100% > 40% → blocked ALL entries incl.
  diversifying ones. Replaced (small tier, explicit flag) by the pro-forma 85% total-utilization
  gate; concentration demoted BLOCK→WARN. (e329bf0)
- **[A1+A3+A4 → #1045] Calibration circuit frozen + strategy-asymmetric** — daily job silently
  no-opped 25 days (7 outcomes < MIN=8 in fixed 30d window); consumer served the frozen 05-15 blob
  with no TTL; apply_calibration silently defaulted ×1.0 for uncovered strategies (puts raw while
  calls halved; 2 recorded gate flips F/AAL). Fixed: window escalation 30→60→90, consumer TTL +
  calibration_stale alerts, `_overall` fallback, ops_health OUTPUT_FRESHNESS registry. (24533a8)
- **[A2 → #1046] Terminal-'cancelled' close orders permanently disarmed all exits** — BUG-C
  overcorrection; one broker-rejected/manually-cancelled close satisfied the idempotency guards
  forever; only the 'watchdog_cancelled' string accident kept retries alive. Fixed: freshness
  window (30min) + retry budget (3/4h) + critical exit_protection_disarmed alert; stale rows
  re-arm. (c63943c)
- **[A6 → #1047] Spread gate mis-keyed to account tier** — crossing the $1k micro→small cliff on
  2026-05-20 silently tightened 0.30→0.10 universe-wide (~250 would-pass kills/11d; killed the
  sub-$60 class behind 3 of 5 live fills). Fixed: dispatch = micro OR underlying <
  PRICE_CLASS_SPREAD_CUTOFF ($60). (02e1020)
- **[A7 → #1048] Stop-side cadence asymmetry** — 15-min monitor enforced cohort TPs but evaluated
  stops at the flat 0.50 default; cohort stops (0.15/0.20/0.30) checked only 2-3×/day; shadow books
  had no envelope backstop and overshot configured stops by $211.80 on 06-08. Fixed: cohort-aware
  stops at monitor cadence, fail-safe to default. (edb70d6)
- **[A5 → #1049] order_sync Step-3 unbounded reconcile** — every historical filled order + one
  pos-check round-trip per close-engine row, q5min (~52k queries/14d, #1 compute sink). Fixed:
  set-based, scoped to open positions. (4bd5779)

## status:reported — open tickets (also EXCLUDED as new findings; refining with new data is allowed only if the refinement changes the action)

- **Dismissed-status funnel gap** — `trade_suggestions.status` never reflects execution (filled
  orders reference `dismissed` suggestions; morning sweep overwrites history); the
  suggested→staged→filled funnel is uncomputable from status. Observability-only.
- **Dead instrumentation fields** — `learning_feedback_loops.entry_mid/exit_mid/
  pnl_execution_drag/pnl_alpha` populated 9/72 rows (90d), zero live readers.
- **Calibration clamp limitation** — [0.5,1.5] cannot represent a negative-realized segment
  (put ratio −3.8 floors at 0.5); calibration under-corrects catastrophic segments by design.
- **EXPECTED_JOBS coverage** — ops_health monitors 4 of ~15 scheduled jobs; nothing watches the
  scheduler/watcher itself. Partially subsumed by the OUTPUT_FRESHNESS registry (#1045) — the
  remaining work is adding entries/jobs, not a new finding.
- **PDT-P0 closure pending** — `alpaca_client.get_account()` int(None) coercions break when
  Alpaca removes the placeholder PDT fields (~2026-07-06). Ticketed P0 in docs/backlog.md.

## status:shipped — 2026-06-10 evening runbook (Phases B+C; PRs #1051 #1052, live on worker 93d19c6)

- **[v5-A1 → #1051] Honest debit-spread PoP at source** — both halves (scanner passes legs
  side→action; calculate_ev passes credit for debit) + CALIBRATION_EV_EPOCH (2026-06-11; pre-fix
  prediction/outcome pairs never calibrate the post-fix predictor) + deploy-time empty-blob reset
  (raw predictions serve until post-fix closes accumulate — calibration is in RAW MODE by design;
  a calibration_stale alert after ~06-20 is the reminder, not a defect). NFLX 06-08 fixture pinned
  both ways (0.6581→0.4840; +95.67→≈−26 SIGN FLIP); credit math pinned unchanged. (756627e)
- **[v5-A3 → #1051] Learning-store dedup + live dimension** — position-level dedup (suggestion_id
  key; order-id retained for legacy), is_paper resolved from routing (live-routed + alpaca_live →
  False) + details_json.routing/position_id; floor 04-13→04-16. Historical dup rows NOT cleaned
  (epoch excludes them from calibration; conviction legacy rollups still see them — ticketed).
- **[06-10 A1 diagnostic → #1052] Stage-quote FEED DIVERGENCE** — entry validator read Polygon-only
  while the scanner priced via the truth layer; 3/3 stage attempts on day one of #1047 died on a
  leg OPRA quoted 2.15×428/2.39×565 (83 trades). Fix: fetch_fn = truth-layer primary → Polygon
  fallback + divergence WARNING; all-sources-dark still raises EntryQuoteUnpriceable.
  Flag ENTRY_QUOTE_SOURCE_ALIGNED default-ON. (93d19c6)
- **Riders (#1051):** [UTILIZATION_GATE]/demotion/[EXIT_EVAL]-cohort lines INFO→WARNING (the 06-10
  observability miss); blocked_reason/_detail stamped on stage-time rejections (quote/cooldown/
  utilization) — closes the swept-as-stale gap. NOTE: the lying [EXIT_EVAL_DEBUG] threshold print
  itself remains TICKETED (not fixed); what shipped is the positive cohort-config WARNING line.
  The runbook's INTRADAY_COHORT_STOP polarity rider was MOOT — #1048 shipped default-ON.

### Pending verifications added 2026-06-10 evening

- ✅ VERIFIED 2026-06-11 10:00Z (M2): raw mode persisting as designed — calibration_update
  succeeded with users_updated:0, escalation tried 30/60/90d all sample_size 0 (epoch bounds
  every window; zero pre-epoch leak), last_write_age_days 0.6 (no false stale alert); latest
  blob still the 06-10 20:27Z empty reset. Consumer serves {} → 16:00Z scan scores raw.
- 2026-06-11 16:00Z: FIRST HONEST-EV CYCLE — record per-candidate ev_raw/pop_raw deltas vs prior
  days (debit EVs should drop ~2×; entries may drop to zero = CORRECT). Calibration ratio should be
  1.0 (raw mode — empty blob).
- 2026-06-11 16:30Z: if a candidate stages, watch for [ENTRY_QUOTE] FEED DIVERGENCE warnings (the
  XLE class should now price via truth layer instead of rejecting) and blocked_reason stamps on any
  rejected rows.
- Nightly-audit queue: CLOSE-side Polygon-only quote validation check (same divergence class).

### 2026-06-10 v5 FULL baseline run (all adversarially verified CONFIRMED; report `audit/reports/2026-06-10.md`)

- **[A1 2026-06-10 — CRITICAL, see ALERT-2026-06-10.md] Debit-spread PoP/EV = raw long-leg delta** —
  breakeven interpolation (ev_calculator.py:54-70) unreachable from the only production call path:
  scanner omits `legs` (options_scanner.py:3411) AND `credit=premium` is passed only for credit
  strategies (ev_calculator.py:165) → PoP falls to `abs(delta)` (:91-92). Sign-flips live entries
  (NFLX 06-08: EV +95.67 → ≈−26/ct; XLF 06-09: +55.92 → ≈+3..6/ct, below the $15 gate — passed on
  inflated PoP alone). Commit 9a2cef1 (04-12) claimed this exact fix but never wired the call site;
  test file module-skipped (#775), zero active coverage. Fix = (a)+(b) together (legs w/ side→action
  map + credit for debit), MUST sequence with reset/relearn of the floored debit calibration
  segments (06-10 blob halves both; uncoordinated fix double-corrects ≈0.24).
- **[A2 2026-06-10] Daily-loss envelope realized-blind; entry circuit breaker blind twice** — all
  FOUR check_all_envelopes feeders pass open-book unrealized only (intraday_risk_monitor.py:221,
  paper_autopilot_service.py:228, paper_mark_to_market.py:103, workflow_orchestrator.py:2834 passes
  neither), violating the risk_envelope.py:573 contract: realized stops vanish from the 8% daily
  brake (06-08 −$84 = 47.3% of budget invisible to ~22 subsequent cycles); sequential stops can
  never trip it (4×−3% = −12%/$266.50 with no brake); CB omits weekly_pnl (:256-261 → 0.0 default)
  and skips ALL envelope checks on an empty book (:227). Fix: broker-true daily (equity−last_equity,
  mirroring weekly; never fabricate) + feed all four sites + wire weekly into CB + empty-book
  aggregates (companion to the daily fix).
- **[A3 2026-06-10] Learning store double/triple-counts and can't tell live from simulator** —
  dedup keyed on closing-order id with position-level pnl (paper_learning_ingest.py:224-232,:339):
  ADBE f6eee0e9 ×2 / AMD 91d4e119 ×2 = 76.5% of training dollars; NFLX whipsaw thesis ×3 (live
  −$42/ct broker fill vs −$91/ct simulator forks); is_paper hardcoded True (:375,:394; live ingest a
  no-op stub); calibration unscoped to cohorts (calibration_service.py:258-267). The 06-10 10:00Z
  post-#1045 write trained on exactly this set (60d, N=18 claiming −$4,281.50 vs 12 deduped
  real-broker outcomes −$2,017); the frozen 05-15 blob was ALSO duplicate-trained (LONG_CALL n=10
  incl. 2 AMD dups). Fix: position-level dedup, CALIBRATION_PNL_FLOOR_DATE→2026-04-16, live/shadow
  dimension at ingest (position_scope pattern). Runner-up: pop denominator asymmetry (:299-315) +
  dead DTE segmentation (every blob ever = {_all, unknown}).
- **[A4 2026-06-10] Ops-health alert delivery 0% lifetime** — all 5 detection classes route only to
  send_ops_alert_v2 (ops_health_check.py:111-274; zero risk_alerts writes); OPS_ALERT_WEBHOOK_URL
  unset on worker AND BE → suppressed no_webhook inside status=succeeded (916 runs / 869 unhealthy /
  0 alerts EVER since 2026-01-22); severity map lacks "critical" (→0 < warning,
  ops_health_service.py:942-946) so even a webhook wouldn't deliver job_never_run; the #1045
  OUTPUT_FRESHNESS watcher inherits the dead tail. Fix: dual-channel to risk_alerts (error/critical,
  existing alert() helper + fingerprint cooldown) AFTER fixing the chronic data_stale false positive
  (30-min threshold vs once-daily jobs) and the severity map. Runner-up: scheduler_heartbeat written
  but absent from EXPECTED_JOBS — scheduler death undetectable.
- **[A5 2026-06-10] Hot-queue head-of-line blocking puts the loss monitor last in line** — monitor +
  order_sync share the serial otc worker with unbudgeted suggestions_open (no internal time budget;
  10-min RQ ceiling; options_scanner has zero deadline constructs). 06-03: 422.7s scan (70% of
  ceiling, provider latency — same workload 14.9s on 06-08) → order_sync waited 417.1s, monitor
  129.0s; daily 16:00Z grid collision dequeues the monitor LAST (25-55s, live capital open 06-09).
  Fix: route monitor+order_sync to a dedicated queue on the idle worker-background ("rq worker risk
  background") gated on read-back + monitor-cadence freshness alert (mis-route = silently disabled
  loss protection); + ~120s scan budget with loud exit_reason.
- **[A6 2026-06-10] Entry-budget stack book-blind: open positions contribute $0** — RBE
  (risk_budget_engine.py:54-57,156-208) and PortfolioAllocator._sum_open_cost_basis
  (portfolio_allocator.py:116-144) read fields absent from the 32-col paper_positions schema →
  usage:0 in 4/4 cycles since 06-08 on a non-empty book; remaining overstated 2.16× (06-08) / 1.41×
  (06-09) RBE-side; the documented 85%-less-cost-basis deduction is a no-op; the :2340 exhausted
  guard cannot fire from usage accumulation; underlying_allocation has ZERO consumers though
  utilization_gate.py:46 cites it as retained; the workflow_orchestrator.py:2179-2186 comment claims
  "under-counts slightly" + a nonexistent "backlog #80". Fix: shared paper-aware position-cost
  adapter (avg_entry_price×100×qty debit; H9 fail-loud) + ONE cap-semantics policy (40% vs 85% vs
  RISK_MAX_UTILIZATION_PCT) + wire-or-delete underlying_allocation. Runner-up: counts.universe_size
  = scanner_emitted (3 conflation sites) — universe regressions invisible in the funnel;
  rank_and_select greedy BREAK (small_account_compounder.py:280-286).
- **[A7 2026-06-10] Time-scaled profit capture unreachable in production** —
  _time_scaled_target_profit_pct's sole caller is the cohort-resolve-FAILURE fallback
  (paper_exit_evaluator.py:397); both production exit paths use flat cohort tp via
  build_exit_conditions (:421-423); the champion lookup resolves any position → ~100% of production
  positions live on the flat bar (aggressive +50% for life, incl. the max-theta window where the
  documented curve drops to ~0.245); CLAUDE.md Exit-thresholds asserts the opposite; the curve has
  zero test references (flat IS pinned). BAC 06-04 fire (+18.8% of $1,020 4ct entry) explainable
  only by the flat bar. Realized cost $0 so far (no winner aged into divergence). Fix: doc truth-fix
  + optional flag-gated min(tp, time_scaled) wiring, shadow-first, capture-earlier-only. Runner-up:
  no time-stop for stalled theses (dte_threshold only at 7 DTE, scheduled path only);
  paper_eod_snapshots accrues phantom post-close rows during manual-close reconciliation lag.
- **[A8 2026-06-10] Negative decisions 100% outcome-unmeasured (counterfactual lens adopted →
  audit/area8.md)** — ~2,384 rejects/blocks/dismissals per 30d vs 6 learned closes (~400:1);
  calibration trains only on gate-survivors (calibration_service.py:258-259); d8_v1 rejection
  capture lacks expiry → 0% of 2,361 reject rows repriceable (options_scanner.py:295-305); executor
  risk blocks stamp nothing (paper_autopilot_service.py:269-275; 06-09 XLF blocked_reason null);
  policy_decisions captured 1 rejected outcome/30d; gate-bug detection latency historically 11-25d,
  code-audit-only. 06-09 blocked XLF hand-repriced +$32..$66 in <1 day (point-in-time; +$24..$42 at
  re-read) vs held book ≈−$30. Fix (additive only): expiry in d8_v1 capture + nightly read-only
  counterfactual marker on the 100%-repriceable dismissed/blocked suggestions + per-gate
  reject-vs-accept metric with info alert at ≥3 consecutive inverted windows (never auto-loosen).

## status:reported — 2026-06-11 NIGHTLY run (report `audit/reports/2026-06-11.md`)

- **[N1 2026-06-11] CLOSE/internal-fill quote reads still Polygon-only (#1052 divergence class, close
  side)** — outcome of the ledger-queued nightly check. Stage-time combo quote (`paper_endpoints.py:645`,
  feeds TCM staging values for ALL orders incl. closes) and the internal fill engine's fresh-quote read
  (`:1179`, prices every internal/shadow fill) remain legacy `_fetch_quote_with_retry`; #1052's
  `_aligned_leg_quote_fetch` is wired ONLY into `_validate_entry_quotes`. A Polygon-dark-but-OPRA-real
  leg (the 06-10 XLE class) on a shadow CLOSE → TCM missing_quote_fallback fill at a stale
  staging-derived price (`:1219-1230`) or a stalled close — biases shadow learning outcomes/D6.
  LIVE path insulated (monitor marks = MarketDataTruthLayer `intraday_risk_monitor.py:462-487`; live
  fills = broker). Impact prospective (zero close orders since); severity LOW-MEDIUM. Fix: reuse the
  aligned fetch at both sites, observe-first.
- **[N2 2026-06-11] Stage-time skip stamping gap (refinement of the dismissed-status gap + #1051
  rider — changes the action)** — per-cohort symbol-dedup (`paper_autopilot_service.py:746-770`) and
  user-level dedup/min-edge/min-score filters (`:390-427`) skip with `continue` at logger.INFO and
  never call `_stamp_blocked_reason` (stamps cover only cooldown/utilization/quote, `:850-894`) —
  suggestions stay pending/NULL and get swept. Observed: both 06-10 16:30Z NFLX forks (aggressive
  `ff1f65b7…`, neutral `2c1d7f79…`) unprocessed + unstamped; dedup is the high-probability cause
  (both cohort books hold NFLX) — per-event attribution HYPOTHESIS (INFO line unretrievable),
  stamping gap itself code-certain. Severity LOW, observability-only. Fix: stamp
  `symbol_already_held` / `edge_below_minimum_at_stage` / `below_min_score` at the three skip sites.

## status:shipped — 2026-06-11 incident arc + post-close gate (PRs #1055 #1056 #1057 merged; #1058 #1059 at CI)

- **[06-11 incident → #1055] Credit-OPEN mleg sign** — first CHOP condors submitted +1.54/+1.43,
  live gateway instant-rejected in 4ms (the #101 close class, open side). Stamp `is_credit_open`
  from `_net_mid_cost` + handler flip + coherence guard. Merged mid-day by operator;
  LIVE-VALIDATED same session: QQQ filled −1.61 (limit −1.54, +$7 improvement), SPY −1.48
  (−1.43, +$5), third condor accepted+rested at −1.28; 12/12 legs priced by the #1052 truth
  layer (Polygon dark on ALL of them).
- **[06-11 incident → #1056] Fill-commit raw signed entry** — `_commit_fill`/`_repair` stored
  Alpaca's SIGNED filled_avg_price into avg_entry_price/max_credit (violating mark_math's
  absolute contract) → phantom −$300 unrealized on a +$10.50 position → 16:30Z phantom −22.8%
  daily breach force-closed the ENTIRE live book ($0 realized only because the close limits were
  mis-signed too). `_abs_entry_premium`/`_weighted_abs_entry_avg` at all six write seams +
  round-trip regression on the day's actual numbers.
- **[06-11 incident → #1056] Close-path signed limit** — short-structure closes staged the
  SIGNED mark as the limit (−1.39 buy-to-close): gateway reject + an unfillable RESTING close
  that satisfied idempotency and DISARMED exit protection. `_close_limit_and_direction`
  (unsigned magnitude; structural direction; loud disagreement) + handler inverse guard. Also
  fixes the internal-fill realized-P&L sign — the 19:00Z shadow stop close recorded +$2,369.22
  on a −$234.78 trade (the signed limit double-negated through the synthetic close leg).
- **[06-11 V4 gate trail → #1057] Utilization gate signed netting** — `committed=$56` while the
  broker held $1,365 (condor credits netted against the NFLX debit). Per-structure commitment:
  net-debit = net cost basis; net-credit = margin basis (max wing width × 100 × qty, matches
  Alpaca's $1,000 hold); naked/unboundable → fail-closed.
- **[06-11 trace — fix 06-12] Live close double-submission** — `_stage_order_internal`
  broker-submits alpaca-mode orders itself AND `_close_position` submits the same row again;
  the second call's pre-cancel kills the first broker order (2 broker orders per close, first
  canceled ~0.45s in). Never seen before: no live system close had ever executed. Writeup
  `docs/double_submit_close_trace.md`; single-submitter staging param + regression queued 06-12.
- **[v5-A2 → #1058] Realized-blind daily brake** — min(open-book proxy, broker
  equity−last_equity) into all four feeders + weekly into the circuit breaker + empty-book
  de-gates (breaker + MTM). Same-day empirical: real −8.3% day (equity 2075.42 vs 2263.85) read
  as ≈−4% by the proxy. Tightens-only.
- **[v5-A4 → #1059] Ops alert delivery** — dual-channel: risk_alerts PRIMARY (critical→critical,
  error→high) + webhook secondary; severity map gains "critical" (was 0 → the most severe class
  always suppressed); data_stale ALERT market-hours-gated (nightly staleness is structural);
  canonical alert() accepts "high" (was silently downgrading); synthetic_delivery_test payload
  hook for the end-to-end proof.

### Data corrections (2026-06-11, operator-"go" precedent; all documented in-session)

- Live QQQ `6798e58f` / SPY `a5393e2b`: avg_entry_price/max_credit ABS-corrected (−1.61/−1.48 →
  +1.61/+1.48). Applied ~90s after the 16:30Z monitor had already fired on the phantom.
- Shadow QQQ `85db73c8`: realized_pl +2369.22 → **−234.78** (arithmetic truth: credit 1.5246×7
  entry, 1.86 buy-back) BEFORE the 21:20Z learning ingest (learning_ingested was false — zero
  contamination); neutral-cohort cash_balance −$2,604 (the close's fill event credited +1302
  instead of debiting 1302).

### 2026-06-13 combined run (week-review + 8-area audit + CLAUDE.md refresh)

WEEK VERDICT (06-08→06-13): live realized **−$109** (a9f977bf NFLX −84,
7f604f7a NFLX +48, a5393e2b SPY −45, bc399a4f MARA −28), live open = QQQ
condor 6798e58f broker-unrealized **−$45**; shadow realized −$920 (mark-bias
caveat). Fees negligible (TAF pending $0.57). Modeled-vs-realized EV gap:
every staged EV positive (+26…+96), aggregate realized deeply negative;
post-epoch clean read ≈ −$67/trade optimism (raw-mode, uncalibrated —
expected, relearn ~06-20). Live MARA round-trip (18:25→18:46Z) confirms the
N1/UnboundLocalError fix unblocked the 16:00Z funnel.

SETTLED THIS RUN — do not re-find (folded to docs/backlog.md, origin 06-13):
- A1: post-#1051 EV ordering weakly agrees (2 winners carried the highest
  staged EV); uniform +EV optimism is raw-mode, not a defect. No action.
- A2/A4: ghost_position sweep flags shadows (no live-routed filter,
  `alpaca_order_sync.py:245`) → 73 shadow-noise alerts/wk burying real
  desync. → P2.
- A3: calibration healthy in raw mode (job ran 06-11/06-12 `insufficient_data`,
  last real write 06-10; 5/8 post-epoch closes). is_paper tags ALL learning
  rows paper incl. live closes → P2.
- A4: OUTPUT_FRESHNESS watches ONE table (`ops_health_service.py:79`);
  ingest/mark-refresh stalls silent. → P2.
- A5: this run respected budgets (≤10 Part-1 SQL, ≤4 broker, 0 web, archived
  the 240k backlog unread). Largest avoidable cost would have been reading
  it — avoided.
- A6: stage deaths dominated by REAL spread_too_wide_real (323) /
  no_fallback (359), not feed artifacts; #1052 working. chain_mechanics
  anomaly 24×/wk = legacy spread_pct deep-ITM edge (observability noise) →
  P2.
- A7: hold-time bimodal — debit spreads ~94–116h, condors 5–35h, live MARA
  0.3h (cohort-stop velocity). Next binding velocity constraint = the
  one-shot/day executor (P1), not fees/cooldowns.
- A8: XLE dead-leg rejects (#1038, settled 06-10) are UNMARKABLE on the
  executable side — counterfactual indeterminate by doctrine; GLD reject was
  an HONEST save (spread_debug total_ev −934). Additive proxy field →
  RESEARCH.
- TOP-3: (1) OUTPUT_FRESHNESS expansion, (2) ghost-sweep shadow scoping,
  (3) close-side quote check. No conflicts; (1)+(2) share the order-sync/ops
  surface.

PENDING VERIFICATIONS (06-13 night / next session):
- CLAUDE.md refresh PR merges per the W2 gate (CI green on the doc PR; main's
  last gate was clean at #1064 23:49Z). After merge: H8-verify both workers
  recycled to the new SHA; the DEGRADED + raw-mode-reset lines fire once on
  the new container (designed, not an incident).
- backlog.md reorg: full pre-0613 history preserved in
  docs/backlog_archive_2026-06-13.md (move-don't-lose).

## status:reported — 2026-06-15 NIGHTLY run (report `audit/reports/2026-06-15.md`)

**NO NEW FINDINGS.** Quiet weekend (markets closed 06-13/06-14); window 06-13
run → 06-15 05:03Z. Clean operation: both workers on `5778760`/#1065
(CLAUDE.md refresh, dual-parity deploy 06-13 03:15:47Z — the 06-13-pending
merge landed); weekend job silence (only `paper_exit_evaluate` 06-13 00:28Z
[placed the resting TP] + `phase2_precheck` 06-15 05:00Z, 0 failures, 0 stuck
rows); **H11 risk_alerts critical/high since 06-13 = ZERO**; broker healthy
(equity $2,179.15, OBP $1,804.15, one live QQQ 07-10 condor −$45 with resting
TP `550fccc5` GTC 0.81 alive/untouched). Flags clean, no regressions.

- **OVERTURNED CANDIDATE (verify-before-asserting):** SPY `manual_bench` cooldown
  (06-12 15:46Z, correctly valued −45, until 06-15 13:30Z) looked like a
  cohort-stops-don't-auto-cooldown gap → **already fixed in deployed code**:
  `intraday_risk_monitor.py:355` → `_write_cohort_stop_cooldown` (`:757-772`,
  `reason="cohort_stop_force_close"`), shipped #1062. The manual bench predated
  the fix (event on worker 5681919). Not a finding.

VERIFICATIONS CLOSED THIS RUN (do not re-find):
- ✅ **PR #908 live credit-mleg-close** — SPY iron condor close `1f444239`
  (06-12 15:30:07Z): buy-to-close at POSITIVE limit 1.96, filled POSITIVE 1.93,
  single order, instant clean fill, no Sign-incoherent raise → realized −45.
  Credit structure closed correctly. **Pending since the first ledger list — DONE.**
- ✅ **Double-submit pre-fix confirmed** — QQQ condor close attempts `fc1625f1`
  (06-12 13:30:07Z submit→cancel 0.6s) + `0675f969` (13:30:08Z, watchdog-cancel
  13:35Z) = documented pre-cancel double-submit on worker 5681919 (#1064
  single-submitter deployed 06-13 00:20Z, after). SPY/NFLX/MARA = single orders
  (instant fills). Single-submitter fix deployed but UNEXERCISED on a resting close.
- ✅ **#1034 TP fires write price-normalized corroboration rows** —
  `exit_mark_corroboration_observations`: NFLX TP 06-12 15:15Z (4.7355/+314.70 →
  4.131/**+133.35**, divergence_frac 0.086, `corroborated_allow`); SPY stop 15:30Z
  (`stop_loss_never_suppress`); QQQ TP 13:30Z.
- ✅ **Corrected-NFLX ingest** — `1e2dd73f` realized_pl=133.35; outcomes_v3 LPD pair
  sums +181.35 = 133.35 + 48.00. The +314.70 fiction did not propagate.
- ✅ **#1056 write-side** — DB QQQ condor `avg_entry_price=1.61` (positive); coherent.

PENDING VERIFICATIONS (carried — all fire on today's 06-15 RTH, the first
session on #1062+/#1065 code after the weekend):
- **#1034 corrected normalization + Stage-2 enforce, FIRST FIRE.** Every
  corroboration row in-window is PRE-fix (worker 5681919); the QQQ 13:30Z phantom
  (mark −0.65/+96 vs achievable −7.6/**−599**) scored divergence_frac **0.0604**
  `would_suppress=false` — the exact value CLAUDE.md says the 06-12 fix re-scores
  to ~0.91. `EXIT_MARK_SANITY_ENFORCE_ENABLED=1` deployed but never observed on a
  live fire. A phantom TP today should re-score ~0.91 → SUPPRESS (stops never).
- **Cohort-stop auto-cooldown FIRST FIRE** (`_write_cohort_stop_cooldown`, #1062) —
  on the next cohort-stop force-close; should write `reason=cohort_stop_force_close`
  (no manual bench needed).
- **Resting-TP exit-evaluator deferral** (`skipped_resting_tp_owns_profit_side`) —
  first QQQ-condor monitor tick today (resting TP placed post-close 06-13, no RTH
  monitor since).
- **#1058 `[EQUITY_STATE] realized-blind gap`** — 06-12 RTH logs aged out of Railway
  retention; re-check on today's session.
- **#1065 DEGRADED + raw-mode-reset lines** — fire once on the first CONVICTION read
  = first scan (16:00Z); no scan since the recycle.
- **#1059 synthetic-proof wiring** still unmerged (`9c957d9`); webhook still deferred.

### Data corrections (2026-06-12 night, operator-ordered; same precedent as 06-11)

- Shadow NFLX ×3 `1e2dd73f` (conservative): realized_pl **+314.70 → +133.35** at 18:00:58Z,
  BEFORE the 21:20Z learning ingest (learning_ingested was false — zero contamination).
  Basis: its OWN 15:15:04Z corroboration row — triggering mid 4.7355 vs achievable 4.131
  (P86 sell at bid 6.14 − P79 buy at ask 2.009) → (4.131 − 3.6865) × 300 = 133.35. The
  $181.35 delta was the optimistic-mid fiction; the code-side fix (internal fills at the
  EXECUTABLE side + fill_quality flag) ships tonight so this is the LAST manual instance
  of the class. Guarded UPDATE (realized_pl=314.70 AND learning_ingested=false) — idempotent
  against any concurrent session. paper_orders row 4d175584 left as-is (historical record of
  what the old fill simulation did; order_json carries no fill_quality — pre-fix row).

### Pending verifications added 2026-06-12 night

- Post-21:20Z TONIGHT: learning ingest consumed realized_pl **133.35** (not 314.70) for
  `1e2dd73f` — verify learning_trade_outcomes_v3 / learning_feedback_loops row.
- Morning signatures (06-13): (a) any TP fire writes a corroboration row with the
  price-normalized divergence; phantom → `exit_tp_suppressed_phantom_mark` alert + NO close
  staged (Stage-2 live). (b) exactly ONE broker submission per close (single-submitter,
  745ced4). (c) `[EQUITY_STATE]` successful broker daily fetch on the first monitor cycle —
  no "broker daily P&L unavailable" line (d68029c). (d) any internal/shadow fill carries
  order_json.fill_quality + the `[INTERNAL_FILL]` WARNING line. (e) the QQQ resting TP
  (buy-to-close GTC, limit 0.81) alive at the broker, untouched by the watchdog, visible to
  the evaluator as `skipped_resting_tp_owns_profit_side` if its TP condition trips.
- 15:30:08Z `paper_order_marked_needs_manual_review` alert: RESOLVED BENIGN — it was the
  second submission against the already-filled SPY close (intent-mismatch reject, the
  double-submit class); 745ced4's terminal-reject classification returns these gracefully
  without the manual-review mark. No operator action on the order itself (SPY close filled
  clean at 1.93, realized −45).

### Pending verifications added 2026-06-11 night

- 06-12 first credit fill row: avg_entry_price/max_credit POSITIVE (the #1056 write-side proof).
- 06-12 closes: positive limit on credit-position closes, no `Sign-incoherent` raise; the
  double-submission pattern persists (documented) until the 06-12 single-submitter fix.
- #1058 signature: `[EQUITY_STATE] realized-blind gap` WARNING whenever broker day < proxy.
- #1059 signature: `ops_*` rows appearing in risk_alerts (first ops delivery ever); synthetic
  proof row written + deleted post-deploy.
- ✅ #1048 VERIFIED 2026-06-11 19:00Z — first real cohort-stop fire: shadow QQQ 7-lot breached
  the neutral stop (−$235 vs −$213 threshold) and closed intraday at monitor cadence (the
  realized-P&L sign corruption it exposed is the #1056 internal-fill item above).
- ~~Railway auto-deploy MISSED bcbfb0c~~ **ERRATUM (06-12): it self-deployed ~10 min after
  merge** (SUCCESS 20:18:46Z) — the hook lags up to ~10 min after rapid merges and the
  listing API lags further; no forced recycle was required (the marker-var attempts errored
  client-side but one landed harmlessly, same SHA). The durable lesson stands: H8-verify the
  worker SHA before trusting behavior to a merge — but don't declare a deploy missing inside
  the lag window.

## Pending verifications (not findings — check, then update here)

- ✅ VERIFIED 2026-06-10 10:00Z: first calibration write post-#1045. job_runs verbatim:
  `users_updated:1, users_skipped:0, user_details: attempts [{30d insufficient_data n=7},
  {60d ok n=18}], window_used:60` — the escalation worked exactly as designed on the first
  run, ending 26 days of silent no-ops. Fresh calibration_adjustments row 10:00:03Z
  (total_outcomes 18) with top-level keys `LONG_PUT_DEBIT_SPREAD` (first time ever:
  normal/_all ev_mult=0.5 pop_mult=0.5 [clamp floor], n=5, ev_calibration_error +$450.90,
  pop_calibration_error +0.6234), `LONG_CALL_DEBIT_SPREAD`, and `_overall` (n=18,
  ev_mult=0.5, error +$453.71). Today's 16:00Z scan is the first to score puts calibrated.
- ✅ VERIFIED 2026-06-10 16:00:34Z: `[CONVICTION]` honesty line fired EXACTLY ONCE on the first
  conviction read (entry ranker): "V3 performance-summary source unavailable (PGRST205 …
  learning_performance_summary_v3 …) — falling back to legacy … DEGRADED". Silent swallow dead.
- ✅ VERIFIED (behaviorally) 2026-06-10 16:30Z: #1044 — same 100%-NFLX one-position book that
  produced `risk_envelope_breach` on 06-09 now PROCEEDS through the breaker (result
  status=partial, per-suggestion processing reached). ⚠️ OBSERVABILITY MISS: all
  [UTILIZATION_GATE] lines (flag echo, demotion, per-evaluation numbers) are logger.INFO and
  the worker surfaces only WARNING+/print — invisible in Railway logs. Follow-up: bump those
  lines to WARNING (or set worker log level) so "log every evaluation" is actually observable.
- ✅ VERIFIED 2026-06-10: #1047 — sub-$60 rejections carry nested `spread_debug.spread_debug.
  threshold: 0.3` (CMCSA 0.3985 vs 0.30, CSX); scanner_emitted 14 (prior 1-12); FIRST 2-candidate
  staged day (XLE + NFLX). #1045 application live: puts calibrated for the first time (NFLX
  ev_raw 89.6→44.8 pop 0.321; XLE 84.1→42.0 pop 0.296) — asymmetry gone.
- ✅ BONUS-VERIFIED 2026-06-10 16:30Z: #1038 first LIVE rejections — all 3 XLE cohort forks
  raised `entry_quote_unpriceable: leg=O:XLE260717C00058000 quote={bid:0, ask:0}` (error, not
  executed). The fabricated-fill class is dead on a real dead leg.
- ✅ VERIFIED 2026-06-10: #1049 — alpaca_order_sync avg 1.38s today vs 6.46s prior (−79%).
- ⏳ #1048 exercised-no-trigger: cohort conditions loaded without failure warnings all day; no
  position crossed a cohort stop (book in profit) — first behavioral confirmation pends a breach.
- ✅ SPCX monitor first run 16:45:01Z: scanned_today=true, quote/chain false (pre-listing,
  correct), rejection_reasons [insufficient_history, no_fallback_strategies_available] — the
  loud zero-history skip on record; no scan poisoning.
- Next system close: PR #908 live credit-mleg-close validation.

## status:reported — 2026-06-30 NIGHTLY run (report `audit/reports/2026-06-30.md`)

Window 06-15 → 06-30 (15-day gap; parked week 06-18→06-29 = zero trades; resume-armed tonight).
Infra movement: PRs #1094–#1098 merged + `PAPER_AUTOPILOT_ENABLED` 0→1 (first live-autopilot arm).
Both workers SUCCESS @ `f7dab1d`. Book FLAT (live + shadow). H11 zero critical.

- **[A4 2026-06-30 — FINDING] Learning-ingest silent in-result-error masking (P2→P1; refines the
  ledgered "OUTPUT_FRESHNESS watches ONE table").** `paper_learning_ingest` ran 5×/7d all
  `status=succeeded` while every run 06-23→06-29 carried `result.counts.errors=1,
  outcomes_created=0` (the `opened_at` 42703, fixed by #1098 tonight). EXPECTED_JOBS checks job
  STATUS; OUTPUT_FRESHNESS watches `calibration_adjustments` ONLY → a 6-day silent learning-loop
  death went unalerted. Parked week masked the P&L cost (zero closes); under live autopilot a
  recurrence silently starves calibration + loses real outcomes. FIX (additive, no infra): alert on
  `job_runs.result.counts.errors>0` (status-succeeded included) OR add `learning_feedback_loops` to
  the freshness registry → detection 6d→0d. RISK zero. CONFIDENCE high.
- A1/A6/A7 UNCHANGED (no new fills since 06-17). A2 — 4c fail-open CLOSED (#1094 live); multi-position
  / loss-precedence now live-relevant but backlog-P2 (don't fix ad hoc). A3 — relearn 5/8 post-epoch
  live, raw by #1076 design; ingest break lost ZERO outcomes (flat book that window); path-to-8 now
  depends on autopilot volume. A5 — this loop's only waste: `get_orders` 109k overflow (use
  symbols-filter/subagent next time); else within budget.
- **Four-source disagreement:** −84 NFLX 06-08 LIVE close → paper_positions cohort `3d289dca` (live)
  vs v3 `is_paper=true` (paper); ledgered is_paper P2, pre-epoch so relearn-count-safe but understates
  v3 live realized (−113 vs true −197). Reported not averaged.
- **A8:** lens KEPT (Negative-Decision Efficacy; no data-backed replacement tonight). Named next-run
  replacement **Entry-Fill Efficacy** (staged-live-order watchdog-cancel blind spot, 06-03 NFLX
  precedent) — adopt once autopilot generates staged-live data. See area8.md.

PENDING VERIFICATIONS (next session — first live-autopilot session):
- First 11:30 CT executor cycle on `PAPER_AUTOPILOT_ENABLED=1`: did it stage/fill or pass the EV gate?
- First post-fix `paper_learning_ingest` run (~21:20Z): `outcomes_created>0` on a close, `errors=0`,
  A4 cols (entry_iv_rv_spread/realized_vol_over_hold) populate.
- Entry-Fill Efficacy baseline: of any staged live order, fill vs watchdog-cancel + price vs limit.

## status:shipped — 2026-06-30 post-close runbook · Phase 1 (PR #1100 → main `8faf133`, both workers H8'd)

- **[Phase 1] alert-write resilience + A4 silent-failure detector** (squash `8faf133`; worker +
  worker-background SUCCESS @ 8faf133 21:55Z). (1a/1b) `observability/alerts.py` risk_alerts insert
  wrapped in retry-with-backoff (0.25/0.5s) on TRANSIENT stale-keepalive disconnects ONLY
  (`RemoteProtocolError`/"Server disconnected"); existing `alert_write_failed` log kept as the FINAL
  fallback; distinct `alert_lost_after_retries` marker when a transient exhausts retries. Right-sized
  retry, NOT a durable queue (signature = idle-keepalive drop). (1c) `ops_health_service.
  get_silent_job_failures` + `ops_health_check §3.5` fire a NEW `job_succeeded_with_errors` (high) via
  canonical `alert()` on any `status=succeeded` job with `result.counts.errors>0` (the masking class
  that hid the 6-day `opened_at` ingest death), fingerprint+cooldown, added to `_RISK_EGRESS_ALERT_TYPES`;
  `learning_feedback_loops` already in OUTPUT_FRESHNESS. Detection 6d→0d. 14 new tests + 27+5 regression
  green; ADDITIVE (ingest/executor/exit/monitor untouched). **SYNTHETIC PROOF PASSED:** inserted a
  `succeeded`/`errors=1` job_runs row → dispatched `ops_health_check` → `job_succeeded_with_errors`
  risk_alert fired end-to-end (run_id matched, 22:01:00Z) → both synthetic rows deleted.
  **Operator flag:** `OPS_ALERT_WEBHOOK_URL` unset → a fully-dropped insert reaches NO external
  destination; `alert_lost_after_retries` is the only in-process visibility. Closes the ledgered
  OUTPUT_FRESHNESS / N2-alert-delivery silent-failure gap (the WRITE side; the read-side egress poller
  remains deferred).

- **[Phase 2] entry executable round-trip cost gate** (PR #1101, squash `0ea6583`; worker +
  worker-background SUCCESS @ 0ea6583 22:35Z). Fixes the SOFI 06-30 own-goal class: admitted on EV
  +$30.63 but ~$135 of executable bid/ask cross made it underwater-on-executable from entry →
  force-closed at a 100%-spread-cost loss; the scanner's 5%-of-EV slippage PROXY
  (`canonical_ranker._estimate_slippage`) waved it through. NEW `exit_mark_corroboration.
  executable_roundtrip_cost` (PURE; reuses `compute_corroboration`'s executable basis long→bid/short→ask
  — UNIFIED with the exit, zero refetch; Σ per-leg (ask−bid)×contracts×100). NEW
  `paper_endpoints._apply_entry_roundtrip_gate` in `_stage_order_internal` (after #1038's validated
  `_entry_leg_quotes`, before TCM/insert/submit): `honest_ev_after_cost = ticket.EV − round_trip`,
  REJECT < `MIN_EDGE_AFTER_COSTS` ($15). OPEN-only (closes exempt), skips no-EV (shadow), allows on
  incomplete executable quote (#1038 owns dark legs), WARNING-logs every eval, stamps
  `blocked_reason='ev_below_roundtrip_cost'` (fail-soft), raises `EntryRoundtripCostExceedsEV`
  (#1038-shaped; autopilot counts not-executed). Flag `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` default-ON
  (explicit falsy → legacy). 12 tests (incl. SOFI→REJECT, anti-over-reject PASS, UNIFICATION entry==exit
  basis, flag both ways) + 50+87 regression. ADDITIVE — executor/exit/monitor-force-close/ingest
  untouched (exit_mark_corroboration change = new sibling helper + import only). Resolves the SOFI
  own-goal at the ENTRY (NOT by loosening the stop). Verify on tomorrow's first scan.

- **[Phase 3 — status:DEFERRED 2026-06-30, GATED] Exit-trigger basis calibration (full-cross
  over-pessimism).** The −3% per-symbol envelope force-closes on the FULL-CROSS executable estimate
  (`exit_mark_corroboration.executable_close_estimate`/`compute_corroboration._executable_for`,
  long→bid/short→ask; SOFI `c99d8af2` 06-30: −$65 estimate vs −$40 achievable fill, INSIDE the −$62
  envelope). **WHY DEFERRED:** Phase 2 (#1101) closes the dominant class at ENTRY (SOFI can't be admitted
  now); the residual (a position admitted with tolerable round-trip whose quote later transiently
  widens/one-sides enough to trip the full-cross envelope while the achievable close is still in
  tolerance) is RARE with **N=1 data** — a tuned `k≈0.23` from one fill, on the one stop direction where
  a mistake MASKS real loss, is over-fit. **REOPEN:** ≥10–15 real close fills accumulated (via the
  precursor instrumentation, shipped below) → build on the fill-improvement DISTRIBUTION, not a hand-picked
  constant. **DESIGN (carry forward):** TWO-QUOTE CONFIRMATION — require BOTH the full-cross decision basis
  AND the achievable marketable-limit to breach before force-closing; floored at cross; ≤ mid; gated on
  `quote_complete`/non-wide; NO tuned constant. Survival fixtures: SOFI replays to ~−$40 (SURVIVES,
  −40 > −62) AND a −$200 directional loss STILL fires. **⚠ UNIFICATION TRAP (recon pt 4):** Phase 2's
  `executable_roundtrip_cost` recomputes (ask−bid) directly at `exit_mark_corroboration.py:408` while the
  exit reads `achievable_close` from `_executable_for:191-199` — a Phase 3 that changes ONLY the exit
  primitive makes ENTRY and EXIT diverge, re-creating the entry-admits-what-exit-kills bug this arc fixed.
  Phase 3 moves BOTH seams onto ONE per-leg executable price or it does not ship.

- **[Phase-3 PRECURSOR — SHIPPED 2026-06-30] Close-fill gap instrumentation.** PR #1102 → main `b3479a8`
  (off `0ea6583`). ADDITIVE / observe-only — makes the deferred Phase-3 decision data-driven instead of N=1.
  On EVERY close (force-close AND normal) emits `[CLOSE_FILL_GAP] symbol=… position_id=… cross=<full-cross
  executable estimate> mid=<trigger mark> fill=<marketable-limit fill> gap_fraction=(fill−cross)/(mid−cross)
  reason=…`; the quad is also persisted into the EXISTING close `order_json` JSONB (no migration → SQL-queryable
  for the REOPEN gate beyond short Railway log retention). New pure helper `services/close_fill_gap.py`; cross/mid
  threaded stage→fill via `order_json` (stamped in `paper_exit_evaluator._close_position` post-submit, read back
  at `alpaca_order_handler._close_position_on_fill` LIVE reconcile + the internal/shadow fill). Degenerate
  (mid==cross)→gap None; missing stamp→fill-only NA; every block best-effort try/except — NEVER affects a close.
  NO close-decision / envelope / trigger-basis / force-close / sizing change; no flag. 16 unit + 41 touched-path
  regression tests green (SOFI 06-30 fixture → 0.2326 ≈ 0.23). H8 ✅ both workers SUCCESS @ b3479a8
  (start 23:30Z, prior 0ea6583 REMOVED). First `[CLOSE_FILL_GAP]` line lands on the next live or shadow close.

## status:reported — 2026-07-01 NIGHTLY run (manual; report `audit/reports/2026-07-01.md`)

First session after the live-autopilot arc; verification-first. Both workers @ `b3479a8` all
day (no recycle). Broker flat, equity 2,093.74 (Δ −41.06 = SOFI −40 + fees). H11: 1 critical
= the shadow force-close below (functioning control, not an incident).

- **[A5 2026-07-01 — FINDING] Scanner persist seam unprotected against the stale-keepalive
  disconnect burst (now a 2-day pattern).** 16:00:09Z: 8× "Server disconnected" on
  suggestion_rejections inserts inside the scheduled scan (job result `persist_failures: 8`);
  same class + window as 06-30's storm. #1100's retry wraps ONLY `observability/alerts.py`
  alert() — scanner persists un-retried → 8 rejection rows lost today (observability data, no
  live-risk surface). FIX (additive): reuse the #1100 transient retry at the scanner persist
  seam (or pre-ping the connection before the post-scan write burst). RISK zero. CONF high.
- **[A4 2026-07-01 — REFINEMENT, changes action] Ghost-sweep shadow scoping P2→P1.** 58
  shadow-ghost warns in 2 days from ONE shadow position (51× 06-30 + 7× 07-01) vs ~73/wk
  baseline — the unscoped sweep (`alpaca_order_sync.py:245`) floods exactly when autopilot
  live flow makes a real desync time-critical. Additive scoping only.
- **[A4 2026-07-01 — instance, no new finding] First stranded critical:** 13:30:09Z critical
  `force_close` reached the DB and nothing else — `OPS_ALERT_WEBHOOK_URL` UNSET both workers,
  zero egress lines in logs. Operator owns setting it (+ `HEARTBEAT_PING_URL`, also unset).
- **[A7 2026-07-01 — note] `[CLOSE_FILL_GAP]` line emits at INFO** → invisible on the
  WARNING+/print worker (the [UTILIZATION_GATE] observability class). DB persistence (the
  durable channel) verified working on its first event. Cosmetic rider: bump to WARNING.
- **A8 lens SWAPPED:** Entry-Fill Efficacy ADOPTED (the SOFI staged-live lifecycle is the
  06-30-named trigger data); Negative-Decision Efficacy retired after 6 runs — parting
  datapoint: the conservative SOFI fork's REJECT (edge_below_minimum, EV 19.1) beat both
  accepting books (−40 live / −1,044.48 shadow). Its standing capture/marker recommendation
  stays in backlog RESEARCH, not withdrawn. `audit/area8.md` rewritten.
- Shadow SOFI force-close 07-01 13:30:09Z (−1,044.48; 17 lots; 21h overnight hold; open-
  rotation full-cross 0.84 vs mid 1.57, divergence 0.869): the **GATED Phase-3 class
  exercising** — cited, NOT re-found. All controls fired as designed (verifications below).
  Cohort-comparability caveat: the loss lands on neutral's policy-lab ledger at 26× the live
  twin (#1017 modeled-fill bias, now with a large concrete instance).

VERIFICATIONS CLOSED THIS RUN (the three 06-30 pendings + bonus — do not re-find):
- ✅ **First autopilot executor cycle**: 06-30 16:30Z staged + broker-filled SOFI live (fills
  broker-verified; entry at the 1.44 net limit, ~10s to fill); 07-01 both cycles clean with 0
  candidates (correct zero-entry day on honest scanner math, 382 rejections).
- ✅ **First post-fix paper_learning_ingest** (#1098): 06-30 21:20Z errors=0/created=1;
  07-01 21:20Z errors=0/created=1/dup-skipped=1 (position-level dedup ✓). Live SOFI v3 row
  **is_paper=FALSE**, pnl −40.0; **post-epoch live closes 5→6**. `entry_iv_rv_spread`
  populated (0.1166, first ever); `realized_vol_over_hold` NULL (hypothesis: hold too short —
  verify on a multi-day close before calling it a writer gap).
- ✅ **#1076 live-only calibration EMPIRICALLY confirmed**: 07-01 10:00Z escalation 30/60/90
  all sample_size=6 = exactly the live count (11 post-epoch outcomes exist, only 6 live seen)
  → insufficient_data → raw_mode_reset_written. Raw mode holds until 8.
- ✅ **#1073 Layer A first exercise**: 2 suggestions stamped `status='executed'` 06-30 at the
  position-insert seam.
- ✅ **#1062 first AUTOMATIC cohort-stop cooldown write**: (c8a3a3b0, SOFI) until 07-02
  13:30Z, reason=cohort_stop_force_close, realized_loss −1044.48. #1040's bench is now armed
  with a real row.
- ✅ **#1080 per-position triggers first live fire**: cohort stop evaluated on CORROBORATED
  UPL (obs row 13:30:05Z: mid 1.57/+26 vs achievable 0.84/−1,044.48, divergence 0.869,
  quote_complete=true, stop never suppressed); internal fill at executable w/ fill_quality
  (#1017); [INTERNAL_FILL] WARNING line present.
- ✅ **#1102 first event**: fill-side persist wrote `close_fill_gap_fill=0.84`, cross/mid/
  fraction NULL = the DOCUMENTED fill-only design for internal/shadow closes. Informative
  gap_fraction pends the first LIVE close.
- ✅ **Phase-B EXIT_EVAL_DEBUG honesty observed live**: printed the cohort threshold
  −494.496 (= 0.20 × 2,472.48 basis), not the flat default.
- ✅ **[CONVICTION] DEGRADED**: 0 lines today = CORRECT (v3 view live since #1076) — the
  once-per-recycle DEGRADED expectation is obsolete; do not re-expect it.

PENDING VERIFICATIONS (added 2026-07-01):
- First LIVE close post-#1102 → informative gap_fraction (broker fill vs cross) in
  order_json. The log line is INFO-invisible — query the DB, not Railway.
- First `ENTRY_ROUNDTRIP_COST_GATE` evaluation (next staged candidate): WARNING eval line +
  `blocked_reason='ev_below_roundtrip_cost'` on any reject; classify spread-eaten (correct)
  vs edge-lost (over-reject flag, operator-investigate only).
- 07-02 10:00Z relearn: sample stays live-only n=6 (the 07-01 shadow −1,044.48 is_paper=true
  must NOT appear in the count).
- `realized_vol_over_hold` on the next multi-day close — NULL on short holds is DESIGNED
  (`A4_MIN_HOLD_BARS=3` daily bars; the 15-min/21-h SOFI holds can't qualify); only a NULL on
  a ≥3-day hold would be a writer gap.
- 07-02 13:30Z SOFI cooldown expiry: if SOFI re-emits before expiry, FILTER + fail-closed
  STAGE gates must bench it (#1040's first full pre-ranking exercise).

## status:built — 2026-07-01 post-close · A5 scanner persist-seam retry (PR #1104, CI GREEN, MERGE PENDING operator)

- **[A5 07-01 fix] scanner rejection-persist transient-disconnect retry** — branch
  `fix/scanner-rejection-persist-retry` (tip `a955fc2`), PR #1104, CI green on run 3.
  The 16:00Z post-scan write burst lost 8 `suggestion_rejections` rows to stale-keepalive
  "Server disconnected" (2-day pattern; #1100 wrapped ONLY alerts.py).
  `RejectionStats._persist_rejection` now retries with backoff (0.25/0.5s) reusing #1100's
  classifier (`alerts._is_transient_disconnect`); ONLY transient disconnects retry — any other
  exception keeps the single-attempt fail-soft path byte-for-byte. Exhausted transient →
  DISTINCT `rejection_row_lost_after_retries` marker + unchanged fallback; recovered retry →
  NEW `persist_retry_recoveries` count in the scan job_runs.result (DB-queryable) + WARNING
  line. Backoff sleep is constructor-injected (`retry_sleep=`, default time.sleep test-pinned):
  CI runs 1+2 proved dotted-path @patch on options_scanner is order-fragile in the full suite
  (the MagicMock-shadowing class the suite itself documents at
  test_credit_spread_emission._read_anomaly_threshold). No flag (observability-only; clean path
  unchanged: one attempt, zero sleeps). ADDITIVE — scan decisions/aggregate counts/close paths
  untouched. 9 new tests + 97 touched-path regression local + full CI.
  **Rider (ledger-named 07-01):** `[CLOSE_FILL_GAP]` emits at WARNING (was INFO-invisible);
  level test-pinned.
- **Merge blocked by the session's self-approval gate (correct behavior):** the agent-authored
  PR merge auto-deploys both live workers; operator merges. AFTER merge: H8 both workers
  (deployment SUCCESS at the squash SHA, container start > merge time), then the pendings below.

PENDING VERIFICATIONS (added with #1104; valid only after operator merge + H8):
- Next 16:00Z scan disconnect burst: `persist_failures=0` + `persist_retry_recoveries>0` in the
  scan job_runs.result (retry absorbed it), or the distinct `rejection_row_lost_after_retries`
  marker if one outlives the backoff.
- First live close post-merge: [CLOSE_FILL_GAP] line now VISIBLE at WARNING in Railway logs —
  the "query the DB, not Railway" caveat on the earlier pending item becomes obsolete at this SHA.

## status:reported — 2026-07-02 NIGHTLY (v5.1 first run; report `audit/reports/2026-07-02.md`)

Quiet night: zero market activity since the 07-01 report; movement = #1104 (persist retry,
shipped) + #1105 (docs) merged 02:39/02:41Z, both workers SUCCESS @ `b6a28e1` (H8 clean,
mid-night recycle, no orphaned cycles). Broker flat, equity 2,093.74 == last_equity. H11: 1
critical = the ledgered 07-01 shadow force-close.

- **ONE-TIME CORRECTION (owner, v5.1 contract): the 2026-07-01 A8 swap to Entry-Fill Efficacy
  was ADOPTED IN ERROR and is REVERTED.** Negative-Decision Efficacy is RESTORED as the A8
  graduated standing area (audited every run; does not rotate). Entry-Fill Efficacy is
  RETIRED — not moved to A9; its spec is preserved in `audit/area8.md` under SUPERSEDED
  (move-don't-lose). Reason of record: A8 is the standing counterfactual area; single-run
  lens rotation is Area 9's mechanism. EFE's subject matter stays auditable under A1/A6/A7
  and may compete for the A9 slot on merits, with no incumbency.
- **[A9 2026-07-02 — FINDING, first audit of the new rotating lens "Alert & Signal
  Integrity"] `ops_data_stale` alert content lies about its trigger: 57/69 (83%) of 30d
  firings self-contradictory** ("Market data is stale … Stale: 0 … Reason: ok",
  `stale_symbols=[]`; one at age_seconds=54). Mechanism: `ops_health_check.py:117` ORs
  market_freshness | job_freshness, but message (:141-143) + details (:144-149) are built
  from market_freshness ONLY — every job-arm firing is mislabeled as market-data staleness;
  the correct `stale_reason` (:120-121) never enters the alert; fingerprint (:124-128) hashes
  the empty symbol list → all job-arm firings share one fingerprint. The job-arm predicate
  (30-min threshold vs 1×/day suggestions_open/close, `ops_health_service.py:198-227`) is the
  LEDGERED 2026-06-10 root cause — cited, not re-found; the mislabel wiring is the new
  surface. Realized cost: the 07-01 audit itself mislabeled the class ("chronic
  calibration-freshness artifact"). Projected cost: ~2-4 false highs/RTH-day egress to the
  ops webhook the day OPS_ALERT_WEBHOOK_URL is set → fix the wiring BEFORE/WITH webhook
  arming (order-coupled with the standing TOP-3 #1). FIX (additive): message from
  stale_reason + `trigger_source` + job_freshness fields in details + per-arm fingerprint; no
  predicate/threshold change (that is the separate ledgered item). RISK zero (content-only).
  CONF high. Spec: `audit/area9.md` (fresh adoption, no graduation proposed).
- A1/A2/A6/A7 UNCHANGED (zero fills/scans/closes in window). A3 counter re-verified 6/8 live
  post-epoch (30d: live n=6 −153; paper n=9, 5 post-epoch, −1,870.80). A5 loop self-audit:
  11 SQL (3 wasted on column-name misses — introspect information_schema FIRST), 3 broker, 0
  subagents; prior-session H8/H11 pulls reused. Q9 note: scanner persist-failure key is
  `result.counts.rejection_persist_failures` (options_scanner.py:311) — use it for the #1104
  verification query.

PENDING VERIFICATIONS (2026-07-02 session, in addition to the standing 07-01 list):
- 10:00Z relearn: sample_size=6 live-only (shadow −1,044.48 is_paper=true excluded).
- 13:30Z SOFI cooldown expiry: FILTER + fail-closed STAGE gates bench a pre-expiry re-emit.
- 16:00Z scan: #1104 first live test — `counts.rejection_persist_failures=0` (+
  `persist_retry_recoveries>0` if a disconnect burst occurs); [CLOSE_FILL_GAP] now
  WARNING-visible on any close.
- Scheduled 00:23 CT nightly (v5 prompt) collides with report file `2026-07-02.md` — operator
  to skip or accept overwrite (this run covers the window).

## status:shipped — 2026-07-02 post-close · A9 data_stale content fix (PR #1106 → main `91b1319`, both workers H8 SUCCESS 03:20:55Z)

- **[A9 fix, item 1 of tonight 3] data_stale alert content from the firing arm** — squash
  `91b1319`. NEW pure helper `ops_health_check.build_data_stale_alert_content(market, job)`:
  message/details/fingerprint from the arm(s) that FIRED. Job-arm → names the stale source +
  age vs threshold + true reason (trigger_source="job", job_* detail keys); market-arm →
  EXACT legacy message AND legacy fingerprint shape (cooldown history survives the deploy);
  both → both named, " | "-joined. Job-arm fingerprints hash {job_source, job_reason, arms}
  instead of the empty market symbol list (per-arm dedup buckets). PREDICATE UNTOUCHED
  (test-pinned) — the 30-min-vs-daily-cadence job-arm threshold stays the separately-ledgered
  2026-06-10 item (own PR later, per operator 1c). Regression fixture pins the verbatim 07-01
  production shape: "Market data is stale ... Stale: 0 (). Reason: ok" can never emit again.
  12 new tests + 57 touched-path regression + CI green first try. One-time cooldown reset for
  job-arm firings only. Sequencing honored: shipped BEFORE webhook arming.

PENDING VERIFICATION: next RTH inter-scan gap (e.g. ~14:07Z or ~15:07Z ops_health_check) →
the ops_data_stale row (if the job arm fires) must read "Job-based data freshness is stale.
Source: job_runs. Age: ~N min ..." with trigger_source="job" and NO market-data language.

## status:armed — 2026-07-02 post-close · egress webhook LIVE (item 2 of tonight 3, operator action)

- **`OPS_ALERT_WEBHOOK_URL` SET on BOTH workers ~03:35Z** (operator; names-only hygiene —
  value never in transcript). Var-change recycle: worker + worker-background BOTH SUCCESS
  03:35:44Z, SHA unchanged `91b1319` → running processes carry it. Code reads confirmed:
  `ops_health_service.py:670/:1188` + `observability/alerts.py` (#1096/#1100 senders).
  Sequencing honored: #1106 content fix deployed BEFORE arming (no cry-wolf channel).
  Standing TOP-3 #1 (3 consecutive reports) is CLOSED pending first-egress proof.
- **⚠ `HEARTBEAT_PING_URL` SET but INERT — NO READER EXISTS.** Grep 07-02: zero code
  references (`jobs/handlers/heartbeat.py` is only the internal scheduler job_runs
  heartbeat; no PING_URL/healthchecks reader anywhere). The external dead-man's switch
  (durable-oversight Window 1, P2 half) was NEVER BUILT — only the A4 detector half shipped
  (#1100). The var is correct env-first pre-staging, but **monitoring-by-absence is NOT
  active**; a dead scheduler still alerts nobody externally. DOC≠BUILT instance — do not
  count the switch as armed until its PR ships and pings are observed at the provider.

PENDING VERIFICATION (egress arm): first egress-eligible alert (critical, or the ~14:07Z
ops_data_stale job-arm firing if allowlisted) must produce a webhook send — check for the
sender's egress log line on the worker AND delivery at the operator's channel; a stranded
critical with the var set = new finding (delivery-path bug, not config).

## status:shipped — 2026-07-02 post-close · ghost-sweep live scoping (item 3 of tonight 3; PR #1107 → main `6898bf9`)

- **[07-01/07-02 TOP-3 #3] ghost_position sweep scoped to live-routed portfolios** — squash
  `6898bf9`. Recon first (PR was gated on it): ALL 58 warns 06-30→07-01 traced to ONE
  position — the neutral-cohort shadow SOFI (`08002beb`, `routing_mode=shadow_only`), firing
  every 5-min sync from open+15min to seconds before its 13:30Z force-close. Sweep correct
  per code, spurious per intent (a shadow never exists at the broker). Fix: sweep portfolio
  set through #1014 canonical `position_scope.live_routed_portfolio_ids`, BOTH halves (ghost
  legs + stale needs_manual_review). **Fail-OPEN polarity, test-pinned**: scope-query failure
  → legacy unscoped sweep + warning (noisy beats blind — a detector must never silently
  narrow). Deliberately NO dedup on the ghost half: a real live ghost keeps nagging at full
  cadence (H10 urgency preserved). Dedup/rate-limit evaluated and REJECTED (would mute real
  desyncs). 7 new tests (`test_ghost_sweep_live_scope.py`, verbatim 08002beb fixture) + 21
  existing green; CI green. Closes the ledgered P2→P1 noise item; §8 seam note ("sweep does
  not exclude shadows") is FIXED at this SHA — CLAUDE.md edit deferred to the next doctrine
  pass.

PENDING VERIFICATION (ghost scoping): next session with an open SHADOW position → zero
ghost_position warns from it across sync cycles (the 08002beb class); any LIVE position
ghost must still alert. H8 VERIFIED 03:44Z: worker + worker-background BOTH SUCCESS @
`6898bf9` (deploys 4b9fd393/4401e0ba), zero error-level lines post-start.

## status:shipped — 2026-07-02 post-close run #2 (operator-directed A1–A5 + B1–B3 recons)

Three builds merged sequentially (one PR / one recycle / H8 each), three read-only recons,
backlog rewritten. All H8s: both workers SUCCESS at the squash SHA, container start > merge,
zero error-level lines post-start.

- **[A1 #1109 `97bace3` 04:09:58Z] dead-man's-switch ping** — heartbeat.run() fires one
  best-effort GET at `HEARTBEAT_PING_URL` (timeout 5s, try/except → single WARNING logging
  the exception CLASS only — the URL embeds the check token, never logged). Unset/empty →
  silent no-op. Pin: run() result byte-identical across success/timeout/unset — a
  healthchecks outage can NEVER fail the heartbeat job. **HEARTBEAT ARMED, end-of-chain
  semantics**: silent check = one of APScheduler→BE→RQ→worker died; diagnose job_runs vs
  Railway. RTH-only trade-off accepted (schedule */30, hours 8–17 CT). Env var pre-staged +
  read back 03:35Z; no var mutation since — recycled containers carry it.
- **[A2 #1110 `716ba2a` 04:15:23Z] typed strategy/regime on trade_closed outcomes** —
  the builder carried both only in details_json while the TYPED columns (the ones
  post_trade_learning._build_segment_key reads) were never written → segment learning
  silently no-oped (83/98 rows NULL; the 06-29 "0/13" was the narrower window). Values were
  available-but-unmapped (the metadata SELECT already pulls strategy+regime). No linked
  suggestion → NULL, never fabricated (H9). Every close from this deploy forward carries
  segments. 82 of 83 legacy NULL rows backfillable from linked suggestions → supervised-
  mutation queue (NOT executed).
- **[A3 #1111 `7bc9927` 04:25:51Z] direct-insert alert egress relay (P1 Window-2)** —
  13 sites insert risk_alerts without alert() (incl. the monitor's force_close): with the
  webhook armed they still egressed NOWHERE. relay_direct_insert_alerts polls post-epoch
  critical/high rows and relays via the SAME Channel-2 sender (client=None, no duplicate
  row), marks metadata.egressed_at/egress_owner=relay. Boundaries: ops_* Channel-1 rows
  excluded; alert() pre-stamps egress_owner=alert on its #1096 allowlist. Epoch
  `ALERT_RELAY_EPOCH` = 2026-07-02T00:00Z (#1051 pattern; 0 post-epoch rows at build —
  the 1,040-row backlog can never fire). Best-effort: unmarked-on-failure → retry next
  poll; 3-consecutive-failure circuit; cap 10/poll. Piggybacked as fail-isolated step 0 of
  ops_health_check (effective cadence HOURLY at :07 — the :37 fire is deduped by the hourly
  idempotency key; contradiction filed P1). **Egress now covers alert() AND direct-insert
  paths.**
- **[A4 EXECUTED 07-02 ~04:45Z, operator-approved in-session]** hygiene sweep: bulk-acked
  exactly **1,040** pre-epoch un-acked critical/high (385 c / 655 h; warn×580,
  force_close×356, ops_data_stale×69 dominate) via one UPDATE setting resolved=true +
  resolved_at + jsonb marker `bulk_ack='hygiene_sweep_2026-07-02'`, cutoff = relay epoch
  07-02 00:00Z (move-don't-lose; both production readers key on recent created_at windows —
  behavior-safe). Post-sweep verification: the ONLY remaining un-acked critical/high row is
  the synthetic relay-e2e row `4d0afb05` (by design, deleted after the 13:07Z proof). H11
  baselines are clean from tonight forward: un-acked critical/high now means LIVE actionable.
- **[A5 #1112] docs/backlog.md rewritten** from ledger + recon verdicts; GATED carries the
  executor-cadence trigger verbatim (NOT MET); #71 guard tokens retained (29 guard tests
  green). Final recycle of the night.
- **[B1 recon — MTM mark-write corroboration → PROMOTED P1]** persisted raw marks are
  DECISION-FEEDING on slow paths: policy-lab champion HARD_DRAWDOWN_LIMIT auto-rollback
  (evaluator.py:605-621 via max_drawdown), go-live checkpoints, autopilot-breaker +
  _marginal_ev fallbacks, close-limit seam (mitigated #1072/#1017). Fast loss paths clean
  (#1071/#1075/#1079/#1080). 14d evidence: 2/3 closes wrong-signed at last persist; SOFI
  persisted +196.52 30min before the corroborated −1,044.48 close. Fix = reuse
  exit_mark_corroboration.executable_close_estimate at BOTH write sites
  (paper_mark_to_market_service.py:206-217 + intraday_risk_monitor.py:780-790, snapshots
  already fetched — zero extra API calls), ADDITIVE fields only. Side-finding: monitor
  Part-B persist doesn't stamp last_marked_at.
- **[B2 recon — migration drift]** the 2-file paper-shadow cluster is the only genuinely
  unapplied pair → GATED apply-as-unit pre-enable (INERT confirmed, doubly so). Tracking:
  27/112 by name (82 pre-era, 1 procedure miss `20260426000000` applied-untracked, 2 gated).
  Process fix (P2): name-normalized drift check vs a checked-in allowlist in the nightly
  audit.
- **[B3 recon — data_stale predicate retune table ready]** union arm: max healthy in-gate
  age 187 min over 10/10 trading days → `OPS_DATA_STALE_MINUTES=360` kills 39/39 job-arm
  false HIGHs (78% of all data_stale HIGHs); market-hours gate suffices for the union arm
  (no new weekend guard). Daily job_late arm (NOT market-hours-gated) needs the
  _rth_job_status warm-up-anchor generalized — 40 Monday warns → 0. Contradictions filed:
  ops_health_check hourly-vs-q30 dedup; suggestions_open 15 runs/10d untraced extras.

PENDING VERIFICATIONS (added 2026-07-02 post-close run #2):
- **Heartbeat first ping** at the 08:00 CT slot (13:00Z) — provider dashboard shows it;
  then the operator handoff (un-pause, cron */30 8-16 * * 1-5 America/Chicago, Grace 45,
  after-hours Grace-to-1-min email test to prove the last hop, restore).
- **Relay synthetic e2e** at the 08:07 CT poll (13:07Z): risk_alerts row
  `4d0afb05-3c9a-4c10-ac40-39f55e292ffb` (relay_synthetic_e2e, critical, 04:26:42Z,
  clearly-labeled SYNTHETIC) must egress to the operator inbox;
  job_runs.result.alert_relay.sent=1 + metadata stamped egress_owner=relay. THEN clean up:
  `DELETE FROM risk_alerts WHERE id='4d0afb05-3c9a-4c10-ac40-39f55e292ffb';`
  A stranded synthetic with the webhook set = delivery-path bug (new finding).
- **First typed segment row**: next trade_closed ingest (21:20Z) carries non-NULL
  strategy+regime; post_trade_learning segment keys build without the suggestion-join
  fallback.
- Standing 07-01/07-02 list unchanged (10:00Z relearn live-only n=6 · 13:30Z SOFI cooldown
  expiry · 16:00Z scan #1104 first live test · #1101 first roundtrip-gate evaluation ·
  first LIVE close post-#1102 gap_fraction).

## status:shipped — 2026-07-02 pre-market build session (P1-A/B/C + approved backfills)

Operator-directed session (~09:00–09:30Z, market closed; all merges pre-08:00 CT job spin-up).
Three sequential builds, each CI-green → squash → BOTH workers (+BE for P1-A) H8 SUCCESS at the
squash SHA, container start > merge. Owner decision of record: ops_health_check cadence intent =
**(a) q30min REAL**.

- **[P1-A #1114 `e133063` 09:02:33Z] q30min-real idempotency bucket** — the hour-granular key
  (`public_tasks.py`) deduped the :37 fire against :07 every hour (99/100 observed runs at :07);
  effective cadence was HOURLY, silently halving the health check AND the A3 relay poll. Key now
  buckets by half-hour via pure `_ops_health_idempotency_key`; same-half-hour retries still dedup;
  `-synthetic` suffix composes unchanged. **Relay SLA restated: a direct-insert critical/high
  reaches the inbox within ~37min worst case** (insert just after :07 → :37 poll + send), vs ~67min
  before. BE verified at the SHA too (the endpoint lives there). VERIFY: two ops_health_check
  job_runs per hour from 13:07/13:37Z today.
- **[P1-B #1115 `0b85de6` 09:12:09Z] data_stale predicate retune** — PREDICATE ONLY (#1106 content
  pins green): `OPS_DATA_STALE_MINUTES` default 30→360 (wiring unchanged: code default + env
  override; if the env name is explicitly set on Railway it shadows — operator names-only check);
  daily `job_late` age is now WEEKEND-EXCLUDED (`_weekend_excluded_age` — Fri-evening→Mon-morning
  reads ~16h ok; a genuinely missed Monday reads ~40h late by Tuesday; flat ~74h raise rejected as
  it would delay Tue–Fri detection). Fixture update ledgered: the watchdog daily pin re-anchored on
  a Thursday (its old 30h window crossed Sunday — reads ~17h effective under the deliberate new
  semantics; the 26h-absent-weekend intent preserved). **VERIFICATION CONTRACT: next RTH day
  job-arm false HIGHs 39→0; next Monday job_late storm 20→0; a real dead daily job still alerts
  same-day (367min > 360 at the 19:07Z check).** The alert channel's last known noise source dies
  here.
- **[P1-C #1116 `b18052d` 09:25:52Z] MTM mark-WRITE corroboration (B1 promote)** — both durable-
  mark write sites (`refresh_marks` + monitor Part-B) now persist
  {mark_corroborated, unrealized_pl_corroborated, mark_quality} ALONGSIDE the raw mid (raw
  byte-identical — the load-bearing pin held; the exit evaluator's close-limit read is
  source-pinned to raw). Design call (owner-delegated): ADDITIVE, not replace — replacing
  current_mark would leak into the LIVE close-limit path, and #1072 already restages live closes
  at achievable. Zero extra API calls (cycle-cached snapshots); dark/incomplete → NULLs +
  uncorroborated stamp (H9). Governance now prefers corroborated: policy-lab cohort unrealized
  (max_drawdown → utility + HARD_DRAWDOWN_LIMIT champion auto-rollback) + go-live checkpoint sums;
  breaker/_marginal_ev FALLBACK branches deliberately untouched. OUTPUT_FRESHNESS now watches
  paper_positions.last_marked_at (168h; flat-book caveat) + generic query NULLS LAST fix.
  Migration `20260702100000` applied pre-merge via canonical apply_migration (tracked).
  **BEFORE-BASELINE (do not re-find): 14d = 2/3 closes wrong-signed at last persist; SOFI 07-01
  raw +196.52 persisted 30min before the corroborated −1,044.48 close (divergence 0.869).**
  Pinned: the SOFI fixture now reads −1,044.48 into cohort scoring. Residual (filed, not built):
  Part-B still doesn't stamp last_marked_at; eod snapshots don't carry corroborated fields.
  VERIFY: first RTH mark cycle writes non-NULL corroborated fields on any open position;
  policy_daily_scores unrealized reflects the corroborated basis at the next eval.
- **[Backfills EXECUTED ~09:35Z, operator-approved in-session after fidelity gates]**
  (a) 82-row typed strategy/regime from linked suggestions (10/10 sample fidelity; exactly 82;
  the 1 non-qualifying row stays NULL as pre-fix legacy; no updated_at trigger — v3 close-time
  COALESCE untouched). (b) 33-row funnel dismissed→executed (10/10 sample had real closed
  positions; exactly 33 = the ledgered 32 + 1 accrued; the trade_suggestions integrity trigger
  guards lineage fields only — status explicitly allowed). Historical segment learning and funnel
  stats are now truthful end-to-end.
- **GATED confirmations (encoded, nothing touched):** executor cadence NOT MET (raw 6/8, #1072
  unexercised) · clamp/winsorize await the 8th live close · Phase-3 exits await ≥10–15 fills ·
  paper-shadow migration pair only at the executor-flag flip (RLS at apply). Operator handoff
  outstanding: healthchecks un-pause + cron */30 8-16 * * 1-5 America/Chicago + Grace 45 +
  after-hours Grace-to-1-min email test.

PENDING VERIFICATIONS (added this session): two health-check runs/hour from 13:07Z · job-arm
false-HIGH count = 0 over today's RTH · Monday 07-06 job_late storm = 0 · first mark cycle
writes corroborated fields · next policy_lab_eval scores on the corroborated basis.

## status:shipped — 2026-07-02 gap-report build session (external-reference audit, operator-approved set)

Operator ran a reference-repo gap analysis (NoFx / flashalpha / TradingAgents / ai-hedge-fund
patterns); approved set built in order. Both builds CI-green → squash → both workers H8.

- **[Gap-4 recon — DOC≠BUILT FINDING: the greeks exposure envelope is DOUBLE-dormant]** —
  DB-verified: across 60d (18 positions) NO leg jsonb has ever carried a `greeks` key and
  paper_positions has no greeks column → `check_greeks` (risk_envelope.py:229) has summed
  ZEROS since inception; AND all four caps default 0 = no-limit. §5's "greeks warn" listing
  is a known-liar until fixed (CLAUDE.md edit deferred to the next doctrine pass, #1107
  precedent). Answers the archived #115b narrowed question on the persisted side. NOT
  silently populated (operator-directed); follow-up filed: populate greeks on legs at stage
  time (stage validation already fetches snapshots that carry them), caps decision after
  inputs are real.
- **[Gap-2 #1118 `49f3ba9` 10:02:34Z] rolling signal-accuracy telemetry (OBSERVE-ONLY)** —
  view `signal_accuracy_rolling` (migration 20260702110000, applied+tracked pre-merge):
  live-only last-20 hit-rate + Brier per scope; ops_health section 3.7 fail-isolated;
  `signal_accuracy_degraded` WARNING at n≥8 AND hit_rate<0.2 (env-tunable). Modulates
  nothing. **FIRST BASELINE (do not re-derive): overall 1/6 wins (16.7%), Brier 0.2751;
  IRON_CONDOR 0/2, LONG_CALL_DEBIT_SPREAD 0/3, LONG_PUT_DEBIT_SPREAD 1/1.** n=6<8 → below
  the alert sample gate today.
- **[Gap-1 #1119 `c0268ce` 10:15:31Z] consecutive-loss streak breaker (NoFx pattern)** —
  N consecutive live losses → `ops_control.entries_paused=true` + critical alert
  (streak_breaker_tripped/_error added to the #1096 egress allowlist). N=3 env-config
  (`STREAK_BREAKER_N`); `STREAK_BREAKER_ENABLED` default-ON tightening polarity; FAIL-CLOSED
  the strong way (evaluation error → PAUSED, never check-skipped — deliberately opposite the
  fail-open READ gate, which consumes a halt this evaluator sets); recovery operator-only
  (no code path writes false — source-pinned); idempotent vs existing pauses. Tail step of
  paper_learning_ingest → job_runs.result.streak_breaker. **Pre-merge bug caught
  (verify-before-asserting): a typed `symbol` select would have 42703'd (no such column —
  #1098 class) and, under fail-closed, paused entries EVERY run; symbol now read from
  details_json, select list source-pinned.** ⚠ **KNOWN TRIP, operator-acknowledged: the live
  stream already holds 5 consecutive losses (SOFI −40 · MARA −15 · QQQ −73 · MARA −28 ·
  SPY −45) — the FIRST evaluation (tonight 21:20Z ingest) trips: entries pause + critical
  alert = free live end-to-end exercise. Operator decision of record: ship, let it trip,
  then un-pause (`UPDATE ops_control SET entries_paused=false, entries_pause_reason=NULL
  WHERE key='global'`). A 21:20Z trip is EXPECTED, not an incident.**
- **[Gap-3 recon + spec — NO build]** `docs/specs/shadow_fill_realism.md`. Recon: live fill
  rate ≈1/3 (17 filled / ~54 orders; 10 watchdog-cancelled unfilled — the NFLX class ≈1 in
  5) vs shadow 100%-by-construction; same-period twin magnitudes 3–45× (size-driven, 5–17
  lots vs 1); only 3 shadow closes carry fill_quality=executable (rest predate #1017);
  cohort twin pairing is (symbol, cycle), NEVER suggestion_id. Recommendation: interim
  option (a) per-contract promotion-time normalization + measured fill-discount (one PR)
  BEFORE the next promotion eval; full post-and-wait model (b) in its own recon-first
  session. Owner decision pending on (a).

PENDING VERIFICATIONS (gap session): 21:20Z tonight — `job_runs.result.streak_breaker.tripped=true`
+ entries_paused=true + streak_breaker_tripped critical in the inbox (egress) → operator
un-pauses per decision of record · signal_accuracy view visible in tonight's ops_health
snapshots · no alert from signal accuracy until n≥8.

## status:verified — 2026-07-02 post-close wrap (~23:30–23:50Z): the breaker exercise + doc sync

- **[#1119 FIRST TRIP — VERIFIED END-TO-END, planned, NOT an incident]** 21:20Z ingest:
  errors=0, outcomes_created=0 (flat day; typed-segment FORWARD proof defers to the next real
  close — the 82 backfilled rows stand). `result.streak_breaker`: enabled/evaluated/tripped/
  paused_written ALL true; window = SOFI −40 · MARA −15 · QQQ −73 verbatim. Chain: ops_control
  entries_paused=true + streak reason verbatim → `streak_breaker_tripped` critical 21:20:03Z,
  `metadata.egress_owner='alert'` (immediate-egress path; relay can never double-send) → zero
  `streak_breaker_error` rows → worker log `[STREAK_BREAKER] TRIPPED` 21:20:09Z. Egress nuance:
  the webhook POST attempt is proven and NO failure logged (failures log at WARNING and would
  show); the success line is INFO (not retained) → final receipt = operator inbox (confirm ④).
  Design note answered by the exercise: the breaker evaluates the TRAILING stream on EVERY
  ingest run (it fired with outcomes_created=0) — no fires-only-on-new-outcomes gap.
- **[RECOVERY EXECUTED ~23:35Z, operator-approved in the wrap]** un-pause UPDATE run;
  read-back `false / NULL`. Entry-seam read: `paper_autopilot_service.py:187-196`
  (`are_entries_paused()` → falls through to the staleness gate when false). Staging proof =
  tomorrow's 16:30Z cycle (PENDING). Breaker critical ACKed (exercise complete).
- **[CLEANUP]** synthetic relay row `4d0afb05` DELETED (post-inbox-window); post-sweep H11:
  **un-acked critical/high = 0 — genuinely zero for the first time on record.**
- **[DOC SYNC]** CLAUDE.md registry #1043→#1119 synced (v3-exists correction, 8th-close
  convergence rule, relay route/SLA, close-limit-reads-RAW pin, breaker un-pause procedure
  VALIDATED, §5 greeks layer marked dormant, §7 v5.1 A8-standing/A9-rotating, §8 liars
  rewritten: greeks double-dormant + shadow-ledger fiction added; EXIT_EVAL_DEBUG/ghost-sweep/
  is_paper/funnel moved to RESOLVED-cite-only; no-symbol-column trap; §9 + entries_paused
  operator-only + introspect-before-select). backlog: P1 tier → gap-3(a) normalization +
  tradeable-universe recon; shipped set retired; supervised-mutation queue closed; new P2s
  (greeks populate-at-stage, breaker-N revisit at n≥15, mark-write residuals). ~38.4k chars.
- **Process note (self-caught):** a PowerShell one-liner clobbered docs/backlog.md mid-edit
  (PS 5.1 kept executing after a Substring exception → Set-Content $null). Recovered via
  `git checkout --`; only an uncommitted edit was lost and redone via the Edit tool. Lesson:
  no destructive shell one-liners on tracked docs — Edit tool only.

OPERATOR-CONFIRM — **ALL FOUR CONFIRMED with evidence (operator, 07-03 session)**:
① healthchecks FULLY ARMED — check un-paused; receive-side 20 pings, every :00/:30 from 08:00
  CT (source = the worker; "new → up" at the first ping, per #1109's prediction); cron
  `*/30 8-16 * * 1-5` America/Chicago, Grace 45; Grace-to-1-min DOWN-email test DELIVERED
  18:45 CT, Grace restored. Residual: check reads DOWN overnight post-test — EXPECTED; the
  08:00 CT ping tomorrow auto-flips UP (the UP email = free second confirmation, pended).
② relay synthetic email DELIVERED 08:07 CT (full payload incl. risk_alert_id 4d0afb05) — the
  A3 relay's last hop proven.
③ OPS_DATA_STALE_MINUTES CONFIRMED UNSET (dashboard names-only) — the 07-02 zero-false-HIGH
  result is attributable to #1115's code default, not an env shadow. Behavioral pass = real.
④ breaker critical email DELIVERED 16:20 CT (full window payload, paused_written=true,
  already_paused=false) — the immediate-egress path proven on a REAL safety event.
**With ①–④ the oversight chain is proven at every last hop** (doctrine-synced: CLAUDE.md §4
"Oversight chain" entry). Breaker semantics operator-confirmed from the ④ payload:
TRAILING-window evaluation on EVERY ingest run — trips can occur on zero-close days (the
07-02 window spanned closes 06-15→06-30); the stronger design, now doctrine. Recovery
mutations from the wrap RE-VERIFIED holding at confirm time (entries_paused false/NULL ·
breaker alert ACKed · synthetic gone · H11 = 0).

PARKED (operator's call, no action): rotate the hc-ping UUID (appeared in screenshots) —
healthchecks regenerate + one env update + recycle, whenever chosen.

PENDING (tomorrow): 08:00 CT heartbeat UP email (test residual clears) · 16:30Z post-un-pause
staging proof (final recovery link) · first typed-segment forward row + breaker re-evaluation
at the next real close's ingest (NOTE: the 3 most-recent live closes are all losses, so the
NEXT losing live close re-trips the breaker BY DESIGN — a win resets) · first [CLOSE_FILL_GAP]
live gap_fraction · gap-3(a) build + tradeable-universe recon = next build window.

## status:shipped — 2026-07-03 build window (~00:45–01:15Z): gap-3(a) + tradeable-universe recon

- **DEADLINE (Step 0):** the champion-vs-shadow comparison runs inside `policy_lab_eval`
  (scheduler 16:30 CT daily; `check_promotion` at policy_lab/evaluator.py:282); gap-3(a)
  landed ~15h before the next eval. (`promotion_check` 17:00 CT is phase-transition hygiene,
  not the comparison.)
- **[Gap-3(a) #1124 `48ddcd4` 01:10:59Z] shadow-ledger promotion-time normalization** — NEW
  `policy_lab/promotion_normalization.py`, called ONLY from check_promotion after the daily-
  scores fetch (governance-only, import-pinned): per-contract division on BOTH sides (daily
  contract-exposure attribution, floors at 1, never fabricates) + the MEASURED fill-discount
  on challenger/shadow rows only — `SHADOW_FILL_DISCOUNT` default **0.31 = 17/55 live fills
  re-measured at build time** (spec said 0.33; fresh count used per instruction; RE-DERIVE
  from live fill data as volume grows, never hand-tune). Ledger rows and percent fields
  untouched (rollback semantics preserved); position-fetch failure degrades divisors to 1.0
  with a WARNING. Flag `SHADOW_PROMOTION_NORMALIZATION_ENABLED` default-ON (measurement-basis
  correction, #1052 class). SOFI twin fixture pinned: live −40 → −40.00 byte-identical;
  shadow −1,044.48@17 → **−19.05** expected contribution. 18 tests + 27 touched-path.
  **BEFORE-STATE: promotion evals compared a real ~31%-fill book to a 100%-fill fiction at
  3–45× magnitudes.** H8: both workers SUCCESS @ 48ddcd4 (01:11Z deploys). VERIFY: next
  16:30 CT policy_lab_eval runs the normalized comparison (job green; no verdict flip
  expected at current n).
- **[Tradeable-universe recon — READ-ONLY, owner-decision input, NO changes]** headline:
  **1 of 84 CLEARS the round-trip gate on strict post-epoch evidence (SPY, net ≈ +$16–23 on
  a single candidacy); 5 MARGINAL (QQQ, NFLX, TSLA, IWM, SLV); ~77 STRUCTURALLY-CANNOT.**
  Structure: honest per-contract EV density is $7–45/ct; sub-$60 underlyings size to 4–21
  contracts so per-ct EV collapses to single digits vs $21+/ct minimum round-trip (the
  SOFI/TLT class — TLT has the tightest spread in the universe, $12/ct, and still cannot);
  expensive single names carry $60–1,500/ct crossings. Only penny-increment index-class
  chains get under ~$40/ct. No real-quote row in 1,436 rejections ever printed below $21/ct.
  Within-universe insight: TSLA/IWM already CLEAR the spread (~$13–14/ct) but die upstream
  on EV — if regime ever hands them positive EV they clear where SOFI never can (HYPOTHESIS
  until a post-epoch candidacy). Outside-universe candidates (HYPOTHESIS): GDX/KRE/XBI/EFA
  penny-program ETFs — but the TLT lesson says tight spread is insufficient without a
  contract-count cap in the sizer. Detail note: the gate's DB stamp reads round_trip=88.00
  (4 cts, $22/ct) vs the 16:30Z log line's 92.00 — same verdict either way; likely quote
  drift between eval and stamp passes (minor, watch on the next rejection).
- **Universe-reshape question FRAMED FOR OWNER (no action):** the small-tier universe is
  structurally spread-eaten — options: (a) accept low frequency (learning-mode consistent;
  gate is doing its job), (b) bias scanner ranking toward the 6 CLEARS/MARGINAL names,
  (c) add penny-program ETFs + a sizer contract-cap, (d) nothing until EV density grows with
  equity. Recon is the decision input; no default assumed.

PENDING VERIFICATION (gap-3(a)): 07-03 21:30Z policy_lab_eval green on the normalized basis.
Gap-3(b) post-and-wait fill model remains its own recon-first session (NOT started).

## status:shipped — 2026-07-03 (July-4th-observed HOLIDAY, market closed all day) · decision (b)+(c)

Owner decision on the universe question: (b) ranking bias BUILT + (c1/c2) recons DELIVERED +
refill screen DELIVERED + contract-cap CLOSED. Broker clock verified is_open=false, next open
07-06 — all merges today are closed-market compliant.

- **[Part 1 #1126 `d42d435` 13:38:37Z] universe-viability candidacy bias — SHIPS DARK** —
  sort-key-only multiplier in rank_suggestions_canonical toward the recon-viable set (SPY 1.30 ·
  QQQ/TSLA/IWM/SLV 1.15 · NFLX 1.10 marginal-provisional, pre-epoch-EV hypothesis in-code).
  Never a filter, never a mutation: stored risk_adjusted_ev byte-identical (the allocator's
  split skew reads it), below-floor stays −999, the stage-seam roundtrip gate reads untouched
  ev; positive scores only (boosting a negative would invert intent). Flag
  `UNIVERSE_VIABILITY_BIAS_ENABLED` strict '=1' (behavioral; non-'1' warns once). **ARMING IS
  AN OPERATOR ENV ACTION (not armed).** 10 tests; H8 both workers @ d42d435.
- **[Merge-timing note — false alarm, retracted with evidence]** the CI watch→merge chain
  slept ~7h and merged at 13:38Z "8 minutes into RTH" — flagged as a §2 violation, then
  RETRACTED against the broker clock (July-4th-observed holiday, is_open=false; the morning
  ops_data_stale market-arm firings are the documented holiday pattern; the recycle swallowed
  nothing — 13:40:01Z order_sync tick green). LESSON KEPT: watch→merge automation must
  clock-check (broker calendar, not weekday) before merging — until a guard exists, don't
  leave merge chains unattended near session boundaries.
- **[Part 2A/2B refill screen — READ-ONLY, owner-decision input; all quotes = off-hours
  holiday snapshot, indicative]** **ADD LIST: EMPTY — zero candidates pass f1–f5.** Best new
  name (CVX $52/ct) exceeds the $40 ceiling off-hours; every sizing-trap NO (BITO $10/ct but
  15 lots · GDX A-grade OI but 9 lots · EFA/KRE/XLRE/FXE) is ROBUST to the off-hours caveat —
  spread compression cannot fix per-ct EV collapse. Conditional shortlist for an RTH
  re-screen: **MRK + CVX** (OI grade A, 2–3-lot sizing, need <~$25–40/ct at RTH — 40–60%
  compression on A-grade names is plausible, HYPOTHESIS). **In-universe verdict FLIPS: DIA
  measured $28/ct (SPY-class-adjacent — amend the 07-03 'structurally cannot' class) and GLD
  viable ONLY on $5-multiple strikes** (its $1-strikes are OI-dead). PRUNE candidates
  (owner-gated; cost is scan/API only): strong = SNAP·NIO·MARA·F·LYFT·AAL·RIVN·SOFI (all
  sub-$20, structurally dead per the sizing trap; ⚠ SOFI = the only name that ever live-filled
  — owner judgment); second tier = T·CMCSA·PFE·KHC·DKNG·WBD·CCL·FXI·KMI·EWZ. CAUTIONS:
  (i) iv_rank warm-up — a fresh add is scanner-invisible ~60 trading days
  (`iv_rank_insufficient_history`, options_scanner.py:3032-3040); **SEEDING EXISTS**:
  `iv_historical_backfill` accepts payload {symbols, days} (handler :94-100, background
  queue, idempotent upsert) — pair any add PR with a one-shot seed; thin-contract history may
  stay sparse; unseeded bulk adds push the iv_pipeline_no_data alert threshold.
  (ii) CORRELATION — {SPY, DIA, QQQ, IWM} = one US-equity-beta trade in four wrappers; the
  envelope doesn't know DIA≈SPY; treat as one bucket in any add/prune decision; the
  diversifying conditionals are MRK (pharma) / CVX (energy, but XOM/XLE overlap) / GLD.
- **[Part 3 — sizer contract-cap CLOSED, evidence-based]** the roundtrip gate's verdict is
  contract-count-INVARIANT (both sides scale with n; per-ct terms decide: ev_ct<cost_ct → no
  n clears; ev_ct>cost_ct → MORE contracts help clear the $15 floor — a cap can only flip
  passes into fails). The hypothesized crowd-out mechanism is allocator-slot ORDER, which
  Part 1 addresses. No cap, item closed; slot re-flow-after-reject noted as a possible future
  recon ONLY if a cycle ever demonstrably loses a viable candidate to a doomed higher-ranked
  one.

PENDING (holiday-shifted): market closed 07-03 → post-un-pause staging proof, typed-segment
forward row, [CLOSE_FILL_GAP], and the breaker's next real evaluation all move to MONDAY
07-06. Today's 21:30Z policy_lab_eval still fires (scheduler is holiday-blind) → verify green
on the normalized basis (no verdict flip expected at current n). Heartbeat pings run 8–17 CT
today regardless → the UP email residual clears today. OWNER DECISIONS OPEN: arm
UNIVERSE_VIABILITY_BIAS_ENABLED=1 (env, no deploy) · RTH re-screen of MRK/CVX (next trading
session, read-only) · prune list · DIA/GLD class amendment.

## status:armed — 2026-07-03 ~15:18Z (holiday window) · decision-execution T-phase

- **[T1 — BIAS ARMED]** `UNIVERSE_VIABILITY_BIAS_ENABLED=1` set on BOTH workers; var-change
  recycles SUCCESS @ `a958fb4` 15:18:27/29Z — running containers created post-set carry =1.
  EXPECTATION CORRECTED vs the instruction: a correct `=1` emits NO log line by design (§3
  strict-parse warns ONLY on a non-'1' value) — silence + behavior is the signature.
  Names-only hygiene forbids a value dump read-back; the behavioral read-back is Monday's
  pin: **07-06 16:00Z scan → sort-key reorder visible in ranking, stored risk_adjusted_ev
  byte-identical (the dark-ship pin, now live).**
- **[T2 — baseline captured; closes at 21:30Z tonight]** 07-02 21:30Z eval (pre-#1124):
  `no_promotion`, challengers die at GATE 2 (`insufficient_trades`: conservative 0, neutral 1
  vs required 10) — the utility comparison NEVER RAN at current volume. Tonight's normalized
  first-eval evidence is therefore: job green + flag-default-ON path executed + same
  insufficient_trades verdict; **the SOFI-twin magnitude proof only becomes observable when a
  challenger reaches Gate 4 (≥10 trades + ≥MIN_TRADING_DAYS)** — do not mistake verdict-
  sameness for the normalization not running.
- **[T3 — OPERATOR-CONFIRM open]** heartbeat pings fired 8:00 CT today (scheduler mon–fri,
  holiday-blind) → the check should have flipped UP at the first ping; confirm the UP email
  arrived (closes the Grace-test residual).
- **[T4 — FILED]** broker-clock guard on watch→merge automation → backlog P2 (merge chains
  check `get_clock.is_open`, fail-safe to NOT-merge; no unattended chains near boundaries
  until built).
- CLOSED/DO-NOT-REOPEN (recorded): contract-cap (count-invariant algebra) · slot re-flow
  (future recon only on a demonstrated lost-viable-candidate cycle) · the empty add-list
  verdict STANDS — no refill re-run without new evidence (tier change or structural change).
- MONDAY QUEUE (own sessions): M1 MRK/CVX RTH re-screen (read-only, mid-session batch) ·
  M2 GLD $5-strike feasibility recon (config-vs-surgery verdict) · M3 standing proofs ·
  M4 post-close universe PR (prune strong tier MINUS SOFI — **SOFI stays as the canonical
  gate sentinel**: if it ever CLEARS the roundtrip gate, the spread regime, EV math, or a bug
  changed and we want to see it loudly; DIA → bias tier 1.15 with the one-beta-bucket note;
  GLD/MRK/CVX per M1/M2 verdicts; adds pair with iv_historical_backfill seeding).

## status:reported — 2026-07-03 v5.3 FULL (weekend deep-dive; report `audit/reports/2026-07-03-FULL.md`)

Budgets: 16/20 SQL · 2/6 broker · 4/12 subagents · 24 files fully read. Broker flat,
SHA `e0bbe6e` everywhere, H11 = 4 (all today's holiday data_stale highs). READ-ONLY held.

- **A9 GRADUATION RECORDED (owner decision 2026-07-03, first exercise of the rule):**
  Alert & Signal Integrity is STANDING/PERMANENT (founding finding shipped #1106+#1115,
  measured 39→0). `audit/area9.md` header frozen as the standing contract. The rotating
  slot moved to A10, adopted this run: **Calendar & Clock Integrity** (`audit/area10.md`
  — five time-boundary instances in 72h; first-run NEW finding: the winter-close blind
  hour, 20:00–21:00Z EST-season staleness+watchdog gap, fix before November).
- **TOP-3 #1 — #1126 viability bias is BUILT-NOT-WIRED (HIGH; double-confirmed):**
  `rank_suggestions_canonical` has ZERO production callers; the executor orders
  candidates via its own local sort (`paper_autopilot_service.py:118-131`). This
  morning's armed flag is INERT; Monday's "bias live" pin is VOID until wired. The
  shipped tests pinned the orphan function — the `9a2cef1` class, self-inflicted
  same-day, caught by PASS-2. Fix = one call site + an executor-path wiring test,
  item 0 of Monday's M4 window. Env stays set (correct once wired).
- **TOP-3 #2 — A9 alert-taxonomy cluster (9 findings, 4 MEDIUM):** `force_close` is a
  costume worn by three realities (31% of rows describe NO close — submitted/FAILED/
  warn-only share one critical type; post-epoch all three relay under one phone title);
  `alert_type="warn"` carries zero semantics (706 rows/30d); severity vocabulary
  fragmented — `medium`+`warn` are the two largest warning-class buckets, invisible to
  canonical `severity='warning'` readers (**misses 83%**); the designed client=None
  egress logs a "legacy mode" misconfiguration WARNING on every relayed row. One
  post-close taxonomy PR fixes the channel before the next live force-close egresses.
- **TOP-3 #3 — one-beta-bucket uncontrolled (A2, MEDIUM):** {SPY,DIA,QQQ,IWM} has NO
  block-level control — `max_correlation_cluster_pct` is declared-never-read (config
  fiction), ranker correlation is same-symbol-only, sector check warn-only with ETFs in
  an accidental shared bucket; the bias (once wired) steers INTO this. Additive control
  candidate, owner-gated.
- Other MEDIUMs: `check_rollback` mis-restores after a "recommended" promotions row +
  cooldown consumed by recommendations (latent until promotions move; cheap fix) ·
  promotion utility is structurally single-factor (tail/slippage/concentration inputs
  never written; drawdown penalty unit-mismatched ≈ ≤$0.40) · stuck-`running` job_runs
  have NO reaper (mid-run recycle orphans permanently; learning chain overlaps the merge
  window) · §4 kill-switch coupling: unsetting ENTRY_QUOTE_VALIDATION_ENABLED silently
  disables the #1101 roundtrip gate · GTC pilot-list UNSET = all-eligible (not
  pilot-off).
- Notables: suggestions_open extras RESOLVED benign (operator --force CLI, 5 of 15) ·
  cooldown-vs-cadence NOT doubled by #1114 (hourly by a 2-second phase margin — thin) ·
  SLV structurally benched until ~Sept (iv warmup; viable-tier aspirational) ·
  resting-TP pilot no longer resting (book flat; unexercised) · A8 reconstructability:
  spread-class 100% quotes/no OCC identity, EV-class 0% legs, spot-at-decision 0%
  everywhere · A7 proposed MERGED into A1/A3 until ≥10–15 live fills · scorecard + full
  owner-decision list (10 items) in the report.

PENDING VERIFICATIONS (unchanged + one added): tonight 21:30Z normalized-basis eval
(baseline captured; expect green + insufficient_trades) · Monday M-queue **with M4
item 0 = the F1 wiring fix** · heartbeat UP email (operator ③④-class confirm).

## status:plan-encoded — 2026-07-03 post-deep-dive EXECUTION PLAN (owner decisions, verbatim runbook)

Owner encoded the week 07-03 evening. THE RUNBOOK for Mon/Tue sessions — recover from here.

- **DOCTRINE ADDITION (staged for M4's doc rider, not yet in CLAUDE.md):** "Tests for a
  flag-gated behavior must pin the PRODUCTION CALL PATH, not the function in isolation —
  an orphan function with green tests is the 9a2cef1/#1126 class." (F1 detection latency
  <24h via PASS-2 vs 2 months for 9a2cef1.)
- **MON RTH (read-only):** M1 MRK/CVX re-screen (f1–f5; hypothesis: $52–70/ct compresses
  <$40/ct) · M2 GLD $5-strike config-vs-surgery verdict (no build) · M3 proofs WITH
  CORRECTION: **"bias live at 16:00Z" pin STRUCK VOID (F1)** — replaced by: 16:30Z
  post-un-pause staging proof · typed-segment forward row / first live [CLOSE_FILL_GAP] /
  breaker re-eval IF a close lands (trailing 3 losses — next losing close re-trips BY
  DESIGN).
- **MON POST-CLOSE — M4, ONE PR (item 0 governs):**
  M4.0 F1 wiring fix — `_viability_rank_key` into `get_executable_suggestions`' sort
  (paper_autopilot_service.py:118-131), flag-gated (env stays armed). THE test: viable
  outranks equal-score non-viable IN get_executable_suggestions' OUTPUT; flag-off
  byte-identical THERE. Orphan-function tests stay but don't count as wiring proof;
  rank_suggestions_canonical fate noted-not-deleted.
  M4.1 universe per M1/M2: prune SNAP·NIO·MARA·F·LYFT·AAL·RIVN (SOFI = permanent
  sentinel, code comment + rationale); DIA → tier 1.15 + one-beta note; GLD per M2;
  MRK/CVX per M1 (+ iv seeding if added).
  M4.2 doc riders: §4 corrections (ENTRY_QUOTE_VALIDATION↔#1101 kill-switch coupling;
  GTC pilot-list unset=all-eligible) · §8 additions (A9-F6 legacy-mode WARNING, A9-F7
  severity fragmentation 83%, A9-F8 one-convention detector; EXIT_EVAL_DEBUG entry
  STAYS) · breaker runbook line ("un-pause without a new WIN re-trips on zero new
  closes") · the doctrine addition above · backlog: F-A1a P2 w/ HARD TRIGGER "ship
  before any challenger reaches 8 trades"; reaper P2-ELEVATED (this week's spare slot);
  winter-close → check Tuesday PR carry else CALENDAR TRIGGER 2026-10-01; F-A2b/F-A2c
  P2 tail (batch w/ reaper if trivial).
  Tests: pruned absent · SOFI present + still gate-rejecting (sentinel pin) ·
  executor-path bias green · flag-off byte-identical. New pin on merge: **bias verified
  ON THE EXECUTOR PATH at Tuesday's 16:00Z scan.**
- **TUE POST-CLOSE — ALERT-TAXONOMY PR (approved):** split force_close →
  force_close / force_close_failed / envelope_violation_warn_only · real types for
  alert_type="warn" · normalize medium/warn severities (extend enforcement beyond
  alert() or map at write) · honest channel2-only wording for the designed client=None
  egress. CONSTRAINTS: relay/egress allowlists updated SAME PR (renamed types must not
  drop off the phone path — pin per-type egress tests) · historical rows untouched
  (readers map old types) · fingerprint continuity noted (fresh cooldown history
  acceptable, say so). Ledger line: "the phone channel stops lying."
- **NEXT SLOT — ONE-BETA BUCKET (recon-then-build):** B1 recon: PREFERRED shape =
  implement the dead `max_correlation_cluster_pct` knob as a real block-level envelope
  check with an ETF bucket map ({SPY,DIA,QQQ,IWM}=us_equity_beta), from_env loads it,
  confirm stage-time sees would-be book; FALLBACK ranker bucket factor. STOP after
  recon. B2 build: additive-only BLOCK, default-ON safety polarity, tests (2 same-bucket
  at cap → 3rd BLOCKED stamped; cross-bucket unaffected; flag-off legacy). Must land
  before the book routinely holds 2+ positions.
- Also rides any PR: OUTPUT_FRESHNESS `suggestion_rejections` @120h one-liner
  (no-weekend-exclusion caveat noted).
- **A7 MERGE + A1/A6 REFRAMES approved** — prompt v5.4 is owner-enacted after M4, not a
  session task. Retirement counters: all standing areas at 0.
- Gap-3(b): untouched, own recon-first session.
- STILL PENDING TONIGHT: 21:30Z policy_lab_eval normalized-basis close (baseline:
  no_promotion / insufficient_trades 0-and-1 vs 10; expect same verdict, job green).

## status:reported — 2026-07-04 NIGHTLY (report `audit/reports/2026-07-04.md`)

Quiet window (07-03 holiday close-of-day → Saturday): zero scans/fills/failures; both
workers SUCCESS @ `3689210` (two doc-only merges post-FULL-report, H8 clean, no recycle
since 17:43Z → env unchanged since the 15:18Z bias arming). Broker FLAT, equity =
last_equity = $2,093.74. Budgets: 14 SQL · 2 broker · 0 subagents. **NO NEW FINDINGS.**

- **⚠ OPERATOR PRECONDITION FOR MONDAY (M3): `entries_paused=TRUE` right now.** The
  breaker RE-TRIPPED 07-03 21:20:04Z on ZERO new closes (trailing-3 verbatim SOFI −40 ·
  MARA −15 · QQQ −73; paused_written=true; critical egressed `egress_owner='alert'`).
  **F-A2e LIVE-CONFIRMED <24h after being reported** — the trailing-window-every-ingest
  reading is production truth; the 07-02 PENDING wording ("next losing close re-trips")
  was the weaker reading. Un-pause any time before Mon 16:30Z buys the full session
  (breaker only evaluates at the 21:20Z ingest tail, mon–fri); expect a re-trip EVERY
  ingest night until a live WIN lands. Recovery stays operator-only (§9).
- ✅ **T2/gap-3(a) verification CLOSED**: 07-03 21:30Z policy_lab_eval GREEN on the
  normalized basis — `no_promotion`, Gate-2 insufficient_trades (conservative 0, neutral 1
  vs 10), exactly the encoded baseline. SOFI-twin magnitude proof still pends a Gate-4
  challenger. Side observation (filed under ledgered F-A1b, cited-not-refound): neutral
  eval row `capital_deployed 1876.2 / positions_opened 0` — window-artifact HYPOTHESIS;
  Gate 2 halts before utility consumes it.
- **A9-F5 rate EXACTLY confirmed**: 7 ops_data_stale highs on 07-03 (4 + 3 at
  17:37/18:37/19:37Z, halting at the 20:00Z gate) vs the "at most one" docstring. Feeds
  the Tuesday taxonomy PR context; no new finding.
- **#1114 re-verified**: 12 ops_health_check runs in 6h = 2/hour. **A3**: ingest dedup
  held (closed_positions_found=2 → duplicates skipped 2, outcomes_created=0); live
  post-epoch stays 6/8, raw mode holds. **Cooldowns**: zero active (SOFI expired
  unexercised). **A8 full protocol**: zero new negative-decision population; 30d ratio
  ≈5,603:15 (≈373:1); roundtrip-reject class still N=1; capture d8_v1 unchanged; NEW
  observation — policy_lab `decision_accuracy.rejection_accuracy` (n=7, informational) is
  the lens's first in-system consumer at cohort grain; per-gate efficacy still unmeasured.
  **A10**: no new instance (holiday patterns exercised as spec'd); retirement counter 0→1.
- Heartbeat UP-email confirm still operator-side; weekend cron silence = no false DOWN
  expected before Mon 08:00 CT.

PENDING VERIFICATIONS (2026-07-04 consolidation — the Monday list, gated on the un-pause):
- **Operator un-pause + ACK the 21:20:04Z breaker critical BEFORE Mon 16:30Z** (else the
  staging proof and all downstream M3 proofs silently no-op again).
- Mon 07-06: 16:30Z staging proof · typed-segment forward row · first live
  [CLOSE_FILL_GAP] gap_fraction · breaker re-eval at 21:20Z (zero-close day → re-trip
  EXPECTED) · #1115 job_late Monday storm = 0 · M1 MRK/CVX RTH re-screen · M2 GLD recon ·
  M4 PR (item 0 = F1 wiring fix; new pin: bias verified ON THE EXECUTOR PATH at Tuesday's
  16:00Z scan).

## status:reported — 2026-07-06 NIGHTLY (Monday 00:00 CT scheduled run, pre-RTH; report `audit/reports/2026-07-06.md`)

Dead-quiet window (07-04 report → 07-06 05:01Z): the ONLY job_run was `phase2_precheck`
07-06 05:00:02Z green; zero fills/orders/scans/suggestions/rejections/alerts (any
severity); zero cooldowns; both workers SUCCESS @ `3689210` = origin/main (no deploys or
recycles since 07-03 17:43Z → env unchanged since the 15:18Z bias arming, by
construction). Broker FLAT, equity = last_equity = OBP = $2,093.74. Budgets: 9 SQL ·
4 broker · 2 Railway · 0 subagents. **NO NEW PRODUCTION FINDINGS.**

- **⚠ OPERATOR PRECONDITION STILL OPEN at run time (05:01Z): `entries_paused=TRUE`**
  (unchanged since the 07-03 21:20:04Z re-trip; reason verbatim SOFI −40 · MARA −15 ·
  QQQ −73). Un-acked critical/high = 8, all 07-03 (1 breaker critical `c598eec4` + 7
  holiday `ops_data_stale` highs). This report is the LAST audit checkpoint before the
  Mon 16:30Z window — un-pause + ACK first thing.
- **AUDIT-LOOP OBSERVATION (local tooling, not production): the Sunday 07-05 FULL run
  never started** — `audit/cron.log` has no start marker between Sat 07-04 00:01 (exit
  0) and Mon 07-06 00:00:02 (this run); Task Scheduler didn't fire (machine off/asleep
  HYPOTHESIS). Realized cost $0 (weekend retroactively verified silent); class = the
  watcher has no watcher. Fix (operator-side, additive): Task Scheduler "run after
  missed start" + "wake to run" on `\nightly-audit`; optional #1109-symmetric
  healthchecks ping on report write. Same log shows 3 historical start-without-end
  markers (06-14, 06-20, 06-30).
- **A3 window-slide note (not new data):** paper 30d reads n=8 / −2,062.80 (was 9 /
  −1,870.80) — writer ran 0× in window; one early-June positive paper row aged out of
  the sliding 30d window. Live unchanged: n=6 / −153.00 all post-epoch; raw mode holds
  at 6/8.
- **A5 lesson:** 2 of 9 SQL wasted on 42703s (`job_runs.job_type`→`job_name`,
  `reentry_cooldowns.expires_at`→`cooldown_until`) — the introspect-first rule applies
  to EVERY table not queried this session, not just learning tables.
- A8 full protocol: zero new negative-decision population; 30d ratio ≈5,255:14 ≈375:1
  (both sides sliding); roundtrip-reject class N=1 all-time; counterfactuals correctly
  empty (market closed). A9: zero new alert rows → nothing to measure; Tuesday taxonomy
  PR stands. A10: no new instance; retirement counter 1→2.

PENDING VERIFICATIONS (2026-07-06 — the Monday list, unchanged + one added):
- Standing Monday list above (un-pause gate · staging proof · typed-segment ·
  [CLOSE_FILL_GAP] · 21:20Z breaker re-eval · #1115 job_late storm=0 [checkable at
  Tuesday's nightly] · M1/M2/M4).
- NEW: operator decision on the missed Sunday FULL — wait for 07-12 vs one mid-week
  FULL after M4 + taxonomy land (NIGHTLY tonight was contract-correct; the FULL cadence
  slipped silently).

---

## 2026-07-06 POST-CLOSE — M4 SHIPPED + ERRATUM + INVERTED-UNIVERSE MARKER

- **⚠ INVERTED-UNIVERSE MARKER (07-06 16:00Z scan — EXCLUDE from gate evidence):**
  Alpaca nulled the retired PDT daytrade fields (weekend 07-04) → `int(None)`
  TypeError in `alpaca_client.get_account()` serializer → OBP read died → $500
  `paper_baseline_capital` fallback → `get_tier(500)`=micro → $60 underlying cap →
  56 `micro_tier_underlying_too_high` rejections → zero candidates at 16:30Z
  executor. Today's zero is the INCIDENT's zero, not the gates' — classified (c),
  excluded from honest-economics and gate-behavior baselines (like the 07-03
  holiday). Scan budget observed deployable=500/cap=450 vs healthy 2093.74/837.50.
- **ERRATUM (process, 07-06 ~19:10–19:25Z):** a compaction-summary date phantom
  ("Tue 07-07") + stale context header (07-01) made a 4-minute-old job_runs row
  (19:05Z) read as a 23h scheduler outage; reported to the operator as a system-wide
  incident with a fabricated-by-arithmetic healthcheck-email claim. Operator
  authorized a BE restart on that false report: redeploy `1b3e7dcd`, same SHA
  `3689210`, swap 19:24:25Z, ZERO missed ticks (19:25:01Z order_sync dispatched by
  the new container, succeeded end-to-end). No incident existed — 143 jobs green
  that day. Same class as the 06-11 deploy-lag erratum + 07-03 holiday false alarm.
  **Fix shipped: STEP 0 clock grounding** (DB `now()` + broker `get_clock` BEFORE
  any time arithmetic; clocks beat headers/summaries/stated time) — operator
  directive, now CLAUDE.md §1 first corollary + session memory.
- **M1 verdict (MRK/CVX RTH re-screen, closed 07-06):** MRK = NO ($41–46/ct
  round-trip crossing on every pair sampled RTH). CVX = MARGINAL-ADD ($25–29/ct on
  healthy-OI 170/175 strikes; the $19 headline pair was a dead-OI mirage) → CVX
  added with iv-seeding (60d) + viability tier 1.15.
- **M2 verdict (GLD strike modulus, closed 07-06):** built as one-line-config at
  the `_split_chain_to_calls_puts` seam — `SCANNER_STRIKE_MODULUS` env (default
  "GLD:5"), subset-or-fallback (never filters to empty). OI-floor generalization
  filed as follow-up (backlog).
- **M4 SHIPPED (this squash):** item 0.1 serializer null-tolerance
  (`_req_float` fail-loud-by-name on required fields; retired daytrade fields
  null→placeholder) · item 0.2 fail-CLOSED capital (live-mode OBP-None → critical
  `account_unreadable_entries_blocked` + deployable 0.0 → CapitalScanPolicy blocks
  the cycle; $500 baseline survives ONLY explicit paper mode; unreadable ops mode
  = live) · item 0.3 pin tests (12 new-file + the CONTRACT-CHANGE rewrite pair in
  test_capital_basis_consistency replacing
  `test_falls_back_to_paper_baseline_on_alpaca_failure`) · item 0b **#1126 bias
  WIRED into the production path** (`get_executable_suggestions` sort at
  paper_autopilot_service.py; sort-key-only, positive scores only, flag-off
  byte-identical; EXECUTOR-PATH wiring test per the new §9 never-do) · item 0.4
  OBP-failure alert wording (consequence now truthful) · M2 modulus · tiers
  +DIA/CVX/GLD 1.15 · OUTPUT_FRESHNESS + suggestion_rejections/120h · CLAUDE.md
  riders (STEP 0 corollary · #1038/#1101 kill-switch coupling · GTC pilot
  unset=ALL correction · #1119 runbook line · §8 A9 additions · §9 two never-dos)
  · backlog riders (F-A1a trigger, reaper P2-elevated, winter-close 2026-10-01
  calendar trigger, OI-floor).
- **Post-merge DB mutations (operator-approved, executed tonight):**
  scanner_universe deactivate SNAP/NIO/MARA/F/LYFT/AAL/RIVN (SOFI stays —
  permanent roundtrip-gate sentinel) + add CVX; `iv_historical_backfill` enqueued
  {symbols:["CVX"], days:60}.

PENDING VERIFICATIONS (2026-07-07, added by the M4 ship):
- **Post-fix live proof (first healthy scan):** scan budget deployable≈2093.74 /
  cap≈837.50, tier=small, ZERO `micro_tier_underlying_too_high` rejections.
- **Bias first live cycle:** executor log shows viability-biased ordering (flag
  armed since 07-03); flag-off comparison not required — wiring test pins it.
- **GLD modulus first scan:** GLD rejections collapse to $5-strike population only.
- **CVX:** IV-integrity-ELIGIBLE as of 07-06 20:28Z — days:90 top-up
  (job f5f7b8be, 111s) after the days:60 seed (a06c143d): 84 distinct
  non-null iv_30d days (2026-03-02→06-30), 0 dup (underlying,as_of_date),
  idempotency held (skipped_existing=55/ok=29/failed=0). Gate rule cited:
  iv_repository.py:26 MIN_IV_HISTORY_DAYS=60; :224-249 sample COUNT of
  non-null iv_30d rows (≤252 recent) — contiguity irrelevant; scanner
  rejection seam options_scanner.py:3060-3067. PIN (16:00Z scan, 11:00 CT):
  CVX in the scanned set, iv_rank computed (sample_size 84+), NO
  iv_rank_insufficient_history rejection for CVX; if it candidates, first
  roundtrip-gate evaluation with verbatim numbers (expect MARGINAL vs $15).
- **21:20Z breaker re-eval (tonight):** expected RE-TRIP (no live win 07-06) —
  critical + email is DESIGNED (runbook); un-pause remains operator-only.

2026-07-06 POSTCLOSE AUDIT (v5.4 first run, operator-invoked; report
`audit/reports/2026-07-06-postclose.md`) — status:reported:
- **A9 FINDING — egress delivery-receipt gap**: `_maybe_egress_risk_alert`
  discards send_ops_alert_v2's result (alerts.py:85-95); success logs at
  invisible info (ops_health_service.py:1379); `egressed_at` never stamped
  by inline sends — safety-trip delivery disputes close on inference, not
  fact (tonight's breaker-email triage = 4 evidence hops). FIX (additive):
  capture insert id → post-send metadata UPDATE {webhook_sent, egressed_at,
  suppressed_reason} + warning-visible receipt log both outcomes. RIDES THE
  TAXONOMY PR (same files, one recycle).
- Pins P1–P5 all PENDING → converge on 07-07 16:00–16:30Z + first close.
- Free-look: broker 0 open orders / 0 positions on flat book (no orphaned
  GTC); fossils unchanged (22 queued / 4 stuck-running).
- Counters: A9→0, others →3 (A7 dormant). No retirement candidates.

## 2026-07-11 (Sat ~02:2x ET) — BUILT: observability remainder — 5 noise classes (#1156)

STEP-0: broker 02:27 ET CLOSED (Sat). **#1156 `cb82692` MERGED + H8 VERIFIED**
(BE `15ac9053` / worker `4c648035` / worker-background `0aed1f7a`, all SUCCESS @
`cb82692`, created 06:45:38–39Z > merge 06:45:36Z). Queue ② — the five items
left after F-A4-1 absorbed the A4-detector half.

1. **Flat-book stale guard** (`get_output_freshness`): count open positions
   once; a flat book (0 open) → `paper_positions.last_marked_at` reads `flat`
   (no alert), not `stale` (~48/day false-HIGH). A HELD position past TTL still
   fires; fail-safe on count error. Both directions tested.
2. **Condition re-emit dedup** (`job_succeeded_with_errors`): **RECON
   CORRECTION** — cross-owner ROW dedup already works (`egress_owner`); the real
   4× was same-condition re-emit. Fingerprint by RUN_ID + 24h cooldown → once
   per run, not 14×. Genuine safety trips (force_close / streak_breaker_* /
   force_close_failed) UNAFFECTED (they keep the shared cooldown).
3. **Accuracy-warn dedup**: fold `wins/n` into the fingerprint (re-alert on
   VALUE CHANGE) + 24h cooldown. Stays observe-only.
4. **IV all-missing → PARTIAL** (chosen per the F-A4-1 contract): `ok==0` with
   symbols present → `counts.errors` → the runner records `partial`.
   Some-missing (ok>0) stays green (individual seasoning is normal).
5. **Stub-vs-real watch**: `EXPECTED_JOBS` now watches `paper_learning_ingest`
   (the real EOD producer, scheduler.py:69), not the `learning_ingest` no-op
   stub. test `DAILY_JOBS` + the `.eq→.in_` mock updated.

Expected H11 delta: **~60+/day quieter** (48 stale + 10–14 accuracy + the
condition re-emits). **⭐ v1.2 report file now ON DISK** (operator dropped it
via #1155, `docs/review/external-full-audit-v1.2-2026-07-10.md`) — the standing
sweep is CLOSED; the I6 wording-fix-inside-the-file remains a pending one-liner.
Untouched: E7 (queue ③, spec on file) · PR2 · F-A3-1 · trading logic.

## 2026-07-11 (Sat ~01:1x ET) — BUILT: F-A4-1 typed job-outcome contract + fossil reap (#1153)

STEP-0: broker 01:54 ET CLOSED (Sat) / DB ~05:5xZ. **#1153 `2478845` MERGED +
H8 VERIFIED** (BE `423bec81` / worker `f0b6b0f2` / worker-background `88f466a7`,
all SUCCESS @ `2478845`, created 06:16:08–09Z > merge 06:16:06Z). ROLLOUT
INVENTORY (post-recycle): **fatal_masked_green=0** (clean — no hidden failures
exposed; the danger was 0-instance pre-build), fossils_remaining=0,
partial_rows=0 (weekend — Monday's runs first exercise the contract), reaped=27.

**PRE-STEP — FOSSIL REAP (supervised):** 27 stranded rows (22 queued + 5
failed_retryable, 19–179d, none needing replay) dead-lettered with a
move-don't-lose annotation (prior_status / days_stale / reason). Before 27,
after 0.

**THE CONTRACT.** The runner recorded a handler's RETURNED failure as
'succeeded' (keyed success solely on `users_failed>0`); a fatal monitor that
returned `{ok:False}` (intraday_risk_monitor / post_trade_learning /
day_orchestrator) was recorded succeeded + invisible to the A4 detector.
- **DESIGN — RAISE-not-return:** the 3 swallow-fatal handlers DELETE their
  catch-all `{ok:False}` returns and RAISE; the runner's exception path owns
  fatals (→ failed_retryable, visible; the next cron re-runs regardless).
- **`_classify_handler_return`** (module-level, testable): derives a REAL
  terminal `partial` from the return — `users_failed>0` OR `counts.errors>0` OR
  a truthy top-level `error` key (future-proofs a new swallow-return).
  Designed-false handlers (ops_health_check `ok:False`→now `ok:True`+`healthy`;
  executor `status:partial`; policy_lab `status:error`) carry none → succeeded.
- **`partial` is a real status** (was mislabeled `failed_retryable`, which the
  scheduler WRONGLY retried + the dependency filter MISSED). EVERY job_runs.status
  consumer from the B2 list migrated: ops_health_service liveness/freshness/
  regime/A4 (`.in_ succeeded,partial`), runner terminal-skip + public_tasks
  TERMINAL_STATES + JobStatus enum, **JobDependencyService phantom
  `partial_failure`→`partial` FIXED**, dashboard (partial→degraded). Scheduler
  retry keys on `failed_retryable` only → partials no longer wrongly retried.
  8 consumer tests updated (mock `.eq`→`.in_`; `ok`→`healthy`) — contract-update
  discipline, not a defect.
- **⚠ `failed_retryable` is now an HONEST LABEL, not a working retry** —
  re-dispatch lands with the **F-A4-2 + reaper** package. **The `mark_retryable`
  finished_at fix is DEFERRED to F-A4-2** (coupling: setting it now + the broken
  re-dispatch would create fossils via the scheduler's flip). C3 verdict: TWO
  builds.
- **ABSORBED obs-PR-#1's A4-detector half** (the `partial` status IS the
  silent-failure signal now). **obs-remainder (queue ②) = flat-book stale
  guard · cross-owner re-egress dedup · accuracy-warn dedup · iv-refresh
  all-missing→ok · stub-vs-real-producer watch.**
- RESIDUAL (cosmetic follow-up): paper_auto_execute still emits `ok:false` on
  gate-rejects (exact return literal not located; the runner ignores `ok`, so
  it is correctly `succeeded` — just ~21 designed-false rows of false-green-query
  noise; ops_health_check's 332 were relabeled).

Untouched: E7 re-wire (queue ③, spec on file) · PR2 client_order_id · F-A3-1 ·
all trading logic. ⚠ The v1.2 report file is STILL not on disk — sweep pending.

## 2026-07-11 (Sat ~01:04 ET) — EXTERNAL AUDIT v1.2 ADJUDICATION (verified vs code@e45290f + DB + broker)

STEP-0: broker 01:04 ET CLOSED (Sat) / DB 05:04Z — agreed. READ-ONLY + doc
writes. ⚠ The v1.2 report file is NOT on disk (`docs/review/` has only the
07-09 packet + v1.1 prompt) — adjudicated from the operator's inline cites;
sweep pending the file at `docs/review/external-full-audit-v1_2-2026-07-10.md`.

**P0 — F-A4-1 (fatal handler results persisted as succeeded) → CONFIRMED
STRUCTURAL, 0 FATAL INSTANCES (bounded).** Chain verified: `runner.py:134`
success keys SOLELY on `users_failed>0` — `ok:false` / `status:partial` /
`counts.errors` all fall to `mark_succeeded` (`job_runs.py:125` writes
`status='succeeded'` blind to the body); `intraday_risk_monitor.py:152-158`
RETURNS `{"ok":False,"error":...}` on a FATAL exception (no `users_failed`, no
`counts`) → recorded succeeded; the A4 detector `ops_health_service.py:669-681`
reads ONLY `counts.errors` → the fatal return is doubly invisible. **No
normalization layer exists (confirmed).** HEADLINE QUERY (45d): 356
`succeeded`+`ok=false` rows BUT **fatal_masked_green = 0 on every job**
(`result ? 'error'` = 0) — the 356 are DESIGNED ok=false (ops_health_check ×332
detecting alerts · paper_auto_execute ×21 gate-rejects · suggestions_open ×3);
**ZERO intraday_risk_monitor false-green rows** — no protection cycle has ever
failed green. So the finding is real-but-unexercised: critical as a CLASS (the
plane beneath all job monitoring), blast radius bounded, rollout won't expose a
hidden backlog (0 current fatals). NEW HEADLINE BUILD (typed outcome contract).

**P1 — E7 (viability bias bypassed) → CLOSURE FALSE = THIRD #1126 INSTANCE.**
The active executor route is `_execute_per_cohort` (`paper_autopilot_service.py
:864-865`), which sorts via a Supabase `.order("risk_adjusted_ev").order("ev")`
on the STORED column. The M4/#1132 viability bias is sort-KEY-only (never
persisted) and lives in `get_executable_suggestions` (`:130,141`), reachable
only at `:506` — AFTER the `:452` early `return self._execute_per_cohort(...)`
when policy-lab is on (the live 3-cohort arch). The wiring test
(`test_m4_obp_failclosed_and_wiring.py:174`) source-string-asserts the DEAD
route — the exact #1126 tell. **The bias is armed + green-tested but INERT on
the live route.** Fix: re-rank the fetched `suggestions` list in Python inside
`_execute_per_cohort` + a test that drives THAT route. (rank_suggestions_canonical
still has ZERO production callers.)

**P1 — F-STATE-I6 → RESOLVED (prompt-wording artifact).** "merged package" =
merged into ONE EPIC (P0-B book-scaling readiness, backlog-level), never
claimed code-shipped; the substantive point (unbuilt, tripwire-only guard) was
already our STATE. Nothing else read "merged" as shipped. Fix the language in
the canonical v1.2 file when placed.

**P2 — HIGH-CONSEQUENCE LATENTS:**
- **F-A10-1 → CONFIRMED (split), LATENT.** (a) missing/unparseable expiry →
  `paper_exit_evaluator.py:158` returns 999 DTE → DTE-based exit conditions
  silently skipped (fail-OPEN; only on absent/corrupt expiry). (b)
  assignment-created EQUITY filtered out of the option sync
  (`alpaca_client.py:540-543`, `len(symbol)>10` heuristic) → unmanaged stock;
  both reconcile paths consume the option-only set. Book flat now → unexercised.
  Assignment-adjacent (A2 charter).
- **F-A2-1 → CONFIRMED (code), likely-not-live-exercised.** The POST-FILL hook
  `maybe_place_gtc_profit_exit` (`gtc_profit_exit.py:328-464`, wired at
  `alpaca_order_handler.py:944`) NEVER checks the pilot allowlist — it parks a
  GTC for any eligible live multileg entry; only `GTC_PROFIT_EXIT_ENABLED`
  (default OFF) gates it (the sweep path DOES check the allowlist). DB: 6
  `intentional_resting_exit` orders (all cancelled, 06-13→07-08) — consistent
  with the pilot sweep; no confirmed out-of-pilot placement (flag OFF). Priority
  jumps only if the flag goes ON before the allowlist is enforced on the hook.
- **F-A3-1 → CONFIRMED (both), NEW loss paths.** Outcome ingest NOT conserved:
  window filter (`:230-235`, 7d roll-off) + silent no-filled-closing-order drop
  (`:382-386`, `skipped_no_order` local-only). Exit cause ERASED: the LFL row
  (`_create_paper_outcome_record`) writes a static `reason_codes:
  ["paper_trade_close"]`, never `position.close_reason` — the learning chain
  never sees WHY a trade closed (close_reason IS carried, but only to
  `policy_decisions.realized_outcome`, a different table, policy-lab-gated).
  Mechanism is DISTINCT from the NFLX-06-08 epoch exclusion (new paths). Feeds
  the thesis-tracker (I5) — amend its charter.
- **F-A4-2 → CONFIRMED (silent-zero).** The automatic retry
  (`runner.py:142-176` → `mark_retryable` → `requeue_job_run` RPC) only FLIPS DB
  state; no `q.enqueue`, no RQ push. DB residue: 22 `queued` (latest 06-22) + 5
  `failed_retryable` (04-10) that never re-ran — the known 22-fossil class, now
  mechanism-explained. Live workers are RQ (no DB-poller in repo). Fix: re-enqueue
  on mark_retryable (or a DB-poll re-dispatcher).

**P3 — REGISTER SWEEP (one-liners):** F-A6-2 REFUTED (counters increment AFTER
eligibility) · F-A3-2 PARTIAL (autotune versions ARE read; but AUTOPROMOTE off
+ unscheduled → logged-not-applied, flag-gated compute-not-apply) · F-A9-1
CONFIRMED ("Confidence N%" from `overall_score`, a 0-100 rank not a probability
— mislabel; `SuggestionCard.tsx:683`) · F-A9-2 REFUTED (UI statuses still
emitted) · F-A8-1/2 PARTIAL (`suggestion_rejections` stores flat reason, no
economics/error category — conflated, not mis-assigned) · F-A10-2/3 PARTIAL
(weekday-only holiday-blind ops checks, BUT execution/monitor defer to broker
`get_clock` which knows holidays; session hours correct; no native calendar) ·
F-A5-1 CONFIRMED (`phase2_precheck` past its 48h self-expiry → `window_expired`
no-op every run; machine-consumed by nothing — dead precheck).

**ECONOMICS (their sharpening):** re-verified on today's live candidate — QQQ
16:00Z calibrated `ev 18.73` (=37.46×0.5), `net −15.27 < floor 15` → does NOT
clear; SOFI `edge_below_minimum`. STRENGTHENS the A6 SETTLED 1-of-N verdict
(does not contradict). Their 78%-thesis caution (5/9 horizons incomplete, n=8)
→ the thesis figure is a directional estimate on a tiny, partly-open sample;
the thesis tracker (I5) is the resolution path.

**EXTERNAL v1.2 SCORECARD (their 3rd engagement):** high hit rate — F-A4-1
(structural CONFIRMED, the class fix), E7 (a real 3rd #1126 instance we missed),
F-A3-1/F-A4-2/F-A5-1/F-A9-1 all CONFIRMED; the rest PARTIAL/REFUTED with the
distinction named. Q1-class method holds; weight high. Two calibrations: F-A4-1's
DANGEROUS manifestation is unexercised (0 fatal); F-A2-1 is flag-gated-off.

## 2026-07-10 (post-close ~16:21 ET) — BUILT: P0-A broker-acknowledged live-close invariant (#1149) [PR1 of 2]

STEP-0: broker 16:21 ET CLOSED (re-confirmed pre-merge) / DB 20:21Z. Post-close;
the live close path — no RTH exceptions. **#1149 `e45290f` MERGED + H8 VERIFIED**
(all three services SUCCESS @ `e45290f`, created 20:21:39–41Z > merge 20:21:37Z).

**E6 EXCLUSION-INTEGRITY FAIL → REMEDIATED (PR1).** Closure claim rewritten to
match the code: *"a live-routed close requires a broker acknowledgement; the
internal-fill block is STRUCTURALLY UNREACHABLE for live routing; every failure
lands in an explicit alarmed non-terminal state (`unknown_reconciling`),
position OPEN — never a silent internal fill."* The 2026-04-16 ghost-position
class is closed in code.

**RECON (STOP-IF-SURPRISED — no surprise in the chain):** the 4 cites re-verified
(routing default False + warn-proceed `:1700-1727` · submit result discarded,
`routed_to='alpaca'` unconditional `:2154-2177` · raised-submit → internal fill
`:2178-2280` · monitor costume `:1428`). ENTRYPOINT MAP: only entrypoints **1**
(scheduled exit evaluator) + **2** (monitor force-close) reach the fallthrough;
resting-TP/GTC (3,5), reconciler (6), orphan-repair (7), `_commit_fill` (8)
close on broker truth or are paper-only; manual endpoint (4) branches on process
`EXECUTION_MODE`, no internal-fill-on-exception. **THE MATERIAL FINDING (→ PR2):**
`client_order_id` is NEVER set at submit — the only broker handle (`alpaca_order_id`)
is lost exactly in the response-lost case; the charter's targeted lookup needs a
submit-path change (PR2). PR1 holds the response-lost case OPEN + alarmed —
invariant still fully held.

**BUILD (PR1):** STRUCTURAL GUARD before the internal-fill block —
`should_submit_to_broker` True → held open (needs_manual_review +
`force_close_failed` critical + `routed_to='unknown_reconciling'`); internal-fill
UNREACHABLE for live; fail-closed on a routing exception; shadow/paper unchanged.
Submit-exception "fall back to internal fill" REMOVED → same held-open. Routing-
query-failure fail-CLOSED (`position_is_alpaca=True` → authoritative portfolio
gate). Monitor success-costume fixed — only a COMPLETED close = success;
`unknown_reconciling` → not-closed, no bench. **`force_close_failed` gets its
FIRST real close-path producer** (allowlisted immediate-egress since #1134).
Reconciler's existing targeted `get_order(alpaca_order_id)` resolves case-(a)
pending closes; case-(b) `client_order_id` auto-resolution is PR2. Additive
(status TEXT, no migration). Tests: `TestAlpacaSubmitFallbackCriticalAlert` (pinned
the REMOVED fallback) → `TestP0ABrokerAckCloseInvariant` + new
`test_p0a_broker_ack_close.py` (guard decision behavioral + 4 seams pinned on
production); 120 exit/monitor tests green; full `_close_position` integration
deferred to PR2.

**CHARTER: BUILT (PR1).** Remaining (PR2, own session): deterministic
`client_order_id` at submit + reconciler `get_order_by_client_id` auto-resolution
of the response-lost `UNKNOWN_RECONCILING` edge. Untouched: stop TRIGGER logic
(what fires a close = Phase-3's territory) — PR1 changes only what happens AFTER
the decision to close.

## 2026-07-10 (early, ~00:1x ET post-close) — BUILD: PoP clamp-AND-log + walk-forward field contract (#1147)

STEP-0: broker 00:08 ET (closed) / DB 04:08Z — agreed. Combined Tier-1 PR per operator GO.
**#1147 `168a752` MERGED + H8 VERIFIED** (BE `5e1d241b` / worker `8a913217` /
worker-background `ca1da3cb`, all SUCCESS at `168a752`, created 04:57:01-02Z >
merge 04:56:59Z). Item 1 rides the recycle via calibration_service; Item 2 is
in zero live paths.

**ITEM 1 — PoP clamp-AND-log (fork verdict: MULTIPLIER overshoot; clamp, not
formula).** The delta-PoP composition (`ev_calculator`, convex combination) is
bounded ≤1 — raw `pop_raw` max 0.7945, 0 rows >1. The >1.0 originated ONLY at
`apply_calibration` (`pop × pop_mult`), already SILENTLY clamped since
2026-04-16 (`calibration_service.py:629`; last >1 row 04-16 16:00Z, zero after).
Made LOUD: `POP_CLAMP_ENGAGED` WARNING (raw pop · mult · product · clamped ·
strategy/regime/dte). **DORMANT-BY-ARITHMETIC:** pop_mult floored at 0.5 and
currently at the floor → pop×0.5 can never breach 1.0, so the log CANNOT fire
today — insurance for the day the multiplier climbs >1.0, NOT dead/broken code
(recorded so a future session doesn't misread "never fires" as broken). Legs
out of scope at the apply site. NO delta-path clamp (would be unreachable —
SKIP per operator).

**ITEM 2 — walk-forward field contract (fork verdict: HONEST CRASH, never
run).** `walkforward_validate_learning_v3.py` read `ev`/`realized_pnl`/`score`;
the VIEW `learning_trade_outcomes_v3` exposes `ev_predicted`/`pop_predicted`/
`pnl_realized` (+strategy/regime). Full rename — the recon's TWO-field diff was
actually FIVE (ev_predicted + pop_predicted + pnl_realized + strategy + regime
resolution; contract-audit catch). DELETED the H9-violating `0.5` prob
fabrication → fail loud. Added `WalkForwardContractError` on zero rows OR a
missing required column (closes the lying-empty class). NO view migration —
strategy/regime already exist + 99/99 populated. **SMOKE-RUN (read-only, n=99)
surfaced a SECOND real bug:** mixed microsecond/whole-second timestamps broke
`pd.to_datetime` → fixed `format='ISO8601'`. Script now runs to completion
honestly (exit 0; tiny-sample NaN Brier; no fabrication) — the rename is DONE,
the script has read the real columns once.

**RECONCILIATION 34→22→16.** The pollution has ONE home:
`trade_suggestions.probability_of_profit` (16 rows). The v3 VIEW's
`pop_predicted` is a JOIN-projection of `ts.probability_of_profit` (view def
confirmed); `learning_feedback_loops` stores no own pop. So 34 AND the earlier
22 were both view+base double-counts of the same 16. **DISPOSITION = ANNOTATE
(not re-derive), supervised, base table:** all 16 `trade_suggestions` rows
annotated (`marketdata_quality.pop_gt1_annotation`, `disposition=
annotate_not_rederive`, `original_pop` recorded), `probability_of_profit`
PRESERVED unchanged; before+after read-backs shown. All pre-04-16, paper,
consumed by nothing live.

**ERRATUM (the premise-check doctrine working).** The 07-10 build spec's ITEM-1
fork verdict placed the overshoot at the delta-cushion composition path; the
pre-build premise check re-confirmed the actual site (calibration multiplier,
already clamped 04-16) and prevented shipping a dead-code clamp. The
fork-verdict METHOD held; the SITE (in the spec AND in the original v1.2
free-look "delta-based overshoot; one-liner clamp") was wrong — corrected here
+ in backlog.

**RIDERS FILED.** (i) PoP CENSUS — verified **7 base PoP computations**
(ev_calculator.calculate_pop; calculate_exit_metrics `abs(delta)` = the
take_profit_limit source; calculate_condor_ev; options_scanner
`_estimate_probability_of_profit`; `_condor_pop_from_legs`;
opportunity_scorer `_calculate_ev_pop`; forecast_interface `forecast_ev_pop`)
+ 2 transforms (apply_calibration, conviction) — NOT "5" (the spec undercounted).
The inverted credit/width one (F-A3-1, latent) is calculate_pop's credit branch.
Rider on the multi-basis/PoP-unification item: **"the unified PoP MUST
bound-assert [0,1] at the compute site"** — the insurance lands once, at the
right place, when that work runs. I touched only the calibration-apply clamp (a
transform), NO base computation. (ii) Clamp boundary-log review trigger:
frequent `POP_CLAMP_ENGAGED` → cushion/multiplier revision, WITH the dormancy
note (can't fire while pop_mult ≤ 1.0). (iii) Prequential UNBLOCKED — the A1a
field-contract prerequisite is CLOSED; remaining for that build: add the
`is_paper=false` live-only filter (smoke-run used 99 mixed rows) + confirm
`ev_predicted` is RAW not calibrated.

## 2026-07-09 EOD (latest) — COMPARATIVE-RECON INTEGRATION (v1.2) + v5.5 CANONICAL

STEP-0: broker 19:35 ET (closed) / DB 23:35Z — agreed. Doc/prompt writes only,
runtime-inert (prompt files read by `run-nightly.cmd` + humans, not services).

**A1 VERIFICATIONS (the recon's two falsifiable code claims + two gated grades):**
- **A1a field contract → CONFIRMED.** `walkforward_validate_learning_v3.py`
  reads `learning_trade_outcomes_v3` expecting `ev`/`expected_value` +
  `realized_pnl`/`pnl`; the table exposes `ev_predicted`/`pnl_realized`
  (+`pnl_predicted`/`pop_predicted`) → `KeyError` at `df['ev'].fillna` (`:101`).
  Script cannot honestly validate the view → field-contract fix folded into the
  calibration-ordering item.
- **A1b F-A2-1 vs recon #4 → MERGE.** F-A2-1's charter had the invariant but no
  explicit reconciling state; the recon supplies `UNKNOWN_RECONCILING` + typed
  transitions + targeted client_order_id lookup + fill+closure invariant
  (Nautilus/Hummingbot cites). Merged into P0-A (what it lacked: the state
  machine + the targeted lookup).
- **A1c(i) replay substrate → CONFIRMED ~55%, but WORSE than graded.**
  `from_decision_id` = ZERO production callers (docstrings + 1 test); capture
  tables `decision_runs`/`decision_inputs`/`decision_features` EXIST **but hold 0
  ROWS** — schema-only, nothing writes them. The replay item's prereq (capture
  rows) is UNMET → its drop-condition fired → item rescoped to include a
  capture-WRITE path first.
- **A1c(ii) earnings gate → CONFIRMED.** `options_scanner.py:3866-3879` gates on
  `days_to_earnings<=2` (hard) / `<=7` (penalty) only — NO event-before-expiry
  check. Grade holds.

**RECON SCORECARD:** claims spot-checked where falsifiable were evidence-verified
(A1a field mismatch, A1c earnings gate, replay caller/schema); coverage grades
materially correct (replay ~55% — adjusted down for the 0-row capture);
falsifiers carried verbatim into the items as retirement conditions (the GOLD
prequential falsifier especially). Recon method: sound; one grade optimistic
(assumed capture rows existed).

**CORRECTION to OUR earlier framing (A2.7, move-don't-lose):** the recon
confirmed **21-DTE / 50%-credit / DTE gates already ~85% EXIST in cohort
policy** — the earlier deep-dive's "position-management conventions missing"
impression is WRONG and is corrected here + filed in the DO-NOT-RE-LITIGATE
backlog section. Do not re-derive them as a new build.

**BACKLOG DIFF:** P0-A absorbed recon #4 state machine; calibration-ordering item
absorbed recon #2 (prequential + A1a field-contract fix + GOLD falsifier); NEW P1
deterministic replay (+ 0-row capture prereq); NEW P2 versioned earnings cohort
(fix gate to event-before-expiry, observe-first); NEW P2 per-leg entry quote
envelope; DO-NOT-RE-LITIGATE standing section seeded.

**v5.5 CANONICAL ON DISK:** `audit/v5-prompt.md` upgraded to v5.5 ELEVEN AREAS
(A1-A9 + A10 rotating Calendar&Clock + A11 permanent Self-Extension) at this SHA;
STATE refreshed to tonight; external prompt STATE re-stamped. **Prompt-drift class
CLOSED: the invoked file (`run-nightly.cmd:8` → `audit/v5-prompt.md`) IS the
version of record; session-prompt changes MUST land here same-day.** Tonight's
midnight run is the first eleven-area (v5.5) nightly.

## 2026-07-09 EOD (late) — EXTERNAL AUDIT v1.1 ADJUDICATION (P0/P1 verified vs code+DB+broker)

STEP-0: broker 19:15 ET (closed) / DB 23:15Z — agreed. READ-ONLY + the one
pre-authorized security commit. Book FLAT now (0 open, 0 live-routed).

**P0-1 CREDENTIAL (F-FREE-1) → LOCAL-ONLY-FAKE (NOT a live compromise).**
`.env.example` (git-tracked since the 2025-11-19 initial commit `82e8ef8`)
carried real-shaped Supabase anon + `service_role` + S3 keys. Fingerprint:
URL is `http://127.0.0.1:54321`, keys are modern `sb_publishable_`/`sb_secret_`
format; production `etdlladeorfgdmsopzmz` exposes a legacy JWT anon key at its
cloud URL — different host/format/value. **No production credential exposed →
no live rotation warranted.** Pre-authorized scrub SHIPPED as placeholders
(PR #1145, `95d3bb5`, NOT merged — left for operator). OPERATOR ITEMS (not
done): git-history cleanup (BFG/filter-repo of the pre-scrub blob) + GitHub
secret-scanning/push-protection enablement. Even LOCAL keys public 8 months
= rotate the local stack at leisure.

**P0-2 LIVE-CLOSE CUSTODY (F-A2-1) → LATENT (chain real, NEVER fired).**
All four sub-claims CONFIRMED at the deployed SHA (d45ad63):
(i) `paper_exit_evaluator.py:1700` `position_is_alpaca=False` default +
`:1712-1727` routing-query failure only WARNs (`paper_exit_routing_query_failed`,
no raise); (ii) `:2162` `submit_and_track` result discarded, `:2172-2177`
returns `routed_to='alpaca'` unconditionally; (iii) `:2178-2207` a RAISED
submit exception (from `get_alpaca_client`/order fetch/imports/the pre-cancel
`cancel_open_orders_for_symbols` at `alpaca_order_handler.py:245`, OUTSIDE the
retry-try) falls through to an INTERNAL FILL — `:2272-2280` writes
`status='filled'` on a LIVE position with no broker ack (fires
`paper_exit_alpaca_submit_fallback_to_internal` critical first); (iv)
`intraday_risk_monitor.py:1428-1434` treats ONLY `deferred_uncorroborated` as
not-closed, so the internal-fill return (no `routed_to`) logs as a SUCCESSFUL
`force_close`. **RUNTIME: never fired on a live position.** All 9 post-epoch
live closes are `close_reason='alpaca_fill_reconciler_standard'` (broker-
reconciled); 42 filled close orders carry a broker id; the 10
`submission_failed`+filled internal-fill rows are all PRE-LIVE alpaca-paper era
(latest 2026-04-06); ZERO `submit_fallback_to_internal` alerts ever (the 3
`paper_order_marked_needs_manual_review`, latest 06-12, are the ordinary
broker-reject path that leaves the position OPEN, not internal-filled).
**→ E6 exclusion-integrity FAIL:** the live-close-custody closure claim fails
as written — the fallthrough hole is real and unclosed, merely un-triggered.
**→ NEW #1 BUILD: the broker-acknowledged-close invariant** (a live close may
NOT record `status='filled'` without a broker ack; raise→retry/needs-manual-
review, never internal-fill). Supersedes strategy work + Phase-3.

**P0-3 RISK CUSTODY (F-A1-1/A1-2) → CONFIRMED book-blind + PREMISE CORRECTED.**
(a) `paper_positions` has NO `cost_basis`/`current_value`/`max_loss`/
`collateral` columns at all → the allocator (`portfolio_allocator.py:116-144`
`_sum_open_cost_basis`) and RBE (`risk_budget_engine.py:99-208`
`_estimate_risk_usage_usd`) read those keys and get None→0, so the OPEN book
contributes ~$0 to utilization/envelope; writer omits them too (both true).
(b) Utilization gate (`utilization_gate.py:323-341`): candidate cost =
`limit_price*contracts*100` = ~$149 for a 1.49-credit IC, NOT the ~$351 max
loss — AND asymmetric with the already-open side (`structure_commitment_usd`
uses `width*100`=margin). **PREMISE CORRECTION (four-source: packet/registry
said "book ≤1 always"; DB says peak 3):** 3 concurrent real-money live
positions ran **2026-06-11 16:20Z → 06-12** (NFLX+QQQ+SPY; again 06-12
18:30-18:45 NFLX+QQQ+MARA). So the book-blind sizing + credit-basis gate + the
one-beta exposure were ALL live-reached, BEFORE the #1139 tripwire shipped
(07-08). Grade: latent-critical **that has already occurred** (no realized harm
— positions were small — but the aggregate cap was un-enforced across that
window). Merges with B1/B2 into ONE "book-scaling readiness" epic.

**P1 VERDICTS:**
- **(d) F-A1-3 calibration ORDERING → CONFIRMED.** `apply_calibration` at
  `workflow_orchestrator.py:3562-3569`, AFTER select(`:2495`)/allocate(`:2634`)/
  size(`:3241`); score/selection/sizing consume RAW ev; only persisted `ev`
  (`:3609`) + post-selection `risk_adjusted_ev` recompute (`:3669-3674`) reflect
  the multiplier. Morning path stamps `risk_adjusted_ev`/`status` on RAW then
  overwrites `ev` (`:1753-1755`) — raw/calibrated divergence on one row.
  **RE-SCOPES tomorrow's 16:00Z proof** (below). NEW P1 (design, not one-liner).
- **(e) F-A3-1 PoP → CONFIRMED-but-LATENT (our adjudication upheld).** The
  inverted `credit/width` branch (`ev_calculator.py:34-42`) accepts ONLY 2-leg
  credit verticals (`credit_spread` et al.); IRON_CONDOR (condor precomp +
  delta-tail) and debit spreads (delta interp) never enter. DB: strategies ever
  stored = IRON_CONDOR/LONG_CALL_DEBIT/LONG_PUT_DEBIT/take_profit_limit — ZERO
  credit verticals ever → branch never reached. (FREE-LOOK: stored PoP > 1.0 on
  debit-spread + take_profit_limit rows (max 1.0704) — impossible probability,
  delta-PoP overshoot; additive one-liner filed.)
- **(f) F-A4-1/A4-2 → both CONFIRMED.** `iv_daily_refresh` returns
  `status:ok` on all-missing (accounting `0==0`); it is ABSENT from
  `EXPECTED_JOBS`, and the watched `learning_ingest` is an explicit NO-OP STUB
  while the real producer `paper_learning_ingest` is unwatched. Observability
  → the carried 3-in-1 PR (recommend SPLIT into a 2nd observability PR, below).
- **(g) F-A9-1 → CONFIRMED.** `signal_accuracy_rolling` win = `pnl_realized>0`
  (realized win-rate), not thesis accuracy. Relabel → `realized_trade_win_rate`
  rides the thesis-tracker build; B1 ≈78% thesis vs this view's 12.5% is the
  exhibit.
- **(h) F-A8-1 → CONFIRMED.** Rejection over-count: inner `process_symbol`
  reason + outer wrapper `no_fallback_strategies_available`/
  `all_strategies_rejected` both `record()` (`options_scanner.py:4106/4141`),
  so `total_rejections` > distinct rejections. Annotate the packet's ~916.
  (Lane A greedy replay used `trade_suggestions`, NOT the 916 figure — Lane A
  unaffected; future rejection-based analysis must dedupe.)
- **(i) F-A2-2 → CONFIRMED (nuance).** `quote_complete=False` requires BOTH
  sides of EVERY leg (`exit_mark_corroboration.py:172-178`); when a non-
  executable side is missing it discards a COMPUTED executable-side divergence
  and force-suppresses — but ONLY for TARGET_PROFIT (`:246-253`); stop_loss is
  NEVER suppressed (`:243-245`). So it's a named mechanism for MISSED profit-
  takes (→ held longer → more stop exposure), NOT direct stop over-pessimism.
  Feeds Phase-3 instrumentation as a specific thing to measure.
- **(j) A10 import-time flags → CONFIRMED, no NEW class.** Module-scope env
  reads: `MIDDAY_TEST_MODE`/`COMPOUNDING_MODE` (`workflow_orchestrator.py:179-180`),
  `CALIBRATION_ENABLED` (`calibration_service.py:34`) — added to the inventory.

**RE-SCOPED "tomorrow 16:00Z proof" language (per d):** a persisted scan row
with `ev == ev_raw × 0.5` proves E1's flag — the multiplier reaches the
PERSISTED ev and therefore the final-stage round-trip gate. It does NOT prove
the calibrated value influenced SCORE, SELECTION, or SIZING — those consume raw
ev by construction (apply runs post-sizing). State it exactly: raw = score /
selection / sizing; calibrated = final-stage gate reading persisted ev +
persisted `risk_adjusted_ev`.

**EXTERNAL v1.1 SCORECARD (exclusion-integrity E1-E9 as graded):** E6 FAIL
(headline — custody closure claim false-as-written); the rest of their P0/P1
CONFIRMED at the line (their runtime-flag/mapping method vindicated again, Q1-
class). Weight: high. 11 packet/prompt disagreements → annotate move-don't-
erase (the ≤1-position premise correction is the load-bearing one).

## 2026-07-09 EOD — BUILD #1143 SHIPPED (shadow-detection + calibration fail-loud) + ⭐ OPTION-B CLOCK-RESET MARKER

**#1143 `655c9aa` — MERGED + H8 VERIFIED.** Post-close (merge 22:54:19Z;
STEP-0 grounded: broker 18:45 ET market-closed, DB 22:45Z). Two fail-safe
fixes:
- **Shadow-detection value match (E2 residue):** `_is_shadow_routing()`
  (`paper_endpoints.py`) now whitelists the REAL production value
  `shadow_only`. The prior check matched `paper_shadow`, which production never
  emits → the #1141 Option-A shadow branch was INERT (all cohorts fell to the
  observe-only legacy-sized basis, `basis=legacy_sized`). Unknown/None routing
  → False → observe-only (fail-safe: an unknown value never flips a live
  decision). Live path still behind `GATE_QTY_FIX_LIVE_ENABLED` default-OFF.
- **Calibration fail-loud:** once-per-scan WARNING at the midday apply site
  (`workflow_orchestrator.py`) + a write-side WARNING when a blob is stored
  while apply is disabled (`calibration_update.py`) + an import-time-flag
  caveat comment (`calibration_service.py`). Logs only; the flag itself was
  re-enabled by env flip earlier this session (a Railway flip needs a recycle
  — exactly what the import-time comment documents).
- **H8:** BE `d1fe9f87` / worker `74f3c83d` / worker-background `dad9b9e0` —
  all SUCCESS at `655c9aa`, created 22:54:22–23Z > merge 22:54:19Z; prior
  `907d4cd` deploys REMOVED. No new flags → no read-back beyond confirming
  `GATE_QTY_FIX_LIVE_ENABLED` OFF + `CALIBRATION_ENABLED=1` (both unchanged).
- **Tests:** `test_shadow_routing_fix.py` (13) pin `_is_shadow_routing` on the
  exact production strings + the routing→gate-decision chain (shadow PASS /
  live REJECT+observe / unknown observe-only / qty=1 invariant) + the two
  fail-loud source sites. CI green (run 29055518433, 1m42s).

**⭐ OPTION-B CLOCK-RESET MARKER — STAMPED AT `655c9aa` (recycle 22:54:22–23Z).**
Both preconditions are now met ON THE RUNNING PROCESS: (1) calibration APPLYING
(`CALIBRATION_ENABLED=1`, re-enabled this session) and (2) shadow-detection
CORRECT (`shadow_only` matched). **The Option-B (live gate-qty apply) observe
window's evidence clock RESETS here: the 9 `[GATE_QTY_SCALED_SHADOW]` observe
lines logged before this recycle are DISCARDED** — they were counted on the
inert-shadow + inert-calibration basis and are not clean. **Clean observe
evidence counts only from the first scan after this recycle (07-10 16:00Z scan
onward).** `GATE_QTY_FIX_LIVE_ENABLED` stays OFF — Option B remains an operator
decision, now to be made on clean data.

**B4 — EXTERNAL-REVIEWER SCORECARD (so future sessions weight their input
correctly):** external Q1 (calibration computes/stores but returns ×1.0 =
a runtime-flag/mapping issue) **CONFIRMED-RIGHT-FOR-THE-RIGHT-REASON** by
internal recon — root cause was `CALIBRATION_ENABLED='0'`, stale since the
06-11 epoch, never restored. Their A7 ("stops saved money") **REFUTED on broker
truth** — the stops mostly force-closed thesis-favorable positions early (B1's
downstream finding); an honest data limitation on their side (no broker
access), not a reasoning error. Net: a **calibration-proven** external — high
weight on their future findings.

## 2026-07-09 EOD — EXTERNAL-REVIEW ADJUDICATION (read-only; verdicts + B1 headline + A6 corrections)

**B1 — THE HEADLINE (the number the external couldn't compute): thesis
hit-rate ≈ 7/9 (~78%) vs P&L hit-rate 1/9 (~11%). THE PROBLEM IS
DOWNSTREAM (execution/exits/costs), NOT the signal.** Scored each live
close's entry thesis against the underlying's path to its INTENDED horizon
(strikes + exp vs 07-09 prices): NFLX(down, hit), NFLX(down, hit, +48),
QQQ-IC 06-15 (QQQ 723 inside 645-750 → hit but force-closed −73), SPY-IC
(751 inside 681-765, on-track, −45), SOFI(18.6>17, on-track, −40),
QQQ-IC 07-07 (inside, −15), QQQ-IC 07-08 (inside, −10) = 7 thesis-
favorable; MARA×2 (13.2<13.5/14, didn't rise) = 2 miss. **6 of 9 were
thesis-RIGHT-but-lost-money** — the underlying was in/toward the profit
zone but the position was force-closed early at a loss (the premature-stop
/ Phase-3 over-pessimism pattern, now quantified). CAVEAT: 5 of 9 expiries
are FUTURE (07-24→08-21) → "on-track" not "hit"; labeled in-progress.
**INSTRUMENTATION GAP FILED: no shadow-to-expiry tracker — positions
force-closed in minutes leave nothing following the underlying to the
original expiry, so thesis quality is only spot-scoreable. This is the #1
missing measurement.**

**A6 — LEDGER CORRECTIONS (broker=truth; the realized P&L was always
RIGHT, the EXIT-PRICE DISPLAY used the MARK not the FILL — mid-vs-fill
confusion, recurring class):**
- QQQ 07-07: exit shown 1.74 (mark) → **broker FILL 1.64**; realized −$15 ✓.
- SOFI 06-30: exit shown 1.53 (mark) → **broker FILL 1.36**; entry 1.44 →
  1.36 = −0.08 ×5×100 = **−$40 ✓ (reconciles the "impossible" row)**.
- QQQ 07-08: exit shown 1.535 (mark) → **broker FILL 1.59**; credit 1.49 −
  1.59 = −0.10 ×1×100 = **−$10 ✓ (the "−5" was the mark)**.
  → The external packet §2a exit-price column reads MARKS; correct to these
  fills on its next revision (packet is committed #1142 — annotate there,
  not erase). P&L rows unchanged.

**A1-A7 VERDICTS (cites in the session):** A1 credit-spread PoP=credit/width
= max_gain/(max_gain+max_loss) (ev_calculator.py:42) — **CONFIRMED inverted
(≈P(loss)); but LATENT** — IRON_CONDOR + debit strategies (the whole live
book) are NOT in that branch's strategy_type list; blocks the 2-leg-vertical
cohort. A2 stop = pct × max_CREDIT (policy_lab/config.py:33), cohorts
0.40/0.50/0.65 — **CONFIRMED credit-relative** (~17% of max loss at 0.40),
naming-clear in config but the basis is credit not max-loss. A3 ranker fee
= fee×contracts×2, NO ×leg-count (canonical_ranker.py:69) + slippage =
5%-of-EV proxy (:145) vs the gate's executable cross — **CONFIRMED
multi-basis; ranker under-costs 4-leg → ordering distortion (small $, but
real)**. A4 score clamped min(100) (guardrails.py:138) — **saturation
CONFIRMED**; but compute_conviction_score DOES use iv_rank conditionally
(:118-123) → "IV not in score" **PARTIAL** (the roi×500 production score not
located). A5 compounder legacy path ~3%×score (~$60) with a self-alert of
"~6-8× smaller budget" — **CONFIRMED sizing-model gap** (production uses the
allocator ≈ max_loss; the legacy fit-test tests a fiction). A6 above. A7
the stops fired on OVER-pessimistic corroborated UPL and the positions were
in-profit-zone at horizon → **"stops saved money" REFUTED** — they mostly
stopped WINNING theses early (= B1's downstream finding + Phase-3).
**External Q1 (runtime flag) CONFIRMED — weight their findings accordingly.**

## 2026-07-09 ~21:29Z — CALIBRATION RE-ENABLED (env flip + recycle, supervised)

**ROOT CAUSE (recon-proven by execution): `CALIBRATION_ENABLED='0'` stale
kill-switch, off since the 06-11 epoch, never restored.** Calibration was
LIVE 04-13→06-10 (38 rows, ev≠ev_raw), then disabled at the epoch to stop
pre-epoch sign-flipped multipliers applying to post-epoch predictions —
correct then, but the master apply switch was never flipped back when the
pool matured (07-09). The apply sites (`workflow_orchestrator.py:3554`
midday scan / `:1740` morning) are gated on the module-level flag; both
skipped. `get_calibration_adjustments` returned the correct 0.5 blob and
`apply_calibration(real blob)` → 19.85 in positive control — **the code was
never broken; the flag was off.** **NEW CLASS LINE: disabled-and-never-
restored** — a deliberate temporary disable with NO re-enable trigger; kin
to dead-triggers (§backlog) and prescribed-not-applied (WakeToRun). The
disable was FAIL-QUIET (no per-scan log; the write job kept computing +
storing a blob nothing read).

**SEQUENCE (all gates cleared before the flip):**
- STEP 1 — 21:20Z SUPPRESSION TEST **PASSED** (edge-trigger case 3, first
  live proof): `suppressed_standing_window:true`, tripped:false,
  paused_written:false, reason "standing_window_already_reviewed —
  fingerprint matches the last trip"; window unchanged, entries stay
  unpaused, 0 trips. #1135 fully validated.
- STEP 2 — pre-flight cleared: the only `MIN_POP=0.60` gate
  (`guardrails.SmallAccountCompounder.apply`) is **DORMANT** (not called by
  the scan; field-name `prob_profit` vs prod `probability_of_profit`;
  superseded by `services/analytics/small_account_compounder.py`) → a halved
  PoP breaks nothing live. Epoch off-reason moot (blob is post-epoch by
  construction).
- STEP 3 — **`CALIBRATION_ENABLED` set 0→1 on worker + worker-background**
  (BE is not an apply site). Recycle → both SUCCESS at `907d4cdd` (= the
  running `03e11d8` apply code + #1142 docs packet the operator merged;
  **zero code change**, H8-verified by diff). **Read-back: env=1, module
  CALIBRATION_ENABLED=True on the worker.**
- STEP 4 — **PRODUCTION PROOF: PARTIAL tonight, FULL pending 16:00Z
  tomorrow.** The forced post-close scan (job cb2db12c) short-circuited on
  the market-data **staleness gate** (age 94.8min, fast_path, processed 0)
  BEFORE scoring — so no scanned ev and no apply-site log tonight. Confirmed
  tonight: flag flipped + module True + `apply_calibration(blob)`→0.5
  (function). **NOT YET CONFIRMED (the built-not-wired class is NOT fully
  closed until this lands): a real scanned `ev == ev_raw × 0.5`** — rides
  tomorrow's 16:00Z scheduled scan on fresh quotes. Verify then.

**⚠ TRUE BOUNDARY MARKER (supersedes the annotated-false 07-09 10:00Z
marker): the apply path is ENABLED from 2026-07-09 ~21:29Z (907d4cdd,
CALIBRATION_ENABLED=1), but NO production ev has been calibrated yet
(tonight's scan was staleness-gated). The FIRST calibrated production ev is
2026-07-10 16:00Z. Every EV ever stamped before that moment was RAW except
the 38 pre-epoch rows (04-13→06-10).** Direction: TIGHTENING (EV×0.5 →
gate rejects more) — doctrine-clean, not a loosening.

**Option-B observe window: reset condition HALF-MET** (calibration now
enabled); fully resets when the shadow-detection one-liner ships. 07-09's 9
observe lines stay discarded (computed on un-halved EV).

**FILED (small PR, tomorrow / with the shadow one-liner): fail-loud
hardening** — log once-per-scan when `CALIBRATION_ENABLED` gates apply off +
flag the compute-but-never-apply waste; optionally move the flag read from
import-time to call-time (so it takes effect without a recycle). A
month-long silent recurrence must be impossible.

**PENDING-VERIFY (tomorrow morning): (1) 16:00Z scan produces ev=ev_raw×0.5
on a real suggestion [closes the class]; (2) the PoP ×0.5 lands only on
display (no live consumer) — confirm no regression; (3) the 21:45Z/22:00Z
learning chain ran clean post-recycle.**

## 2026-07-09 EOD — FIRST-CALIBRATED-SCAN-DAY FINDINGS (doc-only; fix-queue for tomorrow)

Flat day (0 trades, equity $2,067.86, −$0 P&L). First full day on the
supposed ×0.5 calibration + the gate-fix observe-log armed. Two findings,
both Claude Code's own, both fail-safe, both self-caught same day.

- **FINDING #1 (HIGH, headline) — CALIBRATION COMPUTED-NOT-APPLIED**: the
  0.5 multiplier stores at 10:00Z but `apply_calibration` returns ×1.0 at
  the scan — champion first calibrated scan verbatim `ev==ev_raw==39.71`
  (halved would be 19.86). Insert path stamps ev_raw then overwrites
  ev=apply_calibration(...) (workflow_orchestrator.py:1745-1755); equal
  values ⇒ ×1.0 returned. Suspect: `get_calibration_adjustments` fails to
  map an `_overall`-only blob into the `{strategy:{regime}}` return shape,
  so the documented `_overall` fallback (calibration_service.py:577) never
  fires and application silently falls to ×1.0. **CLASS: built-not-wired
  (#1126 family — computes/stores but doesn't reach the decision path).**
  RECON-THEN-FIX, own session, FIRST work tomorrow. Cross-ref: flagged to
  the external reviewer as §1 question (1) — do not double-drive; whoever
  moves first claims it.
- **FINDING #2 (one-liner + test) — OPTION-A SHADOW-DETECTION MISS**:
  #1141's gate keyed `routing_mode == "paper_shadow"`, but production
  values are aggressive=`live_eligible`, neutral/conservative=`shadow_only`
  → matched nothing → ALL cohorts ran `basis=legacy_sized` (observe-only),
  the shadow-side fix INERT, observe-log mislabeled shadows as `cohort=live`.
  FAIL-SAFE (zero live change; the miss defaults to the protected path) but
  promotion-un-biasing didn't happen. FIX: match `shadow_only` (or
  `!= live_eligible`) + pin the test on PRODUCTION routing values (the bug
  was test-fixture `paper_shadow` vs reality `shadow_only` — a test-vs-truth
  value mismatch, adjacent to the 9a2cef1 class). Ships after/with #1.
- **OPTION-B OBSERVE-WINDOW — EVIDENCE INVALIDATED, CLOCK RESET**: 07-09's 9
  `[GATE_QTY_SCALED_SHADOW]` lines are CONTAMINATED — the "would-open"
  new_net was computed on the UN-halved EV (39.71); with the real ×0.5
  (finding #1) new_net ≈ 19.86 − 12 = +7.86 < $15 → would NOT open. And the
  qty7/qty15 lines are shadows mislabeled live (finding #2). **The ~1–2wk
  Option-B observation clock counts ONLY from the SHA where BOTH #1 (calib
  applies) AND #2 (shadow-detection correct) are live. Discard 07-09's 9
  lines.** Re-arm marker to be stamped at that SHA.
- **ERRATA (annotation #6)**: this morning's ritual assertion "every EV
  number is now calibrated ×0.5" was a **verify-before-asserting miss** —
  overturned same day by ev==ev_raw. Pattern line: **TWO Claude-Code errata
  today (this + the recon's "champion always qty-1" caught by the SOFI qty-5
  fixture), both fail-safe, both self-caught within the day.** The standing
  boundary marker (07-08 postclose entry) is annotated in place, not erased.
- **NOISE-CLASS PRESSURE (reinforces the TOP-3 3-in-1)**: the observability
  PR was FIX-TODAY in the morning triage and DID NOT ship (the gate-fix took
  the slot). Carried to tomorrow's 2nd build slot. Today's reinforcement:
  ops_output_stale +7, job_succeeded_with_errors +5, **signal_accuracy_
  degraded ×14 (observe-only warning firing ~2/hr on the losing pool — a NEW
  cry-wolf; ADD a once-per-day / condition-dedup sub-item to the 3-in-1).**

**TOMORROW'S BUILD ORDER (operator's word, post-close, sequential deltas):
① calibration recon-then-fix (#1) · ② shadow one-liner + prod-value test
(#2) · ③ 3-in-1 observability PR (flat-book stale + re-egress dedup + #1104
writer-hardening + accuracy-warn dedup) · ④ stamp the Option-B clock-reset
marker at the #1+#2 SHA.**

## 2026-07-09 MORNING TRIAGE — dispositions recorded (doc-only)

First v5.4-from-disk nightly ran + dead-man pinged GREEN (first live night).
Calibration PRINTED 10:00:03Z: `_overall ev_multiplier 0.5 / pop_multiplier
0.5` (BOTH clamp-floored; ev_calibration_error 65.34 — raw wanted lower;
single _overall bucket, 30d window at n=8) — **raw mode EXITED; EV/PoP now
calibrated ×0.5, the ledgered boundary is CROSSED.** Un-paused + acked the
21:20Z breaker trip + 3 accuracy warnings; fingerprint survived (holds the
QQQ−10 window bd895160 — tonight's suppression test armed).

Dispositions:
- **FILED-TRIGGERED**: #1104 writer-hardening (6/677 rows lost 07-08;
  bundle w/ today's 3-in-1 or next burst) → backlog P2 · reentry_cooldowns
  realized_loss=estimate → FOLDED into the 06-15 backlog item (2-for-2
  live, no new line).
- **ACK-NO-ACTION** (recorded so no re-raise): A6 executor 4×/day = operator
  manual mid-session/post-close cycles, NOT a scheduler defect (scheduled
  cadence is the one-shot) · phase2_precheck = paper-shadow phase-2 gate,
  operator to name it in the scheduler doc.
- **GATED-REOPEN counter: Phase-3 exit over-pessimism now 3rd instance,
  15.5× worst yet** (cohort stop −155 vs broker −10, 07-08). Counter
  **3/[10-15 reopen gate]**. ⚠ **PATTERN NOTE for the reopen session: three
  instances (QQQ 3.3× · SOFI 1.6× · QQQ 15.5×) — the reopen's HEADLINE
  question is "is the cohort stop systematically over-pessimistic on
  defined-risk structures?" (same question SOFI stop-tightness raised).**
  Do NOT act now — gated, outcome-bias-protected; recorded so the reopen
  opens on the pattern.
- **⚠ META-AUDIT DRIFT CAUGHT LIVE (the exact class the 07-08 meta-audit
  targeted): 4 items were ledger-only / prompt-KNOWN-PENDING and had FALLEN
  OFF the actionable backlog.md** — EV-basis recon (LIVE), B1/B2 bucket
  control (LIVE), compounder greedy-stop (LIVE), the #12 06-10-runner batch;
  gap-3(b) existed only as a sub-note. **All re-added to backlog.md this
  session** (P1 for the two live-money, P2 for the rest). Process note: the
  ledger narrative is NOT the actionable list — filed items must land in
  backlog.md or they silently vanish from build-planning.
- **FIX-TODAY queue (pending-today, NOT built)**: the 3-in-1 observability
  PR — flat-book guard on ops_output_stale (A9) + re-egress cross-owner
  dedup (A5) + #1104 writer-hardening (A4). Post-close, one recycle. All
  three health-check/observability-side; zero decision-path risk.
- CONFIRM list checked: F-A1a · reaper · winter-close 2026-10-01 present ✓;
  one-beta tripwire SHIPPED #1139 ✓ (B1/B2 the only open bucket item);
  gap-3(a) SHIPPED #1124 present ✓.

## 2026-07-08 PR-B #1139 ONE-BETA TRIPWIRE — status:SHIPPED

**H8 VERIFIED: squash `7db5a36` (7db5a36dcd4fc1bf58eb67878e387ce2f3c3a2bd)
= origin/main; all three services SUCCESS at that SHA (22:29:35Z);
new-container work flowing by 22:30:04Z (heartbeat OK on the recycled
worker).** PR-A #1138 (`e26bcfe`) merged immediately before — tonight's
midnight nightly runs the v5.4 charter from disk for the first time.

Tripwire live: `concurrent_live_positions_uncontrolled` critical at ≥2 open
LIVE-routed positions, q15 monitor, immediate-egress + receipt.
**VERSION SHIPPED: simplest-correct (ANY 2 live positions), per owner
rationale — bucket refinement stays B1/B2's (still FILED; the alarm is not
the control).** Semantics: alarm-on-onset (position-set dedup; a 3rd
position re-alarms; dedup-read failure alarms anyway; scope-failed cycle
skips). Flag CONCURRENT_POSITION_ALARM_ENABLED default-ON. Disaster-pinned:
never mutates positions/orders/ops_control (test). 12 tests incl. the
production-call-path wiring pin. OPERATOR REMAINING: create the
healthchecks check + set machine env NIGHTLY_AUDIT_PING_URL (PR-A's ping
gate is a logged no-op until then).

## 2026-07-08 META-AUDIT (chat-run, gap register) + TIER-1 PROCESS FIXES — status:SHIPPED (PR-A)

**Meta-audit verdict (full register in session 07-08 ~22:15Z): ship-side
TRUSTWORTHY (ledger↔git 1:1 over 22 commits; 4 spot-checked fixes verified
against RUNNING behavior; zero built-not-wired in the shipped set); intake
side LEAKY (9 goes-silent findings, concentrated pre-ledger 06-10 runners;
2 re-verified STILL REAL); charter side STALE (disk prompt was v5.0/06-12;
scheduled cadence 6 reports/27 nights; 3 silent-empty runs 06-13/14/20).**

PR-A ships: **v5.4 TO DISK** (audit/v5-prompt.md — gap #7; adds A1(iv)
sizing/allocation custody [gap #10] + expected-state: suppression-is-
designed, headless-broker-blind, breaker ritual) · **ping-after-file-exists**
in run-nightly.cmd (gap #8; NO ping existed at all — first wiring;
PowerShell date because %DATE% is locale-formatted and would never match;
gate dry-run verified both directions; operator: create the healthchecks
check + set machine env NIGHTLY_AUDIT_PING_URL, Grace ~26h) · **sweep
convention** (gap #9, CLAUDE.md §7; 07-08 report swept in this PR) ·
**#1104 CLOSED**: operator confirmed reset ~13:45 CT → 18:45:26Z burst =
C1 rotation artifact CONFIRMED; pool-config reopen stays SHUT.

Meta-audit open register (dispositions pending owner triage): expiry-day ×
unpriceable defer seam (live$, own recon) · compounder greedy-stop BREAK
:286 (live$, Tier-2 fix) · EV-basis ∪ fee-unit recon (merged charter,
pre-market session) · F-A1a mechanical guard · one-beta tripwire (PR-B
TONIGHT) · PoP-denom/DTE segmentation (fold into clamp review) · smaller
silents batch (envelope re-egress 13/3h · A9-F4 · F-A2d · N4 · universe_size
mislabel · time-stop/eod-phantoms · N1/N2 · 06-10 A5/A6 partials) · A6
executor-4× question ANSWERED (operator manual cycles, no scheduler change).

## 2026-07-08 POST-CLOSE — #1137 SIGN FIX + FALSE-AGER — status:SHIPPED · THE TRIPLE-GATE POOL SEALED (8/8)

**H8 VERIFIED: squash `2a83174` (2a83174ed78080e329626297d1c9eaab8d8c6bb1)
= origin/main; all three services SUCCESS; worker-background container
20:51:29Z > merge 20:50:03Z — 29 min settle margin before the 21:20Z
ingest (race deadline CI-green-by-21:05Z beaten at 20:49:38Z).**

- **Sign fix live**: `broker_fill_to_mark_basis` (negation, not abs) at the
  live-fill reconciler; QQQ credit pin 1.4167 + SOFI debit 0.2326 + corrupt
  -15.08-shape regression + call-site wiring all test-pinned. **Both
  poisoned rows RE-DERIVED (supervised, read-back)**: bd25cc9d 15.083→
  **1.4167**, 3139842b 3.076→**0.9635**. The live Phase-3 gap dataset (3
  rows: SOFI 0.23 · QQQ 1.42 · QQQ 0.96) is now honest.
- **False-ager fixed**: monitor Part-B persist stamps `last_marked_at`;
  **9** ops_output_stale highs ACKed cause-fixed (2 more had fired since
  the mid-session count of 7; ids in session log).
- **BREAKER — edge-trigger case 2 FIRST LIVE PROOF (21:20:02Z on
  `2a83174`)**: new loss → new window [QQQ −10 bd895160 · QQQ −15 7dd459f8
  · SOFI −40 055ead84] → `edge_trigger:true, tripped:true, paused_written:
  true, fingerprint_stamped:true` — the NEW fingerprint REPLACED the old
  stamp (read-back ✓; MARA 0c54ead8 aged out). Critical receipt:
  webhook_sent=true 21:20:05Z. **Tomorrow's suppression test compares
  against THIS window** — morning un-pause, then a no-close Thursday must
  yield `suppressed_standing_window:true`, no re-pause, no critical.
- **CLOSE #9 INGESTED**: outcomes_created=1, errors=0; typed
  strategy=IRON_CONDOR / regime=normal ✓; gap datapoint born clean
  (its order row was re-derived pre-ingest). **Post-epoch live pool = 8/8.**
- **⚠ TRIPLE-GATE BOUNDARY MARKER — EV numbers change at 2026-07-09
  10:00Z, not tonight**: the pool sealed at 21:20Z tonight, but the relearn
  executes at the scheduled calibration_update (05:00 CT / 10:00Z). First
  real multipliers print then; consumers from that run onward:
  `apply_calibration` → scanner EV/PoP scoring → `risk_adjusted_ev`
  (executor sort) AND `ticket.expected_value` = the #1101 roundtrip gate's
  gross_ev — every gate decision after 10:00Z is on calibrated numbers.
  **⚠⚠ ANNOTATION 2026-07-09 EOD (do NOT erase this marker — correct it):
  this boundary is FALSE. The multiplier COMPUTED + STORED 0.5 at 10:00Z but
  apply_calibration returns ×1.0 at the scan (ev==ev_raw==39.71 verbatim
  07-09) — see the 07-09 EOD entry, fix-queue #1. "Every EV after 10:00Z is
  calibrated" holds only from the SHA where finding #1 ships; re-mark the
  TRUE boundary there.**
  Training pool: {+48, −45, −28, −73, −15, −40, −15, −10} (1W/7L) — expect
  a SHRINK; whether the 0.5 clamp floor binds is the clamp-review question,
  answerable when the multiplier prints. Winsorize: no extreme outlier in
  the live-only pool (max |x|=73) — likely no-action, owner-gated.
- **Accuracy alert**: expected at the first post-ingest health check
  (21:37Z; n=8, hit 12.5% < 0.2) — observe-only; verify in the morning
  ritual.
- **FILED: 06-08 NFLX pre-epoch live close missing from
  learning_feedback_loops** (broker+champion ledger=9 all-time, outcome
  table=8 post-tonight) — pre-epoch-flagged backfill, rides any future PR;
  no effect on the calibration pool (pre-epoch excluded by design).
- Untouched, confirmed: roundtrip gate (EV-basis recon own session — now
  MORE important: the new multiplier flows into that same comparison) ·
  one-beta B1/B2 · reaper · gap-3(b) · #1104 (pending reset-time).

## 2026-07-07 POST-CLOSE — #1135 EDGE-TRIGGER BREAKER — status:SHIPPED

**H8 VERIFIED: squash `be13733` (be137338ac1e89299cc18034bc04c6201427e47f)
= origin/main; BE + worker + worker-background all SUCCESS at that SHA;
container start 22:18:03Z > merge ~22:16Z.** CI green first try. Migration
`20260707221500` (ops_control.streak_breaker_state jsonb, additive
nullable) applied + tracked PRE-merge, read-back verified.

**Semantics live**: re-trip ONLY on window CHANGE. Fingerprint =
CONTENT-based sorted trailing-N outcome row ids, stamped at TRIP time —
**the operator un-pause SQL is UNCHANGED and is sufficient review** (the
window identity was recorded when it paged them). Suppression needs a
POSITIVE match; no-stamp/NULL/malformed/read-error/stamp-failure all
degrade toward tripping. A NEW loss trips instantly (protection intact —
framed in the PR: not loosening, operator-override-respect added). **Flag
`STREAK_BREAKER_EDGE_TRIGGER_ENABLED` DEFAULT-ON** (explicit falsy →
legacy level-trigger byte-identical); wiring test-pinned in
evaluate_and_trip (no #1126-class inert flag). CLAUDE.md §4 runbook
REPLACED (the nightly-re-trip paragraph is retired).

**Baseline + stamp (tomorrow's before/after)**: tonight's 21:20:02Z trip
ran on `5809505` (level-trigger era, PRE-#1135) — window by ingest order =
QQQ −15 (7dd459f8) / SOFI −40 (055ead84) / MARA −15 (0c54ead8); the trip
critical carries the #1134 receipt: webhook_sent=true, egressed_at
21:20:06Z, owner=alert — **#1134's receipt FIRST LIVE EXERCISE, PASS**.
One-time operator-approved stamp EXECUTED post-H8 (tonight's window
fingerprint backfilled via the breaker's own ordering; read-back
confirmed) because the trip predated the stamping code.
entries_paused=TRUE now (tonight's trip — morning un-pause ritual
unchanged).

**TOMORROW'S PIN (first suppression test)**: morning un-pause → 21:20Z
ingest on an UNCHANGED window → expect `suppressed_standing_window: true`
in job_runs.result.streak_breaker, NO re-pause, NO nightly critical,
entries stay armed. A NEW loss instead → trips (also correct). Attribution
clean: #1135 is the only behavioral change in its recycle.

## 2026-07-07 POST-CLOSE — #1134 TAXONOMY + ALERT-INTEGRITY — status:SHIPPED

**H8 VERIFIED (the shipped bar): squash `5809505`
(58095053c10eb76607552355acb1aecc0c2a8a9a) = origin/main; BE + worker +
worker-background all deployment SUCCESS at that SHA; container start
21:10:18Z > merge ~21:08Z; post-recycle job flow confirmed (21:10:01Z
learning_ingest succeeded).** CI green first try (run 28898768862).

**Old→new alert-type map (readers map old→new; historical rows untouched):**
- `force_close` + real submitted close → `force_close` (unchanged, critical,
  immediate egress)
- `force_close` + "Force close FAILED" → **`force_close_failed`** (critical,
  ADDED to immediate-egress allowlist)
- `force_close` + "[WARN-ONLY] … enforcement disabled" →
  **`envelope_violation_warn_only`** (high — was critical; relay path)
- `warn` (envelope block) → **`envelope_violation`** (high; relay)
- `warn` (envelope warn) → **`envelope_violation`** (warning — was the
  out-of-vocab 'medium'; no egress, anti-spam unchanged)
- Writer unification: monitor `_log_alert` now delegates to canonical
  `alert()` (severity normalize medium/warn→warning, error→high; #1100
  retry; owner stamp; receipt) — the which-writer-wrote-it egress lottery
  (today's real force_close on the ≤37-min relay) is closed.

**A9 receipt live**: `metadata.egress_receipt` {webhook_sent, sent,
suppressed_reason, receipted_at} + `egressed_at` stamped post-send;
`[ALERT_RECEIPT]` WARNING both outcomes; FAIL-OPEN test-pinned. **F8 live**:
suggestions_open rolls `rejection_persist_failures` → top-level
`counts.errors` + ok:false; runner folds alert-write-failure deltas into
every job's `counts.errors` (A4-visible; zero-delta byte-identical).

**F3 PATH TAKEN — UNAMBIGUOUS: F3-MINIMAL SHIPPED / F3-FULL FILED.**
Shipped: transient matcher now catches the 18:45Z specimen (httpx
WriteError / "Connection reset by peer" → retries), and a critical/high
whose insert is STILL lost force-egresses the webhook marked
`[DB-ROW-LOST]` (inbox = durable trace; test-pinned). NOT built: the
all-severities durable buffer — warning-class rows still degrade to
logger.exception only; filed as its own item (the critical-class hard
trigger is satisfied by the fail-safe).

PENDING VERIFICATION (tonight/tomorrow): 21:20Z ingest runs on `5809505` —
today's −$15 QQQ close makes the window MARA −15 / QQQ −73 / QQQ −15 →
expected RE-TRIP = **first live exercise of the new immediate-egress path**:
the `streak_breaker_tripped` critical should carry
`metadata.egress_receipt.webhook_sent=true` + `egressed_at` + an
`[ALERT_RECEIPT]` worker-background log line. Also watch: first
`envelope_violation`-typed rows at the next violation; the designed
channel-2 INFO replacing the legacy-mode WARNING; morning un-pause ritual
unchanged.

HYGIENE (filed 07-06, from the M4 CI failure): `test_weekly_report_win_rate.py`
replaces 18 modules (incl. cash_service, options_scanner) with MagicMocks in
sys.modules at import time and NEVER restores — any later lazy in-test import
binds a mock (green single-file local, red full-suite CI; cost tonight: one
red CI round on #1132). M4's test file now binds real modules at import with a
de-poison guard; the POISONER itself is unfixed and has pre-existing order
sensitivity (6 capital-basis failures in explicit weekly-first order — never
CI's alphabetical order). Follow-up: convert to conftest fixture/unpatch;
grep for siblings doing module-level sys.modules assignment without restore.

## status:reported — 2026-07-08 NIGHTLY run (report `audit/reports/2026-07-08.md`)

Window 07-06 05:01Z → 07-08 05:01Z — the 15-day flat stretch ENDED. Both workers
SUCCESS @ `be137338` (#1135) = origin/main HEAD (H8 clean; start 07-07 22:17:35Z).
**First LIVE fill since 06-30:** QQQ iron condor `386a39fe` (aggressive cohort
`3d289dca`), entry 14:37Z (off-schedule executor run, filled 1.49 credit vs 1.41 limit,
+$8 improvement, 76ms), force-closed 17:45Z on `intraday_stop_loss`, realized −$15.00.
`entries_paused=TRUE` since 07-07 21:20Z (breaker re-trip; **operator un-pause required**).
Live champion now 1 win / 7 post-epoch closes, −$168, hit-rate 14.3% (Brier 0.296).
⚠ **RUN LIMITATION:** alpaca MCP tools absent — broker not snapshot-read; live trade
DB-corroborated (execution_mode=alpaca_live + reconciler + is_paper=false), not
broker-confirmed. Equity/OBP not re-read (last $2,093.74 07-06, −15 QQQ ⇒ ≈$2,078.7 DB-derived).

- **[A4 2026-07-08 — FINDING] `close_fill_gap` sign-convention bug corrupts every
  live-close gap_fraction (poisons the deferred Phase-3 reopen gate).** The #1102
  instrumentation computes `gap_fraction=(fill−cross)/(mid−cross)` with NO sign normalization
  (`services/close_fill_gap.py:62-78`). On the LIVE/reconciler path
  `brokers/alpaca_order_handler.py:571` forces `fill=abs(filled_avg_price)` (+1.64) while
  `cross`/`mid` are stamped SIGNED (`paper_exit_evaluator.py:1913,1976` from `current_mark`
  −1.74 / corroboration −1.98). QQQ 07-07, the FIRST live full-quad close, stored
  fraction **15.0833** (=3.62/0.24) vs the correct-sign **1.417**. Internal/shadow exit
  path passes signed fill → self-consistent; only the LIVE path is wrong. Test fixture
  (`tests/test_close_fill_gap.py:44-47`) uses consistent-positive signs (SOFI→0.2326) → CI
  green while production is corrupt = the #1126/9a2cef1 test-green-production-wrong class
  (§9 never-do). Since #1102 shipped: 0 usable live gap_fractions (QQQ corrupt, SOFI-07-01
  shadow null). FIX: one line — sign-match fill at `:571` (drop `abs()`) or abs cross/mid at
  `:567`; add a mixed-sign fixture. RISK zero (observe-only, best-effort try/except).
  CONFIDENCE high (DB arithmetic + code both dispositive). Blast-radius note: the deferred
  Phase-3 "two-quote confirmation" safety fix (reduces over-pessimistic premature
  force-closes: QQQ −49-est/−15-fill, SOFI −65/−40) is GATED on this now-broken distribution.
- **[A5 2026-07-08 — FINDING] Standing-envelope alerts re-egress to the operator phone
  every 15-min monitor cycle (no content-dedup) — cry-wolf burying criticals.** While one
  live QQQ was held, "QQQ is 100% of risk (limit 40%)" was re-written HIGH and relay-egressed
  every cycle → **13 phone egresses in 3h** (14:45–17:45Z) + 26 non-egressed medium
  expiry/sector; the `force_close` critical egressed 18:07Z, AFTER them.
  `risk/risk_envelope.py:316-354` appends fresh each check; `intraday_risk_monitor.py:449-496`
  no changed-since-last-cycle guard (concentration severity default `"block"`→HIGH); relay
  poller `ops_health_service.py:1431` suppresses only per-row already-egressed stamps
  (`:1479`), NO type+symbol+content fingerprint. **Confirmed persists post-#1134** (rename
  kept concentration→high→relay). FIX (additive): apply #1135's edge-trigger principle to
  egress — suppress re-egress of an unchanged (type,symbol,bucket) standing condition within
  a hold. RISK zero (egress-only). CONFIDENCE high.
- **A1/A3/A7 UNCHANGED** (raw mode holds at 7/8 post-epoch live; ingest clean errors=0;
  QQQ condor hold 3h07m = ledgered cohort-stop-dominates-condors). **A2** — GATED Phase-3
  over-pessimism class exercised a 2nd time (QQQ −49 corroborated est vs −15 fill; cited,
  not re-found); its reopen data is the A4 bug. **A6** — binding constraint = EV-after-cost
  ($15 roundtrip floor rejected aggressive `38d57d55` at net +14.45), not cadence; OPEN Q:
  executor ran 4× on 07-07 (14:37 exec-1, 16:30/17:59/18:47 exec-0) vs one-shot/day — likely
  operator retries around the un-pause, confirm.
- **A8** roundtrip-reject class now exercised LIVE (aggressive +14.45 = edge-lost;
  neutral/conservative = spread-eaten); reject-was-a-win again (QQQ passed→−15). Per-gate
  marker still backlog RESEARCH. **A9** no new integrity finding (all alerts honest; the
  egress noise is honest→A5; ops_data_stale silent — market open). **A10** no new instance;
  winter-close blind hour (Nov) still queued; no fixture inside 45d.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **M4 post-fix healthy scan** (07-07): 0 `micro_tier_underlying_too_high`, 76 syms, 0
  `alpaca_options_buying_power_query_failed`. The 07-06 inverted-universe incident's zero was
  the incident's, not the gates' — M4 (#1132) HELD on the next RTH day.
- ✅ **CVX IV-eligibility**: scanned 07-07, `iv_rank_insufficient_history`=0, rejected on
  real `spread_too_wide_real`. **GLD**: scanned clean (no strike/IV errors). M1/M2/CVX closed.
- ✅ **Breaker re-eval**: 07-06 21:20Z re-tripped; 07-07 21:20Z re-tripped on NEW QQQ−15
  (window rolled QQQ−73→QQQ−15). #1134 streak-breaker critical carried `egressed_at`
  21:20:06Z (receipt partial-confirm).

PENDING VERIFICATIONS (2026-07-08 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-07 21:20Z, QQQ−15/SOFI−40/MARA−15). Un-pause
  before the next RTH else the 16:30Z staging proof no-ops.
- **#1135 edge-trigger FIRST SUPPRESSION test — STILL PENDING**: 07-07 21:20Z ran on #1134
  (pre-#1135 deploy 22:17Z) AND a new loss landed (window changed→tripped). The distinctive
  `suppressed_standing_window` path fires 07-08 21:20Z IFF operator un-pauses and no new loss.
- **#1134 first `envelope_violation` typed rows + egress receipt** on the next position-hold.
- **First CORRECTED `[CLOSE_FILL_GAP]`** once the A4 sign fix ships (expect ~1.4, not 15.08).
- **A6 executor-cadence**: confirm whether 4×/day is scheduled or operator-driven.

## status:reported — 2026-07-09 NIGHTLY run (report `audit/reports/2026-07-09.md`)

Window 07-08 05:01Z → 07-09 05:01Z. Clocks grounded (DB 05:01:23Z = broker 01:02 ET ✓).
**Broker READ DIRECTLY this run** (MCP present): equity $2,067.87 = cash = OBP (settled,
flat, 0 positions); 07-08 day −$10.43. H8 CLEAN: all THREE services SUCCESS @ `7db5a36`
(#1139) 22:29:35Z; movers off the prompt pin: `e26bcfe` #1138, `7db5a36` #1139.
**POOL SEALED 8/8** (1W/7L, −$178): live QQQ IC `305e476a` staged 17:41Z (ev 41.75 / pop
0.6425 raw), force-closed 18:00:11Z after ~15min — cohort stop on corroborated −$155 vs
broker fill −$10 (15.5×; Phase-3 class instance #3, counter 3/10-15). Breaker: designed
edge-trigger case-2 trip 21:20Z (window CHANGED: QQQ−10 in / MARA−15 out; fingerprint
stamped; receipt egressed). `entries_paused=TRUE` — **operator un-pause required**.
**CALIBRATION BOUNDARY: first calibrated multipliers print 07-09 10:00Z** (07-08 run was
sample 7 insufficient) — the three 8th-close checks are DUE.

- **[A9 2026-07-09 — FINDING] `ops_output_stale` paper_positions arm = standing HIGH
  false alarm, UNCLEARABLE while the book is flat + paused; the v5.4 STATE "RESOLVED"
  verdict is half-true.** 11 HIGH rows 07-08 (13:07→22:07Z, self-superseding; latest 2
  unresolved, 176→177h and climbing) assert a dead mark-refresh loop while Part-B wrote
  `mark_corroborated −3.04` the same hour. Root: `MAX(last_marked_at)` = 07-01 13:00Z —
  BOTH July QQQ holds ran pre-#1137 code (deploy 20:50Z 07-08 was post-close; QQQ 07-08
  row `last_marked_at=NULL`), and a flat book gives the live fix nothing to stamp. The
  §8 flat-book caveat is DOCUMENTED at `ops_health_service.py:149-152` but UNGUARDED
  (`:527-548` has no open-positions check). Projected ~48 HIGH rows/day for the whole
  pause (0 egressed — ops_* relay-skipped; poisons H11 triage). FIX (additive): flat-book
  guard — `open_n=0` → status `flat`/INFO, never `stale`/HIGH. RISK zero. CONF high.
- **[A5 2026-07-09 — FINDING, broadens the ledgered 07-08 re-egress item] the
  duplicate-egress class includes `egress_owner='alert'` writers, not just the relay.**
  `job_succeeded_with_errors` for the ONE 19:02Z scan run (`run_id ef8a2d4e`) re-wrote +
  re-egressed at 19:07/20:07/21:07/22:07Z — 4 receipted phone hits for one condition.
  The queued dedup fix must fingerprint the CONDITION (run_id / type+symbol+bucket)
  across BOTH owners or it fixes half the class. Watch, same shape:
  `ops_signal_accuracy_degraded` re-writes ~2/hr while hit<0.2 (designed first fire
  07-08 21:37Z at n=8 hit 0.125; warning-only, not egressed — row noise).
- **[A4 2026-07-09 — FINDING, small] rejection-persist retry loses rows when the retry
  hits the same dead connection — first data loss since #1104.** 19:02Z broken-pipe
  burst: 7 inserts recovered, **6 lost for good** (SLV/ISRG/C/HOOD/PLTR/AMGN, broken pipe
  on retry too); `counts.errors=6` with `result.errors=NULL` (count surfaced, items only
  in Railway logs). The #1100 detector caught it and it reached the phone with receipt —
  the chain WORKED; the residual is the writer. FIX (additive): reconnect-then-retry or
  ×2 backoff + stamp failed symbols into `result.errors`. Impact 6/677 (0.9%) of A8's
  counterfactual data. CONF high (logs + counts agree).
- **[A2 2026-07-09 — refinement of the 06-15 deferred cooldown item; metadata-only]**
  `reentry_cooldowns.realized_loss` stores the trigger-time corroborated ESTIMATE, not
  the fill — now 2-for-2 on live closes post-#1080 (−48.99 recorded vs −15 realized
  07-07; −155 vs −10 07-08). Bench durations unaffected; magnitude readers misled.
- **A1** EV-basis recon item (KNOWN-PENDING) reproduced with dispositive numbers on the
  LIVE cohort: aggressive QQQ 16:00Z stamped `net_ev +35.62` but gate-BLOCKED; gate log
  basis `gross_ev 42.14 − round_trip 154.00 = −111.86` (neutral twin; stamped net_ev
  NULL). Two bases disagree on the same candidate; it demonstrably timed the live entry
  (16:00 block → 17:41 pass). Urgency ↑ post-boundary. **A6** unchanged (677 rejections,
  mix stable; iv-seasoning 40/10syms = 06-17 adds, eligible ~mid-Aug; Polygon DARK on 8
  liquid QQQ legs 19:03Z, truth-layer priced — #1052 saved staging). **A8** SOFI sentinel
  quiet; gate discriminated (aggressive edge-passed, shadows spread-eaten). **A10** no
  new instance (counter 2). **A7** dormant, fills 3/10.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **#1134 typed rows + delivery receipt — BOTH egress owners**: 2 `envelope_violation`
  HIGH (17:45/18:00Z) relay-egressed with `egressed_at`; `job_succeeded_with_errors`
  carried full `egress_receipt {sent, receipted_at, webhook_sent}` (alert-owner).
- ✅ **Cooldown bench post-stop**: 19:02Z pending aggressive QQQ NOT staged at the 19:03Z
  executor run (benched until 07-09 13:30Z) — the bench gate exercised, correct.
- ✅ **#1071/#1058 brake line**: `[EQUITY_STATE]` used broker-true −10.43 over the $0
  open-book proxy — tighter value chosen, correct.

PENDING VERIFICATIONS (2026-07-09 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-08 21:20Z window QQQ−10/QQQ−15/SOFI−40);
  un-pause is operator-only.
- **CALIBRATION BOUNDARY 07-09 10:00Z**: expect raw-mode EXIT (first real multipliers on
  8 live closes); run the clamp(0.5-floor) + winsorize reviews (owner-gated). Attribute
  any post-10:00Z scoring/gate shift to the multiplier FIRST.
- **#1135 FIRST SUPPRESSION — decisive test 07-09 21:20Z**: book flat + paused + no new
  close ⇒ expect `suppressed_standing_window: true` and NO new critical. A re-pause/
  critical on the UNCHANGED window = edge-trigger FAILURE (flag hard).
- **First NATIVE post-#1137 `[CLOSE_FILL_GAP]` stamp** on the next live close (the 07-08
  quad was corrected in-DB, not code-native).
- **First post-#1137 hold stamps `last_marked_at`** (currently MAX=07-01 13:00Z; the fix
  is live but UNEXERCISED — this is the condition the A9 finding's "RESOLVED" verdict
  hangs on).
- **#1139 one-beta tripwire**: live but unexercisable at ≤1 position; fires only if 2+
  concurrent live positions ever exist (that event ALSO reopens A2's settled condition).
- **A6 executor cadence** (3rd ask): scans 16:00/17:41/19:02Z + execs 16:30/17:43/19:03Z
  on 07-08 — scheduled multi-cycle or operator-driven?
- **phase2_precheck naming**: 4×/day green job outside the doctrine's scheduler map
  (free-look, no anomaly) — one-line operator naming requested.

## status:reported — 2026-07-10 NIGHTLY run (report `audit/reports/2026-07-10.md`; first v5.5 eleven-area nightly)

Window 07-09 05:01Z → 07-10 05:01Z. DB clock grounded 05:01:05Z; **broker-blind run** (Alpaca
MCP absent — equity ≈$2,067.86 DB-derived, hypothesis). ZERO criticals (H11 clean). Zero-trade
day: 3 SOFI forks (ev_raw 39.71) all blocked `ev_below_roundtrip_cost`; book flat; pool stays
8/8 (1W/7L, −$178); gap counter 3/10–15. H8: HEAD moved `655c9aa`→`d275d28` (4 movers named —
#1144/#1145 docs, **#1147 `168a752` code**, `d275d28` doc-wrap runtime-inert, deployed 05:03:37Z
DURING the audit); all 3 services SUCCESS @ `d275d28`; 5 recycles 22:54→05:03Z, 0 orphaned jobs.

- **VERIFICATIONS CLOSED**: ✅ **#1135 FIRST SUPPRESSION DB-PROVEN** — 21:20:03Z ingest result
  verbatim `suppressed_standing_window:true, tripped:false, paused_written:false` on the
  unchanged 07-08 window; `entries_paused=false` (operator un-pause 11:53:33Z); fingerprint
  intact. Edge-trigger case 3 exercised — breaker fully validated, entries ARMED. ·
  ✅ **EDGE-TRIGGER FULLY PROVEN IN PRODUCTION; the morning un-pause ritual is RETIRED**
  (07-10 AM confirmation — all four silence conditions held: no streak_breaker email overnight ·
  `entries_paused=false` · `streak_breaker_state.last_tripped_fingerprint` intact
  [055ead84/7dd459f8/bd895160, tripped_at 07-08 21:20Z] · 21:20Z 07-09 ingest
  `suppressed_standing_window:true`). This was the last morning it needed checking as a ritual
  item; future mornings assume armed unless a flag-condition fires. ·
  ✅ post-recycle learning chain clean (21:00–22:00Z all green, errors=0) · ✅ universe 78 ·
  ✅ A6-cadence + phase2_precheck = ACK'd dispositions observed again, closed. ·
  ⚠ STATE CHANGE: F-FREE-1 scrub MERGED via #1145 `f6b204c` (was "PR pending"); operator items
  (history cleanup + secret-scanning) still open.
- **[A5 2026-07-10 — quantified continuation, urgency ↑, no new class]** ZERO-trade day wrote
  ~53 warning+ alert rows; `job_succeeded_with_errors` re-egressed the SAME stale run
  `ef8a2d4e` 6 more times (13:07→18:07Z) = **10 cumulative phone hits/2 days for one condition**,
  self-terminating only at the detector's ~24h lookback; ops_output_stale ×10 HIGH (unclearable,
  `MAX(last_marked_at)` still 07-01); accuracy ×20; chain_mechanics ×14; autopilot costume ×3
  (`distinct_error_classes=["EntryRoundtripCostExceedsEV"]` — 100% designed NOs as "failed",
  metadata-proven). **The 3-in-1 observability PR slipped a 2nd consecutive build day.** A9
  rider: the alert text "silently masked failure" is self-falsifying by its 10th delivery —
  message-honesty fix rides the dedup PR.
- **[A1/A3 2026-07-10 — structural arithmetic, exhibit for the OWNER-GATED clamp review; no
  action, no loosening]** From 07-10 16:00Z gate-pass requires `ev_raw ≥ 2×(15 + roundtrip)`:
  QQQ-IC class (cost ≈4.8, ev_raw 41.75) passes barely (thr ≈39.6); SOFI class (cost >24.7)
  needs >79. Expected entry volume ≈ zero-to-rare = do-no-harm working, BUT couples: multiplier
  rises only via pool improvement → pool grows only via closes → closes need entries. Not a
  strict deadlock (30d window ages June losses out ~early-Aug; 0.5-floor review is the owner
  lever). Hand to the clamp review as one exhibit with the funnel arithmetic.
- **[A11 2026-07-10 — proposal]** Run-boundary integrity: pin running SHA at audit START and
  END, name mid-run movers as a header field (tonight's `d275d28` landed 2 min into the run;
  caught only by late deployment listing). Also recorded: scheduled session has NO shell
  (subagents included) — git verified via `.git` metadata only.

PENDING VERIFICATIONS (2026-07-10 → next session):
- **FIRST CALIBRATED PRODUCTION EV — 07-10 16:00Z scan**: persisted `ev == ev_raw × 0.5`
  (re-scoped claim: proves persisted-ev + final gate ONLY; selection/sizing RAW). Option-B clean
  observe lines start counting at the same scan. `POP_CLAMP_ENGAGED` never firing is
  dormant-by-arithmetic, NOT broken (pop_mult ≤ 1.0).
- **First native [CLOSE_FILL_GAP] + first post-#1137 `last_marked_at` stamp** — need a live
  close / held book (none this window).
- **#1139 one-beta tripwire** — unexercisable at 0 positions; fires only at 2+ concurrent live
  (that event also reopens A2's settled condition).
- **3-in-1(+accuracy-dedup) observability PR** — TOP-1 again; verify IF shipped, don't re-find.
