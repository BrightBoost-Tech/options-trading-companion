# Reconciliation-Receipt PRODUCER — Operator Acceptance Packet (2026-07-21)

> **DRAFT PR / RTH-OPEN build. Issues NOTHING by default.** This wires the FIRST
> real code producer to the durable receipt writer
> (`rpc_issue_fleet_reconciliation_receipt_v1`, migration `20260721010000`). It
> applies no migration, writes no production receipt, mutates no fleet/policy
> state, and makes no activation call. The producer is DARK until the operator
> flips one explicit opt-in flag — see the sign-off checklist.

## 1. Which producer (the smallest real one)

**Seam:** `packages/quantum/jobs/handlers/alpaca_order_sync.py` — Step 1.5,
`_resolve_lost_submit` **404/re-arm branch**, now routed through the new
`_reconcile_lost_submits` → `_issue_stale_order_receipt`.

**Why this one.** The two activation-REQUIRED receipt kinds are `stale_order` and
`manual_review` (`shadow_fleet_activation.REQUIRED_RECEIPT_KINDS`), and B4
(`docs/review/fleet-receipt-contract-option-a-2026-07-20.md`) proved both live on
`paper_orders` with a real `user_id` + a `broker_response` jsonb column. The
smallest existing code path that COMPLETES a genuine stale-order reconciliation on
such a row is Step 1.5's response-lost resolution: an order with a deterministic
`client_order_id` but NO `alpaca_order_id`, confirmed NOT-at-broker (404), is
re-armed to the terminal `'cancelled'` state. That cancel IS the reconciliation —
a stale/never-landed order cleared from the working set. It runs on a user-scoped
`paper_orders` row and is one self-contained transaction.

This is intentionally NOT wired into any scoring/entry/exit decision path. The
`manual_review` and `orphan_run` kinds have no standing code producer today (they
were operator SQL on 07-18); they remain operator-script territory and are out of
scope here — see §5.

## 2. Ordering contract (post-commit only)

Per reconciled order, in order:

1. **Reconciliation commits.** `_resolve_lost_submit` writes
   `paper_orders.status='cancelled'` (+ `cancelled_reason`, `cancelled_at`,
   `broker_status`) and returns `'rearmed'`. The write has committed before step 2
   begins. *A pre-commit failure (the cancel UPDATE raises) issues nothing — the
   row is skipped, no marker, no RPC.*
2. **Stamp the marker (a).** `stamp_reconciliation_marker` merges the canonical
   marker into the row's `broker_response` jsonb (non-destructive) and persists it.
3. **Issue the receipt (b).** `issue_reconciliation_receipt` makes ONE
   `supabase.rpc(...)` call to the writer RPC, which re-proves the marker
   server-side and mints exactly one immutable receipt.

Steps 2+3 run only after step 1 committed, and only when the producer flag is ON.

## 3. Exact marker contract

Stamped at `paper_orders.broker_response -> 'reconciliation_receipt'`:

```json
{
  "kind": "stale_order",
  "status": "completed",
  "content_fingerprint": "<64-char sha256 hex>",
  "effective_epoch": "small_tier_v1"
}
```

- **content_fingerprint** = `reconciliation_content_fingerprint("stale_order",
  "paper_orders", <order_id>, <client_order_id>, "small_tier_v1",
  "client_order_id_not_at_broker")` — a deterministic full 64-char sha256 hex over
  the durable reconciliation content. The SAME value is passed to the marker AND
  the RPC, so they match by construction. Determinism gives idempotency: an exact
  replay of the same reconciliation returns the SAME receipt with zero new rows.
- **effective_epoch** = `FLEET_EPOCH` (`small_tier_v1`).
- **actor_class** passed to the RPC = `stale_order_reconciler:alpaca_order_sync`.
- **provenance** = `source_table='paper_orders'` + `source_row_id=<order_id>`
  (never `source_alert_id`). The RPC LOCKs the row `FOR UPDATE`, requires
  `user_id == p_user_id`, kind/epoch/full-fingerprint match, and `status ==
  'completed'`.

The RPC is idempotent on exact replay and RAISEs `receipt_conflict` on a
conflicting replay; both outcomes surface to the caller.

## 4. H9 — failure is loud/partial (never a silent green)

- A **missing durable user scope** (no `user_id` on the row) RAISEs before any RPC
  — never a fabricated scope.
