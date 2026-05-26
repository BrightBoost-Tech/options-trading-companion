# Structural findings — micro tier structure-class viability

This document captures the empirical work behind the "5 verified-fittable structure classes at $681 micro" summary in CLAUDE.md. Read this when reasoning about scanner emission patterns vs available BP, or when assessing tier-transition scope.

Two related notes are kept together here because the second refines the first. The prior note identifies the symptom; the refinement identifies the mechanism.

## 1. 2-leg debit spread geometry at micro BP (2026-05-14)

**Specific finding (well-supported by Path A + Option A experiments):**

At $681 micro BP, with H7 round-trip safety enforced, and with the scanner's current 2-leg debit spread emissions using $5-wide strikes on $50+ underlyings:

- Typical max_loss per contract: ~$500
- Round-trip cost (entry + 1.1× close safety): ~$1,020
- $1,020 > $681 BP → contracts=0 → REJECT at sizing layer
- Result: 2-leg debit spreads on $50+ underlyings cannot pass H7 at current capital

**This is mechanical math, not a tunable parameter.** The H7 check is load-bearing capital invariant (codified after the BAC 2026-05-01 ghost-position incident); the chain geometry comes from underlying market structure ($5-wide strikes are standard for $50–$200 stocks); the budget is the operator's current capital.

**What this DOES NOT imply (over-generalization warned against):**

The diagnostic synthesis initially generalized this finding to "no strategies fit at $681." Operator caught the over-generalization. The specific finding does NOT imply:

