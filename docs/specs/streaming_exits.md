# SPEC: Event-Driven Exits via Alpaca Options WebSocket

Status: PROPOSED — design only (2026-06-12). **Post-validation work.** Do not
build until the fast exit loop (docs/specs/fast_exit_loop.md) has shipped,
its observe-mode data exists, and #1034 Stage-2 enforcement has been
exercised live. This is the third rung of the ladder, not the second.

## 1. Why streaming, and why not yet

The 06-12 forensics showed the chart spike was a mark artifact — tick-level
detection would have produced tick-level *phantom* triggers on the same
degenerate quotes (C750 printed bid 0.76 / ask 14.09 at 13:30Z; a naive
on-tick remark fires TP instantly on that mid). Streaming raises detection
speed AND artifact exposure together; it is only net-positive once the
corroboration/suppression machinery has a live track record. What streaming
eventually buys over the 1–2 min loop: second-scale stop-loss latency and
zero polling cost during quiet hours.

## 2. Subscription lifecycle

- **Source**: Alpaca options websocket
  (`wss://stream.data.alpaca.markets/v1beta1/{feed}`), quotes channel,
  **held legs only** (≤16 symbols at design max; limit is 1,000+ — no
  pressure). Feed entitlement must be verified at startup: the account's
  REST snapshots default to `opra` today; if the WS entitlement resolves to
  `indicative`, quotes are delayed/modified and are **not executable-grade**
  — in that case streaming may pre-screen but every trigger MUST re-quote
  via REST opra snapshot before staging (this check is mandatory startup
  behavior, not a doc note: log the negotiated feed and refuse `act` mode on
  `indicative`).
- **Subscribe on fill**: `alpaca_order_sync` (the fill authority) publishes
  position-opened events; the stream worker diffs its subscription set
  against live-routed open legs each event and on a 60s reconcile timer
  (belt-and-suspenders against missed events).
- **Unsubscribe on close**: same diff. A symbol with zero live legs is
  dropped within one reconcile interval.
- **Disconnect recovery**: on reconnect, REST `snapshot_many` gap-fill for
  all held legs BEFORE re-arming triggers (no decisions on a cold book).
  Disconnected >60s during RTH → `streaming_degraded` high-severity alert;
  the polling loop (Part B) and 15-min monitor are the floor and keep
  running regardless — streaming is additive, never a replacement for the
  floor.

## 3. Trigger path (strictly the same close machinery)

On quote tick for a held leg:

1. **Remark** only structures containing that leg, with the shared mark math
   (`risk/mark_math`) and the 48cf8ec degenerate-quote/stale-fallback guards.
   Coalesce: max one re-evaluation per position per 5s window regardless of
   tick rate.
2. **Debounce**: the exit condition must hold continuously for N seconds
   (start at 30s; tunable env) across fresh ticks — a single print never
   triggers. The 06-12 C750 sequence (degenerate book at 13:30, dip prints
   14:42–14:49 reverting by 14:55) is the calibration case: a 30s-hold
   would have rejected 13:30 outright (one-sided book fails the quote-
   validity guard) and the 14:49 "peak" (condition not held on executable
   side at all).
3. **Corroborate** on the EXECUTABLE side via #1034
   (`exit_mark_corroboration.compute_corroboration`, enforcing, fixed
   spread_width): sell legs at bid, buy legs at ask, all-or-nothing on leg
   quotes. Require two passing corroborations ≥10s apart for target_profit.
   `stop_loss` is never suppressed (doctrine), but its observation row is
   always written.
4. **Stage** through `paper_exit_evaluator._close_position()` with
   `exit_price_override` — the single submitter (745ced4). The stream worker
   calls the same signed internal endpoint the monitor uses; it owns NO
   order-submission code. No second submitter, ever. Idempotency: the same
   already-closed guard + `filter_blocking_close_orders` + per-position
   staging lock that arbitrate monitor/fast-loop dual-fire arbitrate this
   path too.

