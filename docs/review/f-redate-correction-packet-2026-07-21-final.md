# F-REDATE-0718 — Finalized Correction Packet (NOT EXECUTED)

- **Finding:** F-REDATE-0718 (learning-history provenance) — first reported in the
  2026-07-19 FULL audit (`audit/reports/2026-07-19.md` §A3), carried un-remediated
  through 2026-07-21.
- **Recommendation:** **`CORRECT_ALL_CONFIRMED_ROWS`** (retained — see §10).
- **Status:** review artifact only. **The correction SQL in §7 was NOT executed.**
  This packet was produced by a strictly read-only lane (SELECT / information_schema /
  pg_catalog only). **Zero DB rows were written.**
- **Base:** `origin/main` `04b376b5`. **Census clock:** 2026-07-21 (DB `now()`,
  UTC). **Supabase:** `etdlladeorfgdmsopzmz` (project pointer, CLAUDE.md §6).
- **Owner scope:** the single owner UUID (`75ee12ad…`, CLAUDE.md §6). No raw user
  UUID / account id printed.

---

## 1. What happened (one paragraph)

On 2026-07-18 the **F-CREDIT-SIGN** historical data correction (marker fingerprint
`b780271c…`, weekend run) touched 20 shadow rows in `learning_feedback_loops` and
set their `updated_at` to the correction-transaction time
(**`2026-07-18 14:21:36.128964+00`**, identical to the microsecond on all 20 rows —
a single-statement signature). The view `learning_trade_outcomes_v3` derives
`closed_at = COALESCE(lfl.updated_at, lfl.created_at)`, so those 20 rows now present
a **`closed_at` of 2026-07-18** instead of their true close dates (2026-03-17 →
2026-07-14). Row **values are correct** — only the effective close *date* is wrong.
The distortion is a provenance/date defect, not a P&L defect.

Why it matters: the paper-performance / go-live / walk-forward windows key on
`closed_at` and read `is_paper=TRUE`. A +$33,856.46 cluster of legacy-$100k-era
iron-condor shadows therefore reads as *fresh closes on 07-18*, inflating every
paper window that opens from here (§6). **Live calibration is NOT affected** — it is
protected by the `is_paper=false` gate (§5, VERIFIED-CODE).

---

## 2. Verdict summary

| Item | Result | Proof layer |
|---|---|---|
| Row count still exactly 20 | **YES — 20** | VERIFIED (read-only recount) |
| Row-SET stable (same ids, single-txn marker) | **YES** | VERIFIED |
| Aggregate fingerprint `4f1999db…` byte-reproduced | **NO — recipe uncommitted; see §3** | NOT_PROVEN (string only) |
| Canonical fingerprint (recipe defined here) | `97b0dfdbeb2f38ad13714350d2e15d8b` | VERIFIED |
| Broker-live rows in set | **ZERO** | VERIFIED (triple check, §4) |
| Correction is date-only + idempotent + reversible | **YES** (§7–§8) | VERIFIED-by-construction |
| Any DB row written by this lane | **NO** | attested |

---

## 3. Row census (recomputed) — count + fingerprint

**Selection predicate** (deterministic; isolates exactly the F-REDATE set —
`updated_at::date='2026-07-18'` matches *no other* rows in the table):

```sql
SELECT * FROM learning_feedback_loops
WHERE updated_at::date = DATE '2026-07-18'
  AND is_paper = true
  AND updated_at IS DISTINCT FROM created_at
  AND outcome_type = ANY (ARRAY['trade_closed','individual_trade']);
```

- **Count = 20** (recomputed 2026-07-21). Unchanged since the prior census.
- **Canonical aggregate fingerprint (recipe DEFINED here, so future re-runs are
  byte-deterministic):**
  `md5(string_agg(id::text, ',' ORDER BY id))` = **`97b0dfdbeb2f38ad13714350d2e15d8b`**
  (12-char: `97b0dfdbeb2f`).

