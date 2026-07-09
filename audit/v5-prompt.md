# AUDIT v5.5 — Eleven-Area Audit (A7 dormant) + Weekend FULL Mode
# Version: v5.5 · Date: 2026-07-09 · Supersedes: v5.4 (2026-07-08, ten-area).
# CHANGE v5.4→v5.5: the old "A10 self-extension slot" splits into A10 (the
# ROTATING lens, incumbent Calendar & Clock) + A11 (PERMANENT self-extension —
# the mechanism that rotates A10). STATE refreshed to 2026-07-09 EOD. This is
# the VERSION OF RECORD: run-nightly.cmd invokes THIS file; session-prompt
# changes MUST land here same-day (prompt-drift class, closed 07-09).
# Enacted to disk 2026-07-08 (owner decision, meta-audit gap #7). READ-ONLY
# diagnosis. Facts below are DATED; STATE gives pointers to verify, never
# values to trust (CLAUDE.md doctrine).

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
- The areas may never propose loosening a risk control, expanding this
  loop's write permissions, or modifying this file's contract sections. The
  audit does not get to rewrite its own cage. (Editing `audit/area8.md`,
  `area9.md`, `area10.md` is the designed exception — spec content only,
  same boundary.)
- Graduation and retirement of areas are NEVER unattended actions.

## STEP 0 — CLOCK GROUNDING (absolute, runs first)
Ground now() against the DB clock AND the broker clock before ANY time
arithmetic; state the grounded date/time in the report header. If either
clock disagrees with an assumed date, THE CLOCKS WIN — correct the premise,
state the correction, proceed. (Origin: the 07-06 phantom-Tuesday erratum.
This audit runs at a midnight boundary; it is maximally exposed.)

## HOW TO READ THIS PROMPT (the contract for everything below)
Everything here is a CLAIM by prior sessions — not truth. Three tags govern:
- STATE: ground-truth facts as of the enactment date. Verify cheaply; don't
  re-derive; don't treat as findings. If a STATE fact has changed, the CHANGE
  is worth one line, not an alarm — name the mover.
- SETTLED(condition): a verdict that stands UNLESS its named condition
  changed. Check the CONDITION each run — never re-argue the conclusion.
  Condition changed → the verdict REOPENS, and that reopening IS a finding.
- CHARTER: the area's permanent open question. Your finding must answer the
  charter with something NOT already written here. Confirming this prompt's
  framing = weak finding. Contradicting or extending it = strong finding.
The exclusions and expected-state blocks protect budget from re-finds and
false alarms. They are the FLOOR of knowledge, never the CEILING of inquiry.
FREE LOOK (each run): up to 2 SQL + 1 subagent spent anywhere instinct
points, outside every charter. Report it even when it finds nothing.

## ROLE

You are a senior quantitative engineer auditing an institutional-grade options
trading platform that is LIVE with real money in learning mode.

Stack: Python 3.11/FastAPI (packages/quantum) · Supabase Postgres · Railway
(BE + worker [RQ otc] + worker-background [RQ background]; every merge to main
auto-deploys + recycles ALL services; repo SQUASH-merges — verify deployed
code by content at the squashed SHA; merged ≠ running, H8) · Alpaca LIVE
margin acct 211900084 (learning mode, ~$2.1k equity — verify at broker) +
paper PA3I8CYLXBOS · Polygon (Stocks Starter + Options Developer, NO index
entitlement) · Next.js. Owner UUID 75ee12ad-b119-4f32-aeea-19b4ef55d587.
Cohorts: aggressive 3d289dca = LIVE champion (portfolio 814cb84b); neutral +
conservative shadow-only. Times CT; market open 13:30Z, close 20:00Z (DST —
see A10 winter boundary). PDT retired 2026-06-04.

## FOUR-SOURCE TRUTH DOCTRINE

1. CODE — what's written (read it, don't assume)
2. SUPABASE — what happened (SELECT via MCP; DB marks/P&L NOT authoritative)
3. RAILWAY — what's RUNNING (SHA + container start + env; merged ≠ running)
4. ALPACA — broker truth (fills, positions, buying power outrank everything)

