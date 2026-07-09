# Capital Adequacy — design-assumption note (not a deposit recommendation)

**Origin: 2026-07-09 external-review §1 (Lane B / B1). This is a statement of
what the risk policy silently assumes about account size — a design
constraint, NOT advice to add capital.** The account runs in learning mode
(correctness > deployment); low trade frequency is a feature. Recorded so a
future session does not mistake the ~$2k book's near-zero fill rate for a
bug when it is arithmetic.

## The number: ~$7.5–8k for the risk policy to be honored on a 1-lot 4-leg

The live structures are **defined-risk 4-leg (iron condor) and 2-leg
(vertical debit) at 1–7 contracts**. A 4-leg structure is **indivisible below
1 lot** — you cannot buy half an iron condor. So the smallest position the
system can take carries the full 1-lot max-loss, and the per-trade risk cap
must be ≥ that max-loss or the cap is violated the moment ANY 4-leg trades.

Worked arithmetic (the binding case, a 5-wide index condor):
- 1-lot max-loss ≈ (wing width − net credit) × 100 ≈ (5.00 − 1.25) × 100 ≈
  **$375** per contract (QQQ/SPY-class 5-wide; the live book's typical shape).
- Policy: **5% max risk per trade.** For 5% × equity ≥ $375 → equity ≥
  **$7,500**.
- Policy: **20% aggregate deployed.** 20% × $7,500 = $1,500 ≈ **4 one-lots**,
  which is exactly the compounder's small-tier `max_trades = 4`. The two caps
  are mutually consistent only at ≈ $7.5–8k.

So **~$7.5–8k is the divisibility floor** at which a single 1-lot 4-leg trade
fits inside the 5%/20% envelope without breaching it. Below that, either the
per-trade cap is silently exceeded by one indivisible lot, or nothing sized to
the cap can trade at all.

## Why the code's `$5k` boundary and this `$7.5–8k` differ

`SmallAccountCompounder.get_tier` (`services/analytics/small_account_compounder.py`)
draws hard cliffs at **$1k (micro→small)** and **$5k (small→standard)**. The
$5k software boundary is where the tier LABEL changes; the ~$7.5–8k figure is
where the RISK MATH on an indivisible 4-leg lot actually closes. They answer
different questions — one is a config threshold, the other is a
structure-divisibility constraint — and they are not in conflict. Do not
"fix" the tier cliff to match this number; they mean different things.

## What this means at the current ~$2k scale (the real story)

At ~$2k the account is **structurally cost-bound, not policy-bound**: a 1-lot
condor's max-loss ($375) is ~18% of equity — far over the 5% cap — so the
allocator sizes to the cap and the executable per-contract round-trip cost
(~$20–40) then eats the typical ~$40 structure EV before the $15 per-contract
edge floor. The near-zero entry rate is the round-trip gate working as
designed (external packet §1/§2c), not a defect. See
[`docs/small_tier_allocation.md`](small_tier_allocation.md) and
[`docs/risk_math.md`](risk_math.md).

**Bottom line (design constraint, not advice):** the 5%/20% policy on
indivisible 1-lot 4-leg structures is coherent at ≈ **$7.5–8k** equity; the
~$2k learning-mode book is deliberately below that and is expected to trade
rarely. Whether to change **scale, structure class, universe, or the cost
model** is the operator's strategic call (external packet §1 Q2), out of scope
for this note.