**Honesty note on the prior `4f1999db…` string.** The prior 2026-07-21 census
reported an aggregate fingerprint `4f1999db…`, but its *recipe* was never committed
to the repo (no census doc, no receipt row carries it). I tried 21 plausible
recipes — id-set (concat / comma / newline / space / upper-case delimiters),
content hashes (id∥created_at∥pnl), full-row `::text`, sha256 variants, the
`suggestion_id` / `trace_id` sets, and `count|sum` / summary-tuple hashes — **none
reproduced `4f1999db…`.** Per the truth doctrine (verify-before-asserting; a
disagreement is a finding, never averaged or fabricated) I do **not** claim a match.
What *is* proven and is the substantive invariant: the **row-SET is identical** —
count = 20, the id-set is stable (§ Appendix A), and all 20 carry the identical
single-transaction `updated_at` marker. The literal-string continuity to
`4f1999db…` is **NOT_PROVEN**; the set-identity continuity is **VERIFIED**. This
packet adopts `97b0dfdbeb2f…` as the go-forward canonical fingerprint and pins its
recipe so the ambiguity cannot recur.

---

## 4. Per-field verification (all 20 rows)

| Field | Observed | Note |
|---|---|---|
| `id` (PK) | 20 distinct (Appendix A) | learning_feedback_loops primary keys |
| `created_at` (TRUE close) | 2026-03-17 … 2026-07-14 | the truth; **preserved**, never touched |
| `updated_at` (INCORRECT) | **`2026-07-18 14:21:36.128964+00`** on ALL 20 | single-statement signature of the b780271c correction |
| `is_paper` | `true` — all 20 | none broker-live |
| `strategy` | `IRON_CONDOR` — all 20 | shadow-only structure (never live per doctrine) |
| `regime` | `chop` (16) / `elevated` (4) | — |
| `outcome_type` | `trade_closed` — all 20 | all v3-eligible (view filter) |
| `window` (lfl col) | `NULL` — all 20 | v3 coalesces to `ts.window`; contamination is via `closed_at`, not this column |
| `model_version` | `NULL` — all 20 | pre-model-version era shadows |
| `suggestion_id` | present — all 20 | all satisfy the v3 JOIN to `trade_suggestions` |
| `pnl_realized` (Σ) | **+$33,856.46** | matches audit "+$33.8k phantom 20-close cluster" |
| symbol (from `details_json->>'symbol'`) | META, GOOG, TSLA, GOOGL, ISRG, ADBE, MSFT, AMZN, AMD, QQQ | no typed symbol column — rides in details_json |

Routing / cohort: all 20 are **paper/shadow** (`is_paper=true`); linked
`paper_orders` carry only `alpaca_paper` / `internal_paper` / `shadow_blocked`
execution modes (§4-broker). These are legacy-$100k-era iron-condor shadows
(magnitudes up to +$8,668.50), consistent with the shadow-fleet ledger being
partly fiction (CLAUDE.md §8) — an independent reason their dates must not leak
into a fresh window as if newly closed.

**Broker-live exclusion (triple check):**

| Check | Result |
|---|---|
| `lfl.is_paper = true` | 20 / 20 |
| `lfl.is_paper` NOT true | 0 |
| `v3.is_paper = false` (broker-live in the view) | **0** |
| `v3.is_paper = true` | 20 |
| linked `paper_orders` with `execution_mode='alpaca_live'` | **0** |
| execution modes seen on the set | `alpaca_paper, internal_paper, shadow_blocked` (no `alpaca_live`) |

---

## 5. Why live calibration is safe (VERIFIED-CODE)

`packages/quantum/analytics/calibration_service.py:390-391`:

```python
if _train_live_only_enabled():          # CALIBRATION_TRAIN_LIVE_ONLY, default-ON
    query = query.eq("is_paper", False) # excludes all 20 (is_paper=true)
```

