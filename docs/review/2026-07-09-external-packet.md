# External Review Packet — Options Trading Companion
**Assembled 2026-07-09 20:18Z (market close). Read-only runtime evidence for a reviewer with full code access but no DB/Railway/broker access.**

> Redaction: the live brokerage account is "the live account"; the operator UUID is "the owner"; cohorts are champion / neutral / conservative. Dollar P&L and equity are REAL and included by operator decision — the ~$2k scale is the story. No credentials, connection strings, keys, or webhook/ping URLs appear anywhere in this packet.

---

## §1 — EXECUTIVE BRIEF

**What this is.** A fully-automated options income system running on a **~$2,000 live margin account (options L3), in explicit "learning mode" (correctness > deployment)**. Pipeline: scan the universe → score EV/PoP → rank → **entry gates** (quote validation, utilization, round-trip cost) → per-cohort executor → 15-min intraday monitor (marks, envelopes, cohort stops, force-close) → post-close learning/calibration loop. It trades defined-risk structures — **iron condors and vertical debit spreads** — at 1–7 contracts. Three "cohorts" run the same signal: **champion** (live, real money) plus **neutral** and **conservative** (shadow, internal fills, no capital) for policy comparison.

**Where it stands today (broker-verified).**
- **9 real live closes all-time** (06-08 → 07-08), **1 win / 8 losses, −$262 cumulative**. Post-#1051-epoch (≥ 06-11): **8 closes, 1W/7L, −$178.** Current equity **$2,067.86**, flat today.
- Calibration **exited raw-mode this morning (07-09 10:00Z)** at the design **0.5 clamp floor** (the raw multiplier wanted lower on a 1W/7L pool; calibration error 65.34). *Caveat, found today: the 0.5 does not appear to be reaching the live scan EV — see §4.*
- The entry funnel is **correctly near-zero**: at ~$2k, per-contract executable round-trip cost (~$20–40) eats typical structure EVs (~$40), so almost nothing clears the $15 per-contract edge floor. **Zero entries today** was the gate working, not a failure.
- Trade cadence ≈ **1 live close/week**; every learning/promotion gate needs 10–15. This is the central tension.

**THE TWO QUESTIONS WE MOST WANT OUTSIDE EYES ON** *(operator may edit)*
1. **Trace why the calibration multiplier computes and stores but returns ×1.0 at application.** The 0.5 `_overall` multiplier is written to `calibration_adjustments` at 10:00Z, but the first calibrated live scan shows `ev == ev_raw == 39.71` (unchanged). Fresh eyes on the specific path: `calibration_service.get_calibration_adjustments` and the `_overall` fallback (`calibration_service.py:577`, the segment→strategy→`_overall`→1.0 chain) vs the `{strategy:{regime}}` return shape the insert path consumes (`workflow_orchestrator.py:1745-1755`). **Is the `_overall`-only blob failing to map into the return shape, so application silently falls to ×1.0?** (Evidence in §2d.)
2. **Structural viability:** given the code and this evidence, **is the per-contract cost floor a dead-end at this account size** — can a ~$2k defined-risk options book ever clear real executable costs often enough to learn — and **what would you change first** (account scale, structure class, universe, or the cost model)?

---

## §2 — RUNTIME TRUTH THE CODE CANNOT SHOW YOU

The code tells you what *can* happen. This section is what *did*.

### 2a — The live trade ledger (broker truth, real money)

