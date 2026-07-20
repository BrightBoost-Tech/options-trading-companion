# V17-1 Internal-Close Anomaly Census — OPERATOR CORRECTION PACKET — 2026-07-19

**READ-ONLY. No production rows were corrected** (v1.7 authorization `PRODUCTION_DATA_CORRECTION=false`).
This packet exists because the V17-1 verification found a latent atomicity defect (now fixed by
Lanes 1A+1B) AND surfaced a small number of PRE-GUARD historical anomalies. The operator decides
whether any historical reconciliation is warranted; nothing here is actioned.

## Current state: CLEAN

The defect class (a filled internal close-order / cash delta / ledger fill without a matching
committed position close, or a double-booked racing close) has **zero current-state instances**:

- filled `internal_paper` close orders whose position is NOT closed: **0**
- positions with duplicate FILLED close orders (close-marker predicate): **0**

The current guards (already-closed check + `client_order_id` idempotency + the P0-A live-isolation
gate) closed the *sequential* re-entry vector; the residual true-concurrency TOCTOU race and the
single-threaded abort-after-write orphan were the still-live gaps on the pre-fix code, now
eliminated by the atomic RPC (`rpc_commit_internal_close_v1`, Lane 1A) + the route switch (Lane 1B):
the four economic writes are one all-or-none transaction, and a losing CAS/abort writes nothing.

## Historical pre-guard anomalies (the verifier's authoritative list)

All three PRE-DATE the current guards; there have been **zero post-guard recurrences**. They are the
only genuine instances of the class — do not conflate them with legitimate multi-leg fills (below).

| position (short) | date | what | routing |
|---|---|---|---|
| `d077c93d-eafd-4174-9554-6f6ca4f24e3d` | 2026-05-18 | 5 fill events in a ~7-second span + 5 filled close orders (the documented **CSX BUG-C** incident the code comments already cite) | internal_paper |
| `7cb40372…` | 2026-04-03 | 2 filled close orders | mixed alpaca_paper + internal_paper (a live-then-internal double-close now barred by the P0-A guard) |
| `ef009864…` | 2026-04-03 | 2 filled close orders | mixed alpaca_paper + internal_paper (same class) |

## NOT anomalies (do not correct)

A broad "positions with >1 fill ledger event" scan returns **22 positions** — but a multi-leg
spread close legitimately emits ONE fill ledger event per leg, so 2x/3x fill events on a
multi-leg structure is normal accounting, not a double-book. Of those 22, only `d077c93d`
(5x, 2026-05-18) is a flagged historical incident; the rest are legitimate per-leg fills. This
packet does NOT propose touching any of them.

## Operator options (all optional; none authorized here)

1. **Do nothing** — the anomalies are pre-guard, shadow/paper-cohort only (no live broker capital;
   the mixed rows' live legs were separate), and the class is now structurally impossible going
   forward. This is the recommended default given learning-mode (correctness > capital) and that
   champion-promotion P&L is already treated as basis-broken (§8 shadow-ledger fiction).
2. **Reconcile the CSX BUG-C cluster** (`d077c93d`) if its shadow-ledger P&L materially skews a
   specific promotion comparison you care about — a supervised, separately-authorized data
   correction with its own fingerprinted receipt, NOT part of this run.

## Provenance

Census re-run read-only 2026-07-19 against Supabase `etdlladeorfgdmsopzmz` at code main
`d1a7f22b` (post Lane 1A+1B). No `UPDATE`/`INSERT`/`DELETE` against business rows was issued by
the v1.7 run except the two doctrine migration-apply receipts (`risk_alerts`, `info`).