`CALIBRATION_TRAIN_LIVE_ONLY` is default-ON (CLAUDE.md §4 #1076). All 20 rows are
`is_paper=true`, so they never reach a live-applied EV/PoP multiplier. `model_review`
(#1286) keys on the suggestion-id SET, not `closed_at`, and the rows lack scorability
markers — reported unaffected (`model_review.py:271-280`, `:248-264`). The exposure
is confined to the paper-window consumers in §6.

---

## 6. Paper-window contamination (measured, census clock 2026-07-21)

Windows key on `closed_at` (= `COALESCE(updated_at, created_at)`), `is_paper=TRUE`.
"contaminated" = current view; "post-correction" = with `updated_at:=created_at`
applied to the 20 (mirrors the v3 join + filter + is_paper resolution):

| Window | Contaminated (now) | Post-correction | Phantom removed |
|---|---|---|---|
| `go_live` 14d | **22** | **3** | 19 |
| `context` 30d | 23 | 4 | 19 |
| `walk_forward` 60d | 32 | 13 | 19 |

The **19-row phantom delta is constant** across every window: 19 of the 20 have a
true close date (03-17…04-10) outside even the 60d window, so they *only* appear
because of the 07-18 re-date; the 20th (QQQ, true 07-14) legitimately falls inside
all three windows but is still mis-dated to 07-18 and so is corrected too. The
`go_live` 14d figure (**3→22**) reproduces the prior census exactly; the 30d/60d
background counts differ from the prior census only by clock drift in the *genuine*
close population (older real closes aging out) — the phantom magnitude is invariant.

**Downstream re-derivation set** (no code change required — all read the view, which
recomputes automatically once `updated_at` is restored):

- `learning_trade_outcomes_v3` (the view — `closed_at` reverts by construction)
- `services/go_live_validation_service.py:331, 521, 1085, 1455, 2409, 2669, 2913`
  (paper-performance / go-live windows, `is_paper=TRUE`)
- `analytics/walk_forward_autotune.py:403`
- `context_endpoints.py:40, 50`
- (informational, already safe) `analytics/calibration_service.py:373` — gated
  `is_paper=false`; `analytics/model_review.py:147` — suggestion-id-set keyed.

No materialized table, cache, or persisted aggregate stores these rows' `closed_at`;
re-derivation is purely the next read of the view. (If any operator report was
snapshotted between 07-18 and correction time, it should be re-generated.)

---

## 7. THE CORRECTION SQL — idempotent, guarded, atomic — **NOT EXECUTED**

Single atomic `DO` block (mirrors the weekend pattern: single transaction,
row-locked, gate-checked, rollback-on-mismatch). **Date-only:** it touches
`updated_at` and nothing else. **Idempotent:** a re-apply matches 0 rows and returns
a clean no-op (no receipt, no error). **Fail-closed:** any set that is neither the
audited 20 nor already-corrected aborts the whole block.

```sql
-- ============================================================================
--  F-REDATE-0718 CORRECTION  —  REVIEW ARTIFACT, NOT EXECUTED
--  Restores learning_feedback_loops.updated_at := created_at (date-only) on the
--  20 shadow rows re-dated by the 07-18 F-CREDIT-SIGN correction (fp b780271c).
--  v3.closed_at = COALESCE(updated_at, created_at) then reverts to the true close.
--  Scope: is_paper=true ONLY. ZERO broker-live rows in the set (verified).
-- ============================================================================
DO $fredate$
DECLARE
  v_n     int;
  v_fp    text;
  v_rows  jsonb;
  v_left  int;
BEGIN
  -- (1) Measure the target set (count + canonical fingerprint).
  SELECT count(*), md5(string_agg(id::text, ',' ORDER BY id))
    INTO v_n, v_fp
  FROM learning_feedback_loops
  WHERE updated_at::date = DATE '2026-07-18'
    AND is_paper = true
    AND updated_at IS DISTINCT FROM created_at
    AND outcome_type = ANY (ARRAY['trade_closed','individual_trade']);

  -- (2) IDEMPOTENT no-op: nothing left to correct.
  IF v_n = 0 THEN
    RAISE NOTICE 'F-REDATE-0718: 0 rows match — already corrected, no-op.';
    RETURN;
  END IF;

  -- (3) FAIL-CLOSED guard: only the exact audited set may proceed.
  IF v_n <> 20 OR v_fp IS DISTINCT FROM '97b0dfdbeb2f38ad13714350d2e15d8b' THEN
    RAISE EXCEPTION
      'F-REDATE-0718 guard: unexpected set (n=%, fp=%). Aborting — no write.',
      v_n, v_fp;
  END IF;

  -- (4) Capture the reversible pre-image (for the receipt / rollback).
  SELECT jsonb_agg(jsonb_build_object(
           'id', id,
           'old_updated_at', updated_at,
           'restored_updated_at', created_at) ORDER BY id)
    INTO v_rows
  FROM learning_feedback_loops
  WHERE updated_at::date = DATE '2026-07-18'
    AND is_paper = true
    AND updated_at IS DISTINCT FROM created_at
    AND outcome_type = ANY (ARRAY['trade_closed','individual_trade']);

  -- (5) THE CORRECTION (date-only; no value column touched).
  UPDATE learning_feedback_loops
     SET updated_at = created_at
   WHERE updated_at::date = DATE '2026-07-18'
     AND is_paper = true
     AND updated_at IS DISTINCT FROM created_at
     AND outcome_type = ANY (ARRAY['trade_closed','individual_trade']);

  -- (6) POST-GUARD idempotency proof: predicate must now match 0 rows.
  SELECT count(*) INTO v_left
  FROM learning_feedback_loops
  WHERE updated_at::date = DATE '2026-07-18'
    AND is_paper = true
    AND updated_at IS DISTINCT FROM created_at
    AND outcome_type = ANY (ARRAY['trade_closed','individual_trade']);
  IF v_left <> 0 THEN
    RAISE EXCEPTION 'F-REDATE-0718 post-guard: % rows still re-dated', v_left;
  END IF;

  -- (7) AUDIT RECEIPT (durable; embeds the reversible pre-image; see §9).
  INSERT INTO risk_alerts (alert_type, severity, resolved, message, metadata)
  VALUES (
    'data_correction', 'info', true,
    'F-REDATE-0718 correction: restored updated_at:=created_at on 20 shadow '
    || 'learning_feedback_loops rows re-dated by the 07-18 F-CREDIT-SIGN pass; '
    || 'date-only; is_paper=true only; 0 broker-live; v3.closed_at reverts to '
    || 'true close (2026-03-17..2026-07-14).',
    jsonb_build_object(
      'finding',                 'F-REDATE-0718',
      'correction_fingerprint',  '97b0dfdbeb2f38ad13714350d2e15d8b',
      'row_count',               v_n,
      'redate_marker',           'b780271c',
      'old_updated_at_uniform',  '2026-07-18T14:21:36.128964+00:00',
      'true_close_range',        '2026-03-17..2026-07-14',
      'pnl_realized_sum',        33856.46,
      'egress_owner',            'operator_data_correction',  -- relay-skip (self-owned)
      'rows',                    v_rows
    ));

  RAISE NOTICE 'F-REDATE-0718: corrected % rows; receipt written.', v_n;
END
$fredate$;
```

Notes:
- The whole block is one statement → one implicit transaction → all-or-none. A guard
  `RAISE EXCEPTION` rolls back the UPDATE *and* the receipt insert.
- `severity='info'` + `egress_owner` ⇒ the #1111 relay (critical/high only) never
  egresses it; it is a silent durable receipt.
- Re-apply path: (1) finds 0 → (2) `RETURN` clean no-op. No exception, no write.

---

## 8. ROLLBACK SQL — **NOT EXECUTED**

**Canonical (receipt-driven, fully reversible).** Reads the pre-image embedded in
the correction receipt and restores each row's original `updated_at`:

```sql
-- Replace :receipt_id with the risk_alerts.id written by §7 step (7).
DO $rollback$
DECLARE
  v_rows jsonb;
BEGIN
  SELECT metadata->'rows' INTO v_rows
  FROM risk_alerts
  WHERE id = :receipt_id AND alert_type = 'data_correction'
    AND metadata->>'finding' = 'F-REDATE-0718';
  IF v_rows IS NULL THEN
    RAISE EXCEPTION 'F-REDATE-0718 rollback: receipt % not found', :receipt_id;
  END IF;

  UPDATE learning_feedback_loops lfl
     SET updated_at = (e->>'old_updated_at')::timestamptz
    FROM jsonb_array_elements(v_rows) AS e
   WHERE lfl.id = (e->>'id')::uuid
     AND lfl.updated_at IS DISTINCT FROM (e->>'old_updated_at')::timestamptz;

  INSERT INTO risk_alerts (alert_type, severity, resolved, message, metadata)
  VALUES ('data_correction', 'info', true,
    'F-REDATE-0718 ROLLBACK: re-applied the 07-18 updated_at pre-image from '
    || 'receipt ' || :receipt_id::text,
    jsonb_build_object('finding','F-REDATE-0718','action','rollback',
                       'source_receipt', :receipt_id));
END
$rollback$;
```

**Shorthand (all 20 shared one old value).** Because every row's original
`updated_at` was the identical `2026-07-18 14:21:36.128964+00`, the restore reduces
to (id-set in Appendix A):

```sql
UPDATE learning_feedback_loops
   SET updated_at = TIMESTAMPTZ '2026-07-18 14:21:36.128964+00'
 WHERE id IN ( /* the 20 ids in Appendix A */ )
   AND updated_at IS DISTINCT FROM TIMESTAMPTZ '2026-07-18 14:21:36.128964+00';
```

Prefer the receipt-driven form — it survives even if the id-set or the shared-value
assumption ever changes, and it is self-documenting.

---

## 9. Audit-receipt design

The correction WOULD write one `risk_alerts` row (§7 step 7):

| Column | Value |
|---|---|
| `alert_type` | `data_correction` |
| `severity` | `info` (silent durable receipt; not relay-egressed) |
| `resolved` | `true` |
| `message` | human summary (date-only, 20 rows, 0 broker-live, true-close range) |
| `metadata.finding` | `F-REDATE-0718` |
| `metadata.correction_fingerprint` | `97b0dfdbeb2f38ad13714350d2e15d8b` |
| `metadata.row_count` | 20 |
| `metadata.redate_marker` | `b780271c` (the originating 07-18 correction) |
| `metadata.old_updated_at_uniform` | `2026-07-18T14:21:36.128964+00:00` |
| `metadata.pnl_realized_sum` | 33856.46 |
| `metadata.egress_owner` | `operator_data_correction` (relay-skip) |
| `metadata.rows[]` | `{id, old_updated_at, restored_updated_at}` × 20 — the reversible pre-image |

This mirrors the existing `migration_apply` receipt convention (severity `info`,
typed metadata) and makes the correction self-reversing from its own receipt.

---

## 10. Recommendation — **`CORRECT_ALL_CONFIRMED_ROWS`** (retained)

RETAIN the prior recommendation. All 20 rows are confirmed: exactly the audited set,
fingerprint-guarded, `is_paper=true`, **zero broker-live**, values-correct, date-wrong.
Correcting all 20 (a) restores true `closed_at` in the v3 view for every paper-window
consumer, (b) removes the constant 19-row phantom from `go_live` / `context` /
`walk_forward`, and (c) does so with a date-only, idempotent, atomically-guarded,
fully-reversible operation that cannot touch live calibration (already gated) or any
broker-live row (none exist in the set). No partial-subset or `DEFER` alternative is
warranted — the set is homogeneous and the fix is measurement-truth restoration, not
a behavioral change (no flag, gate, threshold, stop, universe, or cadence moves).

**Execution remains operator-gated** and must not run during market hours; it is a
DB write, so it is out of scope for the audit loop and for this lane.

---

## 11. Self-review

- **Date-only?** YES — the UPDATE sets only `updated_at := created_at`; no P&L,
  quantity, or value column is touched.
- **Idempotent?** YES — after one apply, the predicate (`updated_at::date='2026-07-18'
  AND updated_at IS DISTINCT FROM created_at`) matches 0 rows, and the block returns a
  clean no-op (step 2), not an error.
- **Reversible?** YES — the pre-image `{id, old_updated_at}` is embedded in the
  receipt; §8 restores it exactly. All 20 shared one old value, so the shorthand
  rollback is also exact.
- **Guarded / fail-closed?** YES — count-must-be-20 AND fingerprint-must-match, else
  the atomic block aborts with no write; a post-guard proves the re-date is gone.
- **Zero broker-live rows?** YES — triple-verified (`lfl.is_paper`, `v3.is_paper`,
  linked `paper_orders` execution modes); live calibration is separately gated
  `is_paper=false`.
- **Did this lane write ANY DB row?** **NO.** Read-only throughout (SELECT /
  information_schema / pg_catalog). The §7–§9 SQL is a review artifact and was not
  executed.

---

## Appendix A — the 20-row id-set (learning_feedback_loops PKs)

Ordered by `id` (the fingerprint ordering). Fingerprint of this exact list:
`md5(string_agg(id, ','))` = `97b0dfdbeb2f38ad13714350d2e15d8b`.

```
0176fb1a-b9c6-453d-9536-ef50a5f5f816   META   +1745.00   true_close 2026-03-17
02379e1c-8e30-4d4f-8311-d9c6f1c4c934   META   +1672.50   true_close 2026-03-17
18a75dc2-5ac9-4c80-8777-a8ac134c9059   META   +1280.00   true_close 2026-03-17
2276e2f7-1f5c-4e22-9f44-0ea094955959   ISRG   +1072.50   true_close 2026-03-17
24a306da-6602-4df8-8498-c320dfad28b8   GOOG   + 183.00   true_close 2026-03-18
386efce7-aeed-425d-9343-f735ff8a6a74   TSLA   + 833.00   true_close 2026-03-17
59c75e7c-ad83-43e8-b959-8c081ae40b86   GOOGL  + 421.00   true_close 2026-03-17
647b5acd-1a7b-4bac-9684-9b85bd54c35c   GOOG   + 479.00   true_close 2026-03-17
7a6fa79c-3df6-4778-92a7-e3f85f54469b   META   +8668.50   true_close 2026-03-18
9272674d-d3fd-457b-9f96-3ba203c7a513   TSLA   +1080.00   true_close 2026-03-17
a7210a41-c428-46ef-8aac-07b5fd33e8a1   QQQ    - 224.04   true_close 2026-07-14
aa0eee72-8b05-4f6d-a1b3-0faaac2cb790   GOOGL  + 930.00   true_close 2026-04-03
aa64670b-a59c-4385-a7ad-047103c4717d   MSFT   +1099.50   true_close 2026-03-18
ac11df2a-bada-4acd-9c26-5077917bbb4a   TSLA   +6142.00   true_close 2026-03-18
b024a9fe-502e-4c32-a828-d771734d6325   ADBE   +5554.50   true_close 2026-03-18
d2a6a5f8-e74b-49d6-b94c-857b2ab73395   AMZN   + 946.00   true_close 2026-04-06
f02b34be-b091-4235-be41-95861f041ce9   AMZN   + 946.00   true_close 2026-04-03
f51d5bcf-1cc0-40d4-a014-5b49c9b3ed84   GOOGL  + 340.00   true_close 2026-03-17
fa3a7018-03d1-471c-8ac6-d16eea8be5f6   AMD    - 242.00   true_close 2026-04-10
ff569793-7486-428b-9692-d568fbf33ba3   GOOGL  + 930.00   true_close 2026-04-06
```

All 20 share `updated_at = 2026-07-18 14:21:36.128964+00` (incorrect), `is_paper=true`,
`strategy=IRON_CONDOR`, `outcome_type=trade_closed`. Σ `pnl_realized` = **+$33,856.46**.

---

## Appendix B — read-only queries used (reproducibility)

1. `information_schema.columns` introspection of `learning_feedback_loops`,
   `learning_trade_outcomes_v3`, `risk_alerts` (no typed symbol column confirmed).
2. `pg_get_viewdef('learning_trade_outcomes_v3')` — confirmed VIEW,
   `closed_at = COALESCE(lfl.updated_at, lfl.created_at)`.
3. Distribution of `updated_at::date` × `is_paper` × `updated_at IS DISTINCT FROM
   created_at` — isolated exactly 20 rows on 2026-07-18.
4. Full 20-row field pull (created_at, updated_at, window, strategy, regime,
   outcome_type, is_paper, model_version, pnl_realized, symbol, v3-eligibility).
5. Broker-live triple check (`lfl.is_paper`, `v3.is_paper`, `paper_orders`
   execution modes).
6. Paper-window contamination measure (contaminated vs post-correction, mirroring
   the v3 join + filter).
7. Canonical fingerprint + full id-set.
8. Downstream consumer code references (grep, VERIFIED-CODE) +
   `calibration_service.py:390-391` is_paper gate (Read).
