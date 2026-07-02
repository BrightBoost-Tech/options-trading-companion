# Shadow-cohort fill-probability realism — recon + spec (gap-3, 2026-07-02)

STATUS: RECON + SPEC ONLY — no build this session (operator-directed). The
build touches champion promotion and gets its own session. Owner decision
needed on option (a) vs waiting for (b).

## Problem

Shadow cohorts (neutral/conservative) fill synthetically: every staged order
fills, at the modeled price, at the cohort's synthetic size. Live orders
demonstrably do neither. Their ledgers feed `policy_daily_scores` → utility →
**champion promotion/rollback** — a live-affecting decision — so the
divergence is not cosmetic. This is the codebase's one genuinely
"backtest-shaped" risk (the system deliberately has no backtester; forward
shadow fills are the analogue of the mid-fill inflation class).

## Recon (2026-07-02, DB-verified)

1. **Fill-probability gap**: of ~54 live-routed broker orders ever staged,
   **17 filled**, **10 died watchdog-cancelled unfilled** (idle 249–297s vs
   the 90s threshold — the NFLX 06-03 class), ~25 otherwise
   cancelled/rejected. Live fill rate ≈ one-third; shadow fill rate = 100%
   by construction. Roughly **1 in 5** live orders is the exact
   "posted, never filled, watchdog killed it" shape that shadows count as a
   position.
2. **Magnitude gap (size × fill)**: same-symbol, same-period twins — SOFI
   live −40 vs shadow −1,044.48 (26×); MARA live −15/−28 vs shadow −675.99
   (24–45×); QQQ live −73 vs shadow −234.78 (3.2×); NFLX live +48/−84/−114
   vs shadow +662.10/−546.00/−273.00 (5–14×). Driver is mostly SIZE
   (shadow synthetic capital sizes 5–17 lots vs live 1) compounded by
   always-fills.
3. **Price-basis residual**: only **3** shadow closes carry
   `fill_quality='executable'` (post-#1017); the other 19 shadow fills
   predate the stamp — most shadow history carries the optimistic-mid bias
   in addition to size/fill-probability distortion.
4. **Scale note**: cohort-era ledgers are thin (live n=6, −153 total;
   shadow n=9, −1,786.80 total). Any promotion decision today is
   data-starved regardless; the ungated single-champion fallback
   ("aggressive" in transition windows) is already ledgered-accepted.
5. **Join note for implementers**: there is NO same-suggestion twin — each
   cohort forks its own suggestion row. Twin pairing is (symbol,
   cycle_date) / fork lineage, not `suggestion_id`.

## Option (a) — interim promotion-time normalization (no fill modeling)

At `policy_lab` evaluation/promotion ONLY (never the ledgers themselves):

1. **Per-contract normalization**: score cohorts on per-contract (or
   per-$-risked) P&L instead of absolute P&L. Kills the dominant 5–17×
   size distortion outright with zero market modeling.
2. **Fill-confidence annotation**: stamp each shadow trade with the live
   fill base rate for its shape (currently ≈0.33 overall; refine by
   order type later) and surface a `modeled_fill_discount` on cohort
   scores; promotion compares discounted scores.
3. Flag-gated (`POLICY_LAB_NORMALIZED_SCORING_ENABLED`, tightening
   polarity default-ON is arguable — recommend explicit opt-in first
   session, flip to default-ON after one observed eval), read-side only:
   ledger rows unchanged (move-don't-lose).

**Effort**: one PR — scoring change in `policy_lab/evaluator.py` (+
`scoring.py`) + fixtures from the recon twins above. ~half a session.
**Risk**: low (read-side, flag-gated, no live path).
**Limitation**: doesn't model WHICH shadow trades wouldn't have filled —
a cohort whose edge lives entirely in unfillable prices still scores.

## Option (b) — post-and-wait synthetic fill model (the real fix)

Shadow staged orders become PENDING synthetic orders that fill only when
marketable on the EXECUTABLE side within the live watchdog window:

1. On stage: record limit + timestamp, state `pending_synthetic`.
2. Each monitor cycle (q15min, snapshots already fetched): fill iff the
   limit crosses the executable side (`compute_corroboration` /
   `executable_close_estimate` primitives — same basis as #1017/#1034/#1101,
   one price model everywhere). Partial-quote → hold (H9, never fabricate).
3. Unfilled past ~5min-equivalent (one cycle at monitor cadence — matches
   live watchdog ~90s+poll behavior as closely as the cadence allows):
   cancel synthetically, mirroring the live watchdog-cancel class.
4. Exits: same patient-then-cross shape on the close side.

**Effort**: 2–3 PRs (pending-order state machine + monitor integration +
close side + survival fixtures replaying the SOFI/NFLX twins). Own session,
recon-first on the fork/fill seams (`policy_lab/fork.py`,
`paper_shadow_executor` seam notes apply).
**Risk**: medium — touches the monitor cycle and cohort ledger semantics;
needs the #1040/#1038 add-to-position seam review noted in §8.
**Note**: cadence mismatch is honest-but-imperfect: q15min checks cannot
reproduce a 90s watchdog exactly; the model errs toward MORE fills than
live, i.e. still slightly optimistic — document, don't oversell.

## Recommendation

**Ship (a) before the next promotion evaluation; build (b) in its own
session, unhurried.** The recon shows the dominant distortion is size
(5–17×) — option (a).1 removes it for one PR of effort, and (a).2's flat
discount covers the fill-probability gap to first order (base rate ≈0.33 is
measured, not modeled). (b) remains the correct end state because it makes
shadow *selection* honest (which trades exist), not just their *weight* —
but at n=9 shadow closes, per-trade fill modeling changes little today
while (a) changes the comparison basis immediately and cheaply. Interim (a)
is worth shipping first.

Prerequisite check before (b): confirm `PAPER_SHADOW_EXECUTOR_ENABLED`
remains off / the paper-shadow migration pair remains gated — (b) is for the
EXISTING internal shadow cohorts, not the Phase-1b paper-shadow executor;
keep the two isolated.
