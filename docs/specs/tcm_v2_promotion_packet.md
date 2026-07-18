# TCM v2 — Routing-Aware Cost Model — Promotion Packet (owner decision)

**Status:** OBSERVE-ONLY dual-run shipped (Lane F). NOT promoted. The frozen
`execution.transaction_cost_model.TransactionCostModel` remains the sole
selector / ranker / gate / executor cost authority. `ENABLE_LIVE_TCM_MODEL`
stays **false** and is read by NO decision path.

This packet exists so the owner — not the loop, not an agent — decides whether
and when the proposed routing-aware commission replaces the frozen fee model in
any decision. It records the evidence so far, exactly what promotion would
change, the gate that must clear first, and the rollback.

---

## 1. What the dual-run is

At the single persisted TCM stamp site (`paper_endpoints._stage_order_internal`,
where the frozen `TransactionCostModel.estimate(...)` output is written into
`paper_orders.tcm`), we ALSO compute a proposed routing-aware model and stamp it
as a **jsonb-additive sibling key** `tcm.tcm_v2_proposal` — the same pattern the
existing `tcm.marketable_entry` sibling uses. Every frozen-model key
(`fees_usd`, `expected_spread_cost_usd`, `expected_slippage_usd`,
`fill_probability`, `expected_fill_price`, `tcm_version`, `missing_quote`,
`used_fallback`) is left **byte-identical** — the route-level test
`test_tcm_v2_dual_run_route.py::TestByteIdentity` pins it by asserting the
persisted `tcm` minus the sibling equals a fresh `estimate()`.

The proposal module is `packages/quantum/services/tcm_v2_proposal.py` (version
tag `tcm_v2_proposal/0.1.0`). It is pure, imports nothing from
scanner/ranker/gate/executor, and never raises on a partial input.

## 2. The one evidenced change: commission by routing

Only **commission** changes; slippage/spread are carried from the frozen model
UNCHANGED (only commission is evidenced today).

| Routing shape | Commission | Source label | Basis |
|---|---|---|---|
| broker (alpaca_paper/alpaca_live + `live_eligible` portfolio) | **$0.00** | `broker_zero_commission_options` | broker truth |
| internal (`internal_paper`) | frozen synthetic fee (`max(qty·0.65, min_fee)`) | `synthetic_estimate` | model estimate |
| shadow (`shadow_only`) | frozen synthetic fee | `synthetic_estimate` | model estimate |

Routing is classified at stage time from `execution_mode` + the portfolio's
`routing_mode` (mirrors `execution_router.should_submit_to_broker`'s
`live_eligible` gate, no extra DB call), independent of `submit_to_broker`
(single-submitter ownership) and `dry_run` (a WHEN, not WHERE, toggle). Unknown
routing values fall to `internal` (synthetic) — the fail-safe direction for a
cost proposal (never understate a cost by calling an unknown route broker-$0).

### Evidence (realized-cost study, consumer #3, PR #1273 merged)

- Verified read-only **2026-07-18**: on **all 42** broker-routed FILLED options
  orders `paper_orders.fees_usd == 0`, and it NEVER equals `tcm.fees_usd`
  (0/42). Zero-commission options; the reconciler stamps no separate
  regulatory/exchange fee (`fees_usd` is the whole roll-up = $0).
- `entry_realized_commission_vs_tcm_estimate` mean **−1.55 USD** — the frozen
  model over-charges commission for the zero-fee options routing.
- Internal / shadow fills carry an estimate-or-ambiguous `fees_usd` (equals
  `tcm.fees_usd` on 76/120 internal_paper + 12/12 shadow_blocked) — realized
  commission there is typed UNAVAILABLE, never fabricated.
- CLAUDE.md §5 still reads "real costs are fees ~$1–2/round-trip"; that doctrine
  line PREDATES the $0-commission evidence. This proposal is the correction,
  staged observe-only.

## 3. The realized join (deferred, at close)

At the stage seam the realized value is UNAVAILABLE by construction
(`no_broker_fill_pre_execution`). It joins AFTER the fact at close via the
broker fill. `tcm_v2_proposal.realized_commission_when_available(...)` reproduces
the study's broker-routed predicate exactly: `execution_mode` in
{alpaca_paper, alpaca_live} AND an `alpaca_order_id` AND `broker_status='filled'`
→ known (`fees_usd`, $0 today); otherwise typed UNAVAILABLE. The offline
consumer that closes the loop already exists:
`scripts/analytics/realized_cost_study.py`.

## 4. What promotion WOULD change (not built)

Promotion means: the ranker/gate/sizing read the **proposed** commission instead
of the frozen fee for broker-routed candidates. Concretely, the entry
round-trip cost gate (`ENTRY_ROUNDTRIP_COST_GATE_ENABLED`, #1101) and the
ranker's cost basis would stop charging ~$1–2/round-trip of phantom commission
on live-routed options — admitting candidates the phantom fee currently rejects,
and changing rank order. That is a **behavioral / loosening** change (CLAUDE.md
§3): it would be gated `ENABLE_LIVE_TCM_MODEL=1` explicit opt-in, absent/empty →
frozen behavior (fail-safe), with the H9 discipline that slippage/spread are NOT
touched (only commission is evidenced).

Promotion is **out of scope for this lane** and is not built here.

## 5. Promotion gate (the number is the owner's, not invented here)

The proposal may not be promoted until enough REALIZED broker-routed examples
exist to confirm the $0 commission holds and to measure the decision impact.
Reference the system's existing convergence conventions rather than a new
number:

- the **#1051 8-close rule** — the calibration raw-mode → live-multiplier
  convergence at 8 post-epoch LIVE closes; and
- the **Phase-3 ≥10–15 close-fills gate** used for the fill-quality work.

Recommended owner packet check before flipping `ENABLE_LIVE_TCM_MODEL`:
1. `entry_realized_commission_vs_tcm_estimate` stays ≈ −(frozen fee) with
   `entry_commission_broker_known` ≥ the chosen N (owner picks N from the two
   conventions above — do NOT let an agent pick it).
2. No broker-routed options fill has appeared with a non-zero `fees_usd` (if one
   does, the $0 premise is broken — reject promotion, re-open the study).
3. Confirm the decision-impact dry-run (rank/gate deltas with the proposed
   commission) is what the owner intends.

## 6. Rollback

- Dual-run (this PR): the sibling key is purely additive and observe-only.
  Rollback = revert the PR; no migration, no data cleanup (the sibling is inert
  jsonb). No decision reads it.
- A future promotion: gated behind `ENABLE_LIVE_TCM_MODEL` — rollback = unset
  the flag (reverts to the frozen fee in every decision) and, if warranted,
  revert the promotion PR.

## 7. Caveats

- The stage-time routing is a PREDICTION (`routing_mode == live_eligible` proxy
  for "will get an `alpaca_order_id`"). A broker submit that later fails
  (`submission_failed`) would have proposed broker-$0 but filled internally —
  the realized join at close is the authority; the stage proposal is a
  hypothesis until the fill confirms it. This is why the realized side is a
  first-class deferred field, not a stage-time assumption.
- Only ONE persisted stamp site exists (`paper_endpoints.py`). The
  `dashboard_endpoints.py` `estimate()` call is an ephemeral HTTP display
  response (not persisted, not decision-feeding) and is intentionally left
  un-instrumented.
- Evidence is a 42-fill snapshot at one date. The gate above requires the
  premise to keep holding as volume grows.
