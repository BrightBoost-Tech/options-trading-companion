# Live close double-submission trace (2026-06-11) — investigation, no code change

Every live close on 2026-06-11 16:30Z produced TWO broker orders ~1s apart,
with the first canceled/rejected within ~0.5s. Status: ROOT CAUSE CONFIRMED,
fix proposed for 06-12. This document is the writeup; no code was changed.

## Observed (broker truth, account 211900084)

| Close | Broker order #1 | #1 outcome | Broker order #2 | #2 outcome |
|---|---|---|---|---|
| NFLX (`4661f468`) | `55c2472b` 16:30:07.621 | **canceled** 16:30:08.07 (+0.45s) | `4b37cc55` 16:30:08.643 | accepted, rested |
| QQQ (`0e88e337`) | `1d30b526` 16:30:10.279 | **rejected** in 10ms (the −1.39 incoherent limit) | `8f3d6461` 16:30:10.708 | accepted, rested |
| SPY (`07943a1e`) | `3d108bcf` 16:30:12.222 | **canceled** 16:30:12.668 (+0.45s) | `eaf64961` 16:30:13.234 | gateway-canceled in 4ms |

Each DB order row stores only #2's `alpaca_order_id`.

## Root cause (confirmed)

The live close path submits the SAME paper_orders row to Alpaca **twice**:

1. `paper_exit_evaluator._close_position` stages the close via
   `_stage_order_internal`. For internal positions it forces
   `EXECUTION_MODE=internal_paper` around the call — but for
   `position_is_alpaca` it does NOT, and `_stage_order_internal`
   (`paper_endpoints.py:822-834`) **submits any alpaca-mode order itself**
   (`submit_and_track` — the entry-path behavior). → **Submission #1.**
2. `_close_position` then fetches the same row and calls `submit_and_track`
   explicitly (`paper_exit_evaluator.py:1707-1715`). → **Submission #2.**
3. Submission #2's **pre-cancel** (`alpaca_order_handler.py:200-215`,
   `cancel_open_orders_for_symbols` — built to clear `held_for_orders`
   conflicts) finds submission #1's order resting on the close's own leg
   symbols and **cancels it**, then re-submits.

Smoking gun: TWO `[ALPACA_HANDLER] Credit-close sign-flip` WARNINGs for the
same order id (16:30:07.588 and 16:30:08.606 — `build_alpaca_order_request`
runs once per `submit_and_track` call), and #1's `canceled_at` falling
between the two builds. The QQQ row fits as the variant where #1 was already
terminal (gateway-rejected) so the pre-cancel had nothing to cancel.

## Why this was never seen before

No LIVE system close had ever executed (the PR #908 validation has been
pending since 06-04; the 05-29 F close was a manual Alpaca-UI close).
Internal-paper closes never broker-submit from `_stage_order_internal`
(execution mode forced to `internal_paper`), so the duplicate seam was
unreachable until today's first live force-closes.

## Consequences while unfixed

- Cancel/churn per live close (~1s of order-state noise, doubled rejection
  surface at the gateway).
- SPY #2's 4ms gateway cancel is consistent with self-cross/wash detection
  against the just-canceled identical #1 — i.e. the duplicate can cause the
  SECOND order to die too, leaving a close order in `pending_new` limbo in
  the DB until order-sync reconciles.
- The pre-cancel can in principle cancel a LEGITIMATE resting close (e.g. a
  future GTC profit-limit on the same legs) — the #1021 watchdog exemption
  protects GTC from the watchdog, not from this pre-cancel.

## Proposed fix (06-12, not tonight)

Single-submitter rule for closes: add `submit_to_broker: bool = True` to
`_stage_order_internal`; `_close_position` passes `submit_to_broker=False`
for `position_is_alpaca` closes and keeps its own explicit
`submit_and_track` (the close-specific pre-cancel semantics live there).
Regression test: a live-mode close produces exactly ONE
`submit_and_track` call / ONE `build_alpaca_order_request` invocation
(assert via call counter), plus a pin that internal-paper closes are
unaffected. Alternative (rejected): dropping `_close_position`'s explicit
submit would silently change pre-cancel ordering and lose the
`[EXIT_EVAL] Submitted close to Alpaca` accounting.