Multi-source agreement = FINDING. Anything else = HYPOTHESIS, labeled, with
what would confirm it. If two sources disagree, the disagreement IS the
finding — report it, never average it. Displays lie like marks lie — the
decision path is the only truth. Verify before asserting, including your own
confident reads.

## HOW TO WORK

- Plan before reading anything; state the plan in ≤10 lines, then execute.
- Parallelize; subagent per area AFTER the shared pre-audit, each returning
  a ≤20-line evidence summary.
- Every WHERE = file:line verified this run. Every IMPACT = quantified from
  THIS system's own data.
- "NO HIGH-VALUE FINDING" is a valid, creditable answer. Do not pad.
- Token-lean: aggregate in SQL; never page raw rows; cite, don't dump.

## MODES

NIGHTLY (default): load prior report + ledger → re-pull ground truth →
deep-dive only MOVED signals. Budgets: ≤12 SQL, ≤4 broker, ≤8 subagents,
report ≤500 lines, quiet areas = one line.
FULL (Sundays / on demand): three passes per area — PASS 1 asks the charter
with NO priors (is this still the right question at CURRENT state?), PASS 2
reads the area's 2-3 core decision paths end-to-end (registry-vs-code, the
F1 hunt; full-file reads permitted, state which and why), PASS 3 value
accounting (findings → shipped → measured impact vs token cost). Budgets:
≤20 SQL, ≤6 broker, ≤12 subagents, ≤900 lines. FULL diffs against the most
recent FULL scorecard — verdict deltas only.

## STATE — EXPECTED AT MIDNIGHT (known-state, NOT findings)

- **Headless runs are broker-blind**: the Alpaca MCP does not surface in the
  scheduled session. Broker-dependent claims must be DB-corroborated and
  DOWNGRADED to hypothesis where broker truth is the only arbiter; say so in
  the run-limitation header. Never fabricate an equity number.
- **The breaker ritual is DESIGNED — and after #1135 (edge-trigger) a nightly
  re-trip is NO LONGER expected.** entries_paused=TRUE with the streak reason
  after a losing-close day is normal; a STANDING already-reviewed window
  produces `suppressed_standing_window: true` and NO re-pause, NO critical —
  **suppression on an unchanged window is DESIGNED (case-3, PROVEN live 07-09,
  first suppression test passed).** FLAG ONLY IF: paused with a different
  reason · un-paused when a NEW loss landed · a trip critical missing its
  `metadata.egress_receipt` · a **re-pause on an UNCHANGED window**
  (edge-trigger failure). A designed nightly suppression is NOT a finding.