All 9 filled closing round-trips on the live account, all-time. (The champion cohort's DB history also carries ~16 April–May closes — those were the **alpaca-paper phase before live routing** and are NOT real money; excluded here, noted in §2b.)

| # | Date | Underlying | Structure | Entry | Exit | Realized | Trigger | Note |
|---|------|-----------|-----------|-------|------|----------|---------|------|
| 1 | 06-08 | NFLX | put debit spread | 3.08 | 2.66 | **−$84** | reconciled | pre-epoch; missing from the learning table (§4) |
| 2 | 06-12 | SPY | iron condor | 1.48 | −1.96 | **−$45** | reconciled | |
| 3 | 06-12 | NFLX | put debit spread | 3.65 | 4.14 | **+$48** | reconciled | **the only win** |
| 4 | 06-12 | MARA | call debit spread | 1.18 | 1.11 | **−$28** | reconciled | |
| 5 | 06-15 | QQQ | iron condor | 1.61 | −2.34 | **−$73** | reconciled | worst loser |
| 6 | 06-17 | MARA | call debit spread | 1.21 | 1.14 | **−$15** | reconciled | |
| 7 | 06-30 | SOFI | call debit spread | 1.44 | 1.53 | **−$40** | reconciled | first autopilot round-trip |
| 8 | 07-07 | QQQ | iron condor | 1.49 | −1.74 | **−$15** | **force-close (stop)** | corroborated UPL −$49 vs raw mid −$25 (§2f) |
| 9 | 07-08 | QQQ | iron condor | 1.49 | −1.54 | **−$10** | **force-close (cohort stop)** | corroborated UPL **−$155** vs broker −$10 = 15.5× over-pessimism (§2f) |

**All-time: 9 closes, 1W/8L, −$262. Post-epoch: 8, 1W/7L, −$178, hit-rate 12.5%.** This is the entire real-money edge dataset. It is small and currently losing — which is precisely why raw-mode-until-8, the 0.5 clamp, and the observe-only accuracy alert exist.

### 2b — Live vs. simulated census (why the "trade history" is mostly fiction)

From the 07-08 diagnostic (counts, not P&L — shadow P&L is not comparable, see caveat):
- **REAL (broker-executed, live money): 9.**
- **SIMULATED: 74.** Of which:
  - **Shadow cohorts (neutral + conservative, internal fills): ~10 recent** — the promotion-comparison population.
  - **Legacy paper (pre-cohort / pre-honest-math era, all >30d old): ~60**, at ~**87% win rate** — the tell-tale of a simulation that never paid executable costs. **Quarantined / bricked**; do not treat as evidence.
  - Manual champion closes: ~4.
- **Fill-realism caveat (the load-bearing one):** shadow orders fill **~100% by construction** at **5–17× live size**; the live fill rate is **~1/3**. The measured **`SHADOW_FILL_DISCOUNT = 0.31`** means of ~10 shadow closes only ~3 would plausibly have filled live. Cross-cohort P&L comparison is **basis-broken** until per-contract promotion normalization is observable (shipped, but unobservable until a challenger reaches promotion Gate 4). **Treat shadow volume as mechanism evidence only, never edge evidence.**

### 2c — The funnel: why almost nothing trades

Universe recon verdict (07-03): of **78 active names**, **1 clears the round-trip cost floor** cleanly (SPY); the viable set is ≈9 (SPY, QQQ, IWM, DIA, SLV, GLD, TSLA, CVX, NFLX-provisional). The binding constraint is **per-contract executable cost (~$21–40) vs typical structure EV (~$40)** against a **$15 per-contract edge floor**.

**Today's full rejection mix** (07-09, ~1,000 rejections — all economics/structure classes, zero capital-state or error classes):

| Reason | Count | What it means |
|---|---:|---|
| `no_fallback_strategies_available` | 221 | no strategy template fit the chain |
| `spread_too_wide_real` | 208 | executable bid/ask too wide to price |
| `execution_cost_exceeds_ev` | 166 | the cost>EV screen (pre-gate) |
| `all_strategies_rejected` | 159 | every candidate template failed |
| `strategy_hold_no_candidates` | 91 | held, nothing viable |
| `iv_rank_insufficient_history` | 50 | the 06-17 universe adds still seasoning toward 60d IV history |
| `condor_no_viable` / `condor_ev_not_computed` | 11 / 10 | condor-specific |

Verbatim gate lines (format: `gross_ev / round_trip / net / decision`), spanning both calibration eras:
```
2026-07-02  SOFI  qty4  gross_ev=30.25 round_trip=88.00  net=-57.75  → reject   (pre-×0.5)
2026-07-08  QQQ   qty1  gross_ev=41.22 round_trip=39.00  net=+2.22   → reject   (pre-×0.5; correct — spread ate the edge)
2026-07-08  QQQ   qty7  gross_ev=42.14 round_trip=154.00 net=-111.86 → reject   (NEUTRAL shadow; the qty-scaling bug, §2e)
2026-07-09  SOFI  qty4  gross_ev=39.71 round_trip=48.00  net=-8.29   → reject   (post-boundary; EV NOT actually halved, §4)
```

### 2d — The calibration story

- **Design:** trains on **live outcomes only** (shadow/paper excluded — a prior incident let a shadow-driven ×1.5 boost reach live scoring). Below 8 live post-epoch closes → **raw mode (×1.0), do-no-harm**. A hard **epoch (2026-06-11)** walls off pre-fix sign-flipped predictions.
- **Exited raw-mode 07-09 10:00Z** at pool = 8. Stored multiplier: **`_overall {ev_multiplier: 0.5, pop_multiplier: 0.5}`, error 65.34** — both at the **0.5 clamp floor** (the raw fit wanted lower on 1W/7L; the clamp is anti-overfit protection at tiny N).
- **Consumes:** the live outcome table. **Feeds:** `apply_calibration` → scan EV/PoP → ranker `risk_adjusted_ev` → the round-trip gate's `gross_ev`.
- **⚠ HEADLINE FINDING (§1 question 1): the multiplier is STORED, not LIVE.** The champion's first calibrated scan (07-09 16:00Z, verbatim): **`ev = 39.71`, `ev_raw = 39.71`** — identical, so **×1.0 was applied, not the stored 0.5.** The insert path (`workflow_orchestrator.py:1745-1755`) stamps `ev_raw = s["ev"]` then overwrites `s["ev"] = apply_calibration(ev_raw, …)`; equal values prove the calibrated call returned its input unchanged. The `_overall` fallback is documented to close exactly this "silent ×1.0" hole (`calibration_service.py:577`), yet the stored blob is `_overall`-only and application still returned ×1.0 — the prime suspect is `get_calibration_adjustments` transforming an `_overall`-only blob into an empty/non-matching `{strategy:{regime}}` return. **Consequence:** "calibration is halving EV to protect a losing pool" is **not currently true**. No live harm today (the funnel rejected on cost regardless), but the protection is inert.

### 2e — The entry-gate qty-scaling bug + Option-A fix

**The bug (proven).** The round-trip gate compared `gross_ev` (per-structure, **unscaled**) against `round_trip` (qty-**scaled** by leg quantity). At qty>1 it compared a per-1-lot EV against a full-position cost. Corrected blast-radius table (the recon's central claim "the champion always sizes qty 1, so this is live-neutral" was **WRONG** — caught via the existing SOFI qty-5 test fixture + a historical query):

| Date | Cohort | qty | gross_ev | sized rt | **old net** | per-contract net | Old → New |
|------|--------|-----|----------|----------|-------------|------------------|-----------|
| 07-02 | champion | 4 | 30.25 | 88 | −57.75 | +8.25 | reject → reject (correct) |
| **07-07** | **champion** | **4** | **42.45** | **28** | **+14.45** | **+35.45** | **reject → PASS ⚠ real LIVE false-reject (missed by $0.55)** |
| 07-08 | champion | 1 | 41.22 | 39 | +2.22 | +2.22 | reject → reject (qty-1 invariant) |
| 06-30 | champion (fixture) | 5 | 30.63 | 135 | −104 | +3.63 | reject → reject (correct) |

The champion sizes **qty 4–5 on cheaper underlyings** (only expensive QQQ is qty 1). So the bug had already **cost one real live entry** (07-07). It also suppressed shadow entries and biased promotion.

**The fix (shipped `03e11d8`, PR #1141, Option A).** `executable_roundtrip_cost` now also returns a per-contract cost; the gate uses **per-structure EV − per-contract cost, floor $15 per-contract**. Cohort split: **shadows apply the fix; the live path stays on the legacy (buggy) decision (observe-only)** behind flag **`GATE_QTY_FIX_LIVE_ENABLED` (default OFF)**, logging `[GATE_QTY_SCALED_SHADOW]` whenever the fix *would* flip a live decision. **The qty-1 invariant is byte-identical (the existing test passes unmodified) — this PR changed ZERO live decisions.** Rationale: the fix opens *more* live trades at qty>1, so it deferred the loosening decision (Option B) behind a data-gathering window — on a currently-losing book, "correct" and "prudent" diverge, and that call is the operator's. *(Two implementation bugs found on the first live day — see §4.)*

### 2f — Exit-path live certification

The exit stack is the most-exercised part and the best-certified:
- **07-07 full-stack force-close** (real timeline): stop fired on **executable-corroborated UPL −$49** while the raw mid said **−$25** (the system trusts the executable side, not the mid); the resting take-profit was **pre-cancelled**, the close **submitted and filled in <1s**, and `[CLOSE_FILL_GAP]` recorded the slippage. Single-submitter discipline held.
- **Close-fill-gap dataset (3 honest points):** SOFI 0.23 · QQQ 1.42 · QQQ 0.96 (the latter two were sign-corrected — the first live credit close exposed an `abs()` bug that corrupted 15.08→1.42; fixed same night).
- **⚠ Phase-3 over-pessimism pattern (gated, NOT acted on):** the cohort stop fires on corroborated UPL that has been systematically worse than the realized fill — **3 instances, ratios 3.3× / 1.6× / 15.5×** (07-08: corroborated −$155 vs broker −$10). The open question when the Phase-3 reopen unlocks (≥10–15 fills): *is the cohort stop systematically over-pessimistic on defined-risk structures?* Deliberately un-acted — never loosen a stop on outcome.

### 2g — Key config / flags AS DEPLOYED (SHA `03e11d8`)

| Flag / constant | Value | Meaning |
|---|---|---|
| `MIN_EDGE_AFTER_COSTS` | **15** | per-contract $ edge floor after executable round-trip |
| `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` | ON (default) | the executable cost gate |
| `GATE_QTY_FIX_LIVE_ENABLED` | **OFF** (default) | qty-fix is observe-only on live (§2e) |
| `CONCURRENT_POSITION_ALARM_ENABLED` | ON (default) | one-beta tripwire (alarm ≥2 live positions) |
| `STREAK_BREAKER_N` | **3** | consecutive live losses → entries paused |
| `STREAK_BREAKER_EDGE_TRIGGER_ENABLED` | ON (default) | re-trip only when the loss-window CHANGES (content fingerprint), not every night |
| calibration clamp | **[0.5, 2.0]** on ev/pop multiplier | anti-overfit; currently at the 0.5 floor |
| active universe | **78** | scanner names |
| calibration mode | exited raw 07-09; multiplier 0.5 stored | but see §2d/§4 (returns ×1.0 at application) |

**Breaker edge-trigger semantics + tonight's status.** N=3 consecutive live losses pause entries; the window identity is a **content fingerprint (sorted trailing-3 outcome row ids)** stamped at trip time, so a *standing* already-reviewed window does NOT re-pause — only a NEW loss (a changed fingerprint) re-trips. The operator un-pause is the "review". **Tonight (07-09 21:20Z) is the first suppression test:** the book was flat today → the window is unchanged `[QQQ−10 / QQQ−15 / SOFI−40]` → the breaker should emit `suppressed_standing_window: true`, NOT re-pause, NOT alert (the final proof of the edge-trigger's distinctive behavior). *Status at packet time: pending (21:20Z).*

### 2h — Alert & signal integrity, proven live this week

The oversight layer was hardened and each hop proven against real events (relevant because a learning-mode system that can't trust its own signals can't be run unattended):
- **Delivery receipts live (4 proofs):** every allowlisted critical now stamps `egress_receipt {webhook_sent, egressed_at}` on its row — proven on the 07-07 & 07-08 force-close criticals and both breaker trips. "Did the safety email leave?" is now one query, not a forensic session.
- **Alert taxonomy split live:** the old single `force_close` type (which wore 3 different realities — real close / failed submit / warn-only) split into `force_close` / `force_close_failed` / `envelope_violation`; the untyped `warn` severity-outside-vocabulary rows are gone from new writers (13 historical ones remain, quarantined by move-don't-lose).
- **F8 loudness chain caught a real loss end-to-end:** a 07-08 connection burst lost **6 of 677** rejection-persist rows on the retry; the silent-failure detector surfaced `counts.errors=6`, wrote a `job_succeeded_with_errors` HIGH, and it reached the phone with a receipt — silent → loud, proven. (The residual writer hardening is filed, §4.)

---

## §3 — DECISIONS + RATIONALE (settled — please don't re-litigate)

**Raw-mode-until-8 live closes.** *Decision:* calibration returns ×1.0 until 8 live post-epoch closes. *Why:* fitting an EV/PoP multiplier on <8 outcomes overfits noise; do-no-harm until real volume. *Reopens if:* the raw-vs-calibrated boundary (crossed 07-09) shows the multiplier is unstable run-to-run.

**Hold the 0.5 clamp floor at N=8.** *Decision:* keep the floor even though the raw fit wants lower (error 65.34). *Why:* a binding floor at N=8 is the clamp doing its anti-overfit job on 1 win of data; the roundtrip gate is the backstop against the residual optimism. *Reopens if:* N grows and the floor still binds with a stable sign.

**Option A over Option B (gate fix observe-only on live).** *Decision:* fix shadows now, keep live decisions unchanged, gather `[GATE_QTY_SCALED_SHADOW]` evidence for 1–2 weeks. *Why:* the fix is a *proven-error* correction (07-07 was +35.45/ct economic), but it opens more live trades on a losing book — correctness and prudence diverge; the operator wants to see how many live entries it would open before flipping. *Reopens:* explicitly, after the observe window (and after the §4 bugs are fixed — the evidence is currently contaminated).

**Never loosen a control on outcome/hindsight.** *Decision:* a losing trade that passed every gate is not evidence a gate is wrong; a killed trade that would have won is one counterfactual data point, not a loosening argument. *Why:* the failure mode of a learning-mode system is rationalizing looser risk after losses. *Reopens:* only a *proven arithmetic error* (like §2e) justifies passing more trades — and even then, cautiously.

**SOFI is a permanent sentinel.** *Decision:* keep SOFI in the universe specifically because it never clears the round-trip gate. *Why:* if SOFI ever *clears*, something changed (spread regime, EV math, or a bug) — it's a live tripwire on the gate itself. *Reopens:* SOFI clearing is itself the finding to investigate.

**Legacy paper quarantined.** *Decision:* the ~60 pre-honest-math paper closes (87% win) are excluded from all learning. *Why:* they never paid executable costs — the win rate is fiction. *Reopens:* never; they're bricked by epoch + is_paper filters.

**Sequential attributable deltas + post-close-only merges.** *Decision:* one behavioral change per PR/recycle, merged only after market close (20:00Z), never fix-forward mid-session. *Why:* every merge recycles both workers and resets once-per-process state; batching changes makes a regression un-attributable, and a mid-session recycle orphans in-flight cycles. *Reopens:* only a sanctioned kill-switch flip (a fixed registry of explicit-falsy safety flags) may act intra-session; everything else waits for post-close. *(This is why #1141 today was built pre-market as observe-only and the operator, not the loop, chose the merge timing.)*

---

## §4 — KNOWN ISSUES & OPEN QUESTIONS (honest defect list — please rank these)

**Fresh today (07-09), both fail-safe, both need a fix:**
1. **Calibration 0.5 not reaching the scan.** Champion scan shows `ev == ev_raw == 39.71` → ×1.0 applied despite the stored 0.5 `_overall`. The "EV is halved on a losing pool" protection is **not currently active**. Root cause TBD (does `get_calibration_adjustments` fail to map an `_overall`-only blob into its `{strategy:{regime}}` return shape? staleness? segment lookup?). No live harm today (funnel rejected anyway) but the assumption is false.
2. **Option-A shadow detection missed.** The fix keys on `routing_mode == "paper_shadow"`, but shadows route as **`shadow_only`** — so shadows got `is_shadow=False` and the fix stayed inert on them, and the observe-log mislabeled shadows as `cohort=live`. Fail-safe (zero live change), but Option A's shadow-side didn't activate and the Option-B evidence is over-counted. One-line fix. **Note the interaction:** the observe-log "would-open" is computed on the *un-halved* EV (issue #1); with the intended 0.5 applied, several would flip back to reject — so **Option B must wait until both are fixed.**

**Standing (filed, tiered):**
3. **Multi-basis cost incoherence.** Three cost models float: scanner modeled (~$5.60), ranker per-structure, gate executable (~$39). Only the gate's qty-scaling flipped a decision (fixed §2e); the cosmetic unification is filed.
4. **Phase-3 over-pessimism** (§2f) — 3 instances, gated until ≥10–15 fills.
5. **Shadow fill realism (gap-3b)** — the post-and-wait fill model is unbuilt; promotion comparison stays basis-broken until then.
6. **Stuck-`running` job reaper** — absent; mid-run recycles orphan job rows.
7. **One-beta bucket control (B1/B2)** — the alarm shipped (tripwire), the actual per-bucket correlation cap is filed.
8. **Compounder greedy-stop** — first non-fitting candidate zeroes the cycle's selection (verified still live); a volume suppressor.
9. **Noise classes dominating H11.** Today's critical/high baseline is inflated by two known-filed false/low-value HIGH classes: **`ops_output_stale`** (a flat-book false-ager — the freshness check ages `paper_positions` when the book is legitimately flat; ~10 rows) and **`job_succeeded_with_errors`** (the #1104 persist-loss re-egressing hourly for one condition; ~10 rows). Plus a re-egress dedup gap (same condition alerts across both egress owners). Fixes are queued (a 3-in-1 observability PR). Not risk — but they poison the audit's own H11 read.
10. **The cadence problem** — ~1 live close/week vs 10–15 needed per learning/promotion gate. This is §1 question 2 in operational form: the system cannot accumulate evidence fast enough to learn at this scale.

---

## §5 — MAP FOR THE READER

**The 6–8 files that matter:**
- `packages/quantum/paper_endpoints.py` — `_apply_entry_roundtrip_gate` (the round-trip cost gate, §2e) + `_stage_order_internal` (the staging seam).
- `packages/quantum/analytics/exit_mark_corroboration.py` — `executable_roundtrip_cost` / `compute_corroboration` (the one executable-side model both entry and exit use; long→bid, short→ask).
- `packages/quantum/ev_calculator.py` — `expected_value = win_prob·max_gain − loss_prob·max_loss` (per-structure EV; the number everything downstream scales or fails to scale).
- `packages/quantum/services/workflow_orchestrator.py` — the scan→score→calibrate→insert path; `apply_calibration` call site (§2d, issue #1).
- `packages/quantum/analytics/calibration_service.py` — `apply_calibration` (segment→strategy→`_overall`→1.0 fallback) + the raw-mode/epoch/clamp logic.
- `packages/quantum/risk/streak_breaker.py` — the consecutive-loss breaker (content-fingerprint edge-trigger).
- `packages/quantum/jobs/handlers/intraday_risk_monitor.py` — the 15-min monitor: marks (fail-closed), envelopes, cohort stops, force-close, the one-beta tripwire.
- `packages/quantum/services/analytics/small_account_compounder.py` — sizing at the $1k/$5k tier cliffs (§4 greedy-stop).

**Glossary.** *Cohort/champion/shadow* = the live book + two paper policy twins. *Gates 1–4* = promotion checkpoints (challenger must reach ~10 trades to promote). *Phase-3* = the deferred exit-basis calibration (unlocks at 10–15 fills). *Epoch (06-11)* = the calibration wall separating pre-fix sign-flipped predictions. *H8* = "merged ≠ running" deploy verification; *H11* = the standing critical/high alert baseline check. *Raw mode* = calibration ×1.0 until 8 live closes.

**Timeline of major ships (PR # · date):** #1051 honest PoP + epoch (06-11) · #1058 realized-blind brake · #1076 live-only calibration (06-18) · #1097 entries-only halt · #1109 dead-man ping (07-02) · #1119 streak breaker (07-02) · #1132 OBP fail-closed + bias wired (07-06) · #1134 alert taxonomy + delivery receipt (07-07) · #1135 edge-trigger breaker (07-07) · #1137 close-fill-gap sign fix (07-08) · #1138 v5.4 audit prompt + dead-man ping wired (07-08) · #1139 one-beta tripwire (07-08) · **#1141 gate qty-scaling fix, Option A (07-09).**

---

## §6 — WHAT WE'RE NOT ASKING

- **Secrets handling** — DB password rotated 07-04, working tree swept, all paths API-key-class; not a review target.
- **Alert plumbing** — delivery is receipt-proven (webhook_sent stamped on the row); not a review target.
- **Historical paper data** — quarantined/bricked (§3); do not mine it for edge.

**Focus:** §1's question — the structural viability of a ~$2k defined-risk options book against real executable costs, and what to change first.
