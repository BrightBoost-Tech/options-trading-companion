# OI Enrichment — Operator Decision Packet (2026-07-21)

**Subject:** merged exact-leg Open-Interest (OI) enrichment (`OI_ENRICHMENT_ENABLED`, PR #1325).
**Author:** Lane E (Opus), read-only assessment. **Base:** `origin/main 04b376b5`.
**Scope:** docs-only. NO code change, NO env change, NO flag flip, NO deploy. This packet
recommends an operator action; it does not perform one.

---

## RECOMMENDATION: `ENABLE_OBSERVE_ONLY`

Enable `OI_ENRICHMENT_ENABLED=1` on the `otc` worker **post-close**, gated on one named
pre-enable check (the active fetcher must resolve to the Alpaca-contracts source — see
Runbook step 1). No code change is required; the module is complete, observe-only, and
kill-switched. If the pre-enable check fails (Alpaca trading-API creds absent so the
fetcher degrades to Polygon, which supplies OI **values but no observation dates**), the
correct fallback is `KEEP_OFF` until creds are provisioned — a Polygon-only enable spends
secondary-provider calls without meeting the observation-date objective that is the whole
point of the module.

**Why not `KEEP_OFF` outright:** the provenance surface is today 100 %
`provider_date_unavailable` (evidence below). That evidence base cannot mature — and the
future OI-floor question cannot ever be answered — unless the enrichment starts running.
The enable is safe by construction (byte-identical scan proven end-to-end; instant kill;
no decision consumer), which matches the learning-mode posture (accrue correct evidence at
low, reversible cost).

**Why not `NEEDS_CODE_CHANGE`:** the module is correctly built and wired (single observe-only
consumer; H9 discipline preserved; hard leg cap + rate budget; typed failures never
fabricated). No correctness or safety defect requires a code change to enable. One efficiency
nit (no cross-candidate fetch cache) exists but is bounded by the window budget and is not
worth a change now — logged below as a future optimization, not a blocker.

---

## Evidence

### Module & wiring (VERIFIED-CODE, base `04b376b5`)
- `packages/quantum/services/oi_enrichment.py` — `is_oi_enrichment_enabled()` (line 77-84):
  unset/empty/any non-truthy → **OFF**; only `1/true/yes/on` (case/space-insensitive) enables.
  Fails **safe** (a secondary provider call is a real cost).
- Convenience entrypoint `enrich_selected_legs` (line 404-428): flag OFF → returns the base
  `oi_by_contract` **same object** (byte-identical no-op, zero provider calls). Flag ON but no
  fetcher configured → also a no-op (no fabrication).
- Scanner seam `packages/quantum/options_scanner.py:4061-4065`: `enrich_selected_legs(legs,
  _oi_by_contract, symbol=symbol)` runs ONLY on a **gate-PASSED** candidate leg set (after the
  spread gate, before the `verdict="passed"` provenance record), wrapped fail-soft.
- Its output `_oi_map_passed` is consumed at **exactly one site** — `options_scanner.py:4086`,
  `oi_by_contract=_oi_map_passed` passed to `provenance_recorder.record_spread_verdict(...)`.
  `grep` confirms `_oi_map_passed` appears only at lines 4061 / 4065 / 4086. It never enters
  `trade_dict`, scoring, ranking, sizing, or any execution path.

### Observe-only safety proof (VERIFIED-CODE + VERIFIED-CI)
- No gate/rank/sizing consumer of OI exists anywhere. `resolve_leg_oi` /
  `compute_oi_counterfactuals` are consumed only by (a) the observe-only provenance recorder
  and (b) read-only report scripts (`scripts/analytics/monday_evidence_reader.py:685`,
  `scripts/analytics/oi_floor_observe_report.py`). The would-be gate `ENABLE_LIVE_OI_FLOOR`
  is **unbuilt** — it appears only in docstrings/comments (`quote_provenance.py:158,302`;
  the report script), read by no code. The floor candidates `[100,250,500,1000]` are
  **counterfactual-only** (`quote_provenance.py:300-304`: "would_pass/would_fail … this
  recorder only records").
- Byte-identical scan under ON-vs-OFF is pinned by
  `test_oi_enrichment_scanner_wiring.py::test_scan_decisions_byte_identical_on_vs_off` — same
  candidates, same rejection histograms, same emission counts; only the OBSERVATION differs.
- Zero-provider-calls-when-OFF is pinned by
  `test_oi_enrichment_safety_contract.py::TestZeroProviderCallsWhenOff` (the fetcher builder
  is never even reached when OFF).

### Current OI availability (VERIFIED-RUNTIME, production DB, 2026-07-21)
`option_quote_provenance` exists; migration `20260718034013 option_quote_provenance` applied.
The only populated cycle is **2026-07-20** (the Monday scan, 79 `leg_set` + 21 `fetch_event`
rows, 16:00–17:34 UTC):

| Metric (leg_set rows with an OI block, n=79) | Count | Share |
|---|---|---|
| `any_oi_unavailable = true` (≥1 leg dark) | 74 | **93.7 %** |
| `any_oi_unavailable = false` (all legs priced) | 5 | 6.3 % |
| zero legs with available OI | 74 | 93.7 % |

Per-leg (n=180 legs across those rows):

| oi_source | oi_available | oi_freshness / date_provenance | legs |
|---|---|---|---|
| `alpaca` (primary) | **false** | `provider_date_unavailable` | 170 (94.4 %) |
| `polygon` (fallback) | true | `provider_date_unavailable` | 10 (5.6 %) |

**Reading:** the module's premise is confirmed live — the Alpaca-primary snapshot carries **no
OI** (170/180 legs dark). The only OI available today arrives via the **Polygon fallback** (10
legs), and even those carry **no OI observation date** (`provider_date_unavailable`). So
**0 % of legs currently have a genuine OI observation date.**

### What enrichment would run against (VERIFIED-RUNTIME, 2026-07-20 cycle)
Enrichment runs only on **passed** leg sets: 26 passed rows / 74 legs that cycle (25 rows had
dark OI); 20 were `selected`. Fan-out is bounded by (a) dedup on bare OCC within each call,
(b) the hard per-call leg cap `DEFAULT_MAX_LEGS_PER_CALL = 8`, and (c) the process-global
window budget `DEFAULT_MAX_CALLS_PER_WINDOW = 120 / 60 s`. The scan runs **one execution cycle
per trading day** (11:00 CT), so real-world cost is a **single small burst/day** (≤ ~74 GETs
worst-case, fewer after dedup) — comfortably under the 120-call window.

---

## Per-dimension assessment

**Provider choice — SOUND.** `make_default_fetcher` (line 375-401) prefers the Alpaca **trading
API** `/v2/options/contracts/{occ}` fetcher when `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` are
present (it returns BOTH `open_interest` AND `open_interest_date` — the only genuine OI-date
source), else Polygon `/v3/snapshot` (OI value, no date), else None (no-op). This is the
correct precedence: the date-bearing source is preferred, the date-less source is an honest
fallback, and absence degrades to a typed no-op — never fabrication.

**Genuine observation-date contract — HONORED.** `oi_observation_date` is the provider's real
OI date and is kept **separate** from `oi_retrieved_at` (retrieval/known-at). `oi_freshness`
is computed **only** from the observation date (`quote_provenance.py:264-284`), never inferred
from retrieval. A provider with no date stays typed `provider_date_unavailable`; a malformed
date → `malformed_date`. Polygon's `polygon_oi_fetcher` deliberately sets
`observation_date=None` (docstring line 293-297: "the value is real, the date genuinely
isn't supplied"). Freshness horizon `DEFAULT_OI_OBSERVATION_MAX_AGE_DAYS = 4`
(env `OI_OBSERVATION_MAX_AGE_DAYS`).

**Rate budget — SOUND.** Thread-safe `RateLimiter` enforces a rolling-window call budget +
optional min-interval; `allow()` returns False → caller records a typed `rate_limited`
outcome (never a fabricated value). One process-global limiter (`_global_limiter`) bounds the
whole scan's secondary fan-out. Defaults 120/60 s; env-overridable
(`OI_ENRICHMENT_MAX_CALLS_PER_WINDOW`, `_WINDOW_SECONDS`, `_MIN_INTERVAL_MS`).

**Leg cap — SOUND.** `DEFAULT_MAX_LEGS_PER_CALL = 8` is a hard ceiling per candidate (a
candidate is 1–4 legs), applied as `targets = targets[:cap]` **before** any fetch — a
whole-universe fan-out is impossible even on a malformed candidate.
Env `OI_ENRICHMENT_MAX_LEGS_PER_CALL`.

**Caching / dedup — ADEQUATE, one nit.** Within a call: bare-OCC dedup (`seen` set) + an
already-available OI is never re-fetched (`coerce_oi(existing.get("oi")) is not None` → skip),
so the 10 Polygon legs that already carry OI would not be re-fetched, and a real `0` is
preserved (pinned by `TestExistingZeroPreserved`). **Nit:** there is no *cross-candidate*
cache — the same dark contract selected in two different passed candidates in one cycle is
fetched twice (each `enrich_selected_legs` call dedups only its own legs). Bounded by the
window budget; a future optimization, not a blocker.

**Observation-date quality — the deciding dimension.** Today = **0 % genuine dates** (all
`provider_date_unavailable`). Post-enable date quality depends entirely on **which fetcher is
active**: Alpaca-contracts → genuine `open_interest_date` (freshness computable); Polygon →
still no date (same `provider_date_unavailable` the 10 fallback legs already show). This is
why the enable is **gated** on confirming the active fetcher (Runbook step 1).

**429 risk — LOW and typed-safe.** On 2026-07-20 the primary path saw **zero 429s** (14 clean
Alpaca fetch events, 1 `miss`, 6 Polygon fallbacks all due to `error` — not rate-limiting).
Enrichment hits a **different endpoint** than the market-data snapshot path (Alpaca trading
API contracts, or Polygon snapshot), so it draws on a separate rate budget and does not
contend with the primary chain fetch. Every fetcher is fail-soft: a 429/non-200/timeout →
typed `miss`/`error`, never a fabricated OI or date (pinned by `TestTimeoutTyped`,
`test_non_200_is_miss`).

**Rollback / kill switch — INSTANT.** Unset (or set falsy) `OI_ENRICHMENT_ENABLED` → the seam
reverts to a byte-identical no-op with zero provider calls (no code, no migration). See
Runbook.

---

## Enable runbook (NOT executed — operator, post-close only)

> Per DEPLOY DOCTRINE §2: an env change recycles the worker, so do this **after 20:00 UTC**
> (no mid-session recycle). Verify current values on Railway; never trust this doc for a value.

1. **Pre-enable gate (verify the date-bearing fetcher is active).** Confirm on the `otc`
   worker env that both `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` are present (name-only check;
   do not print values). If present → `make_default_fetcher` resolves to
   `alpaca_contracts_oi_fetcher` (genuine dates). If absent → it degrades to Polygon (no
   dates): **stop and choose `KEEP_OFF`** until creds are provisioned, or accept an
   availability-only (date-less) enable knowingly.
2. **Set the flag** on the `otc` worker (worker-background too, for symmetry, though the scan
   runs on `otc`):
   ```
   OI_ENRICHMENT_ENABLED=1
   ```
   Leave the four budget knobs at defaults (120/60 s, cap 8) for the first window.
3. **Recycle** the worker(s) so the RQ process picks up the env (workers don't hot-reload).
4. **Read-back (behavioral, not dashboard).** `OI_ENRICHMENT_ENABLED` is not in the 27-flag
   `[FLAG_ECHO]` allowlist, so confirm the effect from the **next scan cycle's** provenance
   rows, not a startup echo:
   ```sql
   SELECT
     count(*) FILTER (WHERE (details->'oi'->>'any_oi_unavailable')::boolean IS FALSE) AS rows_all_oi_available,
     count(*) AS leg_set_rows
   FROM option_quote_provenance
   WHERE record_type='leg_set' AND cycle_date = CURRENT_DATE AND details ? 'oi';

   -- genuine observation dates now arriving (expect >0 only via the alpaca_contracts fetcher):
   SELECT leg->>'oi_source' AS src, leg->>'oi_freshness' AS freshness, count(*) AS legs
   FROM option_quote_provenance,
        LATERAL jsonb_array_elements(details->'oi'->'legs') AS leg
   WHERE record_type='leg_set' AND cycle_date = CURRENT_DATE
   GROUP BY 1,2 ORDER BY legs DESC;
   ```
   Expect: `rows_all_oi_available` climbs from ~5/79 toward most passed rows, and
   `oi_source='oi_enrich'`/`alpaca_contracts` legs show `oi_freshness IN ('fresh','stale')`
   (a real date) rather than `provider_date_unavailable`.

## Rollback runbook (NOT executed — instant, any time)

Unset or falsify the flag on the worker(s) and recycle:
```
OI_ENRICHMENT_ENABLED=0        # or unset the variable entirely
```
The scanner seam immediately reverts to `return base_oi_by_contract` (same object) — a
byte-identical no-op, zero provider calls. No migration, no code revert. Because OI feeds no
gate/rank/sizing, rollback cannot affect any scan verdict, order, or size — only whether the
observe-only provenance rows carry enriched OI.

---

## Minimum natural observation window & acceptance criteria (before any FUTURE step beyond observe-only)

Enabling is observe-only; it authorizes **no** gate/threshold/floor. Before OI could ever be
trusted enough to justify *building* a live OI floor (`ENABLE_LIVE_OI_FLOOR`, a separate future
owner decision), observe for a **minimum of ~10 trading-day scan cycles (~2 calendar weeks)**.
Rationale: the scan produces one cycle/day, so ~10 cycles is the floor for a distribution; the
window must span ≥1 weekend + ideally a holiday so the 4-day freshness horizon is exercised
across session boundaries.

Acceptance criteria to grade at the end of the window (all must hold):
1. **Scan non-interference (hard gate):** candidates, rejection histograms, and emission
   counts remain byte-identical to the OFF baseline across the window (the observe-only
   invariant holds live, not just in test). Any drift → roll back and investigate.
2. **Genuine dates actually arrive:** a material and stable share of enriched legs carry
   `oi_freshness IN ('fresh','stale')` (a real `open_interest_date`), not
   `provider_date_unavailable`. If it stays `provider_date_unavailable`, the Alpaca-contracts
   fetcher is not active — the enable is not meeting its objective.
3. **Freshness is sane:** the `fresh`/`stale` split matches EOD-OI expectations (most dates
   within the 4-day horizon on trading days; `stale` only across long weekends/holidays). No
   `malformed_date`.
4. **No 429 storm / cost blowout:** no rise in `fallback_reason='429'` on the primary path,
   and enrichment `rate_limited` outcomes stay rare (the budget is not the binding constraint,
   or if it is, it is by design). Secondary-endpoint errors stay typed, never fabricated.
5. **0-vs-absent integrity:** enriched OI of `0` is recorded as a real value (not conflated
   with unavailable), and typed failures (`oi_enrich_miss`/`_error`/`_skipped_rate_limited`)
   are named in `oi_source`, never zeroed.

Meeting these criteria authorizes only *continued observation with trusted data*; a live OI
floor remains an independent, later, owner-gated code + decision step.

---

## Self-review
- **Recommendation:** `ENABLE_OBSERVE_ONLY` (gated on the Runbook step-1 fetcher check;
  `KEEP_OFF` fallback if creds absent). Exactly one.
- **Flag state:** `OI_ENRICHMENT_ENABLED` **remains OFF** — this packet does not enable it.
- **Env changes:** none. No variable set/changed by this work.
- **Code changes:** none required; module is complete and correctly observe-only. Docs-only PR.
- **New gate/rank/sizing consumer introduced:** none. OI still feeds only the observe-only
  provenance recorder + read-only report scripts.
- **Reversibility of the recommended action:** instant (unset the flag + recycle; byte-identical
  no-op). No migration, no data mutation.
