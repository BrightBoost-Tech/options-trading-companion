# alpaca_order_sync.sync_orders — analysis

## Status (as of 2026-05-18)

Allow-list entry validated against empirical incident history. Function is structurally awkward (4-Step nested async closure) but functionally sound. **No refactor recommended; re-evaluate at allow-list expiration (2026-08-12).**

## Structure summary

- **Entry:** `run(payload, ctx)` at module level (`packages/quantum/jobs/handlers/alpaca_order_sync.py:26`).
- **Inner:** `sync_orders()` async closure (line 50) containing 4 sequential Steps:
  - **Step 1 (line 59):** Poll Alpaca for in-flight orders' current status via `poll_pending_orders`.
  - **Step 2 (line 95):** Repair orphaned fills (`status='filled'`, `position_id=NULL`, `filled_qty>0`) via `_process_orders_for_user`.
  - **Step 3 (line 124):** Reconcile stuck-open positions (filled CLOSE order, position still `status='open'`) via `_close_position_on_fill`.
  - **Step 4 (line 192):** Ghost-position sweep (env-gated by `RECONCILE_POSITIONS_ENABLED`, default OFF) via `ghost_position_sweep`.
- **Dispatch:** `status_map` at `alpaca_order_handler.py:567-573` — single dict lookup mapping 9 Alpaca states to 4 internal states (`working`, `partial`, `filled`, `cancelled`).
- **Reconciliation authority:** see "H10 surfaces" table below.

## Empirical incident history (last 60 days)

