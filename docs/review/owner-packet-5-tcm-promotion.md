# Owner Packet 5 — TCM v2 promotion threshold (N)

**Decision:** pick the realized-evidence threshold **N** that must clear before
`ENABLE_LIVE_TCM_MODEL` may be flipped, promoting the routing-aware commission
(broker-routed options = $0) into the decision path. **This packet executes
nothing** — the dual-run is observe-only (PR #1273/#1278 merged), the frozen
`TransactionCostModel` keeps sole authority, `ENABLE_LIVE_TCM_MODEL` stays
`false`. Per `docs/specs/tcm_v2_promotion_packet.md` §5, the owner picks N — an
agent must not.

**Recommendation:** the **conservative** threshold —
**15 broker-routed realized entries, spanning ≥2 strategies, with ≥1 qty>1
present, and the $0-commission premise unbroken.** Rationale below; the minimal
(10) variant is offered with its own conditions.

---

## 1. What promotion changes (and what it does not)

Promotion means the ranker / gate / sizing read the **proposed** commission
instead of the frozen fee for broker-routed candidates — chiefly the entry
round-trip cost gate (`ENTRY_ROUNDTRIP_COST_GATE_ENABLED`, #1101) and the
ranker's cost basis stop charging ~$1–2/round-trip of phantom commission on
live-routed options (`tcm_v2_promotion_packet.md` §4). Only **commission**
changes; **slippage/spread are carried from the frozen model UNCHANGED** (H9 —
only commission is evidenced). This is a behavioral / loosening change → gated
`ENABLE_LIVE_TCM_MODEL=1` explicit opt-in, absent/empty → frozen (fail-safe).

## 2. Evidence so far (PR #1273, read-only 2026-07-18)

- On **all 42** broker-routed FILLED options orders,
  `paper_orders.fees_usd == 0`, and it never equals `tcm.fees_usd` (0/42) —
  zero-commission options; the frozen model over-charges.
- `entry_realized_commission_vs_tcm_estimate` mean **−1.55 USD** (frozen model
  over-charges commission).
- Internal/shadow fills: realized commission typed UNAVAILABLE, never
  fabricated (76/120 internal + 12/12 shadow carry the estimate).
- **Caveat:** evidence is a **42-fill snapshot at one date**; the premise
  ($0 broker options commission) must keep holding as volume grows
  (`tcm_v2_promotion_packet.md` §7).

## 3. The two thresholds

### Recommended — conservative: N = 15

Promote only when **all** hold:

| condition | value | why |
|---|---|---|
| broker-routed realized entries with known commission | **≥ 15** | top of the Phase-3 ≥10–15 fills band (the operator's trusted "enough closes" gate); a comfortable margin over the current 42-fill snapshot's tail so the $0 premise is re-confirmed on fresh fills, not only the studied batch |
| strategy mix | **≥ 2 distinct strategies** (e.g. debit_vertical + iron_condor) | commission is per-contract; a single-strategy sample could hide a per-leg fee that only appears on a different structure |
| quantity coverage | **≥ 1 fill with qty > 1** | confirms the $0 holds when the per-contract roll-up scales — the over-charge the model makes is qty-scaled (`max(qty·0.65, min_fee)`) |
| premise intact | **0 broker-routed options fills with non-zero `fees_usd`** | a single non-zero fee breaks the $0 premise → reject promotion, re-open the study (`tcm_v2_promotion_packet.md` §5 check 2) |
| decision-impact dry-run | rank/gate deltas reviewed | confirm the admitted-candidate / re-rank change is what the owner intends (§5 check 3) |

- **Acceptable bias:** with slippage/spread frozen, the only promoted change is
  removing a known phantom commission — a measurement correction in the safe
  direction (never understates a cost). Residual bias is the stage-time routing
  **prediction** (`routing_mode==live_eligible` proxy); the realized join at
  close is the authority (`tcm_v2_promotion_packet.md` §7). Unknown routing
  falls to synthetic (fail-safe).
- **Rollback:** unset `ENABLE_LIVE_TCM_MODEL` on both workers → frozen fee in
  every decision, instantly; revert the promotion PR if warranted. The dual-run
  sibling key is inert additive jsonb — no data cleanup (§6).
- **No-promotion condition:** if by N the mix or qty coverage is not met, do
  NOT promote on count alone — keep observing.

### Alternative — minimal: N = 10

Same conditions, `N ≥ 10` (the promotion Gate-2 / #1051 8-close neighborhood).
Reaches a decision faster; the joint realized set is thinner, so the strategy-
mix and qty>1 conditions become **more** load-bearing (they are the only guard
against a small-sample fluke). Acceptable if the owner wants to promote sooner
and accepts a noisier confirmation of the $0 premise.

## 4. Grounding note

N counts **realized broker-routed entries with known commission**, joined at
close via `tcm_v2_proposal.realized_commission_when_available` (execution_mode
in {alpaca_paper, alpaca_live} AND an `alpaca_order_id` AND
`broker_status='filled'`, `tcm_v2_promotion_packet.md` §3) — not shadow, not
internal (those are typed UNAVAILABLE). The current live realized pool is
small (the challenger study counted 8 broker-live closes all-time,
`challenger-study-2026-07-18.md` §2), so either threshold implies accruing
more live fills before promotion is on the table — consistent with
learning-mode.

---

## APPROVAL TOKEN

> **`TCM_V2_PROMOTION_N=15`** (conservative) — sets the promotion gate to 15
> broker-routed realized entries across ≥2 strategies with ≥1 qty>1 and the
> $0-commission premise unbroken (0 non-zero `fees_usd`) + a reviewed
> decision-impact dry-run, before `ENABLE_LIVE_TCM_MODEL=1` may be issued.
> *(Alternative: `TCM_V2_PROMOTION_N=10` minimal, same conditions.)* Choosing N
> does not promote — flipping `ENABLE_LIVE_TCM_MODEL` remains a separate
> operator step after the gate clears.