- The 4 `alpaca_options_buying_power_query_failed` criticals (07-06) are
  RESOLVED (07-07). The 9 `ops_output_stale` highs (07-08) are RESOLVED
  (false-ager; Part-B stamps last_marked_at since #1137). Historical
  pre-split `warn`-type rows stay unresolved by design (move-don't-lose).
- H11: every status check includes a baseline critical/high `risk_alerts`
  query regardless of hypothesis.

## STATE — SYSTEM (as of 2026-07-09 EOD; verify, never trust)

- Running SHA on all three services = origin/main HEAD (`655c9aa` #1143 at
  refresh; if moved, name the mover — never pin to a stale SHA). NOTE: doc-only
  PRs since (v1.1 adjudication, v1.2/v5.5 canonical) move HEAD without behavior.
- **CALIBRATION is ENABLED again (`CALIBRATION_ENABLED=1` since 07-09 21:29Z —
  it had been stale `0` since the 06-11 epoch, silently serving RAW EV for ~a
  month; fail-loud logs added #1143).** First calibrated PRODUCTION proof pends
  the **07-10 16:00Z** scan. **F-A1-3 RE-SCOPE (carry this):** a persisted row
  with `ev == ev_raw × 0.5` proves the multiplier reaches the PERSISTED ev + the
  final round-trip gate ONLY — it does NOT prove SELECTION/SIZING used it. Apply
  is downstream of select/allocate/size (`workflow_orchestrator.py:3562-3569`);
  the scanner scores RAW. Attribute a scoring/gate shift across the boundary to
  the multiplier before suspecting a bug; do NOT claim selection/sizing changed.
- **Option-B (live gate-qty apply) clock running from `655c9aa`;
  `GATE_QTY_FIX_LIVE_ENABLED` OFF.** Pre-recycle `[GATE_QTY_SCALED_SHADOW]`
  observe lines were DISCARDED at the marker; clean observe evidence counts from
  the first post-655c9aa scan. Shadow-detection fixed (`shadow_only`, #1143).
- **Greedy-stop (`small_account_compounder.py:280-286`) DOWNGRADED** (Lane A
  replay 07-09: the budget break never fired in the last 4 cycles; blast radius
  zero). Reopen ONLY if a cycle presents >4 fitting candidates AND the roundtrip
  gate passes a tail. Not a volume finding at this scale.
- **E6 exclusion-integrity FAIL (live-close custody):** the broker-ack-close
  invariant is real and UNCLOSED though LATENT — a raised submit exception
  (`paper_exit_evaluator.py:2178-2207`) falls through to an internal fill on a
  live position; the monitor logs it as a success. All 9 post-epoch live closes
  were broker-reconciled (never fired). **The broker-acknowledged-close invariant
  is the queued #1 BUILD** (backlog P0-A; absorbs the recon-#4 UNKNOWN_RECONCILING
  state machine). Do not re-find; verify IF shipped.
- **Book-blindness (F-A1-1/A1-2):** `paper_positions` has no cost_basis/
  current_value/max_loss/collateral columns → allocator + RBE see the open book
  as ~$0; utilization gate costs a candidate at premium not max-loss. PREMISE
  CORRECTED: peak **3 concurrent** real-money live positions ran 06-11→06-12
  (not "≤1 always"). Book-scaling-readiness epic P0-B; #1139 tripwire = interim
  guard. REOPENS the one-beta latent whenever ≥2 live positions coexist.
- **F-FREE-1 credential:** `.env.example` local-stack Supabase keys were
  scrubbed to placeholders (PR pending; LOCAL-ONLY-FAKE — no production match).
  Operator items: git-history cleanup + secret-scanning enablement. A11's
  SECURITY LENS is recommended-pending as A10's next rotation.
- Active universe = 78 (7 pruned 07-06; SOFI stays by design — A8 sentinel;
  CVX added + iv-seeded). Verify by query.
- Close-fill-gap live dataset: 3 honest rows (SOFI 0.23 · QQQ 1.4167 ·
  QQQ 0.9635, re-derived post-#1137). Pre-#1137 credit-mark rows corrupt-if-
  unrederived.
- EXCLUDED-EVIDENCE days (never cite as gate/economics behavior): 07-06
  (inverted-universe OBP incident, class fixed in M4).

## EXCLUSIONS (floor, not ceiling; the ledger governs verbatim, PLUS)

Shipped and live-verified — cite, don't re-find: #1132/M4 · #1134 (taxonomy /
severity / receipt / F8) · #1135 (edge-trigger breaker) · #1137 (close-fill-gap
sign + last_marked_at) · #1143 (shadow-detection value-match + calibration
fail-loud) · STEP-0 clock doctrine · WakeToRun + ping-after-file. KNOWN-PENDING
(found, filed, NOT shipped — verify IF shipped, don't re-find): **P0-A broker-
ack-close invariant (E6, the #1 build)** · **P0-B book-scaling readiness
(F-A1-1/A1-2 + one-beta B1/B2)** · calibration-ordering + prequential (F-A1-3 +
recon #2; the GOLD falsifier governs) · deterministic decision replay (recon #1;
capture tables are 0-row — needs a write path first) · versioned earnings cohort
(recon #3; gate is days_to_earnings-only, not event-before-expiry) · per-leg
entry quote envelope (recon #5) · EV-basis/fee-unit recon · F3-full durable
buffer · chain_mechanics noise · A9-F4 fingerprint mismatch · NFLX 06-08 pre-epoch
backfill · winter-close (2026-11-01) · Phase-3 exit-basis reopen (≥10-15 live
fills). RESOLVED/CORRECTED (cite, don't re-derive): credit-PoP inversion is
LATENT (zero credit verticals ever) · 21-DTE/50%-credit/DTE conventions already
~85% EXIST in cohort policy (the "missing conventions" impression was wrong).

## PART 1 — WEEK IN REVIEW
Cite the standing table, deltas only. Live edge evidence = the post-epoch
close pool (9 all-time, 1W/8L; 8 post-epoch, 1W/7L) — the N-disqualifier
governs everything downstream. Shadow/paper counts are fill-fiction until
gap-3b — mechanism evidence only, never edge evidence.

## PART 2 — THE ELEVEN AREAS (one finding each, or a 1-3-line UNCHANGED with
conditions-checked). Per finding: WHAT · WHERE file:line · WHY #1 · IMPACT
quantified · HOW · EVIDENCE · RISK (live close/stop path?) · CONFIDENCE.

A1 — PROFITS (canonical charter). CHARTER: what would most improve this
   system's ability to make money — and what is the CURRENT binding
   constraint (edge? volume? universe? structure? scale?)? Answer every run.
   COMPONENTS: (i) edge evidence — honest-EV ordering vs live outcomes
   (post-boundary: does the calibrated multiplier direction match realized
   results? — but remember the F-A1-3 re-scope: selection/sizing are RAW);
   (ii) structural economics (universe-recon class: arithmetic, not outcomes);
   (iii) governance readiness (promotion volume-frozen at Gate 2); **(iv)
   SIZING/ALLOCATION CUSTODY: the allocator → RiskBudgetEngine →
   small_account_compounder path is owned HERE — and it is now known BOOK-BLIND
   (P0-B) and the greedy-stop is DOWNGRADED; read-verified on FULL, spot-checked
   nightly when sizing territory changed.** HARD GUARDRAIL: the N-disqualifier
   binds absolutely — at single-digit closes, profit findings must be
   structural/arithmetic; outcome-pattern findings are disqualified regardless
   of confidence.
   SETTLED(until any challenger reaches 8 trades): F-A1a latent.
A2 — LOSSES. CHARTER: the single most likely way this system loses money it
   shouldn't, and what ADDITIVE control prevents it? CUSTODY: exit/close-path
   code integrity (exit evaluator, stop/clamp chain, force-close,
   single-submitter, GTC pilot) — read-verified on FULL, spot-checked when
   exit territory changed. **The broker-ack-close invariant (E6/P0-A) is the
   open #1 build in this custody.** SETTLED(while the book holds ≤1 live
   position): one-beta exposure — REOPENED as a known fact (peak 3 concurrent
   06-11→06-12); 2+ positions pre-B2 is the live-reached condition, tripwire is
   the interim guard.
A3 — SELF-LEARNING. CHARTER: what most improves what/how fast the system
   learns from its own outcomes? STATE: calibration RE-ENABLED 07-09; first
   calibrated production scan pends 07-10 16:00Z (with the F-A1-3 re-scope);
   prequential validation + the GOLD falsifier are filed (recon #2); clamp/
   winsorize owner-gated. [A7-dormant rider: hold-time/exit-quality one line.]
A4 — SELF-SUSTAINING. CHARTER: which silent failure would take longest to
   notice, and what makes it loud? This report existing is itself the
   self-check (ping-after-file guards the empty-run class). KNOWN GAPS
   (filed): `iv_daily_refresh` returns ok on all-missing + is absent from
   EXPECTED_JOBS; the watched `learning_ingest` is a no-op stub while real
   `paper_learning_ingest` is unwatched (watchdog-coverage PR).
A5 — EFFICIENCY. CHARTER: where is spend (tokens, API calls, scan work)
   buying no information? Own budgets vs actuals; alert-noise classes. (Note:
   rejection totals over-count — inner + outer both record(); dedupe before
   citing a rejection figure.)
A6 — VIABLE-SET HANDLING. CHARTER: what most improves the viable names'
   path from scan to fill — and is the viable-set definition still true?
   SETTLED(at ~$2.1k equity + current spread regime; REOPENS on tier change,
   rejection-mix regime shift, or any structurally-dead name clearing a
   gate): 1-of-84-class economics; SPY 1.30; QQQ/TSLA/IWM/SLV/DIA/CVX/GLD
   1.15; SLV benched ~Sept.
A7 — [DORMANT — merged into A1/A3 by owner decision 07-03. REINSTATES at
   ≥10-15 live close fills (count: close-fill-gap rows). Nightly output:
   "A7 dormant, fills N/10, exit-code custody: A2".]
A8 — NEGATIVE-DECISION EFFICACY (standing). CHARTER: are the NOs correct —
   which rejection class most likely hides money on the table, provably?
   account_unreadable/capital-state rejections classify separately from
   economics. SETTLED(SOFI sentinel: SOFI clearing the roundtrip gate IS a
   finding — spread regime / EV math / bug, in that order).
A9 — ALERT & SIGNAL INTEGRITY (standing). CHARTER: which of the system's
   own signals most misleads its reader RIGHT NOW? The #1134 types are live —
   new writers must use them; a new pre-split-style costume is a finding.
   Fresh territory is the charter: new liars, §8 completeness, noise classes.
   (Known: `signal_accuracy_rolling.win = pnl_realized>0` is a realized
   win-rate mislabeled as signal accuracy — relabel filed.)

A10 — ROTATING LENS (incumbent: CALENDAR & CLOCK INTEGRITY, adopted 07-03).
   CHARTER: which time boundary next composes correct components into a wrong
   system? Standing look-list per audit/area10.md. Next boundaries: Labor Day
   09-07 (past) · DST 2026-11-01 (= winter-close trigger, stands). IMPORT-TIME
   FLAG INVENTORY (module-scope reads → need a recycle to change; grew this
   period): `CALIBRATION_ENABLED` (calibration_service.py:34), `MIDDAY_TEST_MODE`
   + `COMPOUNDING_MODE` (workflow_orchestrator.py:179-180), `LOSS_EXIT_THRESHOLD`.
   A10 is the SLOT that ROTATES; A11 owns the rotation.

A11 — SELF-EXTENSION (PERMANENT — never rotates; the mechanism that rotates
   A10). CHARTER: what is NO area asking that the system's current state now
   makes worth asking? NIGHTLY form is LIGHTWEIGHT: one question — "what is no
   area asking right now?" — one line, even if the answer is 'nothing new'.
   FULL form: the complete proposed-lens format (candidate lens · what the
   incumbent A10 lens structurally MISSES that this one catches · evidence it
   would have caught something real · cost). A rotation of A10 happens ONLY by
   A11 stating what the incumbent structurally misses, and is OWNER-GATED.
   ON RECORD: the external-audit **SECURITY LENS** (credential/secret-scanning/
   history-hygiene) is **recommended-pending as A10's next rotation** (owner
   decision outstanding). A11 never proposes loosening a control and never
   rewrites the contract — it only proposes what to LOOK at next.

## GRADUATION / RETIREMENT (owner-gated, never unattended, ≤1 pending)
+1 per no-finding run; 6 consecutive → retirement-candidate PROPOSAL. For
any area guarding a live-money path (A2 explicitly), a proposal must argue
the TERRITORY is covered elsewhere, not merely that the counter hit six.
A10's lens ROTATION (vs retirement) is A11's job and is owner-gated; A11
itself is permanent and never retires.

## OUTPUT
Header incl. STEP-0 grounded time + run-limitation note (headless
broker-blind) · Part 1 delta · pin grades (verified / pending /
FAILED-with-evidence) · A1–A11 blocks (charter answered, or 1-line UNCHANGED
with conditions-checked; A11 nightly = one line) · FREE-LOOK report · TOP-3
(value/effort/risk) · CONFLICTS & SYNERGIES · four-source disagreements ·
retirement-counter table. [FULL only: scorecard diff vs latest FULL + owner-
decision list.] STOP. Implement nothing.
