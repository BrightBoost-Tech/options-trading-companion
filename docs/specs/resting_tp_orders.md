# SPEC: Resting Take-Profit Orders (broker-side limit at the tp price)

Status: PROPOSED — design only (2026-06-12). **Most of this exists**: the GTC
profit-limit layer shipped in PR #1021 (`packages/quantum/services/
gtc_profit_exit.py`, flag `GTC_PROFIT_EXIT_ENABLED`, default OFF, never
enabled live). This spec is therefore an *enablement-and-hardening* plan for
#1021, not a new build — and that is why it is the recommended first build
from the 06-12 session.

## 1. Why this is the right first mechanism

The 06-12 forensics verdict was mark artifact: every fast-detection design
(Parts B/C) inherits the mark-quality problem and needs the #1034 gate to be
trustworthy first. A resting buy-to-close limit at the tp price has a
property no detector has: **it cannot be fooled by a quote artifact.** It
fills only when a real counterparty actually trades at the tp price. The
06-12 13:30Z phantom TP (mid said +$96, executable was −$599) would not have
filled a resting limit; conversely a *real* 3-minute touch of the tp price
during the monitor's blind window — the event the operator feared had
happened — gets captured by the exchange with zero cadence dependence.
Detection latency: zero. False-positive rate: zero by construction.
That asymmetry makes D strictly safer than B/C for the profit side.

## 2. Day-limit vs GTC (reconciling the request with validated facts)

The request frames this as "morning-placed day-limit." Two facts supersede
the day-only constraint:

- mleg **GTC** is broker-validated in BOTH shapes on this account:
  opening+debit (2026-05-29) and closing+credit (2026-06-04, limit rested
  and cancelled cleanly).
- The built #1021 layer already places GTC (`gtc_profit_exit.py:215`,
  `time_in_force="gtc"`).

Recommendation: **GTC with refresh-on-recalc** rather than daily
place/expire/resubmit. The tp price is entry-anchored (below), so it does
not change day to day; a daily lifecycle adds 2 order events/position/day
of pure churn and a morning placement race for no benefit. The daily-DAY
variant remains a fallback if GTC behavior surprises (kill: flip the flag,
orders cancel on the nightly reconcile).

## 3. Price computation — entry-anchored, artifact-immune

- Credit structures (condors): buy-to-close limit at
  `entry_credit × (1 − target_profit_pct)` — e.g. the current QQQ condor at
  aggressive tp 0.50: 1.61 × 0.50 = **0.805 debit** (pointer: thresholds
  come from `load_cohort_configs` / `policy_lab_cohorts.policy_config`,
  never hardcode).
- Debit spreads: sell-to-close limit at `entry_debit × (1 + target_profit_pct)`.
- Both are functions of **entry price and cohort config only** — no mark,
  no quote, no staleness. The "resting order at a stale-computed tp price"
  risk in the request collapses to one real case: cohort tp config changes
  while an order rests. Mitigations:
  (a) refresh-on-recalc — the placement job cancels/replaces when the
      computed tp differs from the resting limit;
  (b) nightly reconcile job asserts `resting limit == f(entry, current
      cohort tp)` for every open live position and alerts on drift.
- Placement timing: after the 8:35 CT morning evaluate (fresh marks, post
  opening auction — placement itself needs no marks, but staging-time leg
  validation (#1038-adjacent) should see a sane NBBO, and the known
  opening-mark defect argues for not touching the open).

## 4. Ownership — single-owner doctrine (the 06-11/06-12 double-submit class)

The resting TP is an exception to "the evaluator owns all closes," so the
exception must be visible to every other actor:

- **Marker**: `source_engine = "gtc_profit_exit"` in `paper_orders.order_json`
  (#1021, `gtc_profit_exit.py:58-61`). This is the ownership flag; do not
  invent a parallel `intentional_resting_exit` class — extend the existing
  marker if a rename is wanted.
- **The evaluator KNOWS it exists**: `filter_blocking_close_orders`
  (`paper_exit_evaluator.py:601-689`) already recognizes GTC resting limits
  specially (#1046-aware). Required behavior, with a regression test per
  row: the resting TP must (i) NOT count as a "blocking close order" for
  re-arm logic, but (ii) MUST be returned to the staging path as an
  owned-exit marker so a TP-trigger evaluation becomes a no-op
  (`skipped_resting_tp_owns_profit_side`) instead of a second submission.
- **Fill sequence (no duplicate possible)**:
  1. Resting TP fills at broker at T.
  2. `alpaca_order_sync` (q5min) reconciles the fill, closes the position
     via the canonical close helper (`close_helper.py`) — same path as any
     broker fill (`alpaca_fill_reconciler_*` close_reason).
  3. Any evaluator/monitor cycle between T and the sync sees the position
     still open in DB — but its TP staging is a no-op per (ii) above, and
     even a hypothetical stop-side close in that window hits the
     cancel-then-close sequence below, whose cancel returns
     "already filled" and aborts the duplicate.
  Worst case is a ≤5-min window where the DB book is one position stale —
  the existing order-sync reality, not new exposure.

## 5. Watchdog exemption

Already built (#1021): the idle watchdog kills idle DAY limits
(`alpaca_order_handler.py`, `IDLE_WATCHDOG_SECONDS = 90`, enforced on the
5-min order-sync cadence — the 06-12 QQQ close died exactly this way:
`watchdog_idle_timeout idle=294s threshold=90s`). GTC resting TPs are exempt
via time-in-force + the `source_engine` marker. Everything else the watchdog
still kills — the exemption is the marker, not a watchdog behavior change.
Required test: a DAY close limit and a GTC TP for the same position; watchdog
kills the former, never the latter.

## 6. Stop-side interaction — cancel-then-close, monitor stays the owner

Stops remain monitor-owned (existing doctrine; resting orders are profit-side
ONLY). When the monitor wants to force-close (stop/envelope) while a TP
rests:

1. Monitor's `_close_position` pre-cancel step (745ced4 semantics) cancels
   the resting TP first and **polls to terminal state** (canceled vs filled
   — never assume).
2. Cancel confirmed → submit the stop close through the single submitter.
3. Cancel returns already-filled → the position closed at TP between
   detection and action; abort the stop submission, trigger an immediate
   order-sync pass, done. (This is the good race — TP beat the stop.)
4. Cancel fails transient → bounded retry; while uncanceled, NO stop order
   is submitted (two live close orders for one position is the forbidden
   state — the legs would double-fill).

The 06-12 15:30Z SPY event (second submission rejected by broker intent
check after the first fill) is the proof this sequencing must be strict:
that day the broker's inference was the only guard.

## 7. Partial fills and price improvement

- Current live sizing is qty=1 per structure → mleg fills are atomic; the
  partial-fill question is deferred-but-documented: at qty>1 Alpaca can
  partially fill the combo (whole multiples of the leg ratio only).
  order_sync's partial handling must mark the position partially closed
  (`partials` counter exists in sync results today) and the refresh job
  must re-rest the TP for the residual qty. Test before the first qty>1
  live entry, not before flag-on.
- Price improvement: a limit fills at-or-better by definition; better-than-
  tp fills are free upside, recorded by the reconciler from actual
  `filled_avg_price` (broker truth — never the limit price).

## 8. Lifecycle summary (GTC variant)

- Place: on position open (next placement-job pass after entry fill is
  reconciled), and at 8:40 CT daily sweep for any live position missing its
  TP (idempotent: skip if a `gtc_profit_exit` order already rests at the
  right price).
- Refresh: cancel/replace only when computed tp ≠ resting limit (cohort
  config change) or after partial fill.
- Expire: GTC persists; nightly reconcile cancels orphans (resting order
  whose position is closed — should be impossible via OCO/cancel-then-close,
  alert if found).
- Scope: live-routed positions only; profit side only. #1021 is
  flat-cohort-tp only today — extending to cohort-aware tp via
  `load_cohort_configs` is part of the enablement delta. Shadow cohorts:
  never (no broker orders for synthetic books).

## 9. Risk register

| Risk | Mitigation |
|---|---|
| Resting at wrong tp after cohort config change | refresh-on-recalc + nightly reconcile assert |
| Double-close vs monitor stop | cancel-then-close with poll-to-terminal (§6) |
| Watchdog kills the TP | marker exemption + regression test (§5) |
| Fill seen late (≤5min) by DB book | existing order-sync window; no new exposure; TP-staging no-op prevents dup |
| GTC survives a deploy/recycle unexpectedly | it should — broker-side state is the point; nightly reconcile is the audit |
| Margin/BP interaction of resting close | closing orders release, not consume, BP (H7 covered at entry); verify once in paper at flag-on |

## 10. Rollout and effort

- Flag stays `GTC_PROFIT_EXIT_ENABLED` (behavioral, explicit `=1`).
  Enable sequence: paper account first (1 session, verify place/refresh/
  watchdog-exempt/cancel-then-close), then live with the QQQ condor as the
  pilot (its tp of 0.805 debit is far from market — a harmless resting
  order), then default-on for new live entries.
- Enablement delta on #1021: cohort-aware tp pricing, ownership no-op in
  the evaluator staging path, nightly reconcile, tests above.
- Effort: **~1–2 dev-days + 1 paper session + pilot.** Smallest effort,
  largest guaranteed capture of the three specs.