| Date | Incident | Shape | Fix shape |
|---|---|---|---|
| 2026-04-16 | Ghost-position (PR #764) | cancellation-race | Multi-site: poll filter expansion + 42210000 break + new `ghost_position_sweep` |
| 2026-05-01 | BAC ghost-position (PR #853 + #98) | cancellation-race | Two-layer: write-site alert + recurring stale-review sweep |
| 2026-05-11 | CSX ghost incident (PR #921) | reconciliation-asymmetry | External: manual DB UPDATE per H10 doctrine |
| 2026-05-18 | BUG-A + BUG-C (PR #961) | adjacent surface | Not in `sync_orders` — fixes in `intraday_risk_monitor` + `paper_exit_evaluator` |

**Pattern:** incidents concentrate at dispatch **EDGES** (watchdog, rejection-text extraction, `needs_manual_review`) and at the **reconciliation-asymmetry seam** (operator UI close without our close-order), NOT at the dispatch structure itself. **Refactoring the structure wouldn't have prevented any observed incident.**

## Latent risks (not currently firing)

1. **Partial-fill stalled at `filled_qty > 0`.** Idle watchdog at `poll_pending_orders:579-625` only catches `filled_qty == 0` cases. A partial fill that stops moving (Alpaca leaves `internal_status='partial'` indefinitely) would sit without resolution. Hypothetical at micro tier (contracts=1, partials uncommon); becomes mechanically possible at small tier (allocator emits 2-4 contracts).

2. **Operator UI close without our close-order.** By H10 doctrine, the system structurally avoids auto-closing on Alpaca-side state divergence — too aggressive a posture risks DB-row-as-truth violations during transient Alpaca outages. `ghost_position_sweep` alerts when enabled, but doesn't write the close. Operator-initiated reconciliation is policy. This is codified, not a bug.

3. **Alpaca says open, DB has no record.** Structurally unhandled — `sync_orders` is DB → Alpaca direction only; doesn't import Alpaca-side positions absent from DB. Operationally rare today (operator doesn't open positions via Alpaca UI; system-initiated entries always create DB rows first), but no defense if it ever fires.

## H10 reconciliation surfaces

| Surface | Direction | Authority model |
|---|---|---|
| Step 1 (poll_pending_orders) | Alpaca → paper_orders | Alpaca authoritative for `status`, `filled_qty`, `avg_fill_price` |
| Step 1 fill→close path | Alpaca fill → `paper_positions.status='closed'` via `close_position_shared` | Alpaca's filled close order causes the DB close — Alpaca authoritative |
| Step 3 stuck-open reconciliation | DB-derived (filled `paper_orders` with `position_id` set) → `paper_positions` close | DB-internal consistency — does NOT re-check Alpaca |
| Step 4 ghost-sweep | Alpaca position legs → flag DB open positions with no matching legs | Alpaca authoritative; **alerts only, doesn't reconcile** |

**Step 3 source-engine guard at line 134** (`CLOSE_SOURCE_ENGINES = {"paper_exit_evaluator", "manual_close"}`) is load-bearing — entry orders have `position_id` set post-`_process_orders_for_user`, and reconciling them as closes would auto-close legitimate open positions. Any refactor must preserve it.

## H9 allow-list rationale (validated)

Six logger-only `try/except` blocks across the 4 Steps satisfy the gate's wrapper-shape detection:

- `alpaca_order_sync.py:121-122` — orphan repair failure
- `alpaca_order_sync.py:182-186` — per-position reconciliation failure
- `alpaca_order_sync.py:187-188` — Step 3 outer wrapper
- `alpaca_order_sync.py:213-214` — per-user sweep failure
- `alpaca_order_sync.py:215-216` — Step 4 outer wrapper
- `alpaca_order_handler.py:792-794` — per-order poll failure (covered by parent's allow-list entry; see gate-coverage note below)

**Allow-list entry expires 2026-08-12; forced re-review at that point.**

**Gate-coverage artifact:** the per-order swallow in `poll_pending_orders:792` is structurally similar but not separately gate-flagged — the AST gate's prefix detection catches `sync_orders` as the outer function, and the inner helper inherits coverage transitively. This is a known H9 AST gate limitation (function-scoped detection vs caller-chain scoping), not a defect of this surface.

## If refactor is later motivated — three options

1. **RECOMMENDED — Extract 4 Steps to module-level functions** (`_poll_step`, `_orphan_repair_step`, `_stuck_reconcile_step`, `_ghost_sweep_step`). `run()` becomes a thin orchestrator. **~half day. Risk: very low.** Each step independently testable. Addresses the "nested-handler" framing without touching dispatch logic.

2. **State-machine refactor on the `status_map` dispatch.** Replace sequential `if/elif` with explicit transition table + named `Action` enum. **~1 day. Risk: medium** — touches the core poll loop bugs have concentrated near. Only worth it if a 5th edge-case bug surfaces.

3. **Per-state handler classes.** Over-engineered for the current state count (5 internal states, 4 transition edges). **Not recommended** unless the state surface grows substantially (option exercise, assignment, partial cancellation, replacement order handling — none on the roadmap).

## Tier-transition watch items

When the operator crosses to small tier ($1,500+):

- **Monitor for partial-fill-stalled-with-`filled_qty>0` cases.** The allocator (PR #958) emits 2-4 contracts at small tier, making partial fills mechanically possible.
- **Trigger criterion:** 2+ instances of orders in `internal_status='partial'` with stalled `filled_qty` for >15 min within any rolling 7-day window.
- **If observed:** address via Option 1.5 — extend idle watchdog to track partial fills with stalled `filled_qty` across N consecutive polls. ~2-4 hours of work.
- **If not observed within 30 days post-transition:** defer indefinitely; the latent risk was hypothetical.

The natural observability surface is `paper_orders` query for `status='partial' ORDER BY submitted_at` filtered to entries older than 15 min. Today's micro-tier traffic produces near-zero rows on this query (single-contract orders fill atomically).

## Cross-references

- `packages/quantum/jobs/handlers/alpaca_order_sync.py` — entry point, 4-Step structure
- `packages/quantum/jobs/handlers/alpaca_order_handler.py` — dispatched helpers (`poll_pending_orders`, `_close_position_on_fill`, `ghost_position_sweep`, `submit_and_track`)
- `packages/quantum/services/close_helper.py` — `close_position_shared` (H9-compliant close path)
- `docs/loud_error_doctrine.md` H9 (allow-list rationale), H10 (reconciliation asymmetry)
- `docs/bugs_fixed_history.md` — incident detail for the 4 cancellation-race + reconciliation-asymmetry fixes
- `packages/quantum/tests/h9_allow_list.yml` — `alpaca_order_sync.sync_orders` entry (expires 2026-08-12)