- That NO strategies fit at $681 (some may; not all tested)
- That capital scaling is the only path (strategy class change also changes the math)
- That the H7 check should be modified (it's working correctly)
- That spread-width should be changed across all tiers (yesterday's γ1 near-miss showed why)

**Specific NOT-evaluated cases that may still be viable at $681:**

- 2-leg credit spreads (max_loss = width − premium collected)
- Iron condors (4-leg credit structure with collected premium)
- 1-leg long options where premium is small (max_loss = premium paid)
- 2-leg debit spreads on sub-$30 underlyings with $1 or $2.50 strikes (max_loss reduced by chain granularity)
- Different delta-gap strategies producing narrower max_loss

**Diagnostic gate:** before claiming "strategy X doesn't fit," verify empirically with chain data + sizing math. Without that verification, "doesn't fit" is over-generalization (H12 instance from 2026-05-14 — see `docs/loud_error_doctrine.md` meta-observation).

**Operational implication:** Two strategic responses are possible:

1. **Capital scaling** — adds available BP, makes existing geometry work.
2. **Strategy class shift** — different geometry, may work at current BP.

Both may apply. See `docs/backlog.md` "Capital scaling framework" entry for open questions; α implementation (separate work) tests the strategy-class-shift hypothesis.

**Refinement of "perfect code" (learning-mode):**

The learning-mode codification stated: "At micro tier I want to perfect the code and make sure it enters and exits accordingly. After these are perfected I will add more capital."

The 2026-05-14 finding refines "perfect code" to include **structural fit between emission geometry and operational capital**. A scanner that produces emissions structurally incompatible with available BP at the intended capital level is not "perfected" — it has a structural mismatch.

The codification's discipline is preserved: code must be perfected before capital scales. The finding clarifies that "perfected" includes "structural fit between emission geometry and operational capital."

**Cross-references:**
- Path A experiment (2026-05-12) — empirical refutation of $100 cap (KO H7 trace)
- Option A experiment / PR #932 (2026-05-13) — Path A reverted
- Option A validation 2026-05-14 — empirical refutation of "pure $60 revert reliably produces creatable candidates"
- KO H7 trace 2026-05-13 (downstream gate identification)
- γ1 near-miss 2026-05-13 (wrong-line attribution — H12 instance 4)
- Scheduler-stuck mechanism attribution 2026-05-14 (H12 instance 5)
- Meta-observation 2026-05-14 (H12 applies to synthesis scope; this entry is the corrective)
- `docs/backlog.md` Capital scaling framework entry

## 2. Refinement — entry-premium-vs-width ratio (2026-05-14)

**Pairs with** the prior section. The prior section identifies the symptom; this section identifies the mechanism. Read together.

The prior section identified that current 2-leg debit spread emissions with $5-wide chains on $50+ underlyings exceed H7 round-trip safety at $681. The 2026-05-14 budget-fit diagnostic (empirical test of 22+ structures across 3 sample underlyings: HBAN $15.57, KHC $23.58, KO $80.72) identified the underlying mechanism:

**The H7-fit constraint is governed by entry-premium-vs-width ratio, NOT by width or leg count alone.**

Max_loss for any spread structure follows:
- Debit spread: `max_loss = (width × 100) − entry_premium_paid`
- Credit spread: `max_loss = (width × 100) − premium_collected`

H7 requires `max_loss × 2.1 ≤ available_BP`. At $681 BP, `max_loss ≤ ~$324/contract`.

**Empirical examples (2026-05-14 ~late-morning CT snapshot):**

| Underlying | Width | Structure | Entry/Credit | Max_loss | Fits at $681? |
|---|---|---|---|---|---|
| KO ($80) | $5 | debit ATM-OTM (77.5C/82.5C) | $301 paid | $199 | NO ($418 RT — matches the prior section's firing case) |
| KO ($80) | $2.50 | debit deep-ITM (77.5C/80C) | $175 paid | $75 | YES ($158 RT) |
| KO ($80) | $2.50 | debit ATM-OTM (82.5C/85C) | $65 paid | $185 | NO ($389 RT) |
| KO ($80) | $1 | credit OTM put (79P/78P) | $26 collected | $74 | YES ($155 RT) |
| KO ($80) | $1 | iron condor (78P/79P/82C/83C) | $46 net credit | $54/wing | YES ($113 RT) |
| KHC ($23) | $0.50 | debit ATM (23C/23.5C) | $24.50 paid | $25.50 | YES ($54 RT) |
| KHC ($23) | $1 IC | iron condor (21.5P/22.5P/24.5C/25.5C) | $21 net credit | $79/wing | YES ($166 RT) |
| HBAN ($15) | $1 | debit OTM (16C/17C) | $25 paid | $75 | YES ($158 RT) |

**Implications for scanner emission patterns (observation, not action):**

The scanner's `_select_legs_from_chain` uses delta-target leg selection, which naturally clusters legs ATM-to-OTM. At $50+ underlyings with $5-wide chains, ATM-OTM debit spreads produce the worst H7-fit region (low entry premium → high max_loss). This is exactly why the KO emission failed H7 in the prior section's example. (Note: the spread-width line at `options_scanner.py:1260` is iron-condor-only — see γ1 wrong-line attribution from 2026-05-13, H12 instance 4.)

For scanner emission to produce H7-fittable candidates at $50+ underlyings at micro capital, one of:
- **Different strategy class:** credit spreads collect premium, reducing max_loss
- **Strike-granularity awareness:** KO Jun 12 has $1 strikes, Jun 18 has $2.50 — varies by expiration cycle
- **Universe extending to sub-$30 names** with $0.50 or $1 chain granularity (KHC has $0.50 strikes)
- **Delta-target reaching deep-ITM:** high entry premium → low max_loss (counter-intuitive but mechanically correct)

## Verified-fittable structure classes at $681 (2026-05-14 snapshot)

- **Class A (1-leg long options at modest deltas):** widely fits (16/22 tested). Lower systematic edge; scanner doesn't currently target this surface.
- **Class B (sub-$30 narrow-strike debit spreads):** universally fits (8/8 tested). Robust across $0.50, $1, $2-wide.
- **Class C ($1-wide credit spreads):** fits broadly on both sub-$30 and $50+ names; thin per-contract credit ($9–$46) on $50+ names.
- **Class D (narrow-wing iron condors):** fits per-contract math on KO and KHC. Historically blocked by the `iv_rank` gate in `strategy_selector` until α implementation accumulated historical IV depth. α Phase 3 (2026-05-17, see `docs/alpha_iv_history.md`) makes the data computable for this class; **emission still requires regime conditions** (CHOP / NEUTRAL+high-IV / EARNINGS+high-IV) that have not held in recent cycles (empirical: 0 ICs in 90d at regime=NORMAL; 52 ICs in 90d at regime=CHOP). α was a necessary prerequisite, not a sufficient one — see the 2026-05-21 "data-vs-emission distinction" follow-up in `docs/alpha_iv_history.md`.
- **Class E (cash-secured puts / covered calls):** excluded — underlying capital reservation ($1,400+ even for HBAN) far exceeds $681 BP.

## Downstream-gate observation (2026-05-14 midday cycle)

The 2026-05-14 16:00 UTC `suggestions_open` cycle produced a Ford F `LONG_CALL_DEBIT_SPREAD` candidate (Class B territory, sub-$15 underlying). The candidate passed scanner-internal gates → H7 round-trip safety → universe filter → reached `trade_suggestions` table → blocked at `edge_below_minimum` (EV 15.44 below threshold). Final status: `NOT_EXECUTABLE`.

This refines the budget-fit landscape: **Class B fits H7 but a separate downstream gate (`edge_below_minimum`) catches sub-$30 narrow-strike candidates with thin expected value.** H7 fit is necessary but not sufficient for creatable suggestions.

For an empirical candidate to reach `status=EXECUTABLE`, it must clear: universe filter → scanner emission gates → H7 round-trip safety → `edge_below_minimum` → any further downstream gates not yet observed. For Class B candidates specifically, the binding constraint has shifted from H7 to `edge_below_minimum`.

## What this work refines and what it preserves

Refines: the constraint isn't "width" or "leg count" — it's entry-premium-vs-width ratio. Multiple structure classes fit at $681 with different geometry choices. α is more load-bearing than "observability fill" — it unlocks a verified-fittable structure class. And: H7 fit is not sufficient — `edge_below_minimum` is the next-most-load-bearing downstream gate for Class B.

Preserves: the prior section's specific finding remains accurate (current 2-leg debit spread emissions with $5-wide chains on $50+ underlyings DO fail H7 — that's the symptom). The mechanism explanation doesn't invalidate that symptom observation; it identifies why.

## Sample-size caveats

3 underlyings tested. Bid-ask spreads run 20–100%+ on OTM wings of sub-$30 names. KO IV at 0.17–0.21 is historically low — a vol spike would shift Class C/D credit collected meaningfully and could re-shape the landscape. Findings phrased as "fits today on names tested at current IV," not "always fits."

## Freshness caveat — empirical examples drift

**Added 2026-05-21, PR \<fix/h7-prefilter-and-khc-composition\>.** The worked examples in §2 ("Empirical examples (2026-05-14 ~late-morning CT snapshot)") cite underlying prices that may not hold against current market state. Two empirical examples relevant to today's universe addition were re-verified pre-composition:

| Symbol | 2026-05-14 price (cited above) | 2026-05-21 price (live chain) | Drift | Class re-classification |
|---|---|---|---|---|
| HBAN | $15.57 | ~$38 (inferred from chain) | +144% in 7 days | No longer a clean Class B ($1-wide narrow-strike debit). At $38 with $5-wide chain and wide bid-ask, would be borderline H7-fit and at risk of scanner spread_too_wide rejection. Deferred from PR; revisit on a refreshed structural assessment. |
| KHC | $23.58 | ~$23.85 (delta-interp) | +1% | Still a clean Class B fit. $0.50 strike increments, Alpaca IV/greeks populated, ATM bid-ask 22-37%. Added to scanner_universe by this PR. |

**Why this matters:** the doc treats the §2 worked examples as a static reference for "what trades at micro/small tier." Future readers (human or AI session) reading "HBAN at $15.57 is a Class B fit" and acting on it without re-verification would push a structurally-unfit symbol into production. The fix is doctrinal, not mechanical: **cite-then-verify**. See `docs/loud_error_doctrine.md` H14 "Reference-document freshness" entry for the generalized doctrine; the entry there is what this section is the application of.

### Verified-current additions (2026-05-21 follow-on composition pass)

After PR #976 added KHC alone (insufficient candidate variance for tomorrow's cycle), a follow-on composition pass verified 4 additional sub-$30 underlyings against current Alpaca chain data per H14 cite-then-verify. **All values verified live, NOT from documentation.**

| Symbol | Spot (2026-05-21) | ATM bid-ask % | IV (ATM) | Strike granularity | Sector | Notes |
|---|---|---|---|---|---|---|
| **SNAP** | ~$6.00 | 3.7% | 0.62 | $0.50 | Social media | High option volume (~1826 ATM daily); excellent liquidity for a sub-$10 name |
| **RIVN** | ~$13.50 | 3.3% | 0.92 | $0.50 | EV (US) | Very high IV but tight ATM bid-ask; greeks populated |
| **NIO** | ~$5.50 | 11.4% | 0.65 | $0.50 | EV (China) | Highest sub-$10 option volume in sample (5751 ATM daily); China-correlated |
| **MARA** | ~$13.50 | 5.9% | 0.87 | $0.50 | Crypto mining | Crypto-correlated; high IV; clean chain |

These four are NOT in `underlying_iv_points` (missed α Phase 3 backfill). Debit spreads emit with `iv_rank=50` fallback. IV-sensitive strategies (credit, IC) won't decide cleanly until either backfill is run for them or 60d of `iv_daily_refresh` accumulates naturally.

**Rejected candidates from the same pass** (each with a verification-based reason — not "didn't try"):

| Symbol | Reason rejected |
|---|---|
| HOOD | Spot ~$76 (inferred from $40C deep-ITM). Too high for small-tier H7. |
| PLTR | Spot ~$137 (inferred). Far too high. |
| PINS | Spot ~$18-19, but ATM bid-ask 11-32% across visible strikes. Borderline; deferred. |
| WBA | Chain stale — all quotes timestamped 2025-08 (corporate action / delisting). Excluded. |
| HBAN | Per PR #976 pre-flight: drift from docs $15.57 to ~$38. Same rationale applies here. |

This table demonstrates the H14 doctrine in practice: each candidate was checked against live chain data; the "obvious" choices (HOOD, PLTR, HBAN) failed verification despite documentation/intuition supporting them.

## Re-verification mechanism (proposed, not implemented)

The HBAN drift surfaced today is going to recur — equity prices move; option chain liquidity shifts; corporate actions reshape underlyings. The doc captures snapshots at named dates; nothing surfaces when a snapshot goes stale.

Proposed mechanism (operator decides on shape; tracked separately):

- **Monthly re-verification pass.** Read each cited example in this doc; query current price + ATM chain bid-ask via Alpaca MCP; verify the structural class still holds. Update the table with current values; mark drifted entries explicitly ("stale — current price $X; was $Y at YYYY-MM-DD").
- **Either:**
  - **Runbook entry:** a manual checklist invoked monthly (or quarterly) by the operator.
  - **Scheduled job:** a low-frequency cron that re-verifies, writes findings to `risk_alerts` at severity=info with `alert_type='structural_finding_freshness_check'`. Operator audits results, updates doc.
- **Drift threshold for action:** >15% price move OR ATM-bid-ask change crossing the 10%-of-mid threshold OR strike granularity change. Any single trigger flags the example as stale.
- **Cost is small:** ~5-10 minutes per month manual; ~$0 if a scheduled job (uses existing Alpaca MCP quota).

Without this mechanism, the next session that reads §2 and acts on a stale example will repeat today's surprise. The PR that introduces the mechanism should reference H14 and this section.

## EV-vs-H7 trade-off at small-tier capital

**Added 2026-05-26.** Empirical work 2026-05-22 through 2026-05-26 (three diagnostics + two cycles). This section names the structural constraint that bounds trade frequency at small-tier OBP and closes the structural arc of PRs #970/#972/#973/#974/#975/#976/#977/#978.

### The constraint

At small-tier OBP ($1,031.48 as of the 2026-05-22 observation baseline), the candidate-generation pipeline produces candidates that fail one of two gates with no candidate shape passing both:

- **High-priced underlyings** (MSFT/COST/NVDA/GOOGL/AAPL class): produce sufficient gross EV ($333 average in normal regime; $574-$683 average in elevated/rebound regimes) but **fail H7 round-trip safety** because max_loss ($1,300-$2,400/contract) exceeds the H7-fittable ceiling of ~$491/contract at $1,031 OBP.
- **Sub-$30 underlyings** (AAL/F/KHC/SNAP/RIVN/NIO/MARA class): **pass H7** comfortably (max_loss $25-$150/contract) but produce **insufficient gross EV** ($13-$15 typical) that fails `canonical_ranker.MIN_EDGE_AFTER_COSTS=$15` after slippage and fee subtraction.

There is no candidate shape that simultaneously passes H7 and produces sufficient EV at $1,031 OBP. This is **mechanical capital-vs-position-size arithmetic**, not a code problem: fixed costs (fees, per-contract slippage) amortize over expected return. At small position sizes (1-2 contracts of ~$76 entry), fixed costs are a meaningful fraction of expected return and the canonical_ranker correctly classifies the trade as economically marginal.

### Empirical evidence (three diagnostics, week of 2026-05-19)

| Date | Diagnostic | Empirical finding |
|---|---|---|
| 2026-05-22 | EV threshold diagnostic | AAL gross EV $13.17; formula slippage $0.66 (5%-of-EV floor); realistic combo bid-ask slippage ~$20 for 2 contracts on the actual chain. Net edge **−$9.43 realistic** vs $9.91 formula. Threshold $15 correctly protects capital. Same pattern on 2026-05-14 Ford (EV $15.44) and 2026-05-19 Ford (EV $13.29) — systemic, not anomalous. |
| 2026-05-22 | Comparative diagnostic (A/B/C paths) | Three workstreams (OTM strikes, regime classifier tuning, new strategy classes) evaluated against AAL chain data. **None produces decisive EV uplift at $1,031 OBP.** Path A marginally defensible (1-2 emissions/month best case; PoP miscalibration risk). Paths B and C structurally dominated. |
| 2026-05-26 | Cycle observation | 1 raw opportunity emitted (vs 9 on 5/22). Sub-$30 universe members died at scanner-level gates with chain quality 64-69% bid-ask spread (vs 10-37% on 5/22). AAPL emerged from the high-priced cohort, correctly rejected by H7 at sizing. Confirms intermittent-emission pattern: sub-$30 candidates emit only when chain quality aligns; high-priced candidates emit reliably but never fit H7. |

**Pattern across cycles:** the "low frequency" outcome is the **steady state**, not anomaly. The pipeline is structurally healthy through `canonical_ranker`; the economic gate is correctly enforcing capital safety.

### Historical EV-by-strategy distribution (90d, supporting evidence)

| Strategy | Regime | n | avg EV | avg max_loss |
|---|---|---|---|---|
| LONG_CALL_DEBIT_SPREAD | normal | 40 | **$333** | $1,329 |
| LONG_PUT_DEBIT_SPREAD | normal | 29 | **$381** | $1,700 |
| LONG_PUT_DEBIT_SPREAD | elevated | 13 | $575 | $1,630 |
| IRON_CONDOR | chop | 69 | $70 | $1,010 |
| IRON_CONDOR | elevated | 9 | $49 | $1,254 |

The 90d averages are dominated by high-priced underlyings (avg max_loss $1,000-$2,400). The three sub-$30 emissions reaching `canonical_ranker` in this window (Ford 5-14 EV $15.44, Ford 5-19 EV $13.29, AAL 5-22 EV $13.17) are the LOW outliers of those distributions — empirically confirming that EV distribution is bimodal by underlying price tier.

### Three operational paths (operator decision)

**Path 1: Accept low frequency at small tier.** The pipeline is structurally correct. The economic gate is correctly protecting capital. Low frequency at $1,031 OBP is the system working as designed for the 2026-05-12 learning-mode framework. The marginal trades being filtered out are noise the system correctly rejects, not opportunities being missed.

**Path 2: Capital scaling to standard tier ($5k+).** At standard tier the same gross-EV trade becomes economically viable through size. A $13 gross EV trade at 13 contracts produces ~$170 expected return against ~$20 in fixed costs — easily clears threshold. The candidate distribution from high-priced underlyings maps cleanly onto $5k+ capital (those candidates produce avg EV $333 and have max_loss $1,300-$2,400 which fits standard-tier H7 capacity). Deferred per CLAUDE.md 2026-05-12 codification until operator signals readiness.

**Path 3: Wait for market regime change.** CHOP regime (historically 21-day windows; last 2026-02-24 to 2026-03-17, 66+ days ago) unlocks the iron condor pool — 69 ICs at avg EV $70 emerged during the prior CHOP window. Elevated IV in NORMAL regime produces wider credit spreads with thicker premium. Different regimes produce different candidate distributions; the current sustained normal regime is the worst-case for trade frequency.

### What does NOT resolve this constraint

Six code-side levers have been considered and rejected as ineffective or counter-productive at small tier:

1. **Lowering `MIN_EDGE_AFTER_COSTS`.** Admits trades with negative realistic expected return (realistic slippage on sub-$30 chains is ~$20 for 2 contracts; the threshold-after-formula already understates costs). Opposite of capital protection.
2. **Tightening the slippage formula** to use `combo_spread_share` instead of the 5%-of-EV floor. Would reject MORE trades, not fewer — formula's $0.66 underestimates realistic ~$20 by ~30×. Not operator-aligned (won't unlock execution).
3. **Adding more sub-$30 tickers.** Produces more correctly-rejected candidates of the same EV profile. PR #977 already added SNAP/RIVN/NIO/MARA; today's cycles confirm they're emitting the same $13-$15 EV shape when they emit at all.
4. **Raising allocator per-candidate budget.** Slippage and fees scale linearly with contracts; ratios stay the same. More contracts ≠ better EV-per-cost.
5. **Adding new strategy classes** (single-leg longs, CSPs). Single-leg longs have worse EV profile (full premium exposed to theta; no offsetting short leg). Cash-secured puts are capital-excluded at small tier ($1,300 collateral on AAL > $1,031 OBP). Verified against AAL chain in 2026-05-22 comparative diagnostic.
6. **Regime classifier tuning** to surface NEUTRAL/CHOP more often. Sub-$30 underlyings have $0.50 strike granularity too narrow for IC wing economics (estimated AAL IC EV ~−$2 to +$6); higher-priced candidates that DO produce viable IC EV ($70 avg) fail H7 at $1,031 OBP. Path fails on both ends.

### What this finding refines

The 2026-05-14 entry stated (paraphrased) that the H7 fit constraint at micro BP is governed by entry-premium-vs-width ratio. That mechanism remains correct. This entry adds the second-order observation:

> **At small tier, even structures that PASS H7 (sub-$30 narrow-strike debit spreads — Class B per §"Verified-fittable structure classes") often fail the next downstream gate (`edge_below_minimum`) because the gross EV produced by those structures is mechanically too small for the fixed-cost stack.**

H7 fit is necessary; EV sufficiency after costs is the next-most-load-bearing gate. The 2026-05-14 Ford observation (entry 109-115 above) was the first surface of this; the 2026-05-22 / 2026-05-26 work codifies it as a named structural constraint rather than a per-cycle observation.

### Cross-references (this section)

- 2026-05-22 16:00 UTC cycle (AAL emission, `job_runs.id` for that cycle)
- 2026-05-22 17:29 UTC cycle (post-PR-#974 worker image; same H7 4-of-4 pattern)
- 2026-05-26 16:00 UTC cycle (AAPL emission; 1 raw opportunity vs Friday's 9; sub-$30 dropped at scanner-level due to wider chain quality)
- 2026-05-22 EV threshold diagnostic (canonical_ranker math + formula calibration; conversation transcript)
- 2026-05-22 comparative diagnostic (Paths A/B/C empirical evaluation)
- 2026-05-26 codification diagnostic (this section)
- PRs that built the pipeline through `canonical_ranker`: #970 (universe selection log), #972 (early-exit symmetry), #973 (allocator wiring), #974 (chain mechanics defensive observability), #975 (credit-spread formula), #976 (H7 pre-check + KHC), #977 (SNAP/RIVN/NIO/MARA composition), #978 (operational velocity doctrine)
- `docs/loud_error_doctrine.md` H14 (cite-then-verify) — the doctrinal pattern that captured the HBAN drift during PR #976 pre-flight; complementary to the structural constraint here

### H7_PREFILTER_ENABLED operational note

PR #976 shipped the H7 allocator-aware pre-check in shadow mode (`H7_PREFILTER_ENABLED=false` default). Multi-cycle shadow validation across 2026-05-22 and 2026-05-26 cycles confirmed pre-check decisions match real-H7 outcomes: 4 H7-incompatible high-priced candidates flagged with zero false positives. **The env flag is ready for active flip at operator discretion** (`H7_PREFILTER_ENABLED=true` on the worker service). Flag flip is a Railway env change, not a code change; it changes the `exit_reason` from `no_suggestions_after_gates` to `all_candidates_h7_unfit` on cycles where the pre-check filters all candidates, providing cleaner observability without changing the trade-execution outcome (which is already correctly 0 under both modes given the EV-vs-H7 trade-off codified above).

## Cross-references

- PR #934 (the prior narrow-scope structural finding; the refinement pairs with it)
- 2026-05-14 budget-fit diagnostic (empirical evidence base — see `docs/backlog.md` 2026-05-14 entry)
- Capital scaling framework (`docs/backlog.md` 2026-05-14 framework entry — informs Q1 trigger)
- PR #935 (α historical IV backfill — makes Class D data computable; emission still regime-gated; full history at `docs/alpha_iv_history.md`)
- PR \<this PR\> 2026-05-21 (credit spread chain-mechanics formula fix — Class C credit spreads were silently blocked by `combo_spread / entry_cost` sentinel; switched denominator to `max_loss_share` for credit spreads. 0 credit spreads in 90d before this fix.)
- 2026-05-14 cycle-shape diagnostic (Ford F downstream-gate observation — see backlog refinement sub-section)
- H12 framing-artifact doctrine (`docs/loud_error_doctrine.md`) — the "no strategies fit" over-generalization (instance #5) is what this empirical work corrects; the cycle-shape misread (instance #6) is what surfaced the Ford F observation
