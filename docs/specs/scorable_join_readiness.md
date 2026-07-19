# ⑤ Scorable-Outcome Join Readiness (Lane D audit, 2026-07-19)

Audit of the complete join a NEXT naturally-closed position traverses to become
**scorable** by the event-driven model-review lane (Lane J, `#1286`).

**Verdict: COMPLETE.** No code gap. The join is wired producer→consumer with the
known-at cutoffs immutable, dedup by suggestion, cohorts separate, typed
non-scorable reasons, and exactly-once enqueue. Deliverable is one contract test
(`packages/quantum/tests/test_scorable_join_readiness.py`) that drives the REAL
capture producers end-to-end into the detector — the existing
`test_model_review_event` suite hand-rolls a simplified spot marker (no
`source`), so it would NOT catch a predicate that source-gates instead of
status-gates.

## Join table (hop → verdict)

| # | Hop | Mechanism | Verdict |
|---|-----|-----------|---------|
| 1 | decision event → suggestion | `trade_suggestions.decision_id` (`20260712011627`); study dedups by `suggestion_id` (latest close) | OK |
| 2 | suggestion → OPEN order | `paper_orders.suggestion_id`, marker-gated LATERAL: `order_json ? 'entry_underlying_spot'` == OPEN by construction (closes exempt) | OK — no open-order leakage |
| 3 | stage-seam capture | scan-time spot (`_populate_stage_entry_spot`, source `scan_time`), per-leg IV (`iv`+`iv_status`), delta (`greeks.delta`+`greeks_status`) — all OPEN-only (`position_id is None`), zero extra fetch | OK — captured at stage, never recomputed at close |
| 4 | position → close → outcome | `learning_trade_outcomes_v3`, `is_paper` routing-resolved | OK |
| 5 | scorability detector | `is_scorable_row` = study's own `to_foundation_row`; spot present AND every geometry leg carries iv+delta (BOTH models can score) | OK — predicate = consumer contract, no drift |
| 6 | outcome → challenger_study mapper | geometry ALWAYS from suggestion legs; captured iv/delta merged BY OCC SYMBOL from the OPEN order; F-CREDIT-SIGN corrected flag routed through `#1042` quarantine | OK — no post-outcome / close-leg leakage |
| 7 | mapper → terminal-distribution models | `records_from_rows` → frozen adapter (needs delta) + lognormal challenger (needs spot+iv); abstain typed `missing_spot/iv/delta`, counted never scored 0.5 | OK — typed non-scorable reasons complete |
| 8 | detector → enqueue-once | content fingerprint = sorted scorable ids ⊕ `MODEL_SET_VERSION`; idempotency key + prior-review scan (result+payload) + edge-triggered set change | OK — exactly once per new scorable close |
| 9 | cohorts | `build_study` splits live (`is_paper=False`) vs shadow (`is_paper=True`) into SEPARATE reports | OK — never co-mingled |
| 10 | wiring | detector is a fail-soft tail step of `paper_learning_ingest.run` (not orphaned) | OK — not the `#1126` class |

## The flagged concern (scan_time spot) — resolved, no mismatch

Monday's first close carries spot from the 07-18 scan-spot upgrade
(`entry_underlying_spot.source = 'scan_time'`). The detector predicate
`_entry_spot` gates on **`status == 'populated_at_stage'`**, not on `source`, so
it accepts the scan_time-sourced marker. The predicate/capture join is
consistent; there was no gap to fix.

**Nuance the test now pins:** the scanner CARRIER labels its own source
`scanner_underlying_quote_mid`; the STAGE SEAM re-stamps the persisted marker
source to `scan_time`. Both labels are asserted so a rename on either side fails
loudly.

## Contract test (`test_scorable_join_readiness.py`)

Drives `build_scan_spot_capture → _populate_stage_leg_greeks →
_populate_stage_entry_spot → fetch_study_rows / is_scorable_row →
evaluate_and_maybe_enqueue_review`. Pins: (1) the real capture stamps a
scan_time populated marker; (2) the predicate accepts it and a typed-unavailable
(non-positive) scan marker is NOT scorable; (3) a scorable close enqueues
exactly once with `origin=event/new_scorable_close`; (4) a same-set second
ingest is suppressed; (5) a NEW scorable close changes the fingerprint → fresh
review; (6) live vs shadow scored in separate cohorts, zero mutations.
