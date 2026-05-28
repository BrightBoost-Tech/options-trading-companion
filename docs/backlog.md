# Backlog

This file is the durable home for backlog items. CLAUDE.md references this file but does not duplicate its contents.

Last migrated from CLAUDE.md: 2026-04-28.

---

# Options-Trading-Companion — Working Backlog

(last updated 2026-05-28; supersedes prior inline tracking)

> **Locator caveat:** `file:line` locators in Groups 4–6 are from a read-only
> diagnostic sweep this session unless otherwise noted. `options_scanner.py:2041`
> (combo-width fallback) and `options_scanner.py:3184-3240` (spread gate /
> uniform threshold) were verified directly this session; the rest are
> sweep-sourced and may drift. Behavioral conclusions are anchored in DB ground
> truth (rejection logs, the live F suggestion row) and are authoritative.

**Sequencing note:** Group 1 close-outs and Group 3 diagnostics run
first/parallel (read-only). Group 2 (#3 convention) is the one remaining
correctness fix and is the HARD PREREQUISITE for the exit and modeling work in
Group 4 — designing position-aware exits on convention-ambiguous P&L would
repeat the abandoned-#2 mistake. Groups 5–6 are fill; Group 7 runs passively
over F's lifecycle.

## Group 1 — In-flight close-outs (hours)
- Merge guard PR #987 (payoff-bound guard, shared module, CI-green, awaiting
  merge — branch protection). On merge → Railway redeploys worker → H8-confirm
  worker_boot > deploy_SUCCESS before treating live (~5 min image swap).
- Task 3: confirm fix#1 (#986) at runtime. After 20:00 UTC paper_exit_evaluate,
  verify EXIT_EVAL_DEBUG for bdbe4d04 reads ~+$168 / −$240, decision=HOLD. If
  33.60/−48, real surprise — investigate. [pending ~20:06 UTC background timer]
- Railway token, durable: set RAILWAY_TOKEN (or RAILWAY_API_TOKEN) at User level
  on Windows; restart terminal + Claude Code + MCP. Keeps expiring; blocks #4
  confirmation + all log observation.
- Confirm cost-basis subtraction next cycle: open_positions=1, F's $480
  subtracted from envelope.