## 4. Safety bounds

- **Stop side**: faster stop detection only tightens protection; suppression
  never applies. Envelope force-closes remain monitor-owned (envelopes need
  portfolio-level state the stream worker deliberately does not have).
- **Rate/CPU**: quotes on ≤16 OPRA symbols are at most a few hundred
  msgs/sec in bursts; per-position 5s coalescing bounds evaluation to ≤12
  evals/min/position. Bounded inbound queue (drop-oldest + depth gauge
  metric); processing is pure arithmetic on ≤4 legs — CPU is not a concern,
  but the bound must exist so a feed storm degrades to "slower detection,"
  never to memory growth.
- **Stale-mark guard**: unchanged and structural — marks are computed from
  the tick stream or REST gap-fill only; DB `current_mark` is never an input
  (same rule as the monitor's `exit_price_override` flow).

## 5. Architecture mismatch (stated honestly)

Every existing compute shape in this system is cron-born and short-lived:
APScheduler → signed HTTP → RQ handler → exit. There is no long-lived
connection holder anywhere in the codebase today (verified 06-12: no
websocket/stream client exists). A streaming worker is a NEW service class
with new failure modes the current ops surface does not cover:

- **Placement**: new Railway service (`worker-stream`), single replica,
  long-lived asyncio process, restart-on-exit. NOT an RQ job (RQ semantics —
  timeouts, retries, queue draining — are wrong for a process whose job is
  to never finish).
- **The dangerous failure is silence**: a wedged-but-connected worker looks
  identical to a quiet market. Mandatory: liveness heartbeat row (worker →
  DB every 30s) registered in ops_health OUTPUT_FRESHNESS; heartbeat stale
  >2min during RTH → high-severity alert. The 15-min monitor remains the
  uncancellable floor, so the worst case of total streaming failure is
  "we are exactly as protected as today."
- **Deploy coupling**: merges to main recycle all services (§2 doctrine);
  the stream worker must treat every recycle as cold start (gap-fill,
  re-subscribe, re-negotiate feed). Once-per-process state is reset by
  design — no warm-handoff complexity in v1.
- Kill switch: `STREAMING_EXITS_ENABLED` (behavioral, explicit `=1`);
  additionally `act`/`observe` mode env mirroring the fast loop.

## 6. What it obsoletes, and validation

- Obsoletes the fast polling loop as the *primary* TP/stop detector; the
  loop is retained as fallback (demoted to 5-min cadence or kept at 1-min —
  decide on cost data) and the 15-min monitor stays unchanged as floor.
  Resting TP orders (docs/specs/resting_tp_orders.md) are complementary, not
  replaced: a resting broker-side limit beats ANY detector for fill quality
  on the profit side.
- **Validation plan (shadow first)**: run ≥2 weeks in observe mode logging
  (a) every would-trigger with executable-side corroboration verdict,
  (b) lead time vs the fast loop / 15-min monitor detection of the same
  condition, (c) false-trigger rate (would-triggers whose condition did not
  hold at next REST corroboration). Promote to `act` only on: zero
  uncorroborated would-triggers, demonstrated lead-time benefit, and ≥1
  full disconnect/recovery cycle exercised (kill the service mid-session in
  paper context and verify gap-fill + alerting).

## 7. Effort estimate

- Stream worker (connection mgmt, subscribe lifecycle, coalescing, debounce,
  heartbeat): ~4–6 dev-days.
- Railway service provisioning + ops_health wiring + runbook: ~1 day.
- Trigger→corroborate→stage integration + tests (incl. simulated degenerate
  ticks replaying the 06-12 13:30Z book): ~2–3 days.
- Shadow validation: 2 weeks calendar (passive).
- Total: **~1.5–2 dev-weeks + 2 shadow weeks.** Do not start until B's
  observe data exists; if resting TPs (D) capture the profit side well,
  streaming's residual value is stop latency only — re-scope then.