- A **required-receipt issuance failure** (RPC error / conflict / stamp failure)
  AFTER the cancel committed is recorded in `receipt_errors` with a typed
  `stage='stale_order_receipt'`, counted into `totals['errors']` and
  `stale_order_receipt_errors`, so `alpaca_order_sync.run()` returns `ok=False`
  (`counts.errors >= 1`) — the job goes **partial**. The reconciliation itself
  still stands (the order is cancelled); only the receipt is retried.
- A **pre-commit failure** (cancel UPDATE raises) issues nothing for that row.

Origin-to-top is proven by `TestRunEndToEndPartial`: the RPC is made to raise at
the deepest callee and the TOP-LEVEL `run()` result is asserted partial.

## 5. Flag / polarity

`FLEET_RECEIPT_PRODUCER_ENABLED` — **behavioral / explicit opt-in (§3)**.
Enabled only by the literal value `1`; absent / empty / `true` / `on` / anything
else → **OFF**. Default-OFF because it adds a durable receipt-writer RPC to a live
reconciliation path and fleet receipts are operator-gated. When OFF, the
order-sync path is byte-identical to its pre-producer behavior (verified by
`TestProducerDefaultOff` + `TestRunEndToEndPartial::test_producer_off_run_issues_nothing`).
**This PR leaves the flag UNSET → the running workers issue NOTHING.**

Out of scope (still operator-script / future producers): `manual_review` (the
07-18 seventh row) and `orphan_run` (job_runs hygiene — `job_runs` has no
`user_id`, so per the RPC contract it must route through a user-scoped
`risk_alerts` marker, which no code writes today).

## 6. First-real-receipt runtime falsifier

There is no natural falsifier until the operator opts in, because the producer is
dark by default. To obtain the first durable receipt:

1. Apply migrations `20260720140000` (table) and `20260721010000` (writer RPC) by
   exact name via the migration procedure (NOT this PR).
2. Set `FLEET_RECEIPT_PRODUCER_ENABLED=1` on **both** workers and read it back on
   the running process (§2 deploy doctrine; `[FLAG_ECHO]` if allow-listed).
3. **Falsifier:** the next time an order goes response-lost and is confirmed
   404-at-broker during an RTH `alpaca_order_sync` run, expect —
   - `paper_orders.<row>.broker_response->'reconciliation_receipt'` present with
     `status='completed'`, `kind='stale_order'`, a 64-char fingerprint;
   - exactly ONE new `fleet_reconciliation_receipts` row for that
     (kind, fingerprint), `source_table='paper_orders'`, matching `user_id`;
   - `job_runs.result` for that run shows `stale_order_receipts >= 1` and, on any
     issuance error, `counts.errors >= 1` with a `stale_order_receipt` stage.
   - Re-running against the same (now-cancelled) order mints NO second row
     (idempotent). Absent a qualifying response-lost 404 event, the result is
     **INCONCLUSIVE**, never PASS.

## 7. Operator sign-off checklist

- [ ] Migrations `20260720140000` + `20260721010000` applied by exact name;
      `fleet_reconciliation_receipts` exists and is append-only.
- [ ] This PR merged + deployed; both workers recycled at a SHA > merge time.
- [ ] `FLEET_RECEIPT_PRODUCER_ENABLED` decision made. Leave UNSET to stay dark;
      set `=1` on BOTH workers (read back) to arm.
- [ ] With the flag armed, confirm the first response-lost 404 mints exactly one
      receipt + stamps the marker (falsifier §6); confirm idempotent re-run.
- [ ] Confirm a forced issuance failure marks the job partial (`ok=False`,
      `counts.errors>=1`) — no silent green.
- [ ] No activation performed: `ACTIVATE_FLEET=false`, `entries_paused` untouched,
      fleet counts byte-identical before/after. Receipts are EVIDENCE for a later,
      separately-authorized activation — issuing them authorizes nothing.

## 8. Self-review

- **Can it issue during tests / this run?** No. Tests use a fake supabase +
  injected RPC handler (no real `.rpc`); the flag defaults OFF so the deployed
  workers issue nothing.
- **Can it double-issue?** No. The fingerprint is deterministic per reconciliation
  and the RPC is idempotent on `UNIQUE(receipt_kind, content_fingerprint)`; a
  cancelled order is excluded from Step 1.5's own re-query.
- **Is failure loud?** Yes — required-receipt failure → `counts.errors` +
  `ok=False` (partial); missing scope RAISEs; pre-commit failure issues nothing.
- **Any activation / fleet / policy mutation?** None. The writer touches only
  `fleet_reconciliation_receipts` (INSERT) + the source row (marker stamp / RPC
  `FOR UPDATE` lock). No activation RPC, no registry/fleet write.