## Group 2 — #3 convention consolidation (the one real correctness fix)
Audit complete: 69/70 positions full-count, 1/70 per-spread (CSX d077c93d,
closed BUG-A row), F full-count, ZERO live data exposure. #2 (intraday
double-count) is RESOLVED BY this, not separately. Sequence (own daylight PR;
convention = operator decision but data strongly favors full-count):
  1. Pinpoint the per-spread emitter — the scanner-suggestion → order_json.legs
     seam that wrote quantity=1 for the 4-ct CSX. Authoritative persisted writer
     is paper_endpoints.py:1465 (fill-commit passthrough); current entry/close
     builders emit full-count, so the per-spread value enters at the suggestion
     seam. This is step 1 / the one unfinished audit thread.
  2. Pin convention = full-count (operator decision; 69/70 + current writers +
     paper_mark_to_market's assumption favor it).
  3. Creation-time assertion at paper_endpoints.py:1465 (H9 verified-write):
     assert legs[].quantity == |pos.quantity| for verticals; alert/reject on
     mismatch.
  4. Backfill the 1 closed CSX row, or skip + document.
  5. Unify the two mark readers (_refresh_marks + paper_mark_to_market) to one
     shared full-count implementation; update TestRefreshMarksScale to
     full-count fixtures; decide whether to retain a per-spread rejection test
     now that creation asserts the convention.

**THIRD INSTANCE of the convention defect — the cohort-clone path (observed
via PR #990, 2026-05-28).**
- PR #990's live F-row check observed `legs.quantity=5` IDENTICAL across all
  three cohort suggestion rows (aggressive 5ct / conservative 12ct / neutral
  26ct) despite their differing contract counts. The cohort-fork path
  (`fork.py::_clone_suggestion_for_cohort`) propagates the champion's
  `legs.quantity` to each clone WITHOUT scaling it to the clone's own contract
  count → the non-champion cohort rows are convention-wrong (`legs[].quantity`
  does not match the clone's `pos.quantity`) every cycle.
- This is a DIFFERENT surface than the audit census: the audit (69/70
  full-count, 1 per-spread CSX) was on POSITIONS; this is on SUGGESTION/COHORT
  rows at clone time. The clone defect mints convention-wrong rows
  systematically, not as a one-off.
- Scope impact on #3's sequence:
  * **Step 3 (creation-time assertion at paper_endpoints.py:1465):** must ALSO
    cover the cohort-clone path — the assertion `legs[].quantity ==
    |pos.quantity|` has to fire on clones, not just the champion fill.
  * **fork.py leg-scaling is now an EXPLICIT part of #3** (scale `legs.quantity`
    to each clone's contract count at fork time), NOT the deferred follow-on it
    appeared to be during #990.
  * **Steps 4 (backfill) and 5 (reader-unification)** should account for any
    convention-wrong cohort rows already persisted, not just the single CSX
    position row.
- Known convention-defect surfaces are now THREE: (1) F-shape full-count vs
  (2) CSX per-spread positions, and (3) fork.py cohort-clone propagation of the
  champion's `legs.quantity` to clones. #3 must cover all three.

## Group 3 — Diagnostics pending
- **DONE 2026-05-28 — Credit-spread force-hydrate verification (verdict recorded).**
  Verdict: the `spread_too_wide_real ≈ 2.0` rejection is an **ARTIFACT**, but
  hydration does **not** make credit spreads broadly tradeable. Decisive: **ZERO
  outcome-(c)** across the full price spectrum tested (NIO $5.57, KHC $24.50,
  AMD $518, QCOM $244, ISRG $424) — every wing has a **live two-sided market**;
  "structurally unreachable / no market" is FALSE. The 2.0 is the strike-width
  fallback (`options_scanner.py:2041`) firing because the scanner doesn't hydrate
  the wing NBBO at scan time (`_combo_cost_range_from_legs` → None → falls back to
  strike width → `width/max_loss ≈ 2.0`). Confirmed by the asymmetry tell:
  same-cycle call-debit legs hydrated to real 0.15–0.84 spreads while every
  credit/put-debit alternative logged **exactly 2.0** (13 of 14 rejections) — a
  measured bid-ask cannot be exactly 2.0 across 13 names from $5.50–$300; the
  uniformity is the fallback signature. **BUT hydration ≠ tradeability:** real
  combo spreads are **16–91%, all > 10%**, credits are thin and the combo bid-ask
  is a large fraction of the credit (NIO combo $0.07 vs credit $0.065 — crossing
  eats ~the whole credit; KHC $0.12 vs $0.27 ≈ 44%), the same slippage lesson as
  the F execution; high-IV names (QCOM 91%, ISRG 67%, AMD 30%) are correctly
  rejected. Caveats: representative strikes (exact scanner strikes not logged →
  magnitude illustrative; the two-sided-market finding is exact); quotes ~22 min
  pre-close; 5 names across tiers, 13/14 cycle rejections were the 2.0 fallback.
  → Re-scoped fix lives in the D8 "Credit spreads" item below.
- (DONE — reference, do not re-run: P&L corruption diagnostic; writer/convention
  audit; first-execution status; trader-framework gap map.)

## Group 4 — Design roadmap (post-diagnostic, by thread)
Gated on the gap map (done) and #3 (for exit/modeling work).

### Surfacing quick wins (gap map D1 — data computed, not shown)
- Form + expose reward:risk: max_profit & max_loss per contract are both
  computed (options_scanner.py:1902-1945) but the ratio is never formed and
  max_profit is never persisted (no column).
- Breakeven: long strike + net debit (debit) / short strike − credit (credit).
  All inputs in legs + limit_price. Computed nowhere.
- Payoff/scenario table at emission (deterministic; inputs in hand). The
  trader's single most distinctive artifact. Borderline quick-win/roadmap.
- Fix midday persistence holes (CONFIRMED NULL on the live F row):
  probability_of_profit, max_loss_total, capital_required, rationale are NULL at
  column level with real values buried in sizing_metadata JSONB; net_ev
  (edge-after-costs) only in multi_strategy metadata. Midday path writes fewer
  columns than the morning path. Promote to columns.
- Price-basis note: system surfaces ENTRY $0.96 (order_json.limit_price), not
  the $0.88 mark; operator cannot derive R:R from what's shown without manually
  pulling sizing_metadata.

### Strategy coverage (gap map D8 — per-strategy binding constraint)
- Single-leg longs — **VERDICT IN (2026-05-28 read-only feasibility scope):
  DON'T BUILD (in current form).** Re-scoped from the gap map's "cheapest path
  to more trades / fits H7 broadly."
  - **The mechanical build is genuinely cheap:** ONE `get_candidates` selector
    change adds `LONG_CALL`/`LONG_PUT` templates; all downstream machinery is
    already wired — EV math (`ev_calculator.py:181-193`), PoP (`:82-88`), risk
    primitives (`options_scanner.py:1866-1885`), scanner EV dispatch
    (`:3120-3134`), strategy mapping (`:1841`), H7 round-trip
    (`sizing_engine.py:28-60`, single-leg `close_bp=0`), strategy-agnostic
    ranker (`canonical_ranker.py`). The 1-leg branch (`options_scanner.py:3120`)
    is unreached ONLY because `get_candidates` never appends a 1-leg template —
    its pool is exclusively 2-leg (spreads) and 4-leg (iron condors).
  - **BUT the single-leg EV model is structurally optimistic and was never
    calibrated as a RANKING input** (single legs have never been emitted):
    `long_call` uses a 10× unbounded-gain cap (`UNBOUNDED_GAIN_CAP_MULT=10`),
    `long_put` assumes collapse-to-zero, both use `PoP=delta` with NO theta
    term. Computed single-leg EV is inflated 1–3 orders of magnitude.
  - **Consequence:** building the cheap branch now would inject candidates
    whose EV is fictional; they'd pass the $15 edge gate by enormous margins
    and OUTRANK the debit spreads that are financially superior (a naked long
    has worse real EV — no short leg financing it, long theta). NOT "add
    correctly-rejected candidates" (the credit-spread case) but "add
    incorrectly-ACCEPTED candidates that pull capital toward worse trades."
    One notch worse than the credit-spread parallel.
  - **"Fits H7 broadly" is HALF TRUE:** sub-$30 + mid tiers pass H7 with large
    headroom (premium $43–$169 vs $1,531 OBP), MORE easily than debit spreads;
    but high-priced names (QCOM $243 → $2,513 premium, AMD $519 → $4,310) FAIL
    H7 outright at the system's ~0.60δ preference, and the cheap-deep-OTM escape
    hatch degenerates to a ~10%-delta lottery ticket the broken gate cannot
    reject. **Binding constraint is the miscalibrated single-leg EV model,
    tier-modulated by H7** (which only bites the high tier) — NOT the clean
    EV-vs-H7 squeeze. Here the gates fail to BIND, which is more dangerous than
    a legitimate squeeze.
  - **PRECONDITION to revisit (separate larger PR, NOT queued):** recalibrate
    single-leg EV into a theta-and-drift-aware expected-return model. Real
    modeling work, not a multiplier — and there are ZERO historical single-leg
    outcomes to calibrate against. Even done honestly, the model would likely
    show single longs failing the $15 gate MORE than spreads at this capital,
    adding few real candidates. **PARKED:** expected payoff doesn't justify the
    modeling cost at $1,531 OBP.
  - **Caveat:** OBP figure varies across docs ($1,531 / $1,031 / $501.61); a
    lower OBP only tightens H7 (kills the high tier sooner, shrinks the
    sub-$30/mid pass band) and does NOT change the EV-model finding.
  - Doctrine: this is instance (3) of H15 "Context-repurposed value /
    dormant-path activation" in `docs/loud_error_doctrine.md` — the wired EV cap
    is a correct *bound* but fiction as a *ranking* input for a dormant path.
- Credit spreads — **VERDICT IN (2026-05-28 force-hydrate, Group 3): the 2.0 is
  an ARTIFACT, but hydration does not make credit spreads broadly tradeable.**
  Mechanism confirmed: OTM wing legs lack two-sided NBBO *in the scan-time
  snapshot* → `_combo_cost_range_from_legs` returns None → falls back to strike
  width (`options_scanner.py:2041`) → `width/max_loss ≈ 2.0`. Live, every wing
  tested ($5.57–$424) HAS a two-sided market (zero outcome-(c)), so the 2.0 is a
  fetch gap, not "no market." But the *real* hydrated combo spreads are 16–91%
  (all > 10%) and the combo bid-ask is a large fraction of the thin credit →
  slippage eats the edge (same as the F execution).
  - **Fix shape (separate PR, NOT done here): wing quote-hydration in the
    scanner** — fetch wing-leg NBBO for ALL candidate strategies (not just the
    primary call-debit) before computing the combo metric, instead of falling
    back to strike width. Flips ~13/14 recent rejections from a false-200% to an
    honest spread measurement.
  - **VALUE = correctness/observability, NOT trade volume.** The fix stops the
    scanner emitting a false "no market" signal and lets the TRUE spread be
    measured. Economic payoff is bounded by EV-vs-H7: expect occasional tradeable
    credit spreads in low-IV regimes, not a flood.
  - **Per-strategy spread threshold is necessary-but-not-sufficient:** a
    credit-appropriate threshold (~20%+) only admits the narrowest low-IV wings,
    and at that width the combo bid-ask ≈ the credit, so it mostly admits bad
    fills. This is bounded by EV-vs-H7, NOT a contradiction of it.
  - **PRIORITY: demoted** from "unlock the full registry" to "fix a real fetch
    bug for observability; modest, IV-regime-dependent trade payoff." Worth
    doing; don't over-invest expecting volume.
- Iron condors — STRUCTURAL at small tier. Doubly blocked: NORMAL+directional
  regime → not pooled (last CHOP 2026-03-17); when pooled, condor_ev_not_computed
  (sub-$30 $0.50 strike granularity too narrow for IC wings); high-priced ICs
  fail H7. Phase gate (strategy_selector.py:377-378) is dormant/not the binding
  gate. Not parameter-fixable at this capital/universe.
- CSP/covered call — STRUCTURAL (capital). Absent from registry + collateral
  (>$1,300) exceeds BP. Class E.

### Position-aware / dynamic exits (gap map D6 — cheaper than expected)
- Current model is premium-% only (now qty-scaled to ~+$168/−$240).
  paper_exit_evaluator.py:206-301 reads only max_credit/unrealized_pl/qty; leg
  strikes are ON the position but UNREAD; no live underlying plumbed.
- To enable geometry-aware exits (breakeven-line, distance-to-short-strike,
  fraction-of-max-profit): plumb live underlying price + read stored leg strikes
  into the _check_* functions.
- Per-cohort exit params (stop_loss_pct/target_profit_pct/min_dte_to_exit) are
  ALREADY wired (paper_exit_evaluator.py:630-648) — dynamic-exit variants can
  ride existing plumbing. Test in shadow cohorts vs the live champion on real
  data; never on the live position. PREREQUISITE: #3 corrected marks + ≥ a few
  realized outcomes.

### Cohort differentiation (gap map D7)
- Cohorts currently differ in sizing + already-wired per-cohort exit params.
  Entry-timing is plumbed-but-unused: max_dte_to_enter exists
  (policy_lab/config.py:14-41) but is unused. Making cohorts encode
  entry-timing/thesis profiles (early/contrarian vs momentum-continuation) would
  be new. Natural test venue for the exit-model variants above.

### Modeling / context (gap map D2, D3, D4 — the trader's core critique)
- D2 momentum / extended-move: FEATURE-ABSENT (not scoped out), HIGH. EV off
  current price/IV only (ev_calculator.py:145-235); regime on IV/vol primitives
  only (regime_engine_v3.py:560); RSI computed in factors.py but never consumed;
  ranker no run-up term (canonical_ranker.py). No "already ran +44–75%" signal
  anywhere. Tractable at small tier (distance-from-SMA / %run-up / RSI cheap
  from existing bars) — add as an EV temper or score input.
- D3 catalyst: PRESENT BUT INVERTED. Earnings consumed defensively only (reject
  short-premium within 2d, score×0.5 within 7d; options_scanner.py:3389-3447,
  guardrails.py:85-93). Never asks the trader's question: "is there a forward
  catalyst before expiry to realize the modeled move?" Modeling-absent in the
  thesis direction. Needs a catalyst calendar joined to expiry.
- D4 thesis / "why now": rationale is a templated exit string written only on
  morning exits; midday entries write rationale=NULL (confirmed F). Structured
  provenance exists (agent_signals/decision_lineage) but no human-readable
  directional "why." One-line assembled rationale = surfacing; genuine
  directional thesis = modeling.

## Group 5 — Low-priority cleanups
- #4 executed-counter: likely counts shadow placements (possibly skip_no_quote)
  as "executed" (paper_autopilot_service.py:487,553). Needs Railway logs to
  confirm skip-path. Fix: separate live_executed / shadow_placed /
  skipped_no_quote counters.
- #5 duplicate suggestions each cycle: working as designed (dedup at
  paper_autopilot_service.py:371-374 + no-quote guard prevent double-open).
  Optional: dedup at suggestion generation to reduce noise.
- #6 transient 0/0 Polygon quote: self-resolving; skip_no_quote guard worked.
  Monitor recurrence only.
- Shadow orders stuck "working" (conservative/neutral): confirm they don't
  accumulate across cycles. Cosmetic.

## Group 6 — Doctrine to codify
- EV-vs-H7 trade-off at small tier: confirm the codification landed
  (structural_findings entry / PR #979 family); merge if still
  written-but-unmerged.
  **[NOTE 2026-05-28 — CONFLICT/STATUS: this appears ALREADY LANDED. `docs/structural_findings.md` contains the "EV-vs-H7 trade-off at small-tier capital" section (added 2026-05-26); CLAUDE.md's Bugs-Fixed lists the 2026-05-26 codification; commit `c4ef365` = "doctrine: codify EV-vs-H7 trade-off … (#983)". The "#979 family" label is approximate — the merged codification PR is #983. Treat as DONE unless a specific gap is found.]**
- Verification-gate-before-mutation: caught THREE incomplete/wrong fixes on the
  mark/exit subsystem this thread (eval/execute timing artifact; L478
  cosmetic-vs-decision mislocation; the #2 fix that would have re-armed BUG-A).
  Standard practice now: assume both the obvious location AND a clean severity
  split are suspect until data confirms.
- #1/#2/#3 mis-split lesson: single root cause (no pinned legs.quantity
  convention) modeled as separable severities; the "safe-to-patch-now" #2 wasn't
  safe (mark math conditional on convention). Commit the drafted stub into
  loud_error_doctrine.md.
- Parallel-computation smell WITHIN a file (H13 intra-file): cosmetic-vs-decision
  computations that look alike and sit near each other invite fixing the wrong
  one (L478 vs L215/276).
- Late-entry / momentum-following bias (gap map D5): propose as a
  structural_findings entry. Partitioned: liquidity/IV dependence is INHERENT
  (can't execute into illiquid pre-move chains — same family as EV-vs-H7);
  absence of any extension-penalty is a FIXABLE modeling gap that could
  counterbalance it. Evidence: F suggested after legs ran +44–75%, passed
  because the post-run chain was liquid, IV stabilized, EV cleared $15. Locators:
  gates options_scanner.py:2607-2628,3240; canonical_ranker.py
  MIN_EDGE_AFTER_COSTS.
- Single-leg-longs-unreachable-by-architecture: worth a structural_findings note
  (notable because it's the class that DOES fit H7 at small tier, yet is blocked
  by selector architecture not capital).

## Group 7 — Ongoing observation (passive over F lifecycle; do NOT intervene)
First full-pipeline position still exercising never-run-on-real-data machinery:
- Exit pipeline on a real position (now qty-scaled correctly).
- Hold-period stop scaling (PR #960, sqrt-decay) — never tested on a real debit
  spread; F is first; needs #3 corrected marks.
- mleg sign-flip validation (PR #908) — never exercised on a real multi-leg
  position.
- post_trade_learning — first realized outcome since the 2026-04-13
  pnl-corruption cutoff, when F closes.
- Exit slippage — real test of the 5%-of-EV formula (entry was zero-slippage;
  the exit fill is the test).

## Standing decisions / constraints
- FULL strategy set wanted (no credit-spread exclusion — earlier "no more credit
  spreads" was retracted).
- Capital scaling to $5k+ is the designed envelope and an OPERATOR decision, not
  a code task.
- Never intervene manually on a live position; downstream machinery manages it;
  value is observation.
- Agent does not gatekeep cadence; ships what's requested; reserves pushback for
  evidence-based concerns.
- H14 cite-then-verify before any composition change.

## Highest-leverage items (operator's stated goal lens)
1. ~~Strategy coverage (D8): single-leg longs~~ — **DEMOTED 2026-05-28: VERDICT
   DON'T-BUILD (read-only feasibility scope).** The build is cheap (one selector
   line, all downstream wired) but the single-leg EV model is uncalibrated for
   ranking (10× gain cap / collapse-to-zero / PoP=delta, no theta) → building it
   would inject incorrectly-ACCEPTED candidates that outrank superior spreads.
   Precondition (single-leg EV recalibration) is real modeling work with payoff
   that doesn't justify the cost at $1,531 OBP → PARKED. See D8 entry above.
   Credit-spread force-hydrate verify also DONE (2026-05-28): the 2.0 is an
   artifact (fix = wing hydration) but payoff is bounded by EV-vs-H7 →
   "correctness/observability, modest IV-regime-dependent volume," demoted from
   "unlock the registry." Net: both D8 strategy-coverage levers are now
   re-scoped down; neither is the cheap volume win the gap map implied.
2. Surfacing quick wins (D1): breakeven, R:R, payoff table, midday column holes
   — cheapest operator-facing improvement. **Now the top remaining leverage item.**
3. #3 convention (Group 2): unblocks the exit/modeling roadmap.

---

# Backlog — detail archive (pre-2026-05-28; still referenced by CLAUDE.md)

## Recent operational events

**[2026-05-11] CSX ghost position reconciled.**
Pre-state: `paper_positions` row `1f77f6af-b536-46a3-9975-88dfef41f855`
at `status='open'` (6 days old) despite Alpaca-side close at
2026-05-11 15:06:50Z. Action: UPDATE to `status='closed'`,
`closed_at='2026-05-11 15:06:50.319+00'`,
`realized_pl=-161.00`,
`close_reason='manual_close_user_initiated'`,
`fill_source='manual_endpoint'`. Audit row:
`risk_alerts.id = bed2ccf6-d5e4-4ce1-8a5c-20f98a0f2b7a`. P&L derived
from authoritative Alpaca fills: entry $216 debit (BUY 43C @ $2.66
+ SELL 47C @ $0.50, 2026-05-05), close $55 credit (SELL 43C @ $1.15
+ BUY 47C @ $0.60, 2026-05-11) → -$161.00 realized. Zero fees
(Alpaca paper account doesn't charge regulatory fees on options).
Trigger: yesterday's MTM-staleness intraday blind spot caused operator
to manually close via Alpaca UI; that path bypasses our submission
chain so the DB row was never reconciled. MTM-staleness root cause
since fixed by PRs #919 + #920. Effect: 12+ `ghost_position` alerts
per hour cease firing against this row; open position count = 0.

**FOLLOW-UP: ghost_position alert throttle review** (LOW, ~30-60 min)
PR #98 Option B documented a 1-hour idempotency window on
`ghost_position` alerts via the `metadata->>order_id` JSON-path
filter. Observed today (2026-05-11): 12 fires in 1h against the
single CSX ghost row, ~1 fire per 5 min matching the
`alpaca_order_sync` cadence. Implication: throttle is either broken
OR keyed differently than expected (e.g., per-cycle instead of
per-position, or the keying field doesn't disambiguate cycles).
Priority LOW (only fires on ghost rows, which should be rare
post-reconcile). Investigate after a follow-up ghost surfaces or as
hygiene work. Captured separately rather than fixed inline because
the reconciliation makes the throttle issue operationally inert
today.

**[ADDENDUM 2026-05-12 evening — CSX reconciliation reframed]:**
Today's trade-absence diagnostic revealed that PR #921's
reconciliation was more operationally important than its docs-only
framing suggested. The CSX ghost row was cascading through 3
pipeline gates (suggestions_open's micro-tier "one position" gate
→ paper_auto_execute's per-symbol risk envelope cap → intraday_risk_monitor's
force-close attempt against phantom unrealized) and produced "no
trades today" symptom + 2 critical `paper_order_marked_needs_manual_review`
alerts at 15:15Z. Reconciliation tonight unblocked tomorrow's
suggestion + execution pipeline. Captured as new H10 doctrine entry
in `docs/loud_error_doctrine.md` ("Stale state cascades through
pipeline gates").

**[2026-05-12] Status-check methodology gap captured as H11 doctrine.**
Morning status check missed today's actual critical events because
queries were structured around "did a position open" (anchored on
`paper_positions` and `paper_orders`) rather than "what critical
events happened regardless of operator framing." 2 critical
`paper_order_marked_needs_manual_review` alerts at 15:15Z went
unseen at the morning check; only surfaced ~5h later when the
trade-absence diagnostic widened the query surface to `risk_alerts`
directly. Fix captured as H11 doctrine in
`docs/loud_error_doctrine.md` ("Status-check methodology: critical
alerts as baseline section"). Applies to all future diagnostic
prompts. No code change.

**[2026-05-12] H8 false-alarm pattern + verification discipline
captured (extends existing H8 doctrine).**
Today's trade-absence diagnostic surfaced an H8-class hypothesis
("PR #908 not running on production worker") based on real
evidence (pre-PR-#908 error text at 15:15Z rejection). Verification
refuted the hypothesis cleanly: worker `ee7219f287b94b028478b3803d779251`
booted 19:00:46 UTC on image built 19:00:22 UTC, which postdates
PR #908's merge (2026-05-10 05:40 UTC) — the 15:15Z rejection
happened on a now-REMOVED earlier deploy. Captured as extension
to existing H8 doctrine entry in `docs/loud_error_doctrine.md`,
including:
- Verification procedure (5 steps: PR merge time → deploy SUCCESS
  time → worker boot time → comparison → action gated on result)
- Confirmed instances table (2026-05-04 TRUE H8 + 2026-05-12 FALSE
  alarm; both healthy diagnostic signals)
- Doctrine note: hypothesis-generation produces real value even
  when refuted by verification
- Diagnostic-prompt convention: include verification BEFORE any
  restart action

**[2026-05-12 → 2026-05-13] PR #908 empirical validation pending**
Code is live in production worker (verified 2026-05-12 19:00:46Z
boot, image built 19:00:22Z, post-PR-#908 merge). Empirically
untested on a live close in this image.

**Next validation event:** First natural close that fires after a
new position opens (now unblocked post-CSX-reconciliation).

**What to capture when the close fires:**
- Order's `limit_price` (should be NEGATIVE for credit-side close
  per PR #908's sign-flip design)
- `abs(limit_price)` (should be ≥ 0.01, matching the clamp condition)
- Broker response (filled? rejected?)
- If rejected, error text (compare to pre-PR-#908 format)
- `paper_orders` row with `broker_response` payload for forensic
  inspection
- `risk_alerts` rows fired during the close (use H11 baseline query)

**Failure modes to watch for:**
- Same error text as today's 15:15Z rejection (`"Cannot submit
  options order without limit_price (got -2.08)"`) → suggests
  another code path has the old check; PR #908's scope was
  incomplete
- Different error text → new failure mode, separate investigation
- Alpaca-side rejection (not internal ValueError) → PR #908's
  approach architecturally wrong; sign-flip may not be
  Alpaca-compatible
- Filled successfully → PR #908 empirically validated; mark this
  entry CLOSED with the validation event timestamp

**Why this matters:** PR #908 fixes the class of bug where credit-side
close orders carry positive `limit_price` and get rejected at our
broker handler. The fix shipped 2026-05-10; today's failure was on
the older deploy. Tomorrow's close is the first opportunity to
confirm the fix actually works in production.

**Pre-drafted post-close diagnostic prompt:** deferred. Draft tomorrow
morning when close event is imminent, OR earlier if operator opts to
pre-stage. Decision left to next session.

**[2026-05-12] Warmup-window expectation (TESTABLE HYPOTHESIS).**

**Hypothesis:** During the ~57 remaining trading days of warmup window
(`iv_repository.get_iv_context` requires `sample_size >= 60` at
`iv_repository.py:239`; today is day 3 of warmup with `iv_daily_refresh`
writing `ok=69` rows daily), the system is expected to produce few or
no IV-sensitive strategy trades (credit spreads, iron condors).
Non-IV-sensitive strategies (debit spreads, naked calls/puts) can
still fire if other gates pass.

**Today's data point (2026-05-12, day 3 of warmup):**
- `suggestions_open` at 16:00 UTC: `skipped=false, reason=no_candidates`
- 14 sub-$50 symbols processed (28 filtered by micro-tier price cap)
- 9 IV-sensitive strategies held with `strategy_hold_no_candidates`
- 1 LONG_CALL_DEBIT_SPREAD emission, 0 created (separate watch entry)
- `iv_pipeline_no_data` warning fired (40/40 symbols missing `iv_rank`)
- 0 suggestions produced, 0 trades

**Why this is a hypothesis, not a fact:**
- Prediction depends on what % of candidate strategies are IV-sensitive
  in practice (today's 9-of-14 may not generalize)
- Non-IV-sensitive paths might produce candidates regularly during
  warmup (we just didn't see one survive today)
- Universe rotation, regime changes, or volatility shifts could produce
  unexpected candidates
- 3 days of warmup data isn't enough to validate the prediction shape

**What confirms the hypothesis:**
- Trade count remains near-zero through warmup window
- Trade count rises after day ~60 as `iv_rank` stabilizes

**What refutes the hypothesis:**
- Trades fire regularly during warmup despite IV-sensitive gating
- Trade count doesn't materially change post-warmup
- Some other gate is the actual bottleneck

**Operator implication:**
- "No trade today" during warmup window is EXPECTED, not a bug
- Don't re-investigate every low-trade day during warmup unless H11
  baseline surfaces critical alerts
- Run a fresh diagnostic if pattern breaks (e.g., trades fire
  unexpectedly, OR warmup completes without trade rate change)

**Reference:** Tuesday 2026-05-12 bundled diagnostic synthesis.
Adjacent observations: "1 emission → 0 created" watch and `entry_cost_too_low`
threshold observation (separate entries below). Existing #115
documentation in this backlog covers the upstream `iv_rank` computation
that the warmup window is feeding.

**Status:** Hypothesis logged. Empirical validation across warmup
window. Promote to CLAUDE.md if validated; revise or retract if
refuted.

**[2026-05-12] WATCH: "1 emission → 0 created" downstream-gate question.**

**Observation:** Today's `suggestions_open` produced
`emission_counts_by_strategy: {LONG_CALL_DEBIT_SPREAD: 1}` but
`counts.created: 0`. One LONG_CALL_DEBIT_SPREAD emission didn't survive
a downstream gate to become a created suggestion row. The downstream
gate is unidentified — could be:
- Sizing logic (insufficient capital for the spread)
- EV-ranker (expected value below threshold)
- Risk-adjusted EV gate
- Anti-duplicate / legs-fingerprint dedupe
- Other gate not enumerated in today's diagnostic

**Why this is a watch, not an investigation:**
Today's other rejection counts (52 total: 28 micro-tier price cap, 9
strategy-hold, 9 no-fallback, 4 entry_cost_too_low, 2 all_strategies)
account for most of the rejection volume. The 1 emission-vs-0-created
is small but represents a SILENT-DROP point — emission existed in
the cycle stats, then disappeared without surfacing in
`rejection_counts`.

**Watch criterion:** If "emissions exist but 0 created" persists for
2-3 more days, trace the downstream gate. Possibly H9-shaped
(wrapper-drift between emission and creation — the gap between
"emission_counts_by_strategy" and "counts.created" is the seam).

**Status:** Watch active 2026-05-12 → 2026-05-15 (3 trading days).
If pattern persists past 2026-05-15, escalate to dedicated diagnostic.

**Reference:** Tuesday 2026-05-12 bundled diagnostic synthesis,
"emission_counts_by_strategy" section.

**[2026-05-12 → 2026-05-13] WATCH CLOSED: RESOLVED-NOT-A-BUG, CORRECTED ROOT CAUSE.**

**Resolution date:** 2026-05-13 (Wednesday afternoon).

**Status:** **CLOSED**, but the resolution required a course-correction
from the first attempt's wrong-line attribution.

**Correct root cause:**

H7 `round_trip_bp_insufficient` firing correctly on Path A-admitted
high-priced underlyings whose debit-spread max_loss exceeds round-trip
BP at $681 micro capital.

Specifically (2026-05-13 Wednesday cycle):
1. Tuesday 2026-05-12: Path A bumped MICRO_TIER_MAX_UNDERLYING $60 → $100
2. Wednesday 2026-05-13: Scanner emitted 5 candidates including KO
   ($78.43, LONG_CALL_DEBIT_SPREAD)
3. KO's leg selection ran through `_select_legs_from_chain`
   (`options_scanner.py:1059`) — delta-target based, NOT width-based
4. KO at $78 has $5-wide strike intervals (standard for $50-$100 stocks);
   debit-spread leg_defs target deltas resolving to ~1 strike apart →
   ~$5-wide spread → ~$500 max_loss/contract
5. Sizing engine round-trip BP check (`workflow_orchestrator.py:2671`):
   entry $486 + close safety $534.60 = $1,020 required vs $681 BP
   available → contracts=0 → REJECT
6. Post-loop fired `no_suggestions_after_gates`

**Why the EARLIER attempted resolution was wrong:**

The first resolution attempt (the γ1 fix prompt) attributed the $486
max_loss to `options_scanner.py:1260`
(`width = 5.0 if current_price >= 50.0 else 2.5`). Line 1260 only
applies to iron condors — it's inside `_select_iron_condor_legs`. KO's
debit spread doesn't use that code path. The proposed γ1 fix (change
line 1260's threshold $50 → $100) would have changed iron-condor
widths, not KO's debit-spread max_loss.

The verification escape hatch in the γ1 implementation prompt caught
the error before shipping — STOP triggered when the code path read
revealed line 1260 was iron-condor-only. This became instance 4 of
the framing-artifact pattern (see entry below — promoted to H12
doctrine).

**Why this is CORRECT_FIRING:**

PR #100 added the round-trip BP check after the 2026-05-01 BAC
ghost-position incident. H7 doctrine codifies "Operations preserve
capital invariants in both directions" as load-bearing — NOT tunable.
The gate did exactly what it was designed to do.

**Why the pattern emerged:**

Path A's universe widening to $100 admitted underlyings whose
debit-spread strike geometry produces max_loss exceeding round-trip
BP at current capital. Not a fixable mismatch via spread-width
threshold; the underlying math is "debit spread on $50-$100 stock
needs ~$1,500+ BP for round-trip safety."

**Fix shipped (separate PR, Option A revert):**

Reverted MICRO_TIER_MAX_UNDERLYING $100 → $60 via Railway env (PR
shipping this entry). Restores pre-Path-A creatable-candidate state.
Future capital scaling enables post-revert re-attempt of universe
widening.

**Empirical validation:**

Thursday 2026-05-14 morning cycle: if sub-$60 admits produce a created
suggestion (per pre-Path-A pattern), revert is validated.

**Learning captured:**

- The 2-day watch window with empirical refinement worked correctly:
  N=1 (Tuesday) was vague, N=2 (Wednesday) was actionable.
- However, the actionable investigation produced WRONG WHERE-to-fix
  while correct WHAT-is-firing — instance 4 of framing-artifact
  pattern.
- H12 doctrine promoted in this PR to prevent recurrence.
- Path A's experiment produced clean empirical data: $100 widens
  universe but admitted candidates fail H7 at current capital.
- This validates Tuesday's tier-inflection diagnostic's prediction
  about $50-$100 admits not fitting round-trip BP (though that
  diagnostic itself partially shared the same framing-artifact shape).

**[2026-05-12] OBSERVATION: spread-threshold friction on cheap universe.**

**Observation:** Today, 4 of 14 (~28%) processed symbols rejected with
`entry_cost_too_low`. Backlog item #92's spread-threshold tightening
(closed via #106 classification work on 2026-05-04) may be over-tight
for the <$50 universe slice currently dominating the micro-tier
processable set. Today's rejections matched #106's PFE shape exactly
(threshold=0.3, entry_cost_share=0.05–0.06).

**Why this is an observation, not a finding:**
- Single data point (today). Not enough for statistical inference.
- Universe composition shifts daily; today's <$50 dominance may not
  repeat tomorrow.
- The threshold may be correctly calibrated and today's rejections
  may genuinely indicate "spreads too narrow to make money" — that's
  the gate working as designed (per #106 closure rationale).

**Watch criterion:** Track `entry_cost_too_low` count as % of processed
symbols over next 2 weeks. If consistently >25%, the threshold may
need empirical re-calibration via `ABSOLUTE_SPREAD_THRESHOLD` /
`MIN_ECONOMIC_ENTRY` env overrides. If varies significantly
day-to-day, today's was a snapshot artifact.

**Action:** None today. Empirical observation only.

**Reference:** Tuesday 2026-05-12 bundled diagnostic synthesis,
`rejection_counts` section. Cross-reference #92 (CLAUDE.md design
principles note) and #106 (closed 2026-05-04 — entry_cost_too_low
classification work).

**Status:** Observation logged. 2-week empirical window
(2026-05-12 → 2026-05-26).

**[2026-05-12] REMINDER: PR #924 (H9 AST gate) deploy pairing.**

**State:** PR #924 merged 2026-05-11 but Railway deploy at 18:20 CDT
failed (Docker Hub metadata-pull transient on Metal builder; same
fingerprint as two earlier failures that day). Worker has been on
PR #923's image (`e771e611`, deployed 2026-05-11 17:23 CDT) for ~21
hours as of today's afternoon diagnostic. PR #924's content
(`packages/quantum/observability/h9.py` decorator + AST gate test +
allow-list) is functionally inert in production — zero production
imports of the `h9_exempt` decorator verified 2026-05-12 afternoon.

**Plan:** Pair with next code merge to trigger fresh Railway build
that includes PR #924's content. No urgency since the gate is in
warn-only mode and isn't blocking anything. Alternative: manual
retry via Railway dashboard.

**Validity:** This reminder stays valid until either:
- Next code merge deploys cleanly AND confirms PR #924 content is
  live (h9.py present in deployed image, gate test runs in CI)
- Manual retry of PR #924 deploy is triggered + succeeds
- PR #924's content is determined to be no longer needed (unlikely)

**Verification when triggered:**
- Worker boot time > deploy SUCCESS time (H8 check)
- `packages/quantum/observability/h9.py` exists in deployed image
- `packages/quantum/tests/test_h9_wrapper_drift_gate.py` runs in CI
- `h9_violations.json` artifact appears in CI run output
- Strict-mode flip schedule (2026-05-19) still applicable

**Status:** Pending pairing. Worker confirmed healthy on PR #923's
image at 2026-05-12 18:30 UTC (worker `40aff4b7679c430f85d68889138726ea`
running standard job mix without error).

**[2026-05-12] Tier 1B convenience views shipped.**

Three SQL views applied to surface existing learning analytics data
without ad-hoc SQL (per learning-mode codification in CLAUDE.md
Active focus):

- `symbol_performance` (90-day window, on `learning_trade_outcomes_v3`)
  — per-symbol win rate, P&L, strategy diversity. 17 rows on apply.
- `hold_period_buckets` (90-day window, on `paper_positions`) — hold
  time distribution by outcome bucket (winner / loser / force_close /
  manual_close / reconciler / other). 6 rows on apply.
- `recent_closes_audit` (30-day window, on `paper_positions` LEFT
  JOIN `trade_suggestions` + `learning_feedback_loops`) — full
  decision audit trail per closed position. 13 rows on apply.

**Schema corrections discovered during pre-flight:**
- `learning_trade_outcomes_v3` uses `ticker` + `strategy`; design
  diagnostic draft assumed `strategy_type` — corrected before apply
- `paper_positions` uses `symbol` + `strategy_key`; same difference
- `trade_suggestions.score` is actually in `sizing_metadata` jsonb;
  view uses `sizing_metadata->>'score'`
- `learning_feedback_loops` has no `position_id`; joins via
  `suggestion_id` instead
- `close_reason` enum surveyed empirically (44 target_profit_hit /
  7 manual / 7 stop_loss / 4 reconciler variants / 1 envelope_force)

Migrations 20260513000001-3 applied via `mcp__supabase__apply_migration`
prior to PR merge (idempotent CREATE OR REPLACE VIEW, fully reversible
via DROP VIEW). Audit rows in `risk_alerts` per migration apply
procedure.

**[2026-05-13] Tier 1C: per-suggestion rejection persistence shipped.**

Granular per-rejection rows now persist alongside the existing
aggregate `rejection_counts` in `job_runs.result`. Operator can ask
"which 8 PFE rejections for `entry_cost_too_low` in May, with what
spread context" — previously aggregate counts only.

**Schema:** new table `suggestion_rejections` (id, symbol,
strategy_key NULLABLE, reason NOT NULL, cycle_date, job_run_id
NULLABLE, spread_debug jsonb, created_at) with 3 indices for the
expected queries (per-symbol-reason, per-cycle, per-reason).
Migration 20260513000005.

**Companion view:** `rejection_patterns` — per (symbol, reason)
over rolling 30 days with last spread_debug context. Returns 0
rows initially (forward-only); populates as scanner cycles run.
Migration 20260513000006.

**Capture-point change:** centralized via `RejectionStats` class
in `options_scanner.py` rather than editing 30+ call sites
individually. New behavior:
- `RejectionStats(supabase=..., cycle_date=..., job_run_id=...)`
  constructor opts in to persistence
- `set_symbol(symbol)` stores per-thread context via
  `threading.local()` (scanner uses ThreadPoolExecutor, so per-thread
  isolation is required)
- `record()` and `record_with_sample()` call internal
  `_persist_rejection()` after the existing aggregate increments
- 3 entry-point edits to call `set_symbol()`:
  `_apply_tier_price_filter` loop, `process_symbol(symbol)` top,
  `_process_symbol_multi(sym)` top

**H9 Convention compliance note:** persistence intentionally fails
silently (try/except logs warning, doesn't raise). This is the
OPPOSITE of H9's "verify side effect" — appropriate per Anti-pattern
5 valid case (observability writes must not undo primary work). The
aggregate count in `_counts` remains the authoritative source;
suggestion_rejections rows are supplementary granularity.

**Tests:** 13 unit tests in `test_rejection_stats_persistence.py`
covering: constructor configuration, persistence-when-symbol-set,
no-symbol-no-write, optional-field omission, db-failure isolation,
warning-log-on-failure, threading isolation across 4 worker threads,
aggregate-unchanged sanity. All pass.

**Apply procedure:** migrations 20260513000005 (table) and
20260513000006 (view) applied via `mcp__supabase__apply_migration`
pre-PR-merge per same low-risk profile as PR #928/#929 (forward-only
new table; view is CREATE OR REPLACE). Audit rows in `risk_alerts`.

**Forward-only:** no backfill of historical rejections. Pre-PR
aggregates remain in `job_runs.result.cycle_results.debug.rejection_counts`.
Synthetic backfill from aggregates would produce false granularity.

**Verification post-deploy:** worker recycle on next merge will
load the new code. Tomorrow's 16:00 UTC `suggestions_open` cycle
should populate suggestion_rejections rows. Cross-check:
aggregate `cycle_results.debug.rejection_counts` totals should
equal `SELECT COUNT(*) FROM suggestion_rejections WHERE cycle_date
= CURRENT_DATE GROUP BY reason`.

**Related work:**
- Yesterday's observability design diagnostic (Tier 1C section)
- PR #928 (Tier 1B convenience views — same migration pattern)
- PR #929 (hold_period_buckets v2)
- Learning-mode codification in CLAUDE.md (sets framing — granular
  rejection visibility serves learning-mode goal directly)

**[2026-05-13] hold_period_buckets v2 relabel + exit-threshold doc note.**

Two small follow-ups from today's hold-ratio investigation:

1. `hold_period_buckets` v2 (migration 20260513000004): splits the
   `stop_loss_hit` bucket by P&L sign — `profitable_stop` (1 row,
   AMD iron condor wing-breach exit at +$1,202) vs `stop_loss_exit`
   (6 rows, all true loss-side closes). Resolves the v1 mislabeling
   surfaced by today's investigation. All other buckets unchanged.

2. CLAUDE.md `### Exit thresholds (defaults under empirical review)`
   subsection added under Operational state notes. Documents the
   current 35% target / 50% stop values as INHERITED DEFAULTS (not
   deliberate design), plus the empirical hold-pattern data from
   today's investigation (per-strategy breakdown table). Cross-
   references the N=20 re-evaluation trigger entry below.

Both small. Migration 20260513000004 applied via
`mcp__supabase__apply_migration` pre-PR-merge per same idempotency
profile as v1. Audit row in `risk_alerts`.

**[2026-05-13] WATCH: Exit threshold re-evaluation trigger (N=20).**

**Trigger:** Re-evaluate exit thresholds (35% target / 50% stop) when
debit-spread sample reaches **N=20 per outcome bucket** (winner /
loser).

**Current state (2026-05-13):** 9 winners / 6 losers in 90-day
window. Statistical confidence limited; threshold change would be
tuning on noise.

**Why this watch:** Today's hold-ratio investigation revealed
thresholds are inherited defaults (not deliberate design choices).
Re-evaluation should happen when sample supports inference, not
before. Premature optimization on small N produces worse outcomes
than no optimization. Path-dependent option pricing dynamics +
strategy-mix differences mean small-sample threshold tuning is
particularly risky.

**Re-evaluation method (when triggered):**

Empirical approach (recommended):
- For each closed loser, compute counterfactual P&L at tighter
  stops (e.g., 30%, 40%, 50%) using historical MTM trajectory if
  available
- For each closed winner, compute counterfactual P&L at wider
  targets (e.g., 35%, 50%, 75%)
- Build expected-value curve per (target, stop) pair
- Pick pair with best risk-adjusted EV given current strategy mix

Alternative — theoretical/principled:
- Strategy-specific thresholds (different defaults per strategy
  family — iron condors typically run tighter than debit spreads
  per industry convention)
- Risk-adjusted Kelly fraction analysis
- Time-horizon adjusted (short-DTE wants tighter, longer-DTE wider)

**Anti-criteria (don't trigger re-evaluation if):**
- Sample still <N=20 per debit-spread bucket
- Recent threshold change still being evaluated
- Strategy mix changed materially (rebalance first, then evaluate)
- Bigger blocker active (warmup, capital constraint)

**Decision shape when triggered:**
- Run empirical analysis
- Surface findings + recommendation
- Operator decides: change thresholds, change them per-strategy,
  or leave as-is with documented justification

**Validity:** Until triggered OR until thresholds are changed.

**Related work:**
- Hold-ratio investigation 2026-05-13 (source)
- PR #928's `hold_period_buckets` v1 (tracks data accumulation)
- PR #929 (this PR — v2 relabel + operational note in CLAUDE.md)
- Learning-mode codification — micro tier IS the dev environment for
  evaluating these thresholds against empirical hold patterns

**Status:** Watch active. Re-evaluation conditional on N=20.

**[2026-05-12] OBSERVATION: framing-artifact false-alarm pattern (3 instances).**

Diagnostics can produce concrete-evidence hypotheses whose underlying
ASSUMPTION is wrong. Verification step refutes the conclusion while
the evidence itself remains accurate.

**Instances surfaced this week:**

1. **2026-05-11 H11 status-check methodology gap** (codified as H11
   in `docs/loud_error_doctrine.md`). Operator framing of "did
   anything trade today" produced a status check that missed critical
   risk_alerts. The framing was the gap, not the data.

2. **2026-05-12 H8 PR #908 worker-stale hypothesis** (codified as
   H8 extension). Diagnostic surfaced timestamp evidence suggesting
   PR #908 hadn't deployed. Verification revealed an earlier deploy
   had been replaced; PR #908 was already live. Evidence was
   accurate; conclusion was wrong because the framing assumed a
   single deploy point.

3. **2026-05-12 H8 analytics_events writer-break hypothesis.**
   Yesterday's observability design diagnostic flagged
   `analytics_events` as "stale since 2026-05-05." Verification
   today revealed writes are event-driven and correlate 1:1 with
   trade-lifecycle events. The "staleness" is healthy zero-output
   during zero-activity period — last event 2026-05-05 matches
   CSX entry, no entries since. Evidence (timestamp, row count)
   was accurate; conclusion conflated time-based-stale with
   event-driven-silent.

**Underlying shape:** diagnostic measures something accurately but
interprets the measurement against the wrong baseline expectation.
Verification works by asking "what would this measurement look like
under HEALTHY operation given the actual generative process?"

**Why not new doctrine yet:** H8 already codifies the verification
discipline ("hypothesis-generation produces value even when refuted
by verification"). The "framing artifact" is a sub-pattern of H8
false alarms, not a new doctrine. Capturing the pattern shape may
be useful for future diagnostic prompts (check baseline assumptions
explicitly before concluding) without needing formal doctrine status.

**Promotion criterion:** if a 4th instance emerges with a NEW
underlying shape that H8 doesn't cleanly cover, promote to formal
doctrine. Until then: pattern noted in backlog, applied informally
in diagnostic drafting.

**Diagnostic-design implication:** future diagnostic prompts should
consider including a "baseline assumption" section explicitly:
"what would the measurement look like under HEALTHY operation given
the actual generative process?" Then the verification step compares
observed vs healthy-expected baseline rather than against an
arbitrary expectation.

**Companion Tier 2 observability candidate:** an
`event_driven_writer_health` view that joins event-driven writer
output against the upstream event source (e.g., `analytics_events`
against `paper_positions` lifecycle events). Computes
"events_expected vs events_written" — mismatch = real bug,
zero=zero = healthy quiet day. Would systematically distinguish
shape-(a) time-based stale from shape-(b) event-driven silent.
Captured but NOT shipped as Tier 1.

**Status:** Observation captured. Inform future diagnostic drafting.
Not promoting to formal doctrine without a 4th instance with new
shape.

**UPDATE 2026-05-13:** PROMOTED to H12 formal doctrine. 4th instance
(KO H7 spread-width attribution, Wednesday 2026-05-13) demonstrated
the "wrong-scope-generalization" sub-shape distinct from prior
instances (wrong-baseline / wrong-deploy-model / wrong-temporal-model).
See H12 entry in `docs/loud_error_doctrine.md`. This backlog
observation is now CLOSED — superseded by formal doctrine.

**[2026-05-13] DEFERRED: Universe expansion plan (sub-$100 tickers).**

**Originally scoped:** After Path A's $100 bump (2026-05-12), planned
addition of 10+ sub-$100 liquid tickers from Tuesday's diagnostic
candidate set (NEE, BMY, KHC, HBAN, MRO, GM, MO, NIO, LCID, RIVN).

**Status as of 2026-05-13:** **DEFERRED pending Option A validation.**

**Why deferred:**

Wednesday's downstream gate trace revealed Path A's admitted underlyings
($50-$100 names) fail H7 round-trip BP at current capital. Option A
(revert Path A to $60) shipped concurrent with this entry. The original
sub-$100 expansion scope becomes misaligned — most candidate tickers
were specifically chosen for the sub-$100 band Path A enabled.

**Reactivation criteria:**

After Option A validates (Thursday 2026-05-14 cycle produces created
suggestion from sub-$60 admit), re-scope:

- **If capital scales toward $1,500+:** sub-$100 universe expansion
  becomes viable; Path A's $100 bump may be reattempted.
- **If staying at $681 micro:** sub-$50 universe expansion is the
  viable shape — adds candidates without H7 conflict. Different
  ticker list than Tuesday's (would target sub-$50 liquid names:
  HBAN, MRO, MO, NIO, LCID, RIVN, plus possibly others).

**Status:** Deferred. Reactivate when criteria met. No timeline
commitment.

**[2026-05-12] LEARNING-MODE CODIFICATION.**

**What:** Captured operator's explicit learning-mode framing in
CLAUDE.md `## Backlog → ### Operating mode` subsection (placed
ABOVE Active focus so it frames the focus items below).

**Why:** Today's session repeatedly drifted toward "more trades"
recommendations (Path A widening, Lever 2 IV backfill design,
capital tier inflection analysis) because that's the default shape
of help when operator says "no trades today." Without explicit
codification, future sessions would re-derive the wrong framing
from the same observable state ($681 account, low trade frequency,
warmup gating).

**Source statement (operator, 2026-05-12 afternoon):**

> "At micro tier I want to perfect the code and make sure it enters
> and exits accordingly. After these are perfected I will add more
> capital. Right now I want to focus on logic and learning to
> optimize the best list of options and the best combination for
> profits/time for the account."

**Operational changes from this codification:**
- Capital addition deferred until operator signals readiness — the
  $681 → $1,000 micro→small cliff documented in today's tier
  inflection diagnostic is informational, not actionable
- Observability / analytics infrastructure becomes high-priority work
- "No trade today" no longer auto-triggers investigation if system
  shows working-as-designed behavior (warmup state, micro filters,
  etc.). H11 baseline still fires on critical alerts — orthogonal
  to trade-frequency framing.
- Low trade frequency during warmup window framed as expected, not
  as a problem to fix

**Validity:** Indefinite. Mode change requires explicit operator
declaration. If unsure whether learning-mode still applies, ASK.

**Tension with existing doctrine (surfaced, not resolved):**
- H11 risk_alerts baseline still mandates critical/high severity
  alerts as independent section in every diagnostic. Learning-mode
  doesn't override H11 — it shapes how findings are interpreted.
  Example: "no trade today + zero critical alerts" under
  learning-mode = system working as designed, not a problem to
  investigate.
- Warmup-window hypothesis (testable, codified 2026-05-12 morning)
  predicts low frequency through ~2026-07 — aligns naturally with
  learning-mode's "don't treat low frequency as bottleneck."
- The forward-looking framing means PRIOR session work (Path A
  bump prompts, Lever 2 α design diagnostic) is NOT rewritten.
  Those were correct under their own framing; learning-mode applies
  to FUTURE recommendations.

**Related codifications + work:**
- H10/H11/H8-extension doctrine (codified 2026-05-11 PR #922)
- H9 convention + Slot 1 AST gate (2026-05-11/2026-05-12 PRs #923 + #924)
- Warmup-window hypothesis (codified 2026-05-12 morning PR #925)
- Path A experiment ($60 → $100 universe filter, shipped 2026-05-12
  afternoon, Thursday decision trigger)
- Lever 2 α design diagnostic (drafted; implementation gated on
  Thursday Path A results AND learning-mode-aware decision)
- Tier inflection diagnostic (executed 2026-05-12 afternoon, session
  history) — surfaced the $1,000 cliff that triggered this codification

**Discipline shape:** mirrors PR #922 (H10/H11 doctrine capture)
and PR #923 (H9 convention codification) — findings get codified
durably so they shape future work rather than being re-derived
each session.

**Status:** Codified.

**[2026-05-12 → 2026-05-19] H9 AST gate: flip to strict mode.**
Slot 1 shipped today in warn-only mode (PR ships separately). After
~1 week of CI observability:
1. Review `h9_violations.json` artifacts from each CI run
2. Confirm allow-list is stable (no new legitimate-code violations
   surfacing in stderr warnings)
3. Confirm violation count holds at 7 (current allow-list size)
4. If stable: flip `H9_GATE_STRICT = True` in
   `packages/quantum/tests/test_h9_wrapper_drift_gate.py`
5. If not stable: investigate; may need detection refinement or
   allow-list expansion before flipping

Effort: ~30 min to flip + verify CI is green on the strict assertion.

**[2026-05-12] H9 migration candidates surfaced by Slot 1 scan.**
Real H9 violations found in the codebase scan (currently allow-listed
as deferred work):
- `packages/quantum/services/iv_point_service.py::upsert_point` —
  legacy IV path; logger-only swallow. Migration candidate (~30
  min) OR deprecation if `iv_repository.upsert_iv_point` is canonical.
- `packages/quantum/services/position_pnl_service.py::refresh_marks_for_user`
  — legacy leg-level refresh distinct from `paper_mark_to_market_service.refresh_marks`
  (#919+#920 fix path). Migration candidate (~2-4 hours) — apply same
  pattern (per-position alert + partial-status enum).
- `packages/quantum/services/universe_service.py::sync_universe` —
  print-swallow on upsert failure. Small fix (~30 min); replace
  `print(...)` with `alert()` per Anti-pattern 2.
- `packages/quantum/jobs/handlers/alpaca_order_sync.py::sync_orders`
  — nested handler with multiple logger-only paths. Larger refactor
  (~half day) — needs decomposition before H9 verification points
  can be inserted cleanly.

Effort to close all 4: ~1-2 days total. Not urgent; allow-list
expirations set to 2026-08-12 (3 months) to force re-review.

**[2026-05-12 EOD] Active focus #2 closed: H9 Convention codified.**
H9 doctrine entry in `docs/loud_error_doctrine.md` extended with
"Codified pattern with empirical anchors" subsection — cross-instance
fix-pattern table covering all 5 closed H9 instances (PR-A Layer 4,
Issue B / #908, #864, #62a-D5 / #117, MTM #919+#920), concrete code
anchors per rule (file:line references rather than abstract examples),
boundary-specific applications (DB write / broker API / refresh /
CLI-route), and when-NOT-to-apply guidance. Plus a new
"Class-prevention infrastructure proposals" subsection ranking 3
PR slots:

- **Slot 1 — AST gate** for wrappers-without-verification (~half
  day, precedent PR #917 Class B AST gate, catches all 5 known
  instances at PR time). RECOMMENDED first ship.
- **Slot 2 — Grep test** for silent-exception patterns in wrapper
  paths (`services/` + `brokers/` + `jobs/handlers/`) (~2 hours,
  precedent PR #913). Queued behind Slot 1; may consolidate if
  Slot 1 covers same surface.
- **Slot 3 — Type-narrowing** convention with `Literal["ok",
  "partial", "failed"]` status returns. Adopted as convention for
  new wrappers starting 2026-05-13; no infrastructure work.

Doctrine state after this PR + PR #922:
- H8: extended with false-alarm verification discipline (PR #922)
- H9: extended with codified convention + ranked infrastructure
  proposals (THIS PR)
- H10: cascade-suppression (PR #922)
- H11: status-check methodology baseline (PR #922)
- H12: intent drift across encodings — candidate, awaiting 3rd
  new instance for ratification

CLAUDE.md Active focus block: item #2 retitled to "H9 Convention
Slot 1 — AST gate"; item #3 refreshed (stale D3/D5 reference
replaced with #62a-D1 architectural PR which is the actual
queued HIGH work).

**[2026-05-14] TIER 2 CANDIDATE: dispatcher_health monitor.**

**Surfaced by:** 2026-05-14 08:41 CT pre-cycle status check
identified BE service silent on job dispatches since 05:00 UTC
(~8h40m of effective downtime). H11 baseline didn't catch it
because no internal monitor exists for "expected dispatches missing
during market hours." Only manual status check identified the outage.

**Observability gap:** Scheduler-stuck-detection has no current
mechanism. Worker liveness alone is insufficient because RQ
housekeeping runs even when the scheduler dispatcher is broken
(today's case: worker emitting "cleaning registries for queue: otc"
every ~13.5 min while no jobs got dispatched for 9h+).

**Proposed Tier 2 work:** `dispatcher_health` view + monitor.
- Internal view `expected_vs_actual_dispatches` joining APScheduler
  config-based expected fire schedule against actual `job_runs` fires
- During market hours (13:30-21:00 UTC weekdays), if any `job_name`
  shows `expected_count - actual_count >= threshold` within last
  N min, surface as `risk_alert`
- Threshold tuning needs design discussion (1 missed = transient;
  3+ missed = pattern)

**Effort estimate:** ~half day implementation + design.

**Anti-criteria (don't build yet):**
- α implementation in flight may un-gate priorities
- Operator pain from manual workaround is rare (today is N=1)
- More urgent Tier 2 work surfaces first

**Related shape:** Tier 1A's `event_driven_writer_health` candidate.
Both monitors bridge gaps between worker liveness and component
liveness — "is THIS surface producing output as expected?"

**Cross-references:**
- 2026-05-14 pre-cycle status check
- 2026-05-14 scheduler recovery (manual + restart)
- Tier 1B PR #928 (convenience views infrastructure)
- `event_driven_writer_health` (sibling candidate)
- H12 instance 5 (scheduler-stuck mechanism attribution)

**Status:** Captured. Tier 2 candidate. Prioritization TBD.

**[2026-05-14] TIER 2 CANDIDATE: supabase_http_health monitor.**

**Surfaced by:** 2026-05-14 scheduler recovery diagnostic
(post-restart log analysis) identified the actual root cause: BE
service hung on outbound Supabase HTTP timeouts at
`observability/alerts.py:85` (`httpx.ConnectTimeout`). Scheduler
thread was ALIVE and dispatching; every job hung on its Supabase
write. Surface symptom = no `job_runs` writes; mechanism =
outbound provider hang.

**Observability gap:** No monitor for outbound provider response
times. Today's incident was invisible until manual investigation
pulled BE logs.

**Proposed Tier 2 work:** outbound-provider response-time monitor.
- Track p50/p95 response times for outbound HTTP (Supabase, Alpaca,
  Polygon) during market hours
- If p95 exceeds N seconds for M consecutive minutes during market
  hours → surface `risk_alert`
- Different threshold per provider (Polygon may legitimately take
  longer than Supabase)
- Integrates with existing `observability/alerts.py` infrastructure

**Effort estimate:** ~half day design + build + test.

**Anti-criteria (don't build yet):**
- Provider issues are rare (today is N=1)
- `dispatcher_health` (Tier 2 sibling) may cover the user-visible
  symptom subset
- Vendor-side issues might be better monitored via their own status
  pages than internal infrastructure

**Open scope question:** does `dispatcher_health` subsume this? If
the dispatcher monitor catches "no dispatches," users get the same
signal whether mechanism is scheduler-dead or provider-hung. Design
diagnostic should clarify whether mechanism-monitor is worth
separate work.

**Cross-references:**
- 2026-05-14 scheduler recovery investigation
- `dispatcher_health` (sibling candidate)
- `observability/alerts.py:85` (the actual timeout site today)
- H12 instance 5 (today's mechanism-attribution finding)

**Status:** Captured. Tier 2 candidate. May overlap with
`dispatcher_health`; design diagnostic should clarify scope.

**[2026-05-14] TIER 2 CANDIDATE: count_rows_for_date stale-read mechanism.**

**Surfaced by:** 2026-05-14 evening iv drift investigation found that
the `iv_handler_accounting_mismatch` alert has fired exactly THREE
times in table history, all with identical metadata:

- 2026-05-09 05:06:13Z: stats_ok=1, actual_rows=5, delta=-4
- 2026-05-09 05:48:51Z: stats_ok=1, actual_rows=5, delta=-4
- 2026-05-14 16:00:48Z: stats_ok=1, actual_rows=5, delta=-4

The constant (5, 1, -4) shape across three independent firings is the
smoking gun. This is a structured artifact of the count mechanism,
not three coincidentally-equal real row states.

**Verification of "not real":** `pg_stat_user_tables` on
`underlying_iv_points` shows `n_tup_del=1` LIFETIME, `live_rows=279`,
sum-by-date reconciles to exactly 279 across known good days
(70+70+69+70). If 5 rows had ever existed and been deleted, `n_tup_del`
would reflect that. It doesn't.

**Mechanism (unresolved — Tier 2 investigation candidate):**

Plausible candidates for what produces the (5, 1, -4) artifact:
- Stale Supabase read replica showing pre-deletion state from an
  unrelated table operation
- PostgREST count cache invalidation lag
- HTTP-layer caching between worker and Supabase
- Specific code path in `count_rows_for_date` that constructs a
  misleading filter (e.g., wrong as_of_date type coercion, cross-table
  join, count over a different scope)

**Unification hypothesis (added 2026-05-14 evening, post-investigation):**

Today's count_rows_for_date investigation produced strong directional
evidence that this Tier 2 candidate and the sibling candidate
(`iv_daily_refresh` silent invocation path) may share a single root
mechanism. Evidence:

- All 3 alert firings (2026-05-09 ×2, 2026-05-14 ×1) have identical
  metadata: `stats_ok=1, actual_rows=5, delta=-4`
- All 3 alert firings have NO corresponding `job_runs` entry —
  verified for both days
- The "5" doesn't correspond to any natural counting scope of
  `underlying_iv_points` (no underlying has 5 rows, no source has
  5 rows, total table is 279)
- The "5" is returned regardless of actual table state: 0 rows for
  date → 5; 70 rows for date → 5; different date with 0 rows → 5
- Yesterday's 2026-05-13 cron run (via standard `enqueue_job_run`
  path) reported `accounting_match=true` with `actual_rows=70` —
  the STANDARD path works correctly

**Hypothesis H5:** The silent invocation path uses a different client
context (test client? mocked client? misconfigured client?) that
returns a fixed count of 5. Both surface symptoms (no `job_runs` +
count=5) are produced by the same invocation path.

**Implication for investigation scope:** investigating
`count_rows_for_date` in isolation will miss the unifying mechanism.
The right next move is the silent invocation investigation, which
would likely resolve both candidates.

**Investigation paths ruled out (today, 2026-05-14):**

- Stale read replica (H1): no replicas configured for this Supabase
  project (`pg_stat_replication` returns 0 rows)
- Code-side filter construction (H4): `count_rows_for_date`
  implementation is clean — single `.eq()` filter on DATE column
  with properly formatted `'%Y-%m-%d'` string, no type coercion bug,
  no wrong-table reference

**Investigation paths still unresolved (scope-limited):**

- PostgREST count cache (H2): code uses `count="exact"` which is the
  most reliable count mode; no application-level caching observed;
  cannot rule out supabase-py library bug without inspecting
  installed package source
- HTTP-layer caching (H3): cannot inspect Railway → Supabase HTTP
  infrastructure within read-only investigation scope

**Investigation surface (when prioritized):**

- Read `IVRepository.count_rows_for_date` at
  `packages/quantum/services/iv_repository.py:158-180` carefully —
  what query shape does it produce?
- Try to reproduce the (5, 1, -4) shape: under what conditions does
  count return 5?
- Cross-reference Supabase project configuration (read replicas,
  PostgREST caching settings, connection pool semantics)
- Verify whether the count's "5" is consistent with ANY scope reading
  of `underlying_iv_points` or related tables

**Phase 1 dependency:**

Phase 1's `iv_historical_backfill` handler ALSO uses
`count_rows_for_date` for verification (see
`test_iv_historical_backfill_handler.py:60+`). If the count can return
misleading values, Phase 1's verification path can fire false-positive
alerts AND/OR mask real issues. This is a Phase 1 readiness blocker.

**Effort estimate:** ~45-60 min focused investigation. Could expand
if Supabase configuration access is needed.

**Anti-criteria (don't prioritize if):**

- α implementation in flight with other Phase 1 blockers — wait
- 4th identical (5, 1, -4) firing happens → escalate, not deprioritize
- Operational picture changes substantially (e.g., handler stops
  running) — re-evaluate scope

**Cross-references:**

- 2026-05-14 iv drift investigation (session history; evidence chains
  documented)
- 2026-05-14 iv root cause investigation (precursor)
- H9 doctrine: count check is PR #115 Layer 4 wiring
- H12 doctrine: today's 4th catch surfaced this finding (post-nap
  sync's "5→0 drift" framing was the artifact)
- Sibling Tier 2 candidates: `dispatcher_health`, `supabase_http_health`
  (different infrastructure surfaces, complementary observability)
- Related Tier 2 candidate: `iv_daily_refresh` silent invocation path
  (bundled for Phase 1 readiness path)

**Status:** RESOLVED (2026-05-14 evening).

**Resolution:** H5 unification hypothesis confirmed via the silent
invocation investigation. The alerts come from local developer pytest
execution of `test_iv_daily_refresh_handler.py` against a developer
environment with real Supabase credentials. The test mocks
`IVRepository` (causing `count_rows_for_date` to return hardcoded `5`
at `test_iv_daily_refresh_handler.py:43`) but does NOT mock the
handler's lazy alert import path. When the accounting check fires
(`iv_daily_refresh.py:130-153`), it does
`from packages.quantum.observability.alerts import ... _get_admin_supabase`
which reads env at call time and constructs a real production
admin client, then writes to production `risk_alerts` as a
side-effect of test execution. All evidence reconciled:

- "5" = test mock's hardcoded return value
- "1" = test universe math (only AAPL has snapshot mock; 4 others
  fall to MagicMock fallback marked as `missing_data`)
- "delta=-4" = arithmetic (stats_ok − actual_rows = 1 − 5)
- "no `job_runs` entry" = test calls `run({})` directly, bypassing
  `enqueue_job_run`
- Reproduces across days because test setup is constant code (not
  dependent on table state)
- 2026-05-09 ×2 = PR #115 wrapper-drift debugging windows
- 2026-05-14 ×1 = today's PR work

**Fix applied:** test now mocks
`packages.quantum.observability.alerts._get_admin_supabase` directly
(primary, surgical); `_get_admin_supabase` gains a `PYTEST_CURRENT_TEST`
env-guard returning `None` unless `ALERTS_ALLOW_ADMIN_UNDER_PYTEST=1`
is set (defense-in-depth for any future test that bypasses
handler-level mocking).

**Phase 1 readiness:** CLEAR. The mechanism is test pollution, not
production reliability. Standard `enqueue_job_run` path verified
working (2026-05-13 cron, `accounting_match=true`,
`actual_rows=70`).

**[2026-05-14] TIER 2 CANDIDATE: iv_daily_refresh silent invocation path.**

**Surfaced by:** 2026-05-14 evening iv drift investigation found that
the `iv_handler_accounting_mismatch` alert fired at 2026-05-14
16:00:48 UTC, attributable ONLY to code in
`packages/quantum/jobs/handlers/iv_daily_refresh.py` (verified — only
3 files reference the alert_type: the handler + 2 test files).

**Yet:** no `job_runs` row exists for `iv_daily_refresh` (or
hyphenated variants) for 2026-05-14. Most recent successful
`iv_daily_refresh` job run: 2026-05-13 09:30Z (yesterday's cron). The
04:30 CT scheduled fire for 2026-05-14 did not occur as a tracked job.

**Implication:** the handler ran today via a code path that bypasses
`enqueue_job_run` / `job_runs` observability.

**Timing clue:** the alert fired 26s after `suggestions_open`
completed at 16:00:22Z. Suggests possible inline invocation from
`suggestions_open` or a downstream component during the midday cycle.

**Unification hypothesis (added 2026-05-14 evening, post-investigation):**

Today's count_rows_for_date investigation produced strong directional
evidence that this Tier 2 candidate and the sibling candidate
(`count_rows_for_date` stale-read mechanism) may share a single root
mechanism. See the `count_rows_for_date` entry above for full
evidence chain.

**Hypothesis H5:** The silent invocation path uses a different client
context that returns a fixed count of 5. The "no `job_runs`" symptom
and the "count=5 artifact" symptom are produced by the same
invocation path.

**Implication for investigation scope:** investigating silent
invocation should integrate the H5 framing from the start. Finding
the silent invocation path likely resolves the count=5 mechanism too.
The investigation should specifically look at:

- What client construction does the silent invocation path use?
- Does it differ from the standard handler invocation (via
  `enqueue_job_run`) in client context, configuration, or wrapping?
- Could the path be importing `iv_daily_refresh`'s handler function
  inline rather than via the dispatcher?
- Is there a test/mock client leak into a production code path?

**Refined effort estimate:** still ~45-60 min focused investigation,
but with sharper framing — the search is for a specific code path
that explains both symptoms, not two parallel investigations.

**Investigation surface (when prioritized):**

- Search for any inline calls to `iv_daily_refresh`'s handler function
  from other components:
  ```bash
  grep -rn "iv_daily_refresh\|refresh_iv\|run_iv_daily" \
    packages/quantum/ --include="*.py" | head -20
  ```
- Check `suggestions_open`'s handler / scanner code for any inline
  iv-related calls
- Check `paper_autopilot_service` for any iv refresh triggers
- Verify whether α's `iv_historical_backfill` could share a similar
  silent-invocation risk

**Phase 1 dependency (refined 2026-05-14 evening):**

The CONDITIONAL Phase 1 readiness verdict from the original capture
is refined post-investigation:

- `count_rows_for_date` in the STANDARD path (cron-fired handler via
  the normal Supabase client) is likely reliable. Yesterday's
  2026-05-13 cron run validates this (`accounting_match=true`,
  `actual_rows=70`).
- Phase 1 trigger via the standard `enqueue_job_run` path should
  work correctly.
- The silent invocation path is a separate observability concern
  but doesn't directly block Phase 1 if Phase 1 uses the standard
  path.

Phase 1 readiness is less blocked than the original Tier 2 capture
suggested, while still recommending the silent invocation
investigation as the next priority.

**Effort estimate:** ~45-60 min focused investigation. Could be
shorter if the inline-call path is obvious from a grep.

**Anti-criteria (don't prioritize if):**

- `count_rows_for_date` investigation surfaces a fix that also
  addresses observability — bundle them
- Phase 1 readiness becomes time-critical and silent-handler is
  determined to be benign (low risk of Phase 1 impact)
- Operator decides observability gap can be lived with for Phase 1
  if iv state is verified manually post-trigger

**Cross-references:**

- 2026-05-14 iv drift investigation (session history)
- 2026-05-14 iv root cause investigation (precursor finding of
  "didn't fire at 04:30 CT during outage")
- Related Tier 2 candidate: `count_rows_for_date` stale-read mechanism
- Sibling Tier 2 candidate: `dispatcher_health` (would have caught
  this silent invocation if expected/actual dispatch monitor existed)
- H11 doctrine: critical alerts independent of operator framing (the
  alert fired correctly; the gap is the invocation traceability)

**Status:** RESOLVED (2026-05-14 evening).

**Resolution:** Same mechanism as the sibling `count_rows_for_date`
entry above — see that entry for the full evidence chain. Both
symptoms (no `job_runs` row + `count_rows_for_date` returning
hardcoded `5`) are produced by a SINGLE invocation path: local
developer pytest execution of `test_iv_daily_refresh_handler.py`
against a developer environment with real Supabase credentials.

The test calls `run({})` directly (`test_iv_daily_refresh_handler.py:46`),
bypassing `enqueue_job_run` entirely. No `job_runs` row is ever
created because the dispatcher path is never entered. The
accounting alert that fires inside the handler writes to production
`risk_alerts` via a lazy `_get_admin_supabase` import that
side-steps the test's IVRepository mock.

**Fix applied:** test patches
`packages.quantum.observability.alerts._get_admin_supabase` to
return `None` (primary); `_get_admin_supabase` gains a
`PYTEST_CURRENT_TEST` env-guard (defense-in-depth). See sibling
entry for code references.

**Phase 1 readiness:** CLEAR. Phase 1's
`iv_historical_backfill` handler does not have the same lazy-import
pattern — it writes its audit `risk_alerts` row via the
test-mocked `client` directly (`iv_historical_backfill.py:188`),
so `test_iv_historical_backfill_handler.py` was never at risk.
Verified during today's investigation.

**[2026-05-14] FRAMEWORK CAPTURE: capital scaling preparation.**

**Originated:** 2026-05-14 structural finding (see CLAUDE.md
"Structural learning: 2-leg debit spread geometry at micro BP")
revealed 2-leg debit spreads at $681 + standard $5 chains on $50+
underlyings are structurally incompatible. Two strategic responses
available: capital scaling or strategy class shift. Operator framing:
both may apply.

**This entry captures OPEN QUESTIONS for the capital scaling
framework. NO DECISIONS in this entry — questions are durable
artifacts for future thinking.**

### Open question 1: Trigger criteria

What evidence justifies a capital addition?

Candidates:
- **α validates AND credit spreads also fail H7:** confirms
  structural scope extends beyond debit spreads; capital becomes
  more compelling
- **Budget-fit diagnostic identifies viable structures at $681:**
  capital becomes less urgent (strategy class change is the path)
- **Time-based:** N weeks of post-α observation with zero creatable
  suggestions → capital addition triggered
- **Specific milestone:** code produces N viable creatable
  suggestions per week consistently → ready to scale

Each implies a different patience profile. No single right answer.

### Open question 2: Target amount

Multiple thresholds matter:

- **$1,500:** smallest meaningful change. Standard $5-wide debit
  spread math works ($500 × 2.1 = $1,050 < $1,500). Single position
  capacity restored.
- **$3,000-$5,000:** enables concurrent positions per Tuesday's
  tier inflection diagnostic (4 positions at micro tier with proper
  diversification)
- **$10,000+:** enables small-tier behavior, different concurrency
  policy, different EV calculations

Each level has implications. Operator decides based on risk
appetite + runway + product maturity.

### Open question 3: Validation signals

How do we know a capital addition was right?

Candidates:
- Trade frequency stabilizes at non-zero rate
- Win rate stays consistent with paper-trade baseline (no regime
  shift artifacts)
- No new structural-fit failures surface
- H7 / sizing rejections drop to pre-Path-A rates

### Open question 4: Sequencing vs α

If α is shipping (un-gated by today's findings), should capital
scaling decision wait for α's data?

- **Wait for α data:** more informed decision; α might reveal
  credit spreads work at $681, reducing capital urgency
- **Ship α + plan capital independently:** parallel paths; capital
  decision proceeds on its own timeline
- **Conditional sequencing:** capital decision IF α validates
  structural finding extends beyond debit spreads

### Anti-criteria

Do NOT trigger capital scaling without:
- α implementation shipped + at least 1-2 weeks of observation
- Budget-fit diagnostic results (separate work)
- Explicit trigger from Open Question 1 satisfied

### Decision shape when triggered

- Specific amount chosen + rationale
- Specific validation criteria committed
- Specific monitoring plan post-addition (track Q3 signals)
- Reversibility plan (if signals don't match, what to do)

**Validity:** Until triggered OR until structural finding is
invalidated by α / diagnostic / other evidence.

**Cross-references:**
- 2026-05-14 structural learning note (CLAUDE.md)
- Tuesday's tier inflection diagnostic (concurrency thresholds)
- α implementation prompt (Thursday-gated, may un-gate)
- Future budget-fit diagnostic (informs Q1 trigger)
- Learning-mode codification (refined per today's finding)

**Status:** Framework captured as open questions. No decisions.

**[2026-05-14] Budget-fit landscape diagnostic findings.**

**Conducted:** Empirical scan across 3 sample underlyings (HBAN
$15.57, KHC $23.58, KO $80.72) testing 22+ option structures against
H7 round-trip safety (`max_loss × 2.1 ≤ $681`). Late-morning CT
snapshot; Jun 12 / Jun 18 / Jun 26 expirations (28-42 DTE).

**Key findings:**
- **Class A (1-leg long options):** 16/22 combinations fit. Sub-$30
  names: most ATM and OTM strikes fit. $50+ names: only mid-delta
  calls and OTM puts; ATM and deep ITM fail. Caveat: lower
  systematic edge; current scanner doesn't target directional 1-leg.
- **Class B (narrow-strike debit spreads on sub-$30):** 8/8 fit.
  Discovered: KHC has $0.50 strikes (finer than original prompt
  assumption). HBAN $1-wide and KHC $0.50-$2-wide both fit reliably.
- **Class C (credit spreads):** width-dependent. $1-wide fits
  broadly on both sub-$30 and $50+ names. $2.50-wide on KO ATM-OTM
  marginal (fits or fails depending on premium collected).
  $5-wide on $50+ names fails (same geometry mirror as 2026-05-14
  KO H7 firing).
- **Class D (iron condors with $1-wide wings):** fits per-contract
  math on both KO ($46 net credit → $54/wing max_loss → $113 RT)
  AND KHC ($21 net credit → $79/wing max_loss → $166 RT). BUT
  blocked by `iv_rank` gate in `strategy_selector` until α
  accumulates historical IV depth.
- **Class E (CSPs / covered calls):** excluded by underlying capital
  reservation ($1,400+ even for HBAN @ $14 strike).

**Structural mechanism finding (promoted to CLAUDE.md operational
note in this PR):** The right frame for H7 fit is
entry-premium-vs-width ratio, NOT width or leg count alone. The
scanner's `_select_legs_from_chain` uses delta-target leg selection
which naturally clusters ATM-OTM — the worst H7 region at $50+
underlyings. Strike granularity also varies by expiration (KO Jun 12
has $1 strikes, Jun 18 has $2.50).

**Implications for next direction (NO decisions captured here):**
- **α implementation is more load-bearing than "observability fill"** —
  it unlocks Class D candidates verified-fittable today but blocked
  by `iv_rank` gate. Refines the prior framing where α's value was
  rank-window observability + Polygon-cost hedge.
- Scanner-emission patterns may want awareness of strike granularity
  per-expiration + width-to-premium ratio, not just width.
- Class B fit at sub-$30 names contrasts with current universe
  scope (Option A capped at $60; sub-$30 names present in
  BASE_UNIVERSE but emission rate at micro tier not verified by
  this diagnostic).
- Updates Capital scaling framework Open Question 1: budget-fit
  diagnostic has now identified viable structures at $681 (Class
  B, Class D after α). Per Q1 candidates, this makes capital scaling
  "less urgent" rather than "more compelling" — strategy class
  change is a verified path.

**Cross-references:**
- 2026-05-14 structural learning (CLAUDE.md operational note); this
  diagnostic is the empirical corrective to the "no strategies fit"
  over-generalization caught at synthesis time
- CLAUDE.md operational note in this PR (mechanism explanation)
- PR #935 (α historical IV backfill — directly unlocks Class D)
- Capital scaling framework (2026-05-14 entry, updates Q1)
- H12 framing-artifact doctrine (the H12 instance this diagnostic
  empirically rebuts)

**Re-run trigger:** material IV regime shift (KO IV currently
0.17-0.21 — historically low; a vol spike would shift Class C/D
credits collected meaningfully). Or: broader sample pool (>10
underlyings) to refine fit-rate confidence per class.

**Sample-size caveats:** 3 underlyings is small. Bid-ask spreads
run 20-100%+ on OTM wings of sub-$30 names (e.g., KHC 22C
0.89/2.35 = 164% spread). Mid prices used for fit math; actual
marketable entry cost would be ≥ mid + 0.5×spread. Findings phrased
as "fits today on names tested at current IV" not "always fits."

**Status:** Diagnostic complete. Findings preserved in operational
note + this backlog entry. No automated action.

**Refinement from empirical observation (2026-05-14 midday cycle):**

The 2026-05-14 16:00 UTC suggestions_open cycle produced a Ford
F LONG_CALL_DEBIT_SPREAD candidate (Class B territory, sub-$15
underlying):
- Passed scanner-internal gates ✓
- Passed H7 round-trip safety ✓ (Class B fit confirmed in production)
- Reached `trade_suggestions` creation ✓ (created=1 for the cycle)
- Blocked at `edge_below_minimum` ✗ (EV 15.44 below threshold;
  PoP 32.96%)
- Final status: `NOT_EXECUTABLE`

**Implications:**
- Class B (sub-$30 narrow-strike) DOES emit candidates at $681
  capital — empirical confirmation of this diagnostic's prediction.
- `edge_below_minimum` is the next-most-load-bearing downstream gate
  beyond H7 for Class B-shape candidates.
- The structural finding's framing ("system can't produce trades at
  $681") remains technically correct, but the BINDING CONSTRAINT
  has shifted from H7 to `edge_below_minimum` for Class B candidates
  specifically.

**Follow-up worth considering (separate work, not this entry):**
- What is the `edge_below_minimum` threshold and where is it set?
- Is EV 15.44 (Ford's value) far below threshold or just below?
- Could threshold tuning unlock Class B emissions at micro tier?
- Is `edge_below_minimum` a tuneable parameter or a load-bearing
  invariant like H7?

These are open empirical questions, not actions for this entry.
The Ford F observation also surfaced via the cycle-shape diagnostic
(H12 instance #6 — see `docs/loud_error_doctrine.md`) which caught
that today's midday cycle was a real scanner run, not the "anemic
wrapper" the midday status check initially misread.

**[2026-05-14] UNIVERSE HYGIENE: Stale-ticker audit candidate (Tier 3).**

**Surfaced by:** The 2026-05-14 budget-fit diagnostic encountered MRO
(Marathon Oil) returning Nov 2024 daily-bar data with no recent
quotes. MRO was acquired by ConocoPhillips in Nov 2024; the ticker
is effectively defunct but still present in candidate pools.

**Observation:** BASE_UNIVERSE may contain other stale tickers from
acquisitions, delistings, or name changes that aren't surfaced by
liquidity screens alone. A delisted ticker returns no liquidity (so
liquidity screens filter it), but a recently-acquired ticker may
return stale historical data without obvious upstream failure —
the scanner just doesn't generate emissions for it.

**Proposed audit (Tier 3 candidate, low priority):**
- One-time scan: query each BASE_UNIVERSE ticker via Alpaca /
  Polygon for `latest_quote` and `latest_trade.t`
- Flag tickers with `latest_trade.t > 30 days ago` OR no recent
  quotes
- Cross-reference against a recent-acquisitions list (manual or
  programmatic)
- Update BASE_UNIVERSE: remove confirmed-defunct tickers; surface
  ambiguous cases for operator review

**Effort estimate:** 1-2 hours including the corporate-action
cross-reference step.

**Anti-criteria (don't prioritize if):**
- Scanner gracefully handles stale tickers today (they'd produce
  zero emissions per cycle without breaking)
- No other operational impact observed beyond wasted Polygon API
  calls
- Bigger work items in flight

**Cross-references:**
- 2026-05-14 budget-fit diagnostic (surfacing event)
- `BASE_UNIVERSE` in `universe_service.py`

**Status:** Captured. Tier 3 candidate. Low priority.

**[2026-05-12 20:56 UTC] Path A shipped: MICRO_TIER_MAX_UNDERLYING $60 → $100.**

Lever 1 universe-widening experiment via Railway env var on the
`worker` service. No code change, no PR (Railway audit trail captures
the action). Triggered a fresh build (`a47c24c6-8f51-4f26-82f0-0b6439a035ef`,
BUILDING at the time this entry was written) which will recycle the
worker on completion.

**Pre-bump baseline correction:** Today's combined diagnostic
analysis assumed the threshold was at the code default $50, but
Railway had it set to $60 (long-standing override, predating today's
session). The diagnostic's "$50 → $75" widening math was based on
the wrong baseline. After re-inspection via
`underlying_iv_points.spot` distribution today: 48 scanner-active
symbols sit above $60; operator chose $100 as the conservative tier.

**Pre-bump baseline (Tuesday 2026-05-12 16:00 UTC suggestions_open):**
- 62 universe → 28 micro_tier_rejected → 34 remaining → 14 processed
- Rejection counts (total 52): 28 micro_tier, 9 strategy_hold, 9
  no_fallback, 4 entry_cost_too_low, 2 all_strategies_rejected
- Emissions: 1 LONG_CALL_DEBIT_SPREAD; counts.created: 0
- `iv_pipeline_no_data` warning fired (40/40 missing iv_rank — warmup
  state, day 3 of ~60)

**Expected symbols recovered by $60 → $100 bump:**
8 names in the $60-$100 band — MDLZ $61, EEM $68, KO $78, HYG $80,
XLP $83, NFLX $85, TLT $86, CSCO $98. Effective recovery likely
~5-6 per cycle due to scanner snapshot-timing vs IV-refresh-timing
(48 vs 28 gap observed today). Contracts at these underlyings
should fit micro $450 budget at 2.5-wide spreads (~$200-$400
max_loss/contract).

**What to compare on Wednesday + Thursday's `suggestions_open` cycles:**
- `micro_tier_underlying_too_high` count: expect ~20 (down from 28)
- `symbols_processed` count: expect ~17-20 if 34→14 trim doesn't eat
  the new admissions
- `emission_counts_by_strategy`: expect to rise above today's 1
- `counts.created`: expect >0; this is the actual win condition
- New rejection patterns: watch for `sizing_rejected` /
  `budget_exceeded` if mid-cap contracts exceed budget

**Decision trigger date: 2026-05-15 (Thursday afternoon, post-cycle).**

Decision shape:
- **Widening helped (emissions/creates rise):** Path A worked.
  Decide whether to push further to $150 OR concentrate on the
  34→14 trim investigation. Lever 2 (IV backfill) decision is
  separate and stays on the warmup-window-progress curve.
- **No change in emissions despite more processed symbols:** the
  34→14 trim is the real bottleneck. Investigate the trim before
  any further widening. Path A still keeps the $100 setting; revert
  only if it caused harm.
- **No change in `symbols_processed`:** env var didn't take effect
  OR new symbols are also being eaten by the 34→14 trim. Verify
  env first.
- **Sizing rejections spike:** $60-$100 contracts exceed micro
  budget at sizing layer. Consider reverting OR adjusting sizing
  tolerance. Per diagnostic, this is the less-likely failure mode
  at $100 (sub-$100 names typically use 2.5-wide spreads).

**Reversibility:** instant. Revert via Railway dashboard (set back
to 60) if Wednesday's cycle shows immediate harm. The env-var change
triggered a fresh deploy; revert would do the same.

**Notable adjacent state:**
- A NEW SUCCESS deploy fired at 2026-05-12 14:12 UTC (deployment
  `b76132c7-0909-4550-a942-cc84508f7afa`) — pre-dates this env-var
  change. Worker had already recycled today onto a fresh image
  (likely containing PR #924's H9 gate content via the PR #925 merge
  trigger). Today's 16:00 UTC `suggestions_open` ran on this image,
  not on PR #923's. The current BUILDING deploy from the env-var
  change will be the SECOND restart today. PR #924 deploy pairing
  reminder (entry above) is now likely satisfied — verify when the
  BUILDING deploy completes.

**Related work:**
- Lever 2 α (BS-inversion IV backfill) design diagnostic still
  pending; sequence is "observe Path A first, then decide if α
  warranted vs Lever 2 β (lower `sample_size` constant)"
- "1 emission → 0 created" watch still active (expires 2026-05-15)
- Path A status: shipped (`MICRO_TIER_MAX_UNDERLYING=100`)

**Status:** Shipped. Empirical observation in flight.

**UPDATE 2026-05-14:** Path A experiment CONCLUDED.

Path A produced empirical refutation data on 2026-05-13 (KO H7 trace
identified that $100 admits fail H7 round_trip_bp_insufficient at
$681 BP). Option A reverted to $60 via PR #932 on 2026-05-13. Today's
validation cycle (manually triggered + then misfire-recovered after
scheduler outage) produced refutation data on the reverse hypothesis
("$60 reliably produces creatable candidates") — emissions were 0
today vs Tuesday baseline of 1.

Combined finding: both universe tunings produced refutation data
pointing at the same structural limit (capital + chain geometry).
Structural finding captured in CLAUDE.md "Structural learning:
2-leg debit spread geometry at micro BP" 2026-05-14.

Path A served its purpose. No further universe tuning work without
strategy class change OR capital scaling decision. See capital
scaling framework entry for the decision pipeline.

**Status:** CLOSED. Findings rolled up to structural learning note.

**[2026-05-15] TIER 1 CANDIDATE: worker-queue blocker for long-running backfills.**

**Priority:** TIER 1 — should be addressed BEFORE Phase 3 (full
67-symbol α backfill).

**Surfaced by:** Today's Phase 1 α reference backfill (job_run
`9627c667-61e5-4915-a83c-a584b03bab0a`) executed during trading hours
and demonstrated a worker-queue starvation pattern.

**Mechanism (verified):**

Phase 1 triggered at 2026-05-15 11:55 UTC (US pre-market). Handler
ran on the single worker queue for 30,759 seconds (~8.5 hours).
Every other job that should have fired during that window was queued
behind the backfill and processed only AFTER it completed at
20:28 UTC.

Jobs delayed (scheduled → actual fire, derived from `job_runs`
timestamps):

- `day_orchestrator`:        12:30 → 20:28 UTC  (7h 58m delay)
- `suggestions_close`:       13:00 → 20:28 UTC  (7h 28m delay)
- `paper_exit_evaluate`:     13:15 → 20:28 UTC  (7h 13m delay, morning)
- `suggestions_open`:        16:00 → 20:31 UTC  (4h 31m delay)
- `paper_auto_execute`:      16:30 → 20:31 UTC

When `suggestions_open` finally ran at 20:31 UTC, it fast-path
early-exited on staleness gate:
`market_data_stale (age=30.6min, symbols=['SPY'])` because the
market had been closed 31 minutes.

**Effective state of today:** zero real trading-day pipeline
execution. No cycle-emitted suggestions evaluated. No exit
evaluations during the day.

**Why this matters (escalation path at higher tiers):**

Today's actual cost was low — 0 open positions, micro tier, nothing
to evaluate. The trading-day pipeline starving for 8.5h had no
consequence because there were no positions to risk-manage and no
real candidates to process.

The SAME pattern at higher capital tiers or with open positions
would mean:

- `intraday_risk_monitor` starved → no risk monitoring during
  trading day
- `paper_exit_evaluate` starved → exit signals not evaluated;
  positions could miss stop-loss / take-profit triggers
- `suggestions_open` delayed → no candidate emission during market
  hours
- `paper_auto_execute` delayed → if any candidates HAD emerged,
  they'd reach execution post-close (similar staleness gate behavior)

These are load-bearing for any open-position state. An 8.5h block
is not safe.

**Phase 3 implication:**

Phase 3 (full backfill for remaining 67 symbols, ~67 vs today's 3)
is structurally the same operation. If 3 symbols × 60 days took
8.5 hours, 67 symbols × 60 days scales much longer (potentially
1-2+ days even with batching gains). That would block the
trading-day pipeline for entire trading days. Unacceptable at any
non-zero position state.

**Mitigation options (enumerated, not yet decided):**

**Option A: Schedule long backfills outside trading hours.**

Add a guard in the trigger plumbing (PR #941's HTTP route) that
refuses trigger during US trading hours (13:30-21:00 UTC weekdays)
unless an explicit override flag is passed. Operator self-discipline
to only trigger overnight/weekend.

- Effort: ~30-45 min (small route + script change)
- Cost: requires operator to be available during off-hours OR plan
  ahead
- Risk: low; preserves canonical pattern

**Option B: Move long backfills to a separate worker queue.**

Add a "background" or "low-priority" worker queue for long-running
jobs like backfills. Trading-day pipeline jobs continue on the main
queue. Backfill runs in parallel without blocking.

- Effort: ~half-day to full day (RQ queue config + scheduler routing
  + Railway service config)
- Cost: real engineering work + Railway service overhead (additional
  worker process)
- Risk: medium; new infrastructure surface

**Option C: Make backfill handler chunk-and-yield friendly.**

Refactor `iv_historical_backfill` to process in smaller chunks (e.g.
10 days at a time per invocation) and re-enqueue itself for the next
chunk. Each chunk runs for ~30-45 min; trading-day jobs can
interleave.

- Effort: ~half-day (handler refactor + re-enqueue logic + state
  tracking)
- Cost: more complex handler; need to track partial-completion state
- Risk: medium; introduces re-entrancy considerations

**Investigation surface (when prioritized):**

- Verify current worker queue topology (single queue vs multiple)
- Read scheduler/worker config for any existing job priority
  mechanisms
- Check if RQ supports job priorities or named queues out-of-box
- Cross-reference Railway service config for worker resource
  allocation

**Effort estimate:** decision-only ~30 min; implementation depends
on chosen mitigation (30-45 min for Option A; half-day+ for
Options B/C).

**Anti-criteria (don't prioritize if):**

- Phase 2 validation FAILS and α is refuted — no further backfill
  needed
- Decision made to limit α to current 3 reference symbols permanently
- Operator chooses to manually-time all backfills (acceptable for
  low-tier micro state but not scalable)

**Cross-references:**

- Today's Friday EOD check synthesis (conversation history) —
  evidence chain
- PR #941 (trigger plumbing) — created the trigger surface that now
  needs rate-limiting
- α implementation plan — Phase 3 (full universe backfill) is the
  next step that would be blocked by this issue
- `packages/quantum/jobs/handlers/iv_historical_backfill.py` —
  current long-running implementation

**Status:** Captured. Tier 1 candidate. Should be addressed before
Phase 3 trigger. Phase 2 manual validation is NOT blocked by this
finding (Phase 2 is operator-driven, no worker queue dependency).

**Update (2026-05-15 evening, Phase 2 validation results):**

α Phase 2 manual validation completed with 3/3 symbols passing
(SPY 1.31, AAPL 1.27, AMD 0.26 pct-points delta against barchart
reference for 2026-05-08). α is validated.

This means **Phase 3 (full 67-symbol backfill) is now gated ONLY on
this worker-queue blocker mitigation.** All other prerequisites are met:

- ✓ α implementation merged (PR #935)
- ✓ Trigger plumbing operational (PR #941)
- ✓ Phase 1 reference backfill clean (165 rows, smooth values)
- ✓ Phase 2 validation passed (3/3 within tolerance)
- ⏳ Worker-queue blocker mitigation (THIS candidate)
- → Phase 3 trigger
- → Phase 4 sanity check
- → Phase 5 operational cutover

Priority unchanged: TIER 1, before Phase 3. The three mitigation
options remain enumerated above (trading-hours guard / separate queue /
chunk-and-yield handler). See CLAUDE.md "α Phase 2 — VALIDATED" entry
for full validation table.

**RESOLVED (2026-05-16, Option B — separate worker queue):**

Option B implemented via single engineering PR:

- Added `BACKGROUND_QUEUE = "background"` constant in
  `packages/quantum/jobs/rq_enqueue.py` (alongside existing queue
  plumbing).
- `iv_historical_backfill` route in `internal_tasks.py` now passes
  `queue_name=BACKGROUND_QUEUE` to `enqueue_job_run`. All other
  routes continue to use the default `otc` queue (regression-
  guarded by test).
- Tests added (`test_background_queue_routing.py`): source-level
  structural assertions on the route + unit tests verifying
  `enqueue_idempotent` propagates `queue_name` to the RQ `Queue`
  construction + `make_job_id` signature lock to keep it queue-
  agnostic (prevents future drift that would allow cross-queue
  double-execution).
- New Railway service `worker-background` deployed by operator
  with start command `rq worker background`. Same Dockerfile, same
  env vars (REDIS_URL, SUPABASE creds, Python deps) as the
  existing `worker` service.
- CLAUDE.md Infrastructure table + STARTUP.md local-dev guide
  updated to document the topology.

**Pattern for future long-running jobs:** route to BACKGROUND_QUEUE
by adding `queue_name=BACKGROUND_QUEUE` to the route's
`enqueue_job_run(...)` call. If 3+ jobs need this routing, extract
a registry (YAGNI applied 2026-05-16 — single hardcode for now).

**Phase 3 readiness:** UNBLOCKED. Phase 3 (full 67-symbol α
backfill) can now run on the background queue without starving the
trading-day pipeline. All α-side prerequisites are met (PR #935
implementation, PR #941 trigger plumbing, PR #944/#945 Phase 1+2
verification).

**Defense-in-depth note:** even with queue isolation, Polygon API
rate limits and DB write contention are NOT isolated. Recommend
still scheduling Phase 3 outside US trading hours where possible.

**[2026-05-17] TIER 2 CANDIDATE: anchor-selection time-instability (Finding C).**

**Priority:** TIER 2 — informational; affects iv_rank consumer
expectations + PR-A test design. Not blocking PR-A (which pins
fixtures against today's post-PR-A2 outputs per this finding's
implications).

**Surfaced by:** Post-PR-A2 fresh fixture capture for PR-A
(2026-05-16 17:15-17:20 UTC, against PR #948 merged at 17:11 UTC).

**Mechanism (verified):**

PR-A2 (PR #948) fixed Finding B (contract listing time-instability
via `expired=true`). However, even with stable contract listings,
the handler's anchor-selection algorithm in
`IVPointService.compute_atm_iv_target_from_chain` picks the "best"
anchors from the CONTRACT SET AVAILABLE AT QUERY TIME.

When the available contract set changes — whether by new contracts
being added, expiries passing, OR PR-A2 expanding the visible set
via `expired=true` — the "best" choice shifts. Phase 1 ran against
a constrained set (no expired contracts visible); today runs against
a richer set (expired contracts now visible). The richer set exposes
nearer-DTE anchors the algorithm prefers, causing iv_30d output to
shift even for unchanged historical dates.

**Evidence (5 reference tuples re-captured 2026-05-16 post-PR-A2):**

- **SPY @ 2026-04-15:** Phase 1 iv_30d=0.150654 (anchors 05-15 + 05-22,
  DTE 30/37) → today 0.141438 (anchors 04-24 + 04-24, DTE 9/9).
  Delta 0.92 pct-pts.
- **AAPL @ 2026-04-15:** Phase 1 iv_30d=0.296574 (anchors 05-15 + 05-22)
  → today 0.296574 (anchors 05-15 + 05-15). Delta ~0 (bit-for-bit
  match — the only one of 5).
- **AMD @ 2026-05-08:** Phase 1 iv_30d=0.681414 (anchors 06-05 + 06-12,
  DTE 28/35) → today 0.702508 (anchors 05-15 + 05-15, DTE 7/7).
  Delta 2.11 pct-pts.
- **SPY @ 2026-03-13:** Phase 1 iv_30d=0.219546 (strike=662, exp=05-15
  single anchor q=80) → today 0.338553 (strike=615, exp=03-25). Delta
  11.9 pct-pts. NOTE: strike shifted from truly-ATM (spot 662.29) to
  8% below ATM — suggests contract-filtering interaction beyond just
  anchor selection.
- **AAPL @ 2026-02-20:** Phase 1 iv_30d=0.272318 (single anchor 05-15
  q=80) → today 0.252688 (anchors 03-20 + 03-27, DTE 28/35; true
  interpolation now possible). Delta 1.96 pct-pts.

The AMD case is particularly notable: 2 days ago (Sunday afternoon
pre-PR-A2) it REPRODUCED at delta=0 with full diagnostic match.
Today (post-PR-A2) it DIVERGED at delta=2.11. The expanded contract
set changed the anchor selection from June expiries (Phase 1) to a
closer 2026-05-15 expiry (today).

**Why this matters:**

1. **iv_rank consumer expectations:** if iv_30d for a historical date
   can shift by ~1-2 pct-pts between sessions, downstream iv_rank
   calculations see input drift. Strategy gates that consume iv_rank
   percentile may see their thresholds straddled differently over
   time, even for unchanged historical dates.

2. **Reproducibility of Phase 1 data:** Phase 1's
   `underlying_iv_points` rows are now ARCHIVED snapshots, not values
   that can be reproduced bit-for-bit by re-running. PR-A's tests
   cannot use Phase 1's stored values as ground truth.

3. **Test fixture shelf life:** today's captured fixtures (used as
   PR-A test baselines) will themselves drift over time as further
   expiries pass and re-shift anchor selection. Recommend re-capturing
   fixtures if PR-A test runs are scheduled more than ~2 weeks out.

**Investigation surface (when prioritized):**

- Read `compute_atm_iv_target_from_chain` for the anchor-selection
  algorithm
- Characterize: what makes one anchor "best"? DTE proximity?
  Liquidity? Strike proximity? Quality-score weighting?
- Question: is the algorithm correctly identifying optimal anchors,
  or does it have a systematic bias (e.g., preferring closer-DTE
  even when farther-DTE produces better 30-day interpolation)?
- Question: should anchor selection be deterministic against a
  CANONICAL contract set (e.g., "weekly + monthly anchors only at
  capture time", ignoring richer mid-cycle expiries)?
- SPY @ 2026-03-13's strike shift (662 → 615) suggests the
  contract-filtering layer (`reconstruct_chain_at_date`'s strike
  range filter) interacts with the chain density in ways that affect
  anchor selection. Investigate the filter interaction, not just
  the selection algorithm itself.

**Anti-criteria (don't prioritize if):**

- iv_rank consumers in production are tolerant of ~2 pct-pt drift
  in iv_30d (would manifest as occasional percentile-band straddling
  but not catastrophic at micro tier)
- Phase 1 data is treated as historical snapshot, not reference truth
- Alternative architecture (vendor change, persist chain listings at
  capture time, Polygon tier upgrade exposing historical chain
  snapshots) supersedes per-call algorithm questions

**Effort estimate:**

- Characterize anchor-selection algorithm + filter interaction:
  ~30-45 min reading code + documenting behavior
- Decide on fix shape (algorithm bias correction OR persist chain
  listings at capture time OR accept drift): operator architectural
  decision
- Implementation effort depends on fix shape; ranges from "small
  bias correction" (~1-2h) to "store chain snapshots in new table at
  capture time" (multi-hour refactor + schema change)

**Cross-references:**

- PR #948 — Finding B mechanical fix; this Finding builds on PR #948's
  expanded contract visibility
- Phase 1 results (job_run `9627c667-61e5-4915-a83c-a584b03bab0a`) —
  the stored values that cannot be reproduced
- Polygon tier upgrade investigation (Sunday 2026-05-17 synthesis in
  session history) — alternative architecture path that may obviate
  this finding entirely
- Upcoming PR-A — will pin tests against today's post-PR-A2 fixtures
  per this finding's implications; will NOT use Phase 1 stored values

**Status:** Captured. Tier 2. Not blocking PR-A. Investigation
prioritization is operator decision when iv_rank consumers surface
drift concerns OR when alternative architecture (Polygon tier
upgrade / persist chain listings) is considered.

**[2026-05-17] TIER 3 OBSERVATION: BKNG sparse coverage post-F2a.**

**Priority:** TIER 3 — single-symbol residual; not blocking; iv_rank
decidable for 69 of 70 active universe symbols.

**Surfaced by:** Phase 3 v3 final verification (job_run
`13b89a7e-...`, completed 2026-05-17 21:36 UTC, duration 213 min).

**Observation:**

After F2a (PR raising pagination cap from 1000 to 20000), 18 of 19
previously-sparse symbols recovered to full coverage (61 rows in
61-day window). BKNG (Booking Holdings) remained at 30 rows — same
coverage as pre-F2a Phase 3 attempt.

| Symbol | Pre-F2a rows | Post-F2a rows | Recovery |
|---|---|---|---|
| QQQ | 12 | 61 | ✓ Full |
| GLD | 17 | 61 | ✓ Full |
| IWM | 19 | 61 | ✓ Full |
| META | 24 | 61 | ✓ Full |
| TSLA | 27 | 61 | ✓ Full |
| AVGO | 29 | 61 | ✓ Full |
| **BKNG** | **30** | **30** | **✗ No change** |
| MSFT | 33 | 61 | ✓ Full |
| GOOGL/NVDA | 36 | 61 | ✓ Full |
| (others 38-59) | various | 61 | ✓ Full |

BKNG is the only symbol where F2a's pagination cap raise didn't
help. This rules out "1000 cap was the universal sparse-coverage
cause" — something BKNG-specific is in play.

**Root cause (confirmed 2026-05-17 via diagnostic, ~22:45 Chicago):**

Stock split adjustment mismatch. BKNG (Booking Holdings) underwent
a likely 30:1 stock split during/post the backfill window. Polygon's
API returns split-ADJUSTED historical spot prices (~$167 for what
was actually a $5000+ stock pre-split), but option contract
REFERENCES keep their UNADJUSTED strikes (e.g.,
`O:BKNG260320C03550000` at strike $3550, NOT split-adjusted).

The handler's strike-range filter logic:

1. Fetches spot via `get_historical_spot_price` → $167
   (split-adjusted)
2. Computes filter range [$167 × 0.8, $167 × 1.2] = [$134, $200]
3. Queries Polygon contracts with strike $134-$200
4. Pre-split BKNG chain was at $3000-$6000 strikes; nothing matches
5. Empty chain → `missing_data` for every pre-split date

Daily refresh works because it uses the LIVE chain snapshot
(post-split contracts at $150-200 strikes match current post-split
spot ~$170).

**Empirical evidence:**

- BKNG spot 2026-02-25 (via `adjusted=true`): $166.52
  (actual BKNG trading price was ~$4500-5000 pre-split)
- Empirical chain depth for BKNG in window when queried with the
  pre-split strike range ($3520-$6720): 2741 contracts, 12 distinct
  expiries — well below F2a's 20000 cap, so H1 refuted
- Control comparison (all RECOVERED post-F2a with similar/smaller
  chains): META 3515, NVDA 1668, AVGO 1184, GOOGL 806 — confirms
  this is not a chain-depth issue
- Phase 3 v3 wrote 0 new BKNG rows: 30 existing rows are ALL from
  daily_refresh accumulating over the last ~6 weeks (post-split)
- BKNG missing-date pattern: 2026-02-19 → 2026-04-02 missing
  (entire pre-split half); 2026-04-06 → 2026-05-15 present
  (post-split half) — perfectly bimodal split-at-event

**Original hypothesis disposition:**

- H1 (cap > 20000): REFUTED empirically (chain depth ~2700, well
  below cap)
- H2 (strike-range filter at $4500 spot): related but framed wrong;
  issue is NOT the high spot value, it's the WRONG spot value
  (adjusted vs unadjusted mismatch)
- H3 (Polygon data peculiarity): PARTIAL — splits are a
  generalizable Polygon convention, not BKNG-specific data sparsity
- H4 (different code path): REFUTED — same handler logic; the
  mismatch is upstream in the spot fetch
- **H_NEW (CONFIRMED):** stock split adjustment mismatch between
  adjusted historical spot prices and unadjusted option contract
  references

**Generalizability:**

This is NOT BKNG-specific. ANY symbol that splits during a backfill
window exhibits the same pattern. BKNG is currently N=1 in the
active universe but is the canonical test case.

**Fix shape options:**

| Option | Description | Effort | Risk |
|---|---|---|---|
| F3a | Use `adjusted=false` for spot fetch when computing strike range | ~30-45 min | Medium — may affect other consumers of `get_historical_spot_price` |
| F3b | Query Polygon corporate-actions endpoint to detect splits + apply split-factor correction per (symbol, date) | ~half-day | Medium — new Polygon endpoint integration + per-tuple logic |
| F3c | Detect empty-chain + "suspicious spot" heuristic, log warning | ~30 min | Low — observability only; no behavior change |
| F3d | Accept as data-vendor limitation; daily_refresh closes forward gap | Zero | None |

**Recommendation: F3d for now.**

Reasoning:
- BKNG is N=1 case at micro tier
- daily_refresh closes the gap forward by mid-July 2026 (~30
  trading days from now)
- F3a/F3b engineering disproportionate to current value
- See adjacent Tier 3 observation `[2026-05-17] OHLC unavailable
  for pre-split contract identifiers` — may mean F3a/F3b cannot
  fully recover BKNG even if shipped

**Promote to F3a/F3b if:**

- Another universe symbol splits during a backfill window
- iv_rank-gated strategies need full BKNG historical analysis
- Strategy backtesting requires pre-split BKNG IV data

**Status:** Root cause CONFIRMED (H_NEW). Recommended action F3d
(accept). Captured for promotion when criteria above are met.

**Cross-references:**

- BKNG diagnostic synthesis Sunday 2026-05-17 (in conversation
  history)
- F2a PR (pagination cap raise; worked for 18 of 19 sparse symbols)
- Phase 3 v3 result (job_run `13b89a7e-...`, completed 2026-05-17
  21:36 UTC, duration 213 min)
- Adjacent Tier 3 `[2026-05-17]`: OHLC unavailable for pre-split
  contract identifiers (narrows F3a/F3b's potential value)

**[2026-05-17] TIER 3 OBSERVATION: OHLC unavailable for pre-split contract identifiers.**

**Priority:** TIER 3 — adjacent observation to BKNG split mismatch;
narrows fix-shape options for any future split-correction work.

**Surfaced by:** BKNG diagnostic STEP 2 secondary test (2026-05-17
~22:45 Chicago).

**Observation:**

Even when the correct pre-split contract OCC ticker is identified,
Polygon may not return historical OHLC bars for that contract.

**Empirical evidence:**

Tested `O:BKNG260320C03550000` (BKNG call, expiry 2026-03-20,
strike $3550 — an appropriate ATM strike for BKNG's actual
pre-split spot of ~$3500-4500):

```
get_historical_price_range_for_occ(
    'O:BKNG260320C03550000',
    start_dt=date(2026, 3, 15),
    end_dt=date(2026, 3, 15),
)
→ {} (empty)
```

No historical OHLC bars returned for this contract on this date,
despite the contract being a valid ATM listing for BKNG at the
time.

**Hypotheses (untested):**

1. **Polygon migrated historical OHLC to split-adjusted tickers:**
   When BKNG split, historical OHLC for old-strike contracts may
   have been migrated to new-strike contract identifiers (e.g.,
   the $3550 contract's OHLC may now be accessible via
   `O:BKNG260320C00118300` or similar split-adjusted ticker, where
   the strike is the unadjusted $3550 ÷ 30 = $118.33).

2. **OHLC retention policy excludes pre-split data:** Polygon may
   simply not retain pre-split contract OHLC after the split
   corporate action processes.

3. **Different endpoint required:** A Polygon endpoint other than
   the standard aggregates may serve pre-split historical bars.

**Implication for BKNG fix shape:**

This observation narrows F3a/F3b's potential value:

- **If H1 (migrated tickers):** F3a/F3b need to ALSO translate
  old-ticker references to new-ticker equivalents before fetching
  OHLC. Significantly more engineering work.
- **If H2 (retention policy):** F3a/F3b cannot recover BKNG
  pre-split historical IV regardless of fix effort. The data
  simply isn't there.
- **If H3 (different endpoint):** Investigation surface for what
  endpoint to use.

**Investigation surface (when prioritized alongside BKNG F3a/F3b):**

- Test whether Polygon returns OHLC for hypothetical split-adjusted
  tickers (need split ratio + compute the adjusted OCC ticker)
- Query Polygon's contract reference endpoint with old-ticker to
  see if it returns metadata pointing to a successor ticker
- Test other Polygon endpoints (snapshot, trades, quotes) for the
  old-ticker

**Anti-criteria (don't prioritize if):**

- BKNG (and any future split-affected symbol) accepted as F3d per
  parent entry
- Polygon's stated data retention covers post-split tickers only
  (would confirm H2 without empirical investigation)

**Effort estimate (if investigated):**

- Empirical hypothesis testing: ~30-60 min
- Combined with F3a/F3b implementation (if pursued): adds ~1-2h to
  either F3a or F3b scope

**Status:** Captured. Tier 3. Investigation only when BKNG F3a/F3b
is promoted from current F3d-accept state.

**Cross-references:**

- BKNG residual entry `[2026-05-17]` (parent; F3a-d fix options)
- BKNG diagnostic synthesis Sunday 2026-05-17

---

## Backlog (post-promotion)

**Tier-promotion rewrite — CLOSED 2026-05-06** (PR #<NUM>)

Replaced broken micro_live → full_auto auto-promotion. Pre-rewrite the
handler at `promotion_check.py:26` read state.get for a
`micro_live_green_days` field that doesn't exist in
`go_live_progression` schema. Handler ran 23 times historically without
ever firing the "READY for promotion" critical alert because the
counter was permanently 0.

New gates (operator-confirmed 2026-05-06):
- broker equity ≥ $1500
- cumulative realized_pl > 0 across Alpaca-real closed trades
- alpaca_real_trade_count ≥ 3

Bonus: extracted `get_alpaca_real_closed_trades` shared helper used by
both `daily_progression_eval` (alpaca_paper green-day counter) and the
new `promotion_check` (micro_live → full_auto gate). Both paths now
agree on the trade lens — eliminates drift risk between progression
and promotion accounting.

Diagnostic note: original spec assumed `cumulative_pl=-$82, count=1`.
DB query revealed three lenses with materially different answers:
naive +$66K (inherits 2026-04-16 corruption), date-floor -$1958,
Alpaca-only -$20. Operator confirmed Alpaca-only (matches existing
`daily_progression_eval` pattern). Cross-reference Anti-pattern 9
in `docs/loud_error_doctrine.md` (audit-methodology, 2026-05-05) —
production state should be empirically verified against database
before design specs are locked.

`alpaca_paper → micro_live` logic untouched per operator decision.
Manual override (`ProgressionService.promote()`) preserved.
Doctrine: same dead-state-reference shape as #62a-D7 (PR #879) and
#71 PR-5 (PR #880).

**#65 — Revive `policy_lab_eval`** (HIGH) — **CLOSED 2026-04-26**
Resolved by PR #807 (ImportError fix) + PR #808 (schema-drift fix +
per-cohort observability), merged 2026-04-26 06:15:54Z. First
successful canary populated `policy_daily_scores` with 3 rows at
2026-04-26 06:19Z. Final end-to-end verification pending Monday
2026-04-27 16:30 CT scheduler fire.

**#66 — Polygon Tier 1: dead-code deletion** (LOW)
Remove `packages/quantum/polygon_client.py` (zero non-test callers) and
`market_data.py:_get_option_snapshot_api` (deprecated). Single PR, no
functional change.

**#67 — outcome_aggregator dead-code removal** (LOW)

CORRECTED 2026-04-26: `outcome_aggregator.py` is dead code. Verified:
- `outcomes_log` table empty for all time (zero rows ever).
- No scheduler entry, no GHA workflow, no FastAPI endpoint.
- Only caller is CLI script `scripts/update_outcomes.py` (never run
  in production).
- `calibration_service` reads `learning_feedback_loops`, NOT
  `outcomes_log`.
- 6 test files already marked `@pytest.mark.skip` with reference to
  Cluster I deletion (PR #9 / issue #770).

Saturday 2026-04-25's Diagnostic B premise that this corrupts the
calibration loop was wrong. Hardening was unnecessary.

Action: fold into the dead-code removal sweep already in Priority 3
("Dead-code sweep: v4 accounting ledger, outcomes_log chain, ...").

Cleanup scope:
- Delete `packages/quantum/services/outcome_aggregator.py`
- Delete `packages/quantum/scripts/update_outcomes.py`
- Delete `log_outcome()` from `packages/quantum/nested_logging.py`
- Update `system_health_service.py:95` and `capability_service.py:34`
  to use `learning_feedback_loops` or remove the checks
- Drop `outcomes_log` table via migration (already in Priority 3
  drop-unused-tables list)
- Delete the 6 already-skipped test files

Keep priority LOW. This is hygiene, not safety.

**#68 — Polygon Tier 2: universe_service migration** (LOW —
post-upgrade)

Replace `get_historical_prices` and `get_iv_rank` with Alpaca
equivalents. Original 429-elimination justification resolved by
2026-04-27 Polygon plan upgrade — `universe_service` calls are
no longer rate-limited or 403-blocked. Remaining value is
provider redundancy (vendor lock-in mitigation) and SIP-fallback
viability if live Alpaca account unlocks SIP entitlement (#88).
Reactivate if Polygon billing changes materially or if live
Alpaca SIP becomes available. Effort: ~half day. Priority: LOW —
defer.

**#69 — Polygon Tier 2: market_data.py base-layer migration**
(LOW — post-upgrade)

Foundational refactor for stock bars and quotes via Alpaca.
Original "unlocks downstream cutovers" motivation now optional
post-2026-04-27 Polygon plan upgrade. Remaining value is
provider redundancy. Reactivate as a prerequisite if #68 is
reactivated. Effort: ~1 day. Priority: LOW — defer.

**#70 — Polygon Tier 3: HARD_TO_REPLACE strategy** (LOW —
permanent residual post-upgrade)

`get_ticker_details` (sector, market_cap), `get_last_financials_date`
(earnings ±90d), and `I:VIX` historical bars have no Alpaca
equivalent. Plan upgrade (2026-04-27) makes the Polygon dependency
durable; Supabase-cache patterns for the first two are still
worthwhile to reduce per-cycle Polygon calls (overlaps with
#87b). The `I:VIX` dependency is permanent; document and accept.
Effort: rolled into #87b for the cacheable subset. Priority: LOW.

**#71 — RQ dispatch migration for synchronous task endpoints** (MEDIUM)
Audit `packages/quantum/public_tasks.py` and `internal_tasks.py` for
handlers that run work synchronously instead of dispatching to RQ.
Pattern surfaced from `policy_lab_eval` diagnostic 2026-04-26: the
endpoint ran synchronously, didn't `enqueue_job_run`, produced no
observability trace. Migrate affected handlers to the `enqueue_job_run`
pattern matching reliable peers. Effort: medium (audit + 1 PR per
affected endpoint). Source: 2026-04-26 morning diagnostic.

**PR-1 shipped 2026-05-04** (audit only, PR #872). Findings at
`docs/rq_dispatch_audit_2026_05_04.md`. Inventory:
- 38 total task endpoints (22 public + 16 internal)
- 30 already async (canonical `enqueue_job_run` pattern)
- 8 sync; **5 are migration candidates**, 3 deferred (intentional
  sync per docstring: /paper/process-orders, /validation/shadow-eval,
  /validation/preflight)

**PR-2 shipped 2026-05-04** (1/5 migrations complete, PR #<NUM>).
`/tasks/policy-lab/eval` migrated from inline sync to canonical async
dispatch. Pre-migration: APScheduler fired the endpoint daily at
16:30 CT and the work ran against the request thread with zero
`job_runs` trace. Post-migration: each fire produces a `job_runs`
row.

Intended behavior changes documented in PR description:
- `compute_decision_accuracy` now runs (was silently dropped by the
  inline endpoint — handler always had it; the inline path was the bug)
- Multi-user fan-out supported when payload omits `user_id` (handler
  iterates active users; inline endpoint required user_id)
- Per-stage `risk_alerts` writes from the prior sync handler replaced
  by `job_runs.status='failed'` observability (different shape, net
  observability improves — pre-migration there were zero rows)

Subsequent migrations (PR-3 through PR-7): `/validation/init-window`,
`/validation/cohort-eval`, `/validation/autopromote-cohort`
(includes idempotency redesign PR), `/train-learning-v3` (largest,
needs per-user decomposition). Total remaining: 4 migrations + 1
idempotency redesign.

**PR-3 shipped 2026-05-04** (2/5 migrations complete, PR #<NUM>).
`/tasks/validation/init-window` migrated to canonical async dispatch.
New handler scaffolded at
`packages/quantum/jobs/handlers/validation_init_window.py` (Tier 2
audit blocker resolved); auto-discovered via the existing
`packages/quantum/jobs/registry.discover_handlers` mechanism — no
explicit registration needed.

Pure migration; no behavior changes (unlike PR-2's
`compute_decision_accuracy` reactivation). Operator-on-demand endpoint;
GHA workflow `validation-init-window` fires it daily 8:40 AM CT via
`run_signed_task.py` which accepts both 200 and 202.

**Design note on gates:** the paper-mode + paused gates
(`_check_readiness_hardening_gates`) remain at the endpoint to reject
before enqueue, avoiding "queued then failed" `job_runs` rows for
gate-rejected calls. This pattern generalizes to Tier 3+ endpoints
that share the same gate helper (`/validation/cohort-eval` and
`/validation/autopromote-cohort`).

**PR-3 validated 2026-05-05** via manual GHA fire (Trading Tasks →
manual-task → `validation_init_window` with `force_rerun=true`).
`job_runs` row produced (id `bbfe5863-f207-426a-86e7-772b12820b63`),
status=`succeeded`, handler duration 0.17s DB-side. Handler's return
matches `v3_go_live_state` row exactly; `was_repaired: false` confirms
correct idempotent no-op behavior (existing window state passes
service contract). Auto-discovery + `force_rerun` plumbing + endpoint
gate behavior + new envelope shape all confirmed working end-to-end.
Migration no longer "deployed-untested."

Side observation (not a migration defect): user's `paper_window_end`
is 2026-03-28 (expired). Service-level question whether
`ensure_forward_window_initialized` should re-window expired states;
out of scope for #71 sweep.

**Tier 3 + Tier 4 closed by DELETION 2026-05-05** (PR #879).
PR-4 attempt on `/validation/cohort-eval` (Tier 3) surfaced a
fourth-case finding: the writer targets `shadow_cohort_daily`, a
table that doesn't exist in production. Verification showed neither
the writer endpoint nor the consumer endpoint
(`/validation/autopromote-cohort`, Tier 4) has ever fired in
production — zero `job_runs` rows for either, ever. The whole
shadow_cohort_daily channel was unexercised dead code.

Per #62a-D7 resolution, both endpoints removed entirely rather than
migrated.

**Tier 5 also closed by DELETION 2026-05-05** (PR #<NUM>).
`/internal/tasks/train-learning-v3` diagnostic confirmed zero
production runs ever, no scheduler entry, no GHA workflow caller.
Bonus finding: `CalibrationService.train_and_persist` (the only
unique service method the endpoint called) doesn't exist on the
class — the endpoint would have crashed with `AttributeError` on
first execution if it had ever fired. Same B2-deletion pattern as
#62a-D7.

**#71 SWEEP CLOSED 2026-05-05.** Final state across 5 PRs:
- PR-1 #872 (audit, docs-only)
- PR-2 #873 (`/policy-lab/eval` migrated)
- PR-3 #874 + #877 (`/validation/init-window` migrated, then validated)
- PR-4 #879 (`/validation/cohort-eval` + `/validation/autopromote-cohort`
  deleted as B2)
- PR-5 #<NUM> (`/internal/tasks/train-learning-v3` deleted as B2)

Original audit's "5 migrations + 1 idempotency redesign" became
"2 migrations + 3 deletions." The audit was conservative on
deletion calculus — production-exercise verification (added at
diagnostic stage) caught three endpoints that had never fired,
making the migration-vs-delete decision moot.

**Doctrine note:** future endpoint audits should include
"production-exercise count" as a first-class column. The original
audit catalogued endpoints that EXIST but didn't catalogue endpoints
that FIRE. For #71, those were different sets, and the difference
materially changed scope (3 PRs avoided).

**[ADDENDUM 2026-05-10] Tier 1+2 sweep reactivated** after PR-A's
Layer 2 (#901) and Layer 5 (#905) cascades surfaced the same
body-dropping and legacy-enqueue bug classes in 3+ additional
endpoints that the May-5 audit had missed. Saturday's re-sweep
audit catalogued all 35 endpoints across `public_tasks.py` +
`internal_tasks.py` and produced two follow-up PRs:

- **PR #909 (Tier 1):** extended body acceptance + force_rerun
  forwarding on 3 CLI-exposed internal endpoints
  (`/alpaca/order-sync` full body-add; `/calibration/update` and
  `/autotune/walk-forward` Path-A migration from
  `Body(embed=True)` to single dict body, defaults preserved).
  Fixes silent drop of `force_rerun` from CLI calls — same
  shape as PR #905's iv_daily_refresh fix.

- **PR #910 (Tier 2):** deleted 4 dormant duplicate endpoints
  (`/internal/tasks/{morning-brief,midday-scan,weekly-report,
  universe/sync}`) + cascading dead-code cleanup (legacy
  `from packages.quantum.jobs.enqueue import enqueue_idempotent`
  import + `EnqueueResponse` import + `get_admin_client` helper
  + `supabase_admin` scaffold + 4 dead service imports + 3
  unused stdlib imports) + stale `plaid_backfill` CLI catalog
  entry. Net -130 lines.

Audit synthesis: 35 endpoints reviewed. Active+buggy: 1
(`alpaca/order-sync`, full body-drop). Partial-body: 2
(`calibration/update`, `autotune/walk-forward` — drop
force_rerun only). Dormant duplicates: 4 (deleted). Clean: 28.
public_tasks.py: zero issues.

**Class A pattern fully closed in production code post-#910.**
Only remaining importer of legacy `enqueue_idempotent` from
`packages.quantum.jobs.enqueue` is the operator smoke script
`packages/quantum/scripts/rq_smoke_morning_brief.py` (out of
#71 scope).

**Tier 3 SHIPPED 2026-05-10** (PR #<NUM>): widened PR #901's
class-prevention test as a codebase-wide hard CI gate. New
`TestNoProductionCodeImportsLegacyEnqueue` walks
`packages/quantum/` excluding `scripts/`, `tests/`, `__pycache__/`,
`venv/`; asserts zero matches for
`from packages.quantum.jobs.enqueue import enqueue_idempotent`.
Existing iv_daily_refresh-specific tests preserved (they document
endpoint-specific job_name + handler invariants the wider test
doesn't capture). Fail-then-pass cycle verified: introducing a
legacy import to `internal_tasks.py` produced the expected
violation message with migration hint pointing at
`enqueue_job_run`. **#71 sweep arc fully complete: Tier 1 (PR #909)
+ Tier 2 (PR #910) + Tier 3 (this PR).**

**Follow-up candidate:** smoke script
`packages/quantum/scripts/rq_smoke_morning_brief.py` is the only
remaining importer of legacy enqueue (out of scope for production
CI gate). After deciding the script's fate (delete or migrate),
the legacy `packages/quantum/jobs/enqueue.py` module itself
becomes deletable. Tracked separately as **#118**.

**Class B class-prevention infrastructure SHIPPED 2026-05-11**
(PR \<NEXT\>): AST gate for Class B (silent body-drop) at
`test_internal_tasks_class_b_body_gate.py`. Asserts every
internal_tasks endpoint that BOTH calls `enqueue_job_run` AND
appears in the CLI TASKS catalog at `scripts/run_signed_task.py`
must accept a Body parameter. CLI-catalog intersection precisely
matches the threat model — scheduler-only enqueue callers
(intraday_risk_monitor, day_orchestrator, promotion_check,
heartbeat, phase2_precheck) are auto-exempt. New CLI-exposed
endpoints automatically come under enforcement without code change
in the test (catalog intersection recomputed each run). Closes the
H9 doctrine's Class B candidate; wrapper-grep test for brokers/
+ Result-type narrowing remain as future infrastructure candidates.

**Doctrine validation:** activate-then-migrate pattern held end-to-end.
The 4 dormant Class A endpoints sat with both bugs unsurfaced for an
unknown time; nothing exercised them so nothing broke. For the dormant
case here, deletion was cleaner than migration because functional
public counterparts at `/tasks/*` are already CLI-mapped and active.
This is the second time the doctrine has paid off this week
(first: shadow_cohort_daily B2 deletion, May 5).

**#93 — deployable_capital reads stale Plaid CUR:USD +
paper_autopilot status bypass** (HIGH, FIXED in PR #850)

`cash_service.get_deployable_capital()` previously computed
deployable as `buying_power - cash_buffer - reserved_capital`
where buying_power read from `portfolio_snapshots` (Plaid-sourced)
and reserved_capital was `SUM(sizing_metadata.capital_required)
WHERE status='pending'`. Both inputs were sources of drift.

**Original framing (PR #847 #93 entry) was wrong.** The first
diagnostic attributed the $208 reading to within-day cohort
clone accumulation. Today's diagnostic (2026-05-01) verified
zero cohort clones exist in DB history across all users — D4
sequence is shipped but clone INSERT silently fails (see #97).
Real root cause:

1. portfolio_snapshots last write was 2026-03-26 (5+ weeks
   stale Plaid CUR:USD = $247.84)
2. paper_autopilot status update at line 457 silently bypassed
   for BAC source row (see #96)
3. Net: yesterday's $208 = $500 paper_baseline_floor - $292 BAC
   reservation OR $247.84 stale buying_power, depending on
   fallback path

**Fix shipped (PR #850, 2026-05-01):** replaced
`cash_service.get_deployable_capital` body to read Alpaca
`options_buying_power` directly via new helper
`equity_state.get_alpaca_options_buying_power(user_id)`. Same
architectural pattern as 2026-04-16 `_compute_weekly_pnl` fix
(commit 83872db) — DB-derived state diverging from broker truth
resolved by reading Alpaca-authoritative.

**Verification (2026-05-01 16:00 UTC cycle):**
deployable_capital=$500 (vs prior days' $208/$247.84), budget
cap=$450, no helper failures. Verified working.

**Status:** CLOSED. Both layers fixed; broker-truth read makes
stale Plaid + reservation arithmetic irrelevant. Phantom-row
accumulation continues but is operationally inert (#94).

**#94 — trade_suggestions phantom-row hygiene** (P3-P4)

Source suggestions miss transition on position-close (stay at
`staged` post-execution). Cohort clones from `policy_lab/fork.py`
cannot accumulate — they fail INSERT silently (see #97). Daily
`suggestions_close` cleanup transitions stale `pending` rows
older than today's cycle_date to `dismissed`, but only catches
cross-day rows.

Currently inert post-#93 (broker-truth budget ignores all row
statuses) but rows accumulate indefinitely in the table.

**Risk:** table size growth without bound; no immediate
operational impact post-#93.

**Verify-pass 2026-05-05:** total_rows = 171 (across 5+ months,
oldest = 2025-12-11). Last 14 days produced only 11 rows
(thin universe + micro-tier sizing keeps emission low). Status
mix: 2 pending, 65 staged, 66 dismissed, 38 other. Phantom-row
volume is not operationally concerning — table size is trivial
and growth rate is ~1 row/day. Re-verify monthly OR if cohort
fan-out post-#876 + #97 produces sustained 3x volume increase.

**Options:**
- (a) periodic deep-cleanup job (weekly/monthly, archives
  `dismissed`/`staged` rows older than N days)
- (b) extend close-path to transition source rows to terminal
  state (`closed`, `expired`, etc.)
- (c) post-#97 fix, add cohort-clone cleanup at shadow fill
  materialization

**Effort:** small (~half day for option a; ~1 day for b/c with
proper close-path discipline).

**Priority:** P3-P4. Defer until table size becomes operational
issue or close-path discipline becomes load-bearing for future
feature.

**#95 — fork.py threshold semantic mismatch** (HIGH, AWAITING
NEXT-CYCLE VERIFICATION post-#876)

`_filter_for_cohort` at fork.py:165 originally read
`risk_adjusted_ev` (0-2 ratio) and compared against
`min_score_threshold` (50/70 score-scale). Conservative +
neutral cohorts produced 0 clones for entire DB history across
all users (verified 2026-05-01). D4 sequence (PR2a/PR2b/PR3)
was shipped but operationally inert.

**Fix shipped (PR #851, 2026-05-01):**
1. workflow_orchestrator.py:2961 — persist `score` into
   sizing_metadata at suggestion-insert time
2. fork.py:165 — read `sizing_metadata.score` instead of
   `risk_adjusted_ev` for cohort threshold comparison

**Verification chain status (2026-05-05 verify-pass):**
- Score persistence verified ✓
- Filter logic verified ✓ (filter accepted BAC for all 3 cohorts)
- Clone INSERT path was broken by #97 trace_id collision —
  resolved by PR #876 (closed 2026-05-05)
- End-to-end verification awaits next cohort-firing cycle —
  zero `cohort_name`-tagged suggestions and zero
  `cohort_clone_insert_failed` alerts since #876 merge
  (today's only suggestions_open ran at 16:00:07Z, BEFORE
  #876's 18:55:34Z merge; pre-fix evidence isn't useful)

**Status:** Functionally unblocked. First post-#876 cohort-firing
cycle (likely tomorrow's 16:00 UTC) will produce 3 clones per
qualifying source. Re-verify on first occurrence and close.

**#96 — paper_autopilot status update silently bypassed** — **CLOSED 2026-05-03**
Covered by PR #839's H5b sweep. The status-update swallow at
`paper_autopilot_service.py:460-471` appends to the shared
`_per_suggestion_failures` list with `stage="status_staged_update"`,
and the aggregated H5b alert at line 513
(`alert_type="paper_autopilot_per_suggestion_failed"`,
severity="warning") fires on that list at end-of-loop. The
`stages_affected` metadata field surfaces "status_staged_update"
specifically, so operators querying `risk_alerts` can distinguish this
swallow site from the line-500 full_execution swallow.

The two BAC reproductions cited in the original entry (2026-04-30,
2026-05-01) predated full appreciation of H5b's coverage shape.
Subsequent reproductions produce
`paper_autopilot_per_suggestion_failed` `risk_alerts` rows with
`metadata.stages_affected` containing "status_staged_update".

Operationally inert post-#93 (broker-truth budget ignores pending
status). Latent observability for downstream consumers
(`policy_decisions` joins on status, learning loops filtering on
status) is now in place.

**#97 — fork.py clone INSERT silent failure** — **CLOSED 2026-05-05**

Two-phase resolution following Loud-Error Doctrine v1.0 anti-pattern 4
(silent-failure → loud-failure → diagnose → fix) lifecycle.

**Phase 1 (PR #859, 2026-05-02):** alert wiring at the cloner's
exception path. New `cohort_clone_insert_failed` critical alert
captures `error_class`, `error_message`, `clone_keys`, `cohort_name`,
`ticker` for next-cycle root-cause classification. Observability-only;
no behavioral change.

**Phase 2 (PR #<NUM>, 2026-05-05):** root cause classified from
production alert metadata. First production fire arrived 2026-05-05
16:00:18Z (today's CSX cycle, ~3h after the suggestions_open
producing the source candidate). Both alert rows (conservative +
neutral cohorts) showed identical signature:
- `error_class`: APIError (PostgreSQL 23505 unique violation)
- `constraint`: `idx_trade_suggestions_trace_id_unique`
- `error_message`: same source `trace_id` collided across cohort
  inserts

Schema verification confirmed `trace_id` is row-unique by design
(partial unique index on non-null; column has
`DEFAULT gen_random_uuid()`). Lineage tracking lives in separate
columns (`lineage_hash`, `lineage_sig`, `lineage_version`,
`decision_lineage`) — those are intentionally inherited across
clones. The cloner's `"trace_id": source.get("trace_id")` at
`fork.py:287` was the bug.

Fix: `"trace_id": str(uuid.uuid4())` per clone — single line.
Phase 1's alert wiring retained as the regression canary. 11 new
tests + 4 existing fork regression tests all pass.

**Doctrine validation:** the alert-then-diagnose-then-fix lifecycle
worked end-to-end. Phase 1 alert sat dormant Sat→Mon→Tue afternoon
(zero fires); first fire arrived within hours of CSX surfacing a
successful primary candidate; full root cause classified from
metadata in a single SQL query; fix shipped same day.

**Unblocks:** #95 verification can now confirm cohort comparison
data accumulates (3 cohorts producing rows in `trade_suggestions`
per fork). Any next-cycle CSX-shape candidate produces 3 cohort
clones inserting cleanly.

**#98 — needs_manual_review observability gap** — **CLOSED 2026-05-04**
Both Option C (write-site alert) and Option B (recurring sweep catch) shipped.

**Origin:** 2026-05-01 16:45 UTC BAC close order rejected by Alpaca 3x
with "insufficient options buying power" (required $296, available $204).
`submit_and_track` at `alpaca_order_handler.py:226-242` marked order
status='needs_manual_review' and returned dict (did NOT raise). H5a alert
at `paper_exit_evaluator.py:1226` only fires for raised exceptions, so
silent. Operator discovered ghost position 5+ hours later.

**Option C shipped (PR #853, 2026-05-01):** loud alert at
`submit_and_track:231` immediately when marking status='needs_manual_review'.
Catches ALL callers within seconds.

**Option B shipped (PR #<NUM>, 2026-05-04):** extended `ghost_position_sweep`
with a new check — paper_orders rows in `status='needs_manual_review'` linked
to open `paper_positions` past 1-hour staleness. New `alert_type=
'stale_manual_review_with_open_position'` at warning severity. 1-hour
idempotency gate via `metadata->>order_id` JSON path filter prevents flooding
risk_alerts at sweep cadence (alpaca_order_sync runs every 5 min; without
the gate, BAC's 3-day stuck duration would have produced ~864 alerts).

Defense-in-depth catch when Option C's write-site alert is missed in the
moment. Sweep surfaces persistent stuck state on every cycle until operator
clears it. 5 structural + 4 behavioral tests guard alert wiring + idempotency.

Operationally inert post-#100 (Option A protects against the Friday-class
sizing failure that produced these stuck states), but the class is latent
for non-Friday failure modes: broker outages, non-BP rejections, manual
operator actions that orphan rows, etc.

**Underlying architectural cause:** see #100. The close rejection happened
because sizing didn't check round-trip BP. Options B and C address
observability; #100 addresses prevention.

**#100 — round-trip BP check at sizing** — **CLOSED 2026-05-04**
Resolved by PR #858 (Option A — Formula A entry-premium-based estimator).
Sizing engine now computes `contracts_by_round_trip` as a 4th sizing
dimension via `estimate_close_bp(legs, strategy_type, entry_premium)`;
for *_DEBIT_SPREAD, `estimated_close_bp = max_loss_per_contract` with
`safety_factor=1.1` starting calibration. Wired through
`workflow_orchestrator.py:2643` via a single new kwarg. Test surface
landed: 3 source-level + 9 helper behavioral + 7 sizing integration +
1 regression query.

**Origin incident (2026-05-01):** BAC entry took $292 of $500 OBP,
leaving $204. Alpaca's close-side margin gate required $296. Position
stuck open at broker for 5+ hours. Doctrine entry (#102) plus this
sizing gate (#100) close the loop on round-trip safety as a sizing
invariant.

**Architectural note (carried forward):** future multi-cohort live
routing (#65 `policy_lab_eval`) may need reservation semantics to
prevent simultaneous-cohort competition for live capital — not blocked
by anything today, just a forward-looking pointer.

**#101 — STRATEGIES_ALLOWLIST env knob** (LOW, incident-response
optional)

Environment variable to restrict scanner emission to specific
strategy types. Useful as kill-switch during incidents (e.g.,
"single-leg only after BP-to-close issue") without code
changes.

**Default:** unset (current behavior — all strategies allowed)

**Format:** comma-separated strategy names, e.g.,
`STRATEGIES_ALLOWLIST=long_call,long_put`

**Implementation site:** scanner gate in options_scanner.py,
early-return before strategy emission if not in allowlist.

**Priority downgraded MEDIUM → LOW (2026-05-05 verify-pass):**
the original BP-to-close incident class that motivated this knob
is structurally addressed by #100 (PR #858, round-trip BP at
sizing). The knob is still independently useful for OTHER future
incident classes (regime-strategy mismatch, broker-rejection
patterns, etc.) — orthogonal to #100, not redundant. Defer until
a future incident class actually demands it; ship if and when.

**Effort:** half day (env var read + scanner gate + tests).

**#102 — Round-trip safety as sizing invariant (DOCTRINE)** — **CLOSED 2026-05-03**
Covered by PR #856's "Operations preserve capital invariants in both
directions" entry in `docs/loud_error_doctrine.md` (the H7 framing).
That entry explicitly names sizing as the primary "Patterns to look for"
case (`Sizing: does it check entry_cost AND close_cost ≤
available_capital?`) and cites Option A (#100) as its concrete
application, with the BAC ghost-position incident as origin. CLAUDE.md
Working Style updated with a cross-reference so future operators find
the doctrine from the system-overview surface.

**#103 — Regime → strategy selection breadth audit** — **CLOSED 2026-05-07**

Resolved 2026-05-07 by #107 diagnostic. Of the three possibilities
originally listed:
- "Regime-driven natural selection" — partially correct for W3
  sentiment alone (SPY+QQQ truly bullish-trending)
- "Coverage gap in strategy emission logic" — confirmed yes, but the
  gap is upstream of the selector: iv_rank=50.0 hardcoded fallback at
  `options_scanner.py:2395` routes 4 of 7 strategy paths to
  never-trigger state
- "Threshold calibration too narrow" — partially relevant (SUPPRESSED
  vs NORMAL borderline), but secondary

**Cross-reference:** the regime → strategy selection breadth is
constrained by iv_rank computation breakage, not classifier behavior.
See #107 (diagnostic) and #115 (iv_rank fix). Classifiers themselves
are working; iv_rank upstream is the actual broken lever.

**Re-closure 2026-05-07 by #113 PR-6.** Strategy emission breadth is
now empirically observable via
`job_runs.result.debug.emission_counts_by_strategy` and
`rejection_counts_by_strategy_and_reason`. Future breadth audits
become a single SQL query rather than a recurring investigation —
see #113 entry below for query examples.

— Original entry preserved below for context —

100% of recent live trades (last 14 days) are
LONG_CALL_DEBIT_SPREAD. Code supports more types (iron_condor
function exists at options_scanner.py:1053+) but production mix
is single-shape.

Possibilities:
- Regime-driven natural selection (NORMAL regime favors debit
  spreads): correct behavior
- Coverage gap in strategy emission logic: bug
- Threshold calibration too narrow for non-debit-spread
  strategies: configuration

**Investigation needed:** survey strategy emission across all
regimes (NORMAL, ELEVATED, CONTRACTION) over historical data.
Verify other strategies are reachable in their appropriate
regimes.

**Priority:** LOW. Architectural curiosity, not operational
blocker.

**Effort:** ~half day investigation. Fix scope depends on
findings.

**#104 — RejectionStats coverage audit of `_process_symbol_multi`** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. Loud-Error Doctrine v1.0 anti-pattern 4 (per-iteration
swallow in tight loops) requires every early-return path inside the scanner's
per-symbol pipeline to record a meaningful rejection reason via `rej_stats`.

**Audit conducted against post-#866 source.**

`process_symbol` (line 2257): all 26 `return None` paths verified instrumented
(PR #866 closed the last two via #105/#106 splits). Source-level guard added
(`test_process_symbol_returns_are_all_instrumented`) to detect regression
when new gates are introduced.

`_process_symbol_multi` (line 3200): one silent return at line 3219 —
`if len(cands) <= 1: return None` when the selector produced ≤1 candidate
so no fallback retry is possible. The primary's rejection reason was already
counted by `process_symbol`, but there was no counter for "multi-strategy
mechanism couldn't help because no fallbacks existed." Distinct from
`all_strategies_rejected` which means fallbacks WERE tried and all failed.

Fix: added `rej_stats.record("no_fallback_strategies_available")` at the
silent site. Observability-only — same trades accepted/rejected as before.
Operators can now distinguish how often the multi-strategy mechanism added
value (`all_strategies_rejected` count) vs how often it was inert
(`no_fallback_strategies_available` count) per cycle.

**#105 — `strategy_hold` lumps two distinct conditions** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. `options_scanner.py` recorded
`rej_stats.record("strategy_hold")` at two distinct sites for distinct
conditions:
- Line ~2408: selector returned empty list of candidates
- Line ~2447: explicit `HOLD`/`CASH` verdict from selector

Split into `strategy_hold_no_candidates` and
`strategy_hold_explicit_verdict`. Operators can now distinguish whether
to investigate selector candidate generation versus the HOLD/CASH gate.
Surfaced by 2026-05-04 scanner pipeline diagnostic (6 strategy_holds
in single cycle, ambiguous root cause). Unblocks #107 (strategy
selector low-EV emission investigation needs the disambiguated counts
to tune meaningfully).

**#106 — `spread_too_wide` misnamed for tiny-entry-cost trades** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. The spread formula `combo_spread / entry_cost`
produces deceptively-large percentages when entry_cost is tiny. Today's
PFE rejection (combo=$0.12, entry=$0.06 = 200%) was correctly rejected
(uneconomic trade) but the name suggested a liquidity issue.

Split into three reason codes via classification at the rejection site:
- `spread_too_wide_real` (combo > $0.20 — actual wide spread)
- `entry_cost_too_low` (entry < $0.15 — uneconomic trade, today's PFE shape)
- `spread_too_wide` (boundary case retained — neither absolute threshold triggered)

Tunable via `ABSOLUTE_SPREAD_THRESHOLD` and `MIN_ECONOMIC_ENTRY` module
constants (env-overridable). Operationally inert — same trades accepted/
rejected as before; operators see accurate signal in `rejection_counts`.

**#107 — Regime + sentiment classifier diagnostic** — **CLOSED 2026-05-07**

Diagnostic completed 2026-05-07. Three original hypotheses partially
refuted in favor of a new H4 finding.

**Findings:**
- **Sentiment classifier (H1 verdict):** SUPPORTED. SPY $686 → $733.77
  (+6.96%) over W3's 17 trading days, daily-return std ~0.65%, annualized
  vol ~10.3%. Internal BULLISH classification matches external truth.
  H3 (sentiment sticky-bullish) refuted — W2 had 29 LONG_PUT_DEBIT_SPREAD
  emissions, sentiment does flip when symbols trend down.
- **Regime classifier (H1 weak/H2 weak):** WEAKLY supported either way.
  Regime varied widely in W1+W2 (CHOP=71, NORMAL=63, ELEVATED=26,
  REBOUND=6 across 90 days). W3's 100%-NORMAL streak is plausible given
  actual W3 market regime. Sub-finding: SUPPRESSED never observed in 90d
  despite genuinely low-vol periods (~10% W3 vol borders SUPPRESSED
  threshold). Minor calibration concern, not a strategic issue — both
  NORMAL and SUPPRESSED routes emit debit spreads for BULLISH.
- **🚨 NEW H4 (PRIMARY VERDICT):** `iv_rank = symbol_snapshot.iv_rank or
  50.0` at `options_scanner.py:2395` is a Loud-Error Doctrine
  Anti-pattern 2 violation. iv_rank=50.0 across ALL 166
  trade_suggestions in 90-day window (zero variance). Hardcoded
  fallback masks broken upstream computation.

**Strategic consequence:** iv_rank=50 routes through "normal IV"
selector branches and eliminates 4 of 7 strategy paths:
SHORT_PUT_CREDIT_SPREAD, SHORT_CALL_CREDIT_SPREAD, NEUTRAL+high-IV
IRON_CONDOR, EARNINGS+high-IV IRON_CONDOR all never trigger.
Surviving paths: 3 directional debit spreads + CHOP-regime IRON_CONDOR.
This is the SINGLE root cause of W3's strategy diversity loss.

**Outcomes:**
- New #115 (HIGH) opened for iv_rank fix work
- #103 closed (#107 + #115 supersede the original "regime → strategy
  selection breadth" question)
- #114 (ban-knob experiment) superseded; would not surface credit
  spreads or non-CHOP iron condors under iv_rank=50

**Effort actual:** ~50 min for diagnostic. No PR drafted (read-only).

**#108 — Multi-strategy Phase 2 PR-1: per-strategy realized P&L helper extension** (LOW)

Phase 1 design doc PR-1. Foundation for strategy lifecycle gating.
Extends `get_alpaca_real_closed_trades(user_id, supabase, since=None,
until=None)` (shipped in PR #883) with optional `strategy_name` parameter.
When provided, joins through `paper_orders → trade_suggestions` to
filter to that strategy's closed trades only.

Add `get_strategy_eligibility(strategy_name, user_id, supabase)`
returning `{eligible, cumulative_pl, trade_count}` matching the
tier-promotion gate shape from PR #883.

Tests: 6-8 unit tests on filter behavior + missing-strategy-name
backward-compat.

**Dependencies:** none. Self-contained extension.

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-1.

**PR-1 status (2026-05-07):** shipped on branch
`feat/108-pr-1-strategy-eligibility-helper`. Two changes:

- `get_alpaca_real_closed_trades(user_id, supabase, since=None,
  until=None, strategy_name=None)`: optional `strategy_name`
  parameter narrows results to a single strategy via direct
  `paper_positions.strategy` filter. Step 1 schema check confirmed
  Outcome A — column populated 17/17 for Alpaca-real closed
  positions, no JOIN required. `strategy_name=None` (default)
  preserves pre-#108 behavior verbatim.
- `get_strategy_eligibility(strategy_name, user_id, supabase)`:
  new evaluation function returning `{eligible, cumulative_pl,
  trade_count, min_required_trades}`. Mirrors the tier-promotion
  gate shape from PR #883 but scoped to a single strategy.
  Threshold constant `MIN_TRADES_FOR_STRATEGY_GRADUATION = 3`,
  intentionally separate from `MIN_TRADES_FULL_AUTO` (same value
  today, may diverge later).

**No callers in production code yet.** Both new symbols are
intentionally orphan code awaiting #109 (the lifecycle states
table + daily scheduler hook). An orphan-code marker comment at
`get_strategy_eligibility` documents this and asks the next
operator to revisit if #109 hasn't shipped within ~30 days.

**Manual baseline against operator data (2026-05-07):**

- `IRON_CONDOR`: 3 trades, cumulative_pl=+$5066 → would graduate
  (`eligible=True`)
- `LONG_CALL_DEBIT_SPREAD`: 9 trades, cumulative_pl=-$629 →
  blocked by P&L gate
- `LONG_PUT_DEBIT_SPREAD`: 5 trades, cumulative_pl=-$4457 →
  blocked by P&L gate

When #109 lands, IRON_CONDOR would be the first auto-graduated
strategy under the new gating system.

**#109 — Multi-strategy Phase 2 PR-2: strategy_lifecycle_states table + scheduler hook** (LOW)

Phase 1 design doc PR-2. State machine: DESIGNED → EXPERIMENTAL →
LIVE_FULL → DEPRECATED.

Migration: `strategy_lifecycle_states` table with `strategy_name` PK,
`current_state`, `transitioned_at`, `transition_reason` jsonb,
`closed_trade_count`, `cumulative_realized_pl`, `updated_at`.

Initial seed: existing 5 strategies (LONG_CALL_DEBIT_SPREAD,
LONG_PUT_DEBIT_SPREAD, SHORT_PUT_CREDIT_SPREAD,
SHORT_CALL_CREDIT_SPREAD, IRON_CONDOR) as `live_full` (preserves
current behavior). New strategies (BULL_PUT_SPREAD_0DTE,
CASH_SECURED_PUT) as `designed`.

`evaluate_strategy_lifecycle()` function piggybacked on
`daily_progression_eval` (4 PM CT). Reuses helper from #108.

Graduation: EXPERIMENTAL → LIVE_FULL when cumulative_realized_pl > 0
across ≥3 closed Alpaca-real trades for that strategy.

Tests: graduation logic + state transition + audit log.

**Dependencies:** #108 (helper extension).

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-2.

**PR-2 status (2026-05-07):** shipped on branch
`feat/109-pr-2-strategy-lifecycle-states`. Four pieces:

- **Migration** `20260507000000_add_strategy_lifecycle_states.sql`
  — creates `strategy_lifecycle_states` (strategy_name PK,
  current_state CHECK enum of `designed`/`experimental`/`live_full`/
  `deprecated`, transition_reason JSONB, closed_trade_count,
  cumulative_realized_pl, updated_at trigger). Seeds 5 currently-
  shipped strategies as `live_full` via `ON CONFLICT DO NOTHING`
  (idempotent re-apply). Inline `DO $$` invariant check raises if
  seed leaves the table in unexpected state. RLS enabled with
  service-role-only access (lifecycle is global, not per-user).
- **`evaluate_strategy_lifecycle(supabase)`** in
  `progression_service.py` — first caller of #108 PR-1's
  `get_strategy_eligibility`. Reads EXPERIMENTAL rows, evaluates
  each, transitions eligible ones to LIVE_FULL with audit. Failure
  isolation: per-strategy errors logged + alerted via
  `strategy_lifecycle_eval_error`, sweep continues. Idempotent —
  WHERE filter on `current_state='experimental'` means a second run
  finds nothing.
- **`daily_progression_eval` hook** — sibling step OUTSIDE the
  per-user loop (lifecycle is global). Wrapped in last-resort
  try/except so any unexpected escape doesn't lose the user-loop
  result envelope. Result dict gains `strategy_transitions` key.
- **Audit alert** `strategy_graduated_to_full` (severity=info) on
  every transition, with `cumulative_realized_pl` + `trade_count`
  + `min_required_trades` in metadata.

**`STRATEGY_LIFECYCLE_OWNER_USER_ID` env var** introduced as the
seam for future multi-tenant aggregation. Defaults to the canonical
operator UUID from CLAUDE.md.

**No demotion logic.** `LIVE_FULL → EXPERIMENTAL` and any
transition to `DEPRECATED` are manual-SQL-only per operator
decision. Don't add demotion code in #110+ either.

**Migration applied 2026-05-07 16:10:12Z** via
`mcp__supabase__apply_migration` (audit:
`risk_alerts.id = c2bd23db-a236-408d-88df-b74454ee0405`,
commit `c80c0af`). Verification confirmed:

- 5/5 strategies seeded as `live_full` with correct
  `transition_reason` JSONB
- CHECK constraint enforces 4-value enum
  (`designed`/`experimental`/`live_full`/`deprecated`)
- `set_updated_at_strategy_lifecycle_states` trigger present
- RLS enabled with service-role-only policy

**Day-1 expected behavior:** zero EXPERIMENTAL strategies in the
table on first run (seed places all 5 as `live_full`), so
`evaluate_strategy_lifecycle()` returns `[]` and writes nothing.
First real graduation will fire when #111 (0DTE) or #112 (CSP)
ships their strategy in EXPERIMENTAL state.

**#110 — Multi-strategy Phase 2 PR-3: sizing engine EXPERIMENTAL override** (LOW)

Phase 1 design doc PR-3. Caps EXPERIMENTAL strategies at 1 contract
regardless of normal sizing.

Read lifecycle state in sizing_engine via cached lookup:
- EXPERIMENTAL → cap to 1 contract (override max sizing)
- LIVE_FULL → no override (existing risk-pct math)
- DESIGNED/DEPRECATED → strategy filtered upstream by scanner via
  `banned_strategies` env arg

Tests: 4-6 unit tests on size-override behavior + interaction with
existing risk-pct math.

**Dependencies:** #109 (lifecycle states table).

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-3.

**PR-3 status (2026-05-07):** shipped on branch
`feat/110-pr-3-sizing-experimental-cap`. Three changes plus a new
helper, all coordinated through Option C (lifecycle injected at
scanner emission, no DB dependency in sizing_engine):

- **`load_strategy_lifecycle_states(supabase)`** in
  `progression_service.py` — read helper. Returns
  ``{strategy_name: current_state}`` for the small lifecycle
  table. Fails soft to ``{}`` on read errors or empty seed (caller
  defaults missing strategies to ``live_full``).
- **Scanner gate** in `options_scanner.scan_for_opportunities` —
  loads lifecycle states once per cycle, caches in
  ``lifecycle_states_map``. Each candidate carries
  ``"lifecycle_state"`` in its dict. ``designed`` and ``deprecated``
  candidates short-circuit before construction with
  ``rej_stats.record(f"strategy_{state}")`` so the rejection is
  visible in scanner observability.
- **Sizing engine cap** — `calculate_sizing` accepts new
  ``lifecycle_state`` kwarg. Cap applied AFTER the
  min(risk/collateral/round_trip/max) computation: if state is
  ``experimental`` and ``contracts > 1``, cap to 1 with
  ``experimental_sizing_cap_applied`` INFO log. Sub-threshold
  ``contracts=0`` is preserved (cap is ceiling, not floor).
  ``designed`` / ``deprecated`` reaching here defensively are
  ignored — sizing is not the gate. Returns now include
  ``experimental_capped: bool`` and ``lifecycle_state: str`` for
  downstream observability.
- **workflow_orchestrator wiring** — passes
  ``lifecycle_state=cand.get("lifecycle_state", "live_full")``
  through the single `calculate_sizing(...)` call site in
  `run_midday_cycle`.

**Day-1 expected behavior:** all 5 seeded strategies are
``live_full`` (per #109 PR-2 seed), so neither the scanner gate
nor the sizing cap fires. Behavior identical to pre-#110 verbatim.

**Verification recipe (optional, post-merge operator action):**

1. SQL: `UPDATE strategy_lifecycle_states SET current_state = 'experimental' WHERE strategy_name = 'LONG_PUT_DEBIT_SPREAD';`
2. Wait for next scanner cycle (or trigger manually).
3. Confirm: any LONG_PUT_DEBIT_SPREAD candidate emits with
   ``lifecycle_state="experimental"`` and contracts=1 regardless
   of normal math; INFO log
   ``experimental_sizing_cap_applied`` fires.
4. Confirm: 4:00 PM CT `daily_progression_eval` evaluates the
   newly-EXPERIMENTAL strategy. Operator's actual closed Alpaca-
   real LONG_PUT_DEBIT_SPREAD trades (-$4457 cumulative_pl per
   #108 PR-1 baseline) → eligibility=False → strategy stays
   experimental.
5. Reset: `UPDATE strategy_lifecycle_states SET current_state = 'live_full' WHERE strategy_name = 'LONG_PUT_DEBIT_SPREAD';`

Don't run this verification unless comfortable with reduced
sizing on LONG_PUT_DEBIT_SPREAD until reset.

**Phase 2 lifecycle infrastructure COMPLETE.** Ready for #111
(0DTE) / #112 (CSP) to add new strategies in
DESIGNED/EXPERIMENTAL state.

**#111 — Multi-strategy Phase 2 PR-4: 0DTE bull put spread + intraday cadence refactor** (MEDIUM)

Phase 1 design doc PR-4. 0DTE doesn't exist in selector today.

New strategy entry in `strategy_selector.py` (~30 lines). Scanner DTE
filter: support same-day expiry under feature flag.

**Architectural prerequisite:** intraday polling cadence. Current
`intraday_risk_monitor` runs every 15 min; 0DTE benefits from 5-min
cadence. Two options:
- Conditional cadence (accelerate when 0DTE positions are open) —
  touches load-bearing job
- Parallel `intraday_0dte_monitor` (recommended) — independent
  scheduler entry, no-op when no 0DTE positions

Force-close-by-3:55-PM logic for any 0DTE position not exited via
target/stop.

Tests: scanner integration, exit lifecycle, settlement timing,
force-close behavior.

**Dependencies:** #108 + #109 + #110 (lifecycle infrastructure).
Strategy starts in DESIGNED state until polling refactor lands.

**Capital gate:** 0DTE benefits from concurrent positions (multiple
intraday round-trips). Operator account at $696 supports only one
position via micro-tier gate. 0DTE realistically needs small-tier
($1000+) and ideally standard-tier ($5000+) for efficient deployment.

**Effort:** 3-4 days.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-4 + Step 4c.

**#112 — Multi-strategy Phase 2 PR-5: cash-secured-put + capital gating** (MEDIUM)

Phase 1 design doc PR-5. CSP doesn't exist in selector today.

New strategy entry in `strategy_selector.py` (~20 lines). Single-leg
structure: sizing engine accepts 1-leg candidates with
`collateral_required` field.

Capital gate: `EQUITY_THRESHOLD_CSP = $5,000`. Below threshold,
strategy stays DESIGNED regardless of operator flip.

Auto-close-before-expiry semantics initially (avoids equity-assignment
handling). Real CSP semantics with assignment is a follow-up project.

Tests: capital gate behavior, sizing math, auto-close timing,
refusal-to-emit when below threshold.

**Dependencies:** #108 + #109 + #110 (lifecycle infrastructure).

**Capital gate:** $5,000 minimum. Operator account at $696 doesn't
support CSP at retail-relevant strikes. Strategy stays DESIGNED
indefinitely until equity grows.

**Effort:** 3-4 days for selector + scanner + capital gate.
Equity-assignment handling is separate ~1-week follow-up.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-5 + Step 4d.

**#113 — Multi-strategy Phase 2 PR-6: per-strategy emission counts in observability** — **CLOSED 2026-05-07**

Phase 1 design doc PR-6. Closes #103 (Regime → strategy selection
breadth audit) by making breadth empirically observable.

Add per-strategy emission counts to scanner cycle logs / job_runs
result envelope. Daily aggregate per-strategy counts surfaced in
observability dashboard or log summaries. Enables operator to verify
strategy diversity over time without running ad-hoc SQL.

**Dependencies:** none. Self-contained observability addition.

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-6. Closes/supersedes #103.

**PR-6 status (2026-05-07):** shipped on branch
`feat/113-pr-6-strategy-emission-counts`. Shape A (no new tables,
no dashboard — counts surfaced in existing scanner cycle log +
`job_runs.result` via `RejectionStats.to_dict()`).

Two new dimensions on `RejectionStats`:

- `emission_counts_by_strategy: Dict[str, int]` — incremented at
  the single `process_symbol` successful return point. Both primary
  and fallback paths in `_process_symbol_multi` flow through that
  return, so each emitted candidate counts exactly once.
- `rejection_counts_by_strategy_and_reason: Dict[str, Dict[str, int]]`
  — outer dict keyed by ``strategy_name`` or sentinel
  ``RejectionStats.PRE_STRATEGY_KEY = "__pre_strategy__"`` for
  rejections that happen before a candidate has a strategy
  assigned (universe-level filters, missing data, multi-strategy
  exhaustion).

`record(reason)` and `record_with_sample(reason, sample)` gain
optional `strategy=...` kwarg. ``None`` (default) attributes to
``__pre_strategy__`` so every existing call site (~30 of them)
continues to work without edits. Strategy-known sites in
`process_symbol` migrated to pass `strategy=suggestion["strategy"]`:
`strategy_hold_explicit_verdict`, `strategy_banned`, the lifecycle
gate from #110.

Cycle log line `scanner_cycle_emission_summary` (INFO level) fires
once per scan with both count dimensions, total_emitted,
total_rejected, and symbols_processed in the structured `extra`
fields. Real-time copy of what `to_dict()` surfaces post-hoc.

**#103 closure:** strategy emission breadth is now empirically
observable via `job_runs.result.emission_counts_by_strategy` and
`rejection_counts_by_strategy_and_reason`. Second time #103 has
been closed — first via #107 diagnostic finding (iv_rank=50 root
cause → #115); this closure is the observability infrastructure
that makes future breadth audits unnecessary.

**Operator query examples:**

```sql
-- Daily strategy emission distribution (last 30 days)
SELECT
  DATE(finished_at) AS day,
  result -> 'debug' -> 'emission_counts_by_strategy' AS emissions,
  result -> 'debug' -> 'rejection_counts_by_strategy_and_reason' AS rejections
FROM job_runs
WHERE job_name = 'suggestions_open'
  AND finished_at >= NOW() - INTERVAL '30 days'
  AND status = 'succeeded'
ORDER BY day DESC;

-- Rolling per-strategy emission totals
SELECT
  strategy,
  SUM(count_value::int) AS total
FROM (
  SELECT
    key AS strategy,
    value AS count_value
  FROM job_runs,
    jsonb_each_text(result -> 'debug' -> 'emission_counts_by_strategy')
  WHERE job_name = 'suggestions_open'
    AND finished_at >= NOW() - INTERVAL '30 days'
    AND status = 'succeeded'
) sub
GROUP BY strategy
ORDER BY total DESC;
```

Adapt `result -> 'debug' -> ...` path to actual envelope shape
(orchestrator wraps `rejection_stats.to_dict()` under a `debug`
key in the cycle response).

**Phase 2 lifecycle infrastructure COMPLETE.** Four PRs shipped:
#108 PR-1 (helpers), #109 PR-2 (lifecycle table + scheduler),
#110 PR-3 (sizing override), #113 PR-6 (observability). #111 0DTE
and #112 CSP can now ship strategies in DESIGNED/EXPERIMENTAL state
without further plumbing changes; this PR ensures their emission
behavior is observable from day one.

**#114 — Ban-knob experiment for classifier diagnostic** — **SUPERSEDED 2026-05-07**

Superseded 2026-05-07 by #107 diagnostic finding. Under the
iv_rank=50 hardcoded fallback (see #115), the ban-knob experiment
cannot surface credit spreads or non-CHOP iron condors regardless of
which directional strategy is banned — those paths are blocked
upstream by the iv_rank=50 routing through "normal IV" selector
branches. Banning LONG_CALL_DEBIT_SPREAD would shift output to
LONG_PUT_DEBIT_SPREAD or HOLD only; would not surface the missing
strategy paths.

The experiment becomes useful only AFTER #115 (iv_rank fix) lands.
Revisit then if classifier behavior is still unclear.

— Original entry preserved below for context —

Phase 1 diagnostic surfaced this as the cheapest available classifier
diagnostic — operator action, not coding work.

If regime/sentiment classifiers appear stuck on NORMAL+BULLISH (per
#107 investigation findings), set
`banned_strategies=["LONG_CALL_DEBIT_SPREAD"]` for 1-2 days.

Observe what selector emits in current conditions:
- LONG_PUT_DEBIT_SPREAD → confirms sentiment classification was being
  preferred-but-not-required as bullish
- IRON_CONDOR → confirms sentiment was actually NEUTRAL or regime
  was actually CHOP
- HOLD (no emissions) → confirms classifier output is genuinely
  correct, NORMAL+BULLISH is the right state

**Operator action, not coding work.** ~10 min to flip env var +
24-48 hours of observation.

**Dependencies:** #107 should run first to determine if classifier
needs investigation at all.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Step 4a.

**#115 — iv_rank computation broken; hardcoded fallback masks failure** (HIGH)

**Discovery:** #107 classifier diagnostic (2026-05-07) identified
iv_rank=50.0 across ALL 166 trade_suggestions in 90-day window. Zero
variance is statistically impossible if iv_rank were computing
correctly; confirms hardcoded fallback masks upstream failure.

**Root cause:** `options_scanner.py:2395` reads
`iv_rank = symbol_snapshot.iv_rank or 50.0`. The `or 50.0` is a
Loud-Error Doctrine v1.0 Anti-pattern 2 violation (silent log-only
swallow with default sentinel value). `symbol_snapshot.iv_rank`
returns None/0 for ALL symbols across the full 90-day window,
suggesting the upstream computation has been broken for ≥90 days,
possibly since feature inception.

**Impact:** eliminates 4 of 7 strategy paths in
`strategy_selector.py`:
- BULLISH + high_vol → SHORT_PUT_CREDIT_SPREAD ❌ never triggers
- BEARISH + high_vol → SHORT_CALL_CREDIT_SPREAD ❌ never triggers
- NEUTRAL + high_vol → IRON_CONDOR ❌ never triggers (BULLISH/BEARISH-NEUTRAL path)
- EARNINGS + high_vol → IRON_CONDOR ❌ never triggers (earnings path)

Surviving paths: 3 directional debit spreads + CHOP-regime
IRON_CONDOR (regime-triggered, not IV-triggered). This explains W3's
100%-LONG_CALL_DEBIT_SPREAD streak entirely.

**Recommended approach (two components):**
1. **Upstream diagnostic** (read-only, ~2 hours): find where iv_rank
   is supposed to be computed, why `symbol_snapshot.iv_rank` is
   None/0, what data source it depends on, whether iv_rank ever
   worked historically. Produces evidence for fix design.
2. **Fix PR** (scope unknown until diagnostic): repair upstream
   computation + replace `or 50.0` fallback with `alert()` call per
   loud-error doctrine. Bundle vs split decided post-diagnostic.

**Why HIGH priority:** fixing this likely restores
SHORT_PUT_CREDIT_SPREAD, SHORT_CALL_CREDIT_SPREAD, and high-IV
IRON_CONDOR emissions immediately. Three strategy paths reactivated
by fixing one bug. The lifecycle PRs (#108-#110) are foundation work
for new strategies (0DTE, CSP) but don't unlock anything from
existing strategies. iv_rank fix does — unblocks credit-strategy
emission without writing any new selector code.

**Doctrine cross-reference:** `docs/loud_error_doctrine.md`
Anti-pattern 2 (silent fallback masking upstream failure). Same
pattern shape as #62a-D7 (shadow_cohort_daily missing) and #71 PR-5
(CalibrationService.train_and_persist missing) — code references
state that doesn't produce real values, no alert fires when fallback
path is taken.

**Estimated effort:** Upstream diagnostic ~2 hours. Fix PR scope
undetermined until diagnostic completes.

**Cross-reference:** #107 diagnostic synthesis (2026-05-07).
Closes the original #103 question about strategy selection breadth.

---

**Diagnostic findings (2026-05-07) — verdict: NEVER WORKED.**

Producer cron `iv_daily_refresh` was never registered in
`packages/quantum/scheduler.py:SCHEDULES`. APScheduler introduced
2026-04-01 (commit `7911076`); the job has zero executions in
`job_runs` ever. The handler, signed endpoint, and tests all
exist — only the schedule entry is missing.

**Root cause chain (3 stacked failures):**

1. `iv_daily_refresh` handler is correctly wired
   (UniverseService → MarketDataTruthLayer → IVPointService →
   IVRepository) but never invoked because the SCHEDULES entry
   is absent.
2. `underlying_iv_points` table is empty (0 rows ever). With
   `sample_size < 60`, `iv_repo.get_iv_context()` returns
   `iv_rank=None` deterministically (`iv_repository.py:135`).
3. Two layers of silent fallback mask the upstream failure.
   `options_scanner.py:2395` (`iv_rank or 50.0`) plus
   `regime_engine_v3.py:529`
   (`f_rank = iv_rank if iv_rank is not None else 50.0`). Both
   are Anti-pattern 2 violations per
   `docs/loud_error_doctrine.md`.

**Consumer split (5 silent / 2 explicit):**

- `options_scanner.py:2395` — `iv_rank or 50.0` ⚠️ (the one #107 surfaced)
- `regime_engine_v3.py:529` — `if iv_rank is not None else 50.0` ⚠️
- `strategy_design_agent.py:73` — `context.get("iv_rank", 50.0)` ⚠️
- `analytics/conviction_service.py:189` — `if pos.iv_rank is not None else 50.0` ⚠️
- `analytics/opportunity_scorer.py:141` — `or 0.0` ⚠️ (different sentinel)
- `agents/agents/vol_surface_agent.py:21` — `if iv_rank is None: …` ✓ explicit
- `analytics/guardrails.py:118` — `if iv_rank is not None: …` ✓ explicit

**Operational impact (now explained):**

- 100% NORMAL regime classification in W3: `iv_rank=50` →
  `score=50` → NORMAL bracket via `regime_engine_v3.py:541-548`.
  With real iv_rank values, the regime classifier would
  distribute across SUPPRESSED / NORMAL / ELEVATED / SHOCK as
  designed.
- Strategy emission asymmetry partially explained: iron condor
  trigger requires `iv_rank > 50` strict OR ELEVATED+ regime.
  With frozen iv_rank=50, neither condition fires post-CHOP
  windows.

**Greeks parallel question:** `analytics/greeks_aggregator.py:48-51`
and `api.py:575-578, 943-946` use `delta or 0.0`, `theta or 0.0`,
etc. — same Anti-pattern 2 shape. Whether Greeks are actually
always-None like iv_rank requires checking the truth_layer Polygon
enrichment path post-2026-04-27 plan upgrade. Deferred to **#115b**.

**Fix-scope decision (operator, 2026-05-07): doctrine-aligned, PR-A + PR-B sequenced.**

- **PR-A (~half day):** add `iv_daily_refresh` entry to
  `SCHEDULES` + add `iv_pipeline_no_data` loud-error alert when
  `get_iv_context()` returns None for >N% of universe in a
  single scan cycle. Producer starts populating
  `underlying_iv_points` daily. Alert ensures future silent
  failures of the producer are caught immediately.
- **PR-B (effort TBD; drafted after PR-A lands):** replace
  silent fallbacks at the 5 consumer sites with explicit
  None-routing per `loud_error_doctrine.md` Anti-pattern 2.
  Semantics (skip vs flag vs explicit-route-to-normal)
  decided during PR-B drafting based on warmup-window
  emission tradeoffs.

**Warmup window:** even after PR-A ships, `iv_rank` doesn't
become meaningful until ~60 trading days of
`underlying_iv_points` history accumulate. PR-B is what makes
the fix meaningful from day one — without it, the system
continues using silent 50.0 fallback during the entire warmup
window.

**Cross-references (additional):**

- `docs/loud_error_doctrine.md` Anti-pattern 2.
- Same dead-state-reference shape as #62a-D7
  (`shadow_cohort_daily` missing) and #71 PR-5
  (`CalibrationService.train_and_persist` missing). Now a
  4-data-point pattern.
- Schedule entry pattern: see existing `daily_progression_eval`
  entry in `SCHEDULES` (recently shipped).

**PR-A status (2026-05-07):** shipped on branch
`feat/115-pr-a-iv-schedule-and-alert`. Adds `iv_daily_refresh`
to `SCHEDULES` (4:30 AM CT, before `calibration_update`) and
the `iv_pipeline_no_data` loud-error alert at the scanner
batch-fetch boundary (threshold 0.5 None-rate, 24h dedup via
`risk_alerts` lookup). Producer starts populating
`underlying_iv_points` daily; iv_rank values become meaningful
after ~60 trading days of accumulated history. PR-B
(None-routing at the 5 silent-fallback consumer sites) still
pending — system continues to fall back to 50.0 during the
warmup window until PR-B lands.

**PR-A endpoint URL fix (2026-05-08):** first natural fire at
04:30 CT returned HTTP 404. PR-A's `SCHEDULES` entry used
`/tasks/iv/daily-refresh` but `internal_tasks.router` mounts
at `prefix="/internal/tasks"` — actual handler path is
`/internal/tasks/iv/daily-refresh`. Caught by H2 doctrine alert
(`scheduler_task_http_status_error`, severity=warning) at first
fire — loud-error pathway healthy and load-bearing. Fix shipped
on branch `fix/115-pr-a-iv-daily-refresh-url` (#899): 9-character
URL correction in `scheduler.py:SCHEDULES` + class-prevention
test `test_scheduler_routes_match.py` asserting every
`SCHEDULES` URL resolves to a registered FastAPI route. The bug
is the same **wrapper-drift** class as PR #864's alpaca_client
field-drop — 2nd data point for the doctrine pattern (string
identifier in module A doesn't match real registration in
module B). GHA workflow_dispatch options updated in #900
follow-up (timing race meant the GHA change didn't make the
#899 squash merge).

**PR-A enqueue-path fix (2026-05-08, layer 2):** post-#899 manual
fire HIT the API but the job sat `status='queued'` for 30+
minutes. Root cause: `iv_daily_refresh_task` in
`internal_tasks.py` used the legacy DB-only `enqueue_idempotent`
(from `jobs/enqueue.py`) — wrote a `job_runs` row but never
pushed to RQ. d4bba93 (2026-03-28) migrated 4 sibling endpoints
to canonical `enqueue_job_run` (DB + RQ) but **carved out
iv_daily_refresh as "NOT in target list" with no documented
reason** — undocumented oversight that became a latent bug. PR-A
activating the SCHEDULES entry surfaced it. Fix migrates
`iv_daily_refresh_task` to `enqueue_job_run` and standardises
job_name to underscored `iv_daily_refresh` (matching d4bba93's
discipline + handler `JOB_NAME` constant). Targeted
regression-guard test `test_iv_daily_refresh_enqueue_canonical.py`.
3rd data point for wrapper-drift class. Stuck `iv-daily-refresh`
queued row from the morning's manual fire becomes orphan post-
standardisation — cleanup SQL in PR description.

**Known follow-up scope (not in this PR):** 4 OTHER endpoints in
`internal_tasks.py` still use the legacy enqueue path —
`/morning-brief`, `/midday-scan`, `/weekly-report`,
`/universe/sync`. None are in SCHEDULES so they're dormant
rather than active, but the same shape bug applies. Worth a
sweep PR if any of them ever get scheduled. **[CLOSED 2026-05-10
by PR #910 — #71 Tier 2]:** all 4 dormant endpoints deleted
(deletion preferred over migration since functional public
duplicates already exist at `/tasks/*`). Cascading dead-code
cleanup removed the legacy `enqueue_idempotent` import too —
production code has zero importers of
`packages.quantum.jobs.enqueue` post-#910.

**PR-A write-boundary fix (2026-05-09, layers 3+4):** post-#901
manual fire dispatched the chain end-to-end; handler reported
`{ok: 68, failed: 2}` but `underlying_iv_points` stayed at 0
rows. Two stacked failures at the producer write boundary:

- **Layer 3:** `IVRepository.upsert_iv_point` calls Supabase
  `.upsert(payload, on_conflict="underlying, as_of_date")` but
  the schema had no UNIQUE constraint matching that spec. Every
  upsert errored with PostgreSQL `42P10` ("no unique or
  exclusion constraint matching the ON CONFLICT specification").
- **Layer 4:** the `except` block silently swallowed the error
  with `print(...)` and returned None. The handler's accounting
  incremented `stats["ok"]` based on no-exception, ignoring
  whether the upsert actually succeeded. Classic Anti-pattern 2
  silent fallback combined with handler-trusts-wrapper —
  identical Layer 4 shape will exist at every other handler
  that calls a side-effect-producing wrapper without checking
  the outcome.

Fix shipped on branch `fix/115-pr-a-write-boundary`:

- Migration `20260509000000_add_underlying_iv_points_unique_constraint.sql`
  adds the missing UNIQUE constraint with `IF NOT EXISTS` +
  inline `DO $$` self-verification.
- `IVRepository.upsert_iv_point` returns `bool` reflecting
  actual write outcome. Treats both exception path AND empty
  PostgREST `result.data` (server-side silent rejection) as
  failure. Replaces `print(...)` with structured `logger.error`.
- `IVRepository.count_rows_for_date(as_of_date)` new helper
  for post-loop accounting verification. Returns -1 sentinel
  on query failure so the handler doesn't fire false-positive
  alerts when it can't verify.
- Handler `iv_daily_refresh.py` checks the upsert return value,
  splits stats into `{ok, failed, missing_data}` so `ok`
  reflects only confirmed DB writes. Post-loop verification:
  queries `count_rows_for_date` and fires
  `iv_handler_accounting_mismatch` (severity=critical) if the
  reported `ok` count disagrees with actual DB row count. Makes
  Layer 4 silent regression impossible going forward.

**4th wrapper-drift data point** (Layers 1–3 wrapper-drift,
Layer 4 anti-pattern 2 / handler-trusts-wrapper). Per #901's
escape hatch ("three is a pattern; four is architectural-review
territory") this fix ships the minimum-viable correction AND
seeds Monday's design conversation with concrete questions about
verified-write wrapper conventions across all DB and external-API
boundaries. CSX close-order failure (Issue B from this Friday
session) appears to be the same handler-trusts-wrapper class at
the broker-API boundary — worth bringing to the same review.

**Migration applied 2026-05-09 05:17:11Z** via
`mcp__supabase__apply_migration` (audit:
`risk_alerts.id = 2381223c-28d3-4852-9afb-6a542935f4bc`,
commit `ee826a8`). Verification confirmed both
`underlying_iv_points_pkey (id)` AND new
`underlying_iv_points_underlying_as_of_date_key
UNIQUE (underlying, as_of_date)` constraints present
post-apply. Pre-flight had zero duplicate pairs + empty table,
so constraint applied cleanly. **Layer 3 of the cascade is now
durably closed at the schema level.** Next manual fire (or
Monday 04:30 CT scheduler) will exercise the full chain
end-to-end with both Layer 4 protections (upsert returns
bool + post-loop accounting verification) live in code.

**Layer 5 fix (2026-05-09):** post-Layer-3+4 manual fire produced
`{ok: 0, failed: 70, accounting_match: true}` — Layer 4
accounting honestly reported the failure caused by PostgREST's
schema cache lag. After NOTIFY pgrst, attempted re-fire with
`--force-rerun` returned 202 but no new `job_runs` row appeared.
Diagnosis: `iv_daily_refresh_task` and `daily_progression_eval_task`
endpoint signatures dropped the request body, so the CLI's
`payload={"force_rerun": true}` was silently discarded by FastAPI
before reaching `enqueue_job_run`. Re-fires within the same UTC
day hit terminal-state dedup and never executed.

**5th wrapper-drift in PR-A's chain in 36 hours.** Same shape
across 9 OTHER internal_tasks endpoints (weekly_report,
universe_sync, alpaca_order_sync, intraday_risk_monitor,
post_trade_learning, day_orchestrator, promotion_check,
heartbeat, phase2_precheck) — all accept no request body and
would silently drop force_rerun if anyone tried it. Latent
rather than active; surfaced for follow-up sweep.

Fix shipped on branch `fix/115-pr-a-layer-5-force-rerun-body`:
both targeted endpoints now accept `body: Optional[Dict] =
Body(default=None)`, extract `force_rerun` defensively
(`(body or {}).get("force_rerun", False)`), and forward to
`enqueue_job_run`'s `force_rerun=` kwarg + mark in payload for
audit. Defensive None-handling preserves the no-body path
(scheduled fires that don't send a payload) without crashing.

5 source-level tests in `test_internal_tasks_force_rerun_body.py`
cover the contract on both endpoints. Existing
`test_iv_daily_refresh_handler.py` + sibling tests pass without
changes.

**PR-B-1 status (2026-05-07):** shipped on branch
`feat/115-pr-b-1-scanner-regime-none-routing`. Two consumer sites
now route iv_rank=None explicitly when
`IV_RANK_NONE_ROUTING_ENABLED=1` (default OFF — zero behavioral
change at merge):

- `options_scanner.py:2485` (`raw_iv_rank` block): tags candidate
  with `iv_rank_quality ∈ {real, missing, unknown}`. Module-level
  exit sort prefers `real` over `missing` while preserving the
  `(score, symbol)` secondary order within each tier.
- `analytics/regime_engine_v3.py:529`: when iv_rank is None, routes
  through new `_classify_no_iv_signal()` instead of fabricating
  `f_rank=50.0`. The new path uses realized vol (`rv_20d`) — < 0.30
  → NORMAL, 0.30–0.50 → ELEVATED, ≥ 0.50 → SHOCK; rv_20d unavailable
  → NORMAL (defensive default). Sets `quality_flags.no_iv_signal=True`
  and reports `score=0.0` so downstream observers can distinguish
  this branch from a real NORMAL classification.

PR-B-2 (remaining 3 consumer sites: `strategy_design_agent.py:73`,
`conviction_service.py:189`, `opportunity_scorer.py:141`) still
pending. Same `IV_RANK_NONE_ROUTING_ENABLED` flag will gate those.

**PR-B-2 status (2026-05-07):** shipped on branch
`feat/115-pr-b-2-remaining-consumer-sites`. All 3 remaining consumer
sites routed under the same flag introduced by PR-B-1; default OFF
preserves legacy behavior verbatim. Site-specific semantics
determined by per-site intent diagnostic:

- `agents/agents/strategy_design_agent.py:73` (branch-skip):
  pre-fix `iv_rank = float(context.get("iv_rank", 50.0))` always
  evaluated `50 >= 60` False, silently skipping the high-IV
  override branch. Post-fix when flag ON + iv_rank=None: skip the
  iv-aware branch explicitly with INFO log. SHOCK / CHOP / policy
  overrides still run normally.
- `analytics/conviction_service.py:189` (return-None): pre-fix
  fabricated 50.0 volatility factor and ran scoring. Post-fix when
  flag ON + iv_rank=None: helper returns None, caller routes the
  position to conviction=0.5 (neutral) via the existing branch at
  caller line ~86. Trend/value placeholders at lines 187-188 are a
  separate concern, out of #115 scope.
- `analytics/opportunity_scorer.py:141` (zero-bonus, MOST IMPACTFUL):
  pre-fix `iv_rank = float(market_ctx.get('iv_rank') or 0.0)` then
  `not is_credit and 0 < 50 → iv_bonus = (50 - 0) * 0.2 = 10` —
  silently awarded **maximum 10-point IV bonus** to every debit
  candidate when iv_rank was missing. Post-fix when flag ON +
  iv_rank=None: skip the bonus computation entirely (`iv_bonus=0`)
  with INFO log. Active score distortion eliminated.

**All 5 anti-pattern 2 consumer sites for iv_rank are now closed**
(2 in PR-B-1 + 3 in PR-B-2). #115 remains OPEN until the operator
flips the flag and PR-A's producer accumulates ~60 trading days of
history; only then is the fix value-realised end-to-end.

Pre-flip checklist below applies to PR-B-2 sites identically — same
flag, same operator decision. No new env vars introduced.

**Pre-flip checklist for `IV_RANK_NONE_ROUTING_ENABLED`:**

Before flipping the env var to ON, verify:

1. `job_runs` shows successful `iv_daily_refresh` runs on at least 3
   consecutive business days (PR-A's producer cron is healthy).
2. `underlying_iv_points` has rows for ≥ 80% of `scanner_universe`
   symbols.
3. `iv_pipeline_no_data` alert has fired at least once during warmup
   (confirms PR-A alert wiring works) AND has not fired with
   severity=critical (no catastrophic pipeline failure).
4. No new errors in `regime_engine_v3` logs since PR-B-1 merge.
5. Manual flag flip on a non-prod environment if available.

After flipping:

1. Watch first 3 scanner cycles for changes in candidate emission count.
2. Watch regime classification distribution — should remain similar to
   pre-flip (CHOP/NORMAL/ELEVATED ratios) until ~60 trading days of
   warmup completes.
3. Watch strategy emission distribution — during warmup, expect mostly
   LONG_CALL/PUT_DEBIT_SPREAD as before. Post-warmup, expect IRON_CONDOR
   and credit spreads to reappear as iv_rank values converge.
4. If anomaly: flip OFF immediately. Investigate before re-enabling.

**#115b — Greeks adapter-chain pass-through verification** (MEDIUM)

**[SCOPE NARROWED 2026-05-10]** Per #88 H2 finding, Alpaca
returns populated Greeks (`delta`, `gamma`, `theta`, `vega`,
`rho`) plus `impliedVolatility` for near-ATM contracts via the
options snapshot endpoint. Producer chain confirmed using
Alpaca, not Polygon, for Greeks (verified at
`market_data_truth_layer._parse_alpaca_chain_item` lines
~1599-1605). The original "Polygon plan upgrade hypothesis"
framing is **OBSOLETE** — Greeks are populated at the producer
boundary; the question is whether they survive the adapter
chain end-to-end.

**Discovery:** #115 iv_rank diagnostic surfaced parallel
`or 0.0` fallback patterns for Greeks at
`analytics/greeks_aggregator.py:48-51` and
`api.py:575-578, 943-946`. Same Anti-pattern 2 shape as
iv_rank's `or 50.0`.

**Narrowed question:** Either consumers receive populated Greeks
(no fallback fires; the `or 0.0` is defensive-only), OR they
were populated upstream then dropped by an intermediate
transform (same wrapper-drift class as #864 alpaca_client
field-drop).

**Approach (when scheduled):** read-only adapter-chain probe.
Walk truth_layer → enrichment → consumer for one symbol with
known-populated Alpaca snapshot. Verify `delta`/`gamma`/`theta`/`vega`
arrive at `greeks_aggregator` and `api.py` without sentinel
defaults masking a drop. Check DB variance: do `delta` / `gamma` /
`theta` / `vega` fields in `paper_orders.order_json` (per leg)
or `trade_suggestions.order_json` show variance, or are they
uniformly 0?

- Uniform 0 → Greeks dropped somewhere in the adapter chain
  (wrapper-drift class).
- Varied → fallback is defensive-only; can be tightened to
  `if greek is None: alert()` per loud-error doctrine without
  affecting correctness.

**Timing:** schedule AFTER #115 PR-B verify completes (waiting
on iv_rank warmup so the parallel diagnostic has clean
comparison signal).

**Dependencies:** #115 PR-A merged ✓ + at least 2 weeks of
`underlying_iv_points` accumulating data.

**Estimated effort:** ~1-2 hours diagnostic — smaller than
original framing now that the upstream populates is confirmed.
Fix scope undetermined until diagnostic completes.

**Cross-reference:** #115 diagnostic synthesis Step 5; #88 H2
finding (Alpaca Greeks confirmed populated at boundary, 2026-05-10).

**#115c — Anti-pattern 2 cleanup batch: non-iv_rank/Greeks sites identified by #115 diagnostic** — **CLOSED 2026-05-07**

**Discovery:** #115 diagnostic Step 6 surfaced a small set of
localised (not systemic) `or <sentinel>` patterns in
production code outside the iv_rank and Greeks chains. Same
Anti-pattern 2 shape, smaller blast radius.

**Sites identified:**

- `execution/transaction_cost_model.py:217` — `fill_probability or 0.5`
- `analytics/opportunity_scorer.py:49` — `short_strike or 0.0`
- `analytics/opportunity_scorer.py:50` — `long_strike or 0.0`
- `analytics/opportunity_scorer.py:63` — `debit or cost or 0.0`
- `analytics/opportunity_scorer.py:141` — `iv_rank or 0.0` (also covered by #115/PR-B; remove duplication when batch ships)
- `analytics/conviction_service.py:279` — `avg_ev_leakage or 0.0`
- `analytics/conviction_service.py:280` — `avg_predicted_ev or 0.0`
- `analytics/conviction_service.py:344` — `avg_return or 0.0`

**Approach:** for each site, decide whether the field is
boundary input (validate-and-fail-fast) or internal (route
None forward). Replace `or <sentinel>` with explicit None
handling + alert at the producing-side fallback boundary,
per `loud_error_doctrine.md` Anti-pattern 2.

**Timing:** ships when doctrine-cleanup time is available;
not blocking anything. Coordinate with #115 PR-B if
`opportunity_scorer.py:141` is touched there.

**Estimated effort:** ~2-3 hours total once dispatched.

**Cross-reference:** #72 silent-failure catalog (these are
already counted in the P2 ~165 audit total but not
individually tagged); #115 diagnostic Step 6.

**Shipped (2026-05-07) on branch `feat/115c-antipattern-2-cleanup-batch`.** Per-site verdict from intent diagnostic:

**APPLY FIX (4 sites):**

- `analytics/opportunity_scorer.py:64` (was line 63 in catalog) —
  `debit or cost or 0.0` chained fallback. Pre-fix produced
  `premium=0` → `max_loss=0` and `max_profit=width*100` for any
  debit candidate where both `debit` and `cost` were None — a
  fabricated free-money score from missing data. Post-fix: bail
  with explicit `{"score": 0.0, "debug": {"reason":
  "premium_missing"}}` error result + INFO log. Same
  bail-on-pathological-input shape as PR-B-2's iv_rank fix at line
  142 (just below this site).
- `analytics/conviction_service.py:296+297` (was 279+280) —
  `avg_ev_leakage` / `avg_predicted_ev` paired fix. Pre-fix `or 0.0`
  arithmetically collapsed to neutral 1.0 multiplier when either
  field was None — same outcome as the explicit weak-signal branch
  above (line ~290). Post-fix: explicit None-check stores 1.0 with
  INFO log via the existing `_store_v3_multiplier` helper, mirroring
  the line 290-292 pattern. Pure observability — no behavioral
  change on the happy path.
- `analytics/conviction_service.py:361` (was 344) — `avg_return or
  0.0` in legacy multiplier path. Pre-fix produced `pnl_edge=0`
  ("no edge") indistinguishable from a real zero-edge result when
  `avg_return` was NULL despite `trade_count >= 5`. Post-fix: log +
  `continue`, skipping the bucket entirely. Reordered code so the
  trade_count gate runs FIRST so insufficient-samples buckets don't
  emit "missing avg_return" noise.

**EXCLUDED (3 sites — intentional design):**

- `execution/transaction_cost_model.py:217` —
  `fill_probability or 0.5`. Inside `_handle_missing_quote_fallback`
  for paper-trading missing-quote path. Lines 227-233 explicitly
  document that paper fills happen deterministically at
  `expected_fill_price` regardless. The `fill_probability` value
  flows ONLY into `result["fill_probability_used"]` — an audit-only
  field, not a decision. The 0.5 sentinel documents "no precomputed
  TCM value" in the audit log. Not load-bearing; preserve verbatim.
- `analytics/opportunity_scorer.py:50, 51` — `short_strike or 0.0`,
  `long_strike or 0.0`. The `0.0` sentinel is the documented
  "no leg" value used by downstream dispatch
  (`if short_strike > 0` at line 103, `if short_strike and
  long_strike` at line 60). Single-leg strategies legitimately have
  one strike at 0.0. Changing to None would propagate through Python
  math operators and require coordinated fixes across 10+
  downstream consumer sites — vastly out of #115c scope. Documented
  as intentional design.

**OVERLAP NOTE:** the catalog included
`opportunity_scorer.py:141 — iv_rank or 0.0` which was already
addressed by #115 PR-B-2. Removed from #115c scope as duplicative.

**#115 doctrine arc closure 2026-05-07.** Series scope:

- PR-A: `iv_daily_refresh` schedule + `iv_pipeline_no_data` alert
- PR-B-1: scanner + regime engine None-routing (flag-gated)
- PR-B-2: 3 remaining iv_rank consumer sites (flag-gated)
- #115c: 4 non-iv_rank Anti-pattern 2 sites + 3 intentional-design
  documented exclusions

#115b (Greeks parallel investigation) remains open; gated on
PR-B-2 verify + 2 weeks `underlying_iv_points` data accumulation.

#115 itself remains OPEN — operational realization still pending:
PR-A producer cron firing successfully (Friday 4:30 CT first
natural fire), operator pre-flip checklist, flag flip, ~60 trading
days of warmup.

**#116 — Backfill `underlying_iv_points` from historical option data — compresses iv_rank warmup ~12 weeks → immediate** (HIGH — decision needed)

**Discovery:** #88 H3 finding (2026-05-08). PR-A's
`iv_daily_refresh` produces forward-only Day 1 of warmup as of
2026-05-09. iv_rank requires ~60 trading days of accumulated
history before consumer-side values become meaningful. Without
backfill, the `IV_RANK_NONE_ROUTING_ENABLED` flag stays useful-
but-gated through ~late July 2026.

**Three paths to evaluate. Operator decision required.**

**Path 1 — Forward-only (currently active, no action):**
- Status: Day 1 of warmup in (2026-05-09); accumulating daily.
- Cost: $0 incremental.
- Timeline: meaningful iv_rank ~late July 2026.
- Effort: 0.
- Risk: lowest; the producer chain is already exercised end-to-
  end after PR-A's 7-layer cascade closures.

**Path 2 — Alpaca historical via Algo Trader Plus:**
- Prerequisite 1: OPRA market data agreement signature (free,
  ~30 sec, operator-side click-through on Alpaca dashboard).
- Prerequisite 2: Algo Trader Plus subscription ($99/mo
  recurring; per Saturday's web search).
- Effort: ~half-day implementation (backfill script reusing
  `get_option_bars` SDK method verified working in #88 H2
  diagnostic + integration test verifying upsert path).
- Timeline: meaningful iv_rank immediate after backfill PR ships.
- Risk: known-quantity. Alpaca SDK exposes `get_option_bars` for
  historical option chains; verified populated at the boundary
  in #88. The truth_layer adapter chain is already exercised by
  the daily forward path, so the backfill writes hit the same
  validated upsert plumbing.
- Cost-benefit: $99/mo recurring vs ~12 weeks compressed timeline.
  At current account size ($801.61), $99/mo is ~12% of equity
  per month — meaningful. Becomes more attractive once account
  scales past $5k threshold (#112's CSP capital gate).

**Path 3 — Polygon historical (existing subscription):**
- Prerequisite: investigate Polygon Options Developer plan
  ($79/mo, already paying per #87) historical option-chain
  lookback depth + API surface for IV computation.
- Effort: ~30-60 min diagnostic, then ~half-day implementation
  if feasible.
- Timeline: meaningful iv_rank immediate after backfill PR ships
  (if Path 3 viable).
- Cost: $0 incremental (already paying Polygon).
- Risk: unknown. Polygon historical may not expose option chains
  at the granularity needed; their docs around historical option
  data are less precise than the equity side.
- Open question: does Polygon's current tier expose 60+ days of
  historical option chains by symbol with strikes/expiries that
  allow ATM IV computation?

**Decision points (operator):**
- Which path to pursue (or wait on Path 1)?
- If Path 2: sign OPRA agreement + decide on subscription upgrade.
- If Path 3: run the Polygon historical diagnostic first to
  determine viability.
- Path 1 doesn't require active decision; runs in background
  regardless.

**Cross-references:**
- #88 (Alpaca options data verification — H3 backfill discovery)
- #115 (iv_rank fix; warmup timeline depends on backfill decision)
- #87 (Polygon Options Developer plan upgrade — prerequisite for
  Path 3 evaluation)

**Estimated effort:** Path 1 = 0. Path 2 = ~half day implementation.
Path 3 = ~30-60 min diagnostic + ~half day if feasible.

**#117 — `DROPPABLE_SUGGESTION_COLUMNS` shim doctrine audit** (MEDIUM)

**Discovery:** #62a-D5 diagnostic (2026-05-09). The
`DROPPABLE_SUGGESTION_COLUMNS` shim at
`packages/quantum/services/workflow_orchestrator.py:473-482`
silently strips columns matching a hardcoded list when PostgreSQL
returns "missing column" errors at line 3193, then retries the
insert. Three `execution_cost_*` entries removed in the #62a
sweep PR (D5 Option B); ~6 other entries remain.

**Doctrine concern:** Anti-pattern 2 violation per
`docs/loud_error_doctrine.md` — silent column-strip with
`print()` instead of `alert()`. The shim itself is wrapper-drift:
producer assumes columns persist; shim silently degrades. Same
class shape as PR-A's 7-layer cascade and Issue B's broker-API
fix. Pre-#62a-D5, the `execution_cost_*` fields were silently
dropped on every persist for an unknown duration without any
alert firing — the diagnostic only surfaced the issue because the
broader #62a schema-vs-code audit listed them.

**Three options for the broader shim** (mirrors the per-D5
decision matrix; choose once for the remaining fields rather
than per-field):

- **Option A (audit each entry):** for each remaining DROPPABLE
  entry confirm via grep + DB-state probe whether columns
  SHOULD exist (add via migration) or producer assignments
  SHOULD be removed (ship per-entry deletions). Likely outcome:
  same Option-B-style deletion for most fields since they're
  observability metadata with zero readers (matches D5 pattern).
- **Option B (replace shim with explicit handling):** when
  producers assign optional fields, use a documented "optional
  persistence" pattern that loud-errors on column drop rather
  than silently retrying. Producers carry the responsibility
  for opt-in degrade-gracefully behavior.
- **Option C (remove shim entirely):** require strict
  schema-payload alignment. All producer assignments must
  correspond to existing columns. Silent shim becomes hard
  failure; forces schema-vs-code drift to surface immediately.

**Affected fields after the #62a-D5 cleanup** (~6 remaining):

- `agent_signals`
- `agent_summary`
- `source`
- `marketdata_quality`
- `blocked_reason`
- `blocked_detail`

Verify exact list when investigating; audit may surface
additional latent fields the diagnostic missed.

**Approach (when scheduled):**
1. For each remaining field: run `grep -rn "<field>" packages/quantum/`
   for both writers and readers, then DB query to confirm column
   presence/absence on `trade_suggestions`.
2. Categorize: load-bearing (consumer reads it) vs observability-only
   (write-and-forget) vs dead (no producer or no consumer).
3. For dead/observability-only: ship Option B-style removal
   (single PR per cleanup batch).
4. For load-bearing: add migration column.
5. After all entries resolved: replace the shim with a hard
   failure; the empty list makes the shim trivially deletable.

**Effort:** ~half day audit + per-batch cleanup PRs.

**Cross-references:**
- #62a-D5 (closed via Option B in #62a sweep PR)
- `docs/loud_error_doctrine.md` (Anti-pattern 2)
- Wrapper-drift class catalog (PR-A's 7-layer cascade #115 PR-A
  Layers 1-7, Issue B's 4-layer cascade in PR #908)

**#118 — Delete legacy `packages/quantum/jobs/enqueue.py` module** (LOW)

**Discovery:** #71 Tier 3 (PR <THIS>) confirmed only the smoke
script `packages/quantum/scripts/rq_smoke_morning_brief.py` still
imports the legacy module. Production code is clean (codebase-wide
CI gate enforces this).

**Path forward:**

1. Audit `packages/quantum/scripts/rq_smoke_morning_brief.py` —
   is the smoke script still useful operator tooling, or dormant?
   When was it last run? Does it have a documented operator
   workflow?
2. If dormant: delete the script.
3. If still useful: migrate to canonical
   `packages.quantum.public_tasks.enqueue_job_run` path.
4. After either path: delete `packages/quantum/jobs/enqueue.py`
   entirely (the module has zero importers post-migration).

**Bonus consideration:** the codebase-wide CI gate could be
extended to walk `scripts/` too (currently excluded). Decide
whether smoke scripts and operator tooling are held to the same
canonical-path discipline. Probably yes for consistency, but
worth an explicit operator decision rather than implicit.

**Effort:** ~30 min - 1 hour depending on smoke script status.

**Cross-references:**
- PR #901 (class-prevention test, original scope)
- PR #910 (#71 Tier 2 deletion)
- PR <THIS> (#71 Tier 3 codebase-wide test)

### #72 — Loud-error doctrine + silent-failure catalog

**Phase 1 (doctrine + catalog) complete 2026-04-27.**

Doctrine document: `docs/loud_error_doctrine.md` (v1.0).

**Audit summary:** ~242 silent-failure sites in production
(`packages/quantum/`).

| Pattern | Count |
|---|---:|
| P1 (`try/except: pass`) | ~38 |
| P2 (log-only swallow) | ~165 |
| P3 (`@guardrail`) | 9 |
| P4 (endpoint silent) | ~14 |
| P5 (env-var branch) | ~7 |
| P6 (bare `except`) | ~9 |

| Path heat | Count |
|---|---:|
| HOT (every-trade / every-scan) | ~95 |
| WARM (daily/weekly scheduler) | ~85 |
| COLD (manual / on-demand UI) | ~50 |
| DEAD (gated off; fold into existing dead-code sweeps) | ~12 |

#### #72-Phase 2 — HOT fixes (next 2-4 weeks, ~5 PRs)

- [x] **#72-H1 — `equity_state.py` envelope-skip alert + introduce
      `alert()` helper.** **CLOSED 2026-04-26 by PR #817.** Helper
      shipped at `packages/quantum/observability/alerts.py` (canonical
      location, not `services/observability.py` as originally drafted —
      matched existing `observability/` package convention). Sites
      `services/equity_state.py:_fetch_alpaca_equity` and
      `_fetch_alpaca_weekly_pnl` now write `risk_alerts` on Alpaca
      failure with `alert_type='equity_state_alpaca_account_failed'` /
      `'equity_state_alpaca_portfolio_history_failed'`.
- [x] **#72-H2 — `scheduler.py:_fire_task` HTTP error alerting.**
      **CLOSED 2026-04-26 by PR #818.** Three sites alert: signing
      failure (`scheduler_task_signing_failed`), httpx exception
      (`scheduler_task_http_error`), HTTP 4xx/5xx response
      (`scheduler_task_http_status_error` with response body capped at
      2000 chars). Lazy-singleton supabase client with sentinel
      (`_SUPABASE_INIT_ATTEMPTED`) prevents log spam during sustained
      Supabase outages. (Sentinel later relocated to
      `observability/alerts.py` as `_ADMIN_INIT_ATTEMPTED` per #72-H3.)
- [x] **#72-H2a — `_retry_failed_jobs` ImportError fix + doctrine alert.**
      **CLOSED 2026-04-27 by PR #821.** Function had been silently
      broken since at least 2026-01-10 (3.5+ months) due to
      non-existent `packages.quantum.database` import. Fix swapped to
      canonical `get_admin_client` from
      `packages/quantum/jobs/handlers/utils.py`. Outer except now writes
      `auto_retry_scan_failed` alert per Loud-Error Doctrine v1.0.
      Post-deploy expectation: 5 stuck `failed_retryable` rows will
      progress to `dead_lettered` within ~24h, producing 5
      `job_dead_lettered` `risk_alerts`. Each surfaces a separate
      pre-existing root cause (alpaca_order_sync pytz, alpaca_order_sync
      missing user_id arg, paper_auto_execute trade_suggestions.score
      schema drift, validation_eval StrategyConfig JSON serialization
      ×2). Diagnosis of each underlying issue queued as #76–#79 once
      the dead-letter alerts confirm the failures still reproduce.
- [x] **#72-H3 — `@guardrail` decorator alerts + shared admin
      singleton.** **CLOSED 2026-04-27 by PR (this commit).**
      Decorator-level fix: both fallback paths now write alerts.
      Path A (circuit OPEN) → `{provider}_circuit_open`; Path B
      (retries exhausted) → `{provider}_retries_exhausted`. Metadata
      captures `provider`, `function_name`, args (repr-truncated,
      self-skipped via qualname heuristic), plus path-specific
      fields. Bonus scope: extracted shared `_get_admin_supabase()`
      helper into `observability/alerts.py` and migrated
      `scheduler.py` away from its local singleton — future modules
      adopting the doctrine pattern import from
      `observability.alerts` rather than reinventing.
- [x] **#72-H4a — `workflow_orchestrator.py` trade-decision safety.**
      **CLOSED 2026-04-27 by PR (this commit).** Group A from H4
      diagnostic. Sites `2158` (envelope check) and `2196` (ranker
      positions fetch) now write `risk_alerts` on failure. New
      `alert_type`s: `workflow_envelope_check_failed`,
      `workflow_ranker_positions_fetch_failed`. Establishes the
      `consequence` metadata field convention for `workflow_*`-class
      alerts (which continue silently after the catch, so the
      consequence isn't obvious from `alert_type` alone). Tests use
      source-level structural assertions + `ast.parse` syntax
      validation rather than runtime imports (avoids heavy
      dependency tree).
- [x] **#72-H4b — `workflow_orchestrator.py` calibration data
      integrity.** **CLOSED 2026-04-27 by PR (this commit).** Group B
      from H4 diagnostic. 4 sites covered with new alert_types:
      `workflow_morning_cal_apply_failed` (site 1654, single-fire),
      `workflow_budget_extraction_failed` (site 2076, single-fire,
      bare-except renamed), `workflow_midday_cal_prefetch_failed`
      (site 2172, single-fire), `workflow_per_candidate_cal_apply_failed`
      (site ~2820, **first production use of doctrine's tight-loop
      aggregation pattern**: per-candidate failures collected during
      candidate loop, single summary alert fires after loop with
      `failed_count` + `failed_symbols` (capped at 20) +
      `distinct_error_classes`). Trade-off documented in code comment.
- [x] **#72-H4c — `workflow_orchestrator.py` audit + ancillary.**
      **CLOSED 2026-04-29 by PR #835.** Groups C+D from H4 diagnostic.
      6 sites covered (5 from original + 1 bonus mirror discovered
      during diagnostic): `paper_exit_marketdata_fetch_failed` (line
      1351, single-fire), `workflow_morning_suggestion_insert_failed`
      (1766, loop), `workflow_morning_post_insert_observability_failed`
      (1833, single-fire), `workflow_midday_progression_fetch_failed`
      (1922, single-fire async), `workflow_midday_post_insert_observability_failed`
      (3193, single-fire), `workflow_midday_suggestion_insert_failed`
      (3083, loop — bonus site outside original H4 catalog).
      34 new structural tests in `test_workflow_orchestrator_alerts.py`.

**Deferred from #72-H4 diagnostic (not in scope for any sub-PR):**

- 3 sites (lines `99`, `128`, `169`) — Replay decision-context
  recording. Replay subsystem is gated off via `REPLAY_ENABLE=0`.
  Defers to the Replay wire-up-or-remove decision queued for after
  micro_live stabilizes.
- 2 sites (lines `1131`, `1952`) — `regime_snapshots.insert(...)`.
  Defers to `#62a-D3` (table missing in production). Either the
  migration adds the table or the writes get removed; alerts here
  would be noise until that decision resolves.
- 3 sites (lines `1411`, `1843`, `2060`) — VALID patterns under
  Loud-Error Doctrine v1.0 (input parsing fallback, typed coercion
  with sentinel return, multi-source fallback chain intermediate).
  Documented as compliant for future audits. No fix needed.
- [x] **#72-H5a — `paper_exit_evaluator.py` HOT swallows.**
      **CLOSED 2026-04-30 by PR #838.** First half of #72-H5. 9 alert
      sites covered: per-condition eval (loop), cohort configs load,
      close-loop (loop), open positions fetch (safety), cohort resolve
      exhausted (collapsed 3 paths → 1 alert when all fail), routing
      query (safety), idempotency check (safety), Alpaca DRY_RUN build,
      Alpaca submit fallback to internal (CRITICAL — 2026-04-16
      ghost-position bug shape). **New convention introduced:**
      `operator_action_required` metadata field on critical-severity
      alerts; provides explicit operator runbook text. 57 structural
      tests in new `test_paper_exit_evaluator_alerts.py`.
- [x] **#72-H5b — `paper_autopilot_service.py` HOT swallows.**
      **CLOSED 2026-04-30 by PR #839.** Closes #72-Phase 2 entirely.
      10 alert sites including SAFETY-CRITICAL site 236
      (`paper_autopilot_circuit_breaker_failed`) with
      `operator_action_required` metadata, matching H5a site 9
      convention. Site 4 (lines 411+438) collapsed two-stage pattern
      sharing failures list (status_staged_update + full_execution).
      63 structural tests in `test_paper_autopilot_service_alerts.py`.
      Phase 3 (WARM, shared-helper approach) and Phase 4 (COLD,
      opportunistic) remain as future work.

#### #72-Phase 3 — WARM fixes (this month, shared-helper approach)

- [ ] **#72-W1 — Shared `notes_to_risk_alerts` helper for
      `jobs/handlers/*`.** ~15 sites across `daily_progression_eval`,
      `learning_ingest`, `paper_learning_ingest`, `iv_daily_refresh`,
      `intraday_risk_monitor`, `promotion_check`,
      `reconcile_positions_v4`, `seed_ledger_v4`,
      `refresh_ledger_marks_v4`, `report_seed_review_v4`,
      `run_market_hours_ops_v4`, `strategy_autotune`,
      `suggestions_close`, `suggestions_open`, `validation_eval`.
      Pattern: P2 (notes-list anti-pattern). Effort: ~4h for the helper
      + each handler migration.
- [ ] **#72-W2 — `paper_endpoints.py` post-fill swallow audit.**
      Sites in `_run_attribution` and `_paper_commit_fill` family.
      Pattern: P1/P2. Effort: ~half day.
- [ ] **#72-W3 — `execution_service.py` ledger-record alert.**
      Sites: `services/execution_service.py:182, 193, 256, 271, 349,
      600, 648, 661, 728`. Pattern: P1/P2. Execution-vs-ledger drift
      currently invisible. Effort: ~half day.
- [ ] **#72-W4 — `brokers/alpaca_*` watchdog alerts.** ~12 sites
      across `alpaca_order_handler.py`, `alpaca_client.py`,
      `alpaca_endpoints.py`. Pattern: P2. Effort: ~half day.
- [ ] **#72-Phase3-A — Migrate `_retry_failed_jobs` inline
      `job_dead_lettered` writes to doctrine `alert()` helper.**
      Source: deferred from #72-H2a (PR #821) — 3 inline
      `client.table("risk_alerts").insert(...)` calls in
      `scheduler._retry_failed_jobs` predate the doctrine. Migrate to
      `alert(_get_supabase_for_alerts(), alert_type='job_dead_lettered',
      severity='critical', ...)`. Stylistic refactor; no behavior
      change. Priority: LOW. Effort: ~15 min.

#### #72-Phase 4 — COLD touch-ups (eventual; on-touch only)

- [ ] **#72-C1 — `dashboard_endpoints.py` user-visible failures.**
      ~19 sites of P4 (HTTP 200 + empty payload). Effort: opportunistic;
      patch on-touch.
- [ ] **#72-C2 — Optimizer / agent / regime sub-step fallbacks.**
      Across `optimizer.py`, `analytics/regime_engine_v3.py`,
      `analytics/regime_engine_v4.py`, `agents/runner.py`. Pattern: P2.
      Touch on-modify only.

#### #72-Phase 4 — DEAD-code overlaps (no remediation; fold into existing sweeps)

- `outcome_aggregator.py` (5 sites) — already in #67.
- `nested_logging.py` (6 sites) — already in #67 (log_outcome chain).
- `services/replay/decision_context.py`, `services/replay/blob_store.py`
  (~10 sites) — gated off via `REPLAY_ENABLE=0`; fold into Replay
  evaluation backlog item.
- `analytics/walk_forward_autotune.py`, `services/walkforward_runner.py`
  (~8 sites) — `AUTOTUNE_ENABLED=false` permanently; fold into
  adaptive-caps stack removal item.
- `polygon_client.py` — already in #66.

#### #72 audit method limitations

The audit catches static patterns: `try/except`, decorator-based
swallow, endpoint-silent. It does NOT catch:

1. Methods that raise typed exceptions to a caller that itself
   swallows (the swallow shifts up one frame).
2. Async paths where the exception is captured in a Future and
   never awaited.
3. Errors that propagate cleanly but produce wrong values
   downstream (e.g., a `0` from a defaulted division leaks into
   a sizing calc — the *swallow* is correct, but the *consequence*
   is silent corruption).
4. Operations that "succeed" with a corrupted state (e.g., insert
   succeeds with NULL where downstream expects a value).

Confidence: HIGH on the ~95 HOT site list, MEDIUM on completeness
for COLD/DEAD where greppability degrades. Future drift is expected;
this catalog is a starting point, not a complete enumeration.

**#73 — Remove dead `GET /policy-lab/results` endpoint and table** (LOW)
After PR #808 (closes #65), `policy_lab_daily_results` has zero
writers. Reader at `policy_lab/endpoints.py:42-75` has zero frontend
callers (verified in `apps/web/`). Delete the route, drop the table
via migration, scrub references in CLAUDE.md. Gated on #65 fully
closed (Monday 2026-04-27 verification). Effort: ~1 hour.

**#75 — Drop `nested_regimes` table (orphan after #62a-D2)** (LOW)

Source: #62a-D2 fix on 2026-04-26 deleted `log_global_context`, the
only writer to `nested_regimes`. Table now has zero writers and
zero readers (verified during D2 diagnostic — no Python code reads
the table; no scheduler entry; no FastAPI route).

Cleanup scope:
- Migration to `DROP TABLE nested_regimes`.
- Remove the original creation migration if appropriate (or keep
  as a historical artifact).

Effort: ~30 min, single PR. Bundle with the existing "drop unused
tables" Priority 3 batch.

Priority: LOW — orphan table costs nothing, just noise.

**#74 — Remove `RISK_EQUITY_SOURCE=legacy` rip-cord from `equity_state.py`** (LOW)

Source: 83872db (2026-04-16) committed *"Kept 72h for safety;
scheduled for removal in a follow-up PR."* Now 10 days stable.

Cleanup scope:
- Remove `_estimate_equity_legacy` and `_compute_weekly_pnl_legacy`
  from `equity_state.py`.
- Remove `RISK_EQUITY_SOURCE` env-based switching logic.
- Update `.github/workflows/ci-tests.yml:24` (currently sets
  `RISK_EQUITY_SOURCE=legacy`).
- Prune legacy-branch tests in `test_equity_state_helpers.py`.

Effort: ~1-2 hours, single PR, no functional change in production
(rip-cord is unset in Railway env, defaults to `alpaca`).

**#85 — Universe price filter for micro tier** (HIGH — RESOLVED 2026-04-27)

Source: 2026-04-27 19:16 UTC manual rerun (validating PR
feat/micro-tier-90pct-single-position). With $500 capital and the
new $450 per-trade budget computing correctly, the cycle still
produced 0 suggestions because the only viable scanner output was
AMZN at $1247 underlying / $1223 max_loss/contract — which exceeds
$450 budget. ~80% of the 62-symbol universe (FAANG + high-priced
ETFs) produces uneconomic candidates.

Resolved by PR feat/85-micro-tier-universe-price-filter:
`options_scanner._apply_tier_price_filter` drops symbols with
underlying > $50 (configurable via `MICRO_TIER_MAX_UNDERLYING` env)
for micro tier only. Inserted after the batch quote fetch, before
per-symbol option-chain calls (saves Polygon API calls too).
Threshold aligns with existing 2.5-vs-5 spread-width split.

**#86 — Late-day liquidity degradation in scanner** (LOW —
informational)

Source: 2026-04-27 19:16 UTC manual rerun. BAC went from
"score=100, tradeable" at 17:10 UTC to "spread_too_wide=14.2%" at
19:16 UTC (2:16 PM CT, ~45 min pre-close). Same underlying, same
chain, same scanner — just 2 hours later in the trading day.

Operational implication: scheduled 16:00 UTC cycles (11:00 AM CT)
should not have this problem. Manual reruns close to market close
will. **Don't manual-trigger after 1:00 PM CT for testing
purposes.** Priority: LOW — informational. Tomorrow's normal
schedule is in the right window.

**#87 — Polygon 429 storm chronic** (HIGH — RESOLVED 2026-04-27)

Resolved by Polygon plan upgrade: Stocks Basic ($0) → Stocks
Starter ($29/mo) and Options Basic ($0) → Options Developer
($79/mo), total $108/mo recurring. Diagnostic-first
investigation initially framed the storm as deploy-induced cold
cache + retry amplification, but operator's plan check revealed
the true root cause: Basic tier hard-capped at 5 calls/min/product
*and* lacked entitlements for snapshot / Greeks / IV / Open
Interest endpoints (the `403 NOT_AUTHORIZED` errors on
`/v3/snapshot` for option contracts in worker logs were the
clearest signal, but my diagnostic underweighted them).

Lesson: when web-search returns "paid plans are unlimited" and
the data shows persistent 429s, the actual plan tier (free vs
paid) is the first thing to verify, not the second. The
operator's dashboard check would have shifted the diagnostic
weight in 5 minutes.

**#87a — Polygon rate limiter** (LOW — deprioritized)

Source: deferred from #87 (2026-04-27). My #87 diagnostic
proposed a client-side token-bucket rate limiter (~30 min
implementation) as a tactical guard. After plan upgrade, the
underlying need is gone — the Starter/Developer tier no longer
caps at 5/min, so bursts are safe. Consider during a future
defensive-engineering pass (belt-and-suspenders against future
plan downgrades or unexpected provider throttling), but not
urgent.

**#87b — `scanner_universe` metadata backfill** (MEDIUM — RESOLVED 2026-04-28)

**RESOLVED via operational fix — no code change required.**
Universe_sync trigger run on 2026-04-28 (post-Polygon-upgrade)
populated metadata for all 62 symbols. Pre-state: 9/62 scored.
Post-state: 62/62 scored, 62/62 with avg_volume_30d, 62/62 with
iv_rank. Sync ran in 26s vs 145s pre-upgrade (6× speedup
confirmed Polygon plan upgrade unblocked the helper calls).

Underlying issue: pre-upgrade Polygon Basic-tier rate limits
caused per-symbol metric-fetch failures to cascade silently
through the sync loop (each symbol's exception caught + skipped).
Post-#87 plan upgrade removed the rate cap; a manual sync trigger
populated everything. Audit-trail row in
`risk_alerts.alert_type='universe_sync_backfill'` (id
`6b9430d1-215e-4539-81dc-2497f029a7ed`).

Code-shape concerns (originally listed as part of #87b — sync
schedule cadence, on-failure alerts) deferred to #72-W phase or
follow-up. Operational state is now correct.

**#88 — Verify Alpaca options data access** (LOW)

Source: 2026-04-27 Polygon plan upgrade follow-up (#87
resolution). Today the Alpaca SIP fallback failed for live cycles
(`subscription does not permit querying recent SIP data` errors
on equity bars). Worth understanding what the live Alpaca account
provides as a backup data source — equity SIP, options snapshots,
options Greeks, etc. — but no longer urgent with the Polygon plan
upgrade covering the primary path. Verify on the Alpaca dashboard
whether the live account is entitled to SIP data and options
snapshots; document findings in this entry, then decide whether
to wire `MarketDataTruthLayer` Alpaca-fallback paths that
currently dead-end.

Effort: ~30 min Alpaca dashboard check + ~half day to wire
fallbacks if entitled. Priority: LOW — Polygon primary now
covers the path.

**#91 — Regime-scaled universe price filter** (LOW)

(Renumbered from #88 on 2026-04-27 to honor operator's explicit
numbering of the new #88 — Alpaca options data verify entry
above. Original PR feat/85-micro-tier-universe-price-filter
commit message references "#88" — refers to this entry
pre-renumbering.)

Source: deferred from #85 design (2026-04-27). #85 ships with a
static $50 threshold. In shock-regime cycles, the $450 normal
budget collapses to $225 — but the static $50 filter still allows
BAC ($286 max_loss) through, only to be sizing-vetoed downstream.
Promote to dynamic when shock-regime cycles repeatedly produce
sizing-veto rejections of micro-tier candidates.

Implementation sketch: `threshold = 50.0 × regime_mult_for_micro`
(so $40 elevated, $25 shock). Effort: ~1 hour. Priority: LOW —
defer until evidence demands it.

**#89 — Tier-aware `RISK_MAX_SYMBOL_PCT` envelope cap** (LOW)

(Renumbered from #85 on 2026-04-27 to honor operator's explicit
numbering of universe-filter / late-day / 429 entries above.
Original PR feat/micro-tier-90pct-single-position commit message
references "#85" — refers to this entry pre-renumbering.)

Source: micro tier sizing fix (2026-04-27). The risk envelope at
`packages/quantum/risk/risk_envelope.py` enforces `RISK_MAX_SYMBOL_PCT=0.4`
(40% per-symbol cap) regardless of tier. Under micro tier with 90%
per-trade sizing, BAC at $286 = 57% of $500 capital VIOLATES the
envelope cap. Currently warn-only at the pre-entry check site
(`workflow_orchestrator.py:2186-2222`), so it logs warnings but
doesn't block. Future cleanup: tier-aware envelope cap (e.g., 1.0
for micro tier, 0.4 for standard). Effort: ~1 hour, single PR, plus
matching test in `risk_envelope` test suite. Priority: LOW —
warn-only path means no operational impact today.

**#90 — `STRATEGY_TRACK` env var cleanup** (LOW)

(Renumbered from #86 on 2026-04-27 — same reason as #89.)

Source: micro tier sizing fix (2026-04-27). With tier-aware
`RiskBudgetEngine`, `STRATEGY_TRACK` is now no-op for micro tier
(engine takes the tier branch before the risk_profile switch). Only
affects small/standard tier `per_trade_pct`. Currently set to
`balanced` on both BE and worker services in Railway. Cleanup:
remove the env from Railway (defaults to `balanced` if unset),
simplify the engine code to drop the unused branch (or keep for
small-tier conservative/aggressive override flexibility). Effort:
~30 minutes. Priority: LOW — cosmetic.

### #62a — Schema drift audit COMPLETE 2026-04-26

Audit catalog: **12 drift instances** found across 70 tables, ~1,100
columns, ~60 production write sites, 85 migrations.

The initial Saturday/Sunday findings (3 instances — PR #6 enum, #65
`policy_lab_daily_results`, `outcomes_log` cols) captured a fraction
of actual drift. The audit revealed 9 additional instances including
1 latent live-trade-routing issue and 4 broken data-collection paths
(regime persistence dead, cohort fan-out broken, execution-cost
gating dropped silently, regime_snapshots table missing).

Method limitations documented (8 false-negative classes — see
"#62a audit method limitations" below). Confidence: **HIGH on 10
actionable findings, MEDIUM on completeness.**

Catalog summary:
- **1 CRITICAL** in audit (verified DOWNGRADED to HIGH-LATENT
  after deep-dive — see #62a-D1).
- **4 HIGH** (cohort fan-out broken, regime persistence dead,
  execution-cost gating silently dropped, regime_snapshots table
  missing).
- **3 MEDIUM** (governance state, shadow_cohort_daily, legacy
  execution_service).
- **4 LOW** (rebalance flow, outcomes_log dead-code,
  symbol_regime_snapshots, OOB tables).

Status: AUDIT COMPLETE. Catalog forms the work plan for #62 proper.
Sub-items #62a-D1 through #62a-D12 below.

#### #62a-D1 — wire evaluator output to live route (HIGH; architectural PR queued)

Verified 2026-04-26: column missing from `policy_lab_cohorts`, but
autopilot has produced zero orders in 8+ days, and live routing
goes through `fork.py:67` cohort_name tag path — not through
`_get_champion_portfolio`. Not Monday-blocking.

Compounding issue: migration `20260402000000_small_account_cohorts.sql`
intends `'neutral'` as champion; live code (`fork.py:67`) hardcodes
`'aggressive'`. The two designs disagree.

**Prerequisite before fix:** resolve `'neutral'` vs `'aggressive'`
intent disagreement.

Fix scope after intent resolution:
- `ALTER TABLE policy_lab_cohorts ADD COLUMN is_champion boolean DEFAULT false`
- `UPDATE` to set `is_champion=true` on the resolved cohort.
- Decide whether `_get_champion_portfolio` should actually be
  reachable, or be deleted (the live routing stays in fork.py's
  tag-based path).
- Optional: clean up 3 orphan $500 "Main Paper" portfolios from
  2026-04-02.

Effort: ~2-4 hours after intent resolution.

---

**[ADDENDUM 2026-05-12 — sub-investigation complete + framing corrected]**

Monday's sub-investigation (read-only diagnostic) refuted both the
original "missing column" framing AND Monday morning's reframing as
"complete the shadow-evaluate-promote system." The system is already
complete in two parts that don't talk to each other.

**Two-architecture finding:**

| Architecture | Status | Mechanism |
|---|---|---|
| Champion/challenger evaluator | EXISTS_COMPLETE; runs daily | `promoted_at` column + 7 promotion gates + `policy_daily_scores` + `policy_lab_promotions` audit |
| Live route hardcode | EXISTS_COMPLETE; runs in production | `fork.py:67` hardcodes `cohort_name = "aggressive"` |

The evaluator (`packages/quantum/policy_lab/evaluator.py`) is fully
built: 7 promotion gates (≥3 trading days, ≥10 closed trades, no
-20% drawdown, ≥15% utility margin, ≥70% posterior probability
challenger > default, drawdown not worse than champion, 2-day
cooldown), `UPDATE policy_lab_cohorts SET promoted_at = NOW()`
write at line 537-545, `policy_lab_promotions` audit table,
rollback path, env-gated AUTO_PROMOTE. 4 successful job runs to
date (latest 2026-05-08 21:30Z), 0 promotions written (no
challenger has passed all gates so far OR AUTO_PROMOTE off).

`fork.py:67`'s hardcode is original to the file (git blame shows
commit `f396334f` from 2026-03-20 — the first commit that
introduced fork.py). Never had dynamic-selection. The two
architectures were authored independently and never wired.

**Two `is_champion` silent-failure query sites are bugs:**
- `paper_autopilot_service.py:867` `_get_champion_portfolio` —
  queries `is_champion=True`, wrapped in try/except: pass,
  returns None on exception (column doesn't exist → always None)
- `paper_exit_evaluator.py:892` — fallback path queries
  `is_champion=True`, logs to `_resolution_failures` list

Both were written when someone assumed the migration's
`is_champion=true` intent would land as a column. Migration
INSERT does name `is_champion` in the column list but does NOT
set `promoted_at`. Someone (operator) manually `UPDATE`'d
`promoted_at` on neutral around 2026-04-02 21:28Z (closest to
the migration apply window) as initial-champion designation.

**Operator intent confirmed 2026-05-12:** aggressive = starting
champion (matches fork.py:67's hardcode AND the live trading
that's been running for 6+ weeks). Conservative + neutral run
as shadow challengers on separate `paper_portfolio_id`s. When
evaluator promotes a challenger (manually approved per C-1
endpoint), live route follows.

**Current DB state misalignment:** `promoted_at` is set on
`neutral` (not aggressive) — predates the intent clarification.
Architectural PR will correct.

**Endpoint chosen: C-1 — read promoted_at + manual promotion only**
- AUTO_PROMOTE stays OFF until evaluator's 7 gates have empirical
  track record (currently 4 runs / 0 promotions; not enough data
  to trust automated cohort switches on live capital)
- C-2 (keep hardcoded aggressive) was rejected because the
  evaluator's daily scoring would have no consumer
- C-3 (full automation) was rejected as premature

**Architectural PR scope (queued, ships after CSX validation week
completes):**
- DB: `UPDATE policy_lab_cohorts SET promoted_at = NOW() WHERE
  cohort_name = 'aggressive'`; `UPDATE ... SET promoted_at = NULL
  WHERE cohort_name = 'neutral'`
- Fix the 2 silent-failure `is_champion` query sites:
  - `paper_autopilot_service.py:867` `_get_champion_portfolio` —
    rewrite to `WHERE promoted_at IS NOT NULL ORDER BY promoted_at
    DESC LIMIT 1`; or delete if redundant after fork.py:67 change
  - `paper_exit_evaluator.py:892` — same rewrite or delete
- `fork.py:67`: read current champion's `cohort_name` via
  `promoted_at` lookup instead of hardcoding `"aggressive"`
- `POLICY_LAB_AUTOPROMOTE` stays OFF (no env-var change needed)
- Optional cleanup: 3 orphan $500 "Main Paper" portfolios from
  2026-04-02 (deferred per original entry — still applies)

**Effort:** ~half day for architectural PR. Single validation
cycle (live trading params don't change from current state because
aggressive's policy_config matches the current hardcoded live route
— wire-up is mechanical correctness, not behavior change).

**Open future considerations (NOT in architectural PR scope):**
- **Evaluator gate validation** — review the 7 gates for sanity
  (sample size thresholds, posterior probability cutoff, drawdown
  bounds). Should happen before AUTO_PROMOTE is enabled. Currently
  4 runs / 0 promotions could be either "gates working, no
  qualifying challenger" or "gates miscalibrated" — empirical
  signal needed.
- **AUTO_PROMOTE enablement** — separate work item; needs
  empirical track record of manual promotions matching evaluator
  recommendations first.
- **Doctrine candidate** — "parallel architectures without
  integration" as new class adjacent to H9 wrapper-drift. Two
  complete subsystems can each work in isolation while the
  integration seam (the writer's output → consumer's input wire)
  is the bug. Worth design-review discussion.

**Cross-references:**
- Sub-investigation diagnostic 2026-05-12 (session history)
- Sunday's #62a-D1 initial diagnostic 2026-05-10 (session history)
- H9 doctrine (`docs/loud_error_doctrine.md`) — adjacent class
- CLAUDE.md "Cohort architecture" section — known-gap state
  documented in tandem with this entry

#### #62a-D2 — `nested_regimes` writer deleted (CLOSED 2026-04-26)

Originally classified as HOT-HIGH "rename keys in writer". Diagnostic
revealed three layered failures: wrong column names, missing required
`timestamp` field, silent try/except. Plus zero readers anywhere
(no code, no scheduler, no FastAPI route) and zero rows ever written.

Resolution: **deleted `log_global_context`** rather than fix —
empty-table writes don't fit the loud-error doctrine emerging from
#62a/#67. Also removed dead `_get_supabase_client` helper, dead
`supabase` import in `backbone.py`, dead import in `optimizer.py`,
and three unused test mocks. Table-level cleanup tracked as #75.

#### #62a-D3 — `regime_snapshots` table missing (HOT, HIGH) — **CLOSED 2026-05-10**

Files: `api.py:627`, `workflow_orchestrator.py:1155`, `:2087`.
Migration `20251213000000_regime_snapshots.sql` exists but never
applied. Daily morning + midday cycles attempt persistence and
fail silently.

Fix: apply migration, OR delete the writes (decide if snapshot is
needed for backtest/replay).

**[CLOSED 2026-05-10 by #62a sweep PR]:** chose deletion. Saturday's
diagnostic verified all 3 writers wrapped in `try: ... except: pass`
("non-critical write" comment) and ZERO production readers anywhere.
The in-memory `GlobalRegimeSnapshot` dataclass is load-bearing for
risk budget + strategy selection; only the audit-trail persistence
was missing. PR deleted 3 writers + the migration file. Closes
**#62a-D11** in same PR (same migration defined `symbol_regime_snapshots`
with zero writers).

#### #62a-D4 — Cohort fan-out routing safety + symbol drop fix — **3-PR SEQUENCE SHIPPED 2026-04-30**

PRs #842 (PR2a routing safety gate) + #843 (PR2b shadow fill simulation)
+ #844 (PR3 clone-builder symbol field removal) all merged
2026-04-30. The architectural sequence (routing_mode column +
dispatch enforcement + simulated fills + symbol-drop) is
functionally complete.

**End-to-end verification gate:** the original D4 verification
step ("shadow trades start appearing in trade_suggestions") was
blocked by the subsequent #97 trace_id collision discovered
2026-05-05 — second cohort INSERT failed unique constraint, so
even though D4 unlocked the path, fan-out remained at
{aggressive: 1, others: 0}. PR #876 (closed 2026-05-05) resolved
the trace_id collision. Both #95 and D4 verification gate on the
same upcoming cohort-firing cycle (likely tomorrow's 16:00 UTC).
Tracked under #95's "awaiting next-cycle verification" status —
no separate action needed for D4.

Status: SHIPPED. Verification rolled into #95.

---

(Original D4 framing preserved below for context — describes the
architectural intent of the 3-PR sequence as designed pre-ship.)

Status: HIGH — multi-PR architectural work, **NOT one-line fix.**

Original audit finding: clone path writes `symbol` key to
`trade_suggestions` but column is `ticker`. Single-key drop appears
trivial.

Verification finding 2026-04-26: applying the drop in current
`micro_live` mode could route conservative/neutral cohort orders to
the live broker, violating the design intent that shadow cohorts
are paper-only learning channels (operator clarification 2026-04-26:
fan-out is meant to amplify *learning* per trade — one cohort
trades real capital, others produce shadow observations that must
NEVER reach the live broker).

Current implementation conflates routing: `EXECUTION_MODE` is
global; no portfolio-level safety. Restoring shadow data flow
without routing enforcement is unsafe.

**Required sequence (3 PRs):**

**PR 1 — Add `routing_mode` column to `paper_portfolios`**
- Migration: `ALTER TABLE paper_portfolios ADD COLUMN routing_mode
  text NOT NULL DEFAULT 'live_eligible'
  CHECK (routing_mode IN ('live_eligible', 'shadow_only'))`
- UPDATE existing cohort portfolios:
  - Conservative Cohort, Neutral Cohort → `'shadow_only'`
  - Aggressive Cohort → `'live_eligible'` (current champion path)
  - Main Paper → `'live_eligible'`
- Effort: ~30 min.
- Risk: LOW (data-only change, no code change yet).

**PR 2 — Routing dispatch enforcement**
- Modify broker dispatch to check `portfolio.routing_mode` before
  live submission.
- Implement `_simulate_fill` for shadow_only portfolios (decide
  between mid-price simulation, mirror-champion, or paper_mtm
  reuse).
- Tests: assert shadow_only portfolios never reach Alpaca
  regardless of `EXECUTION_MODE`.
- Effort: ~1 day.
- Risk: MEDIUM (architectural change, needs careful testing).

**PR 3 — Apply original #62a-D4 single-line symbol fix**
- Drop `"symbol": source.get("symbol")` from clone dict at
  `packages/quantum/policy_lab/fork.py:229`.
- Verification: shadow trades start appearing in `trade_suggestions`;
  `paper_orders` for shadow_only portfolios show simulated fills.
- Effort: 5 min code + 30 min verification.
- Risk: LOW after PRs 1 and 2 land.

Total effort: **~2 days across 3 PRs.**

Architectural principle: each portfolio's intent (live-capable vs
shadow-only) becomes explicit data, not implicit code-path
knowledge. Safe by default — new portfolios default to
`live_eligible`; shadow status must be intentionally set.

Verified production state (still true as of 2026-04-26):
**0 conservative/neutral shadow clones in 30 days** vs 58
aggressive. Shadow eval data collection has been broken at the
source for the entire month. The "189 cohort decisions" stat
referenced in CLAUDE.md cohort architecture section is from
`policy_decisions`, NOT actual shadow trades.

#### #62a-D5 — `execution_cost_*` columns silently dropped (HOT, HIGH) — **CLOSED 2026-05-10 (Option B)**

File: `packages/quantum/services/workflow_orchestrator.py:473-482`.
3 columns (`execution_cost_soft_gate`, `execution_cost_soft_penalty`,
`execution_cost_ev_ratio`) dropped via `DROPPABLE_SUGGESTION_COLUMNS`
retry shim on every suggestion write. Verified absent from
`trade_suggestions` schema.

**Decision needed:** are these signals load-bearing for execution
gates? If yes, add columns via migration. If no, remove the
computation and the shim entirely.

**[CLOSED 2026-05-10 by #62a sweep PR — Option B chosen]:** Saturday's
diagnostic verified the 3 fields had ZERO production readers. The
load-bearing mechanism (`unified_score.score -= EXECUTION_COST_SOFT_PENALTY`
in-memory + `HIGH_EXECUTION_COST` badge append) was preserved. PR
deleted the 3 candidate-dict producer assignments at
`options_scanner.py:3318-3322` + the 3 entries from
`DROPPABLE_SUGGESTION_COLUMNS` + the now-dead local variable
`execution_cost_soft_gate_triggered`. Test simulator + assertions
updated.

**Broader DROPPABLE shim doctrine concern** (Option C from the
diagnostic) captured separately in **#117** — the shim itself is
Anti-pattern 2 territory (silent column-strip + retry, `print()`
instead of `alert()`); ~6 other DROPPABLE entries deserve the same
audit-then-add-or-remove treatment.

#### #62a-D6 — `model_governance_states` table missing (MEDIUM) — **CLOSED 2026-05-10**

Migration `20251215000000_learned_nesting_v3.sql` partially applied
— ALTER statements landed but `CREATE TABLE model_governance_states`
did not. Learned Nesting v3 governance writes fail silently.

Fix: apply table-creation portion, OR delete the writes if Learned
Nesting v3 is dormant.

**[CLOSED 2026-05-10 by #62a sweep PR — backlog framing was inaccurate]:**
Saturday's diagnostic found ZERO code references in the entire
codebase — no writers, no readers, no imports, no "Learned Nesting"
string mentions. The "writes fail silently" framing was wrong; there
were NO writes at all. PR deleted the orphan migration file. Pure
build-by-contract residue from a feature spec that was never built
or was deleted.

#### #62a-D7 — `shadow_cohort_daily` table missing — **CLOSED 2026-05-05**

Resolved by removing the cohort shadow eval entirely (PR #<NUM>).
Earlier framing referenced `POLICY_LAB_AUTOPROMOTE=false` as the
gating env var, but verification revealed the consumer is actually
gated by `AUTOPROMOTE_ENABLED` at `public_tasks.py:1207` (separate
flag from `POLICY_LAB_AUTOPROMOTE` which gates a different
policy_lab evaluator). Both gates default off and neither has been
observed flipped on in production.

**Production-exercise verification (load-bearing):** zero `job_runs`
rows ever for `validation_cohort_eval` (the writer endpoint) AND
zero rows ever for `validation_autopromote_cohort` (the reader
endpoint). The whole shadow_cohort_daily channel was unexercised
dead code — the writer's silent no-op (table missing) had no
downstream consumer to even notice.

**Resolution shape — Branch B2 (delete entirely):**
- Removed both endpoints + their helpers from `public_tasks.py`
- Removed `ValidationCohortEvalPayload` + `ValidationAutopromoteCohortPayload`
  from `public_tasks_models.py`
- Removed dispatch entries from `scripts/run_signed_task.py` +
  `scripts/invoke-task.ps1`
- Removed two scheduled job blocks + manual-dispatch enum entries
  from `.github/workflows/trading_tasks.yml`
- Deleted dedicated test files; surgical removal of references in
  shared test files
- Service method `eval_paper_forward_checkpoint_shadow` PRESERVED
  (still used by `/validation/shadow-eval` which stays — intentional
  sync per audit)

Side benefit: closes Tier 3 (cohort-eval) and Tier 4 (autopromote-cohort)
of the #71 RQ dispatch sweep by removing rather than migrating those
endpoints. See #71 entry for sweep impact.

If autopromote reactivation is ever pursued, restoration requires
re-implementing the eval, the persistence (table + writer), and the
consumer logic together as a unified feature, not piece-by-piece.
See git history for the original endpoint shape (PR #<NUM>).

#### #62a-D8 — `trade_executions` 8 wrong columns (MEDIUM) — **CLOSED 2026-05-10**

File: `packages/quantum/services/execution_service.py:215-254`.
Writes `mid_price_at_submission`, `order_json`, `trace_id`,
`window`, `strategy`, `model_version`, `features_hash`, `regime`
— none in legacy `trade_executions` schema. Canonical execution
path is `paper_orders` + `position_legs`.

**Prerequisite:** trace whether `register_execution` is on any
active path. If dead → delete the legacy `ExecutionService`. If
alive → drop-cols-or-add-cols decision.

**[CLOSED 2026-05-10 by #62a sweep PR — fully dormant, deletion
chosen]:** Saturday's diagnostic verified the table has 0 rows
ever (latest_write timestamp NULL); `register_execution()` had
ZERO production callers (only tests); the readers
(`exit_stats_service.py`) handled the always-empty
`insufficient_history=True` path that both call sites already
defaulted to. PR deleted: `register_execution` + 5 helper methods
(`_record_to_position_ledger`, `_record_multi_leg_fills`,
`_record_single_leg_fill`, `_resolve_leg_action`,
`_extract_underlying`) + 4 module-level legs-fingerprint helpers
+ `get_batch_execution_drag_stats` + `get_execution_drag_stats`
+ `simulate_fill` + `exit_stats_service.py` + `self.executions_table`
init field + the scanner's batch-fetch call (always returned `{}`)
+ trade-builder + workflow-orchestrator caller sites (always took
the insufficient-history default). Drop-table migration shipped:
`20260510000000_drop_trade_executions.sql`.

**Migration applied 2026-05-10 20:08:01Z** via
`mcp__supabase__apply_migration` (audit:
`risk_alerts.id = 1553150d-353b-4729-ac2f-650a081f6009`,
`schema_migrations.version = 20260510200701` /
`name = drop_trade_executions`, commit `0acf897`). Verification
confirmed: table dropped + both inbound FK constraints
(`fk_suggestion_execution`, `fills_trade_execution_id_fkey`) gone +
both orphan columns (`suggestion_logs.trade_execution_id`,
`fills.trade_execution_id`) survived as nullable shells.

**Apply-time finding (worth noting for future audits):** the
migration comment had said "no inbound FKs" based on the original
diagnostic; pre-flight at apply time surfaced 2 inbound FKs from
`suggestion_logs` and `fills`. Both columns had ZERO populated rows
(suggestion_logs: 216 total / 0 with FK set; fills: 0 total) and
their only writer (`register_execution` via
`position_ledger_service._insert_fill`) was already deleted in the
same PR, so the CASCADE was operationally safe. The diagnostic's
inbound-FK check was incomplete — for future drop-table migrations,
run a `pg_constraint` query against `confrelid` rather than relying
on `information_schema.referential_constraints`. Captured this as a
diagnostic-methodology lesson.

**Orphan-column cleanup follow-up:** `suggestion_logs.trade_execution_id`
and `fills.trade_execution_id` survive as nullable shells. Neither
has any writer post-PR-#912 deletion. Worth a small follow-up PR to
drop the columns + remove `trade_execution_id` from `_insert_fill`'s
parameter signature (its docstring already notes it's historical).
Low priority; not load-bearing.

**PRESERVED:** `ExecutionService.estimate_execution_cost` (called
by `optimizer.py:543` — the only active caller) — refactored to
always use the heuristic spread proxy since the history branch's
data source was deleted.

`outcome_aggregator.py` reads of `trade_executions` (lines 111+127)
fold into separate **#67** cleanup; outcome_aggregator is itself
flagged dead in that entry.

#### #62a-D9 — `trade_suggestions` rebalance flow extra cols (LOW)

File: `packages/quantum/api.py:869-885,898`. Writes `symbol`,
`confidence_score`, `notes` — none in schema. Rebalance flow likely
unused; insert 400s if exercised.

Effort: ~1 hour (verify cold, then either fix or remove endpoint).

#### #62a-D10 — `outcomes_log` 5 cols (LOW) — TRACKED UNDER #67

5 cols (`status`, `reason_codes`, `counterfactual_pl_1d`,
`counterfactual_available`, `counterfactual_reason`) absent. Already
folded into the dead-code sweep via backlog #67.

#### #62a-D11 — `symbol_regime_snapshots` table missing (LOW) — **CLOSED 2026-05-10 via #62a-D3**

Created by migration `20251213000000_regime_snapshots.sql` (same as
D3) but no active write site found in code. Note only — no fix
needed unless a writer is reintroduced.

**[CLOSED 2026-05-10 via #62a-D3]:** the migration file defining
this table was deleted as part of D3's deletion sweep (same PR).
Zero writers existed; deletion confirms no future writer will
be reintroduced via this migration.

#### #62a-D12 — Out-of-band tables (LOW) — ACKNOWLEDGE, NO ACTION

7 tables exist in prod with no creator migration: `audit_logs`,
`profiles`, `portfolios`, `option_positions`, `weekly_trade_reports`,
`user_settings`, `plaid_items`. Pre-migration-tracking artifacts.
Don't rebuild migration history; just acknowledge.

### #62a audit method limitations

The audit catches static patterns: dict-literal upserts,
enum-constraint writes, migration-vs-prod schema diff. It does
NOT catch:

1. `**kwargs` / variadic dict expansion in writes.
2. Dicts built across functions (9 sites flagged opaque).
3. `SELECT *` reads on schema-drifted tables.
4. JSONB metadata field shape conventions.
5. Joins / RLS / FK referencing dropped columns.
6. Views drifting from base tables.
7. Migrations rolled back via dashboard.
8. **Migration intent vs runtime code disagreement** (the
   `'neutral'` vs `'aggressive'` issue under D1 was caught only
   by manual review of the migration file, not by any automated
   step).

Confidence: HIGH on 10 actionable findings, MEDIUM on completeness.
Future drift is expected; this audit method catches the bulk but
not all.

---

