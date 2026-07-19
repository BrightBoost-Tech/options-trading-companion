# Parallel-Implementation Orchestrator Results — 2026-07-19

ORCHESTRATOR=fable · SUBAGENTS=opus (adversarial review before every merge; serialized) ·
market CLOSED throughout · **ZERO broker writes · ZERO production-DB writes · ZERO migrations ·
ZERO env changes · ZERO fleet mutations this run** · `ACTIVATE_FLEET` / `entries_paused`
untouched.

Evidence labels: **VERIFIED-GITHUB** (merged squash SHA on main) · **VERIFIED-DEPLOYMENT**
(Railway per-merge deploy SUCCESS + container start) · **VERIFIED-DB** (Supabase read /
recompute — this run made NO writes). Verify all live flag VALUES on Railway per CLAUDE.md §1 —
never trust this file for a value.

## Merged + deployed (six; serialized; per-merge all-services SUCCESS + broker/alert checks)

Each lane carried an adversarial review before merge. **VERIFIED-GITHUB + VERIFIED-DEPLOYMENT**
for every row. Serialized merge order: #1290 → #1289 → #1291 → #1293 → #1294 → #1292.

| PR | squash SHA | lane | state / notes |
|---|---|---|---|
| #1290 | `89a736807` | D3 ratio-blindness FIXED | `leg_full_contract_count` owner helper; a 1×2 ratio spread now scales to 150 (was ratio-blind); a 1:1 structure is byte-identical to the pre-fix path; `check_greeks` + `compute_stress_scenarios` both migrated to the helper. **§8 D3 line now RESOLVED** |
| #1289 | `b3f10031` | TCM v2 realized-accrual reporting | no schema change; the join spine (v2 stamp → realized close) is proven; **0 / 528 v2 stamps exist yet** — v2 accrues on post-#1278 cycles, so the report is empty-by-construction today |
| #1291 | `bd87025f` | SQL-mirror parity fixtures | 6 families, 78 tests; **ZERO defects found** (the SQL mirror already agreed with the Python path across all six families) |
| #1293 | `d60b7ad0` | fork / collection sweep | root cause = rq fork-context at import; 6 files fixed; 12-file subprocess harness added; **full-suite collection now 0 errors** |
| #1294 | `21e88e5f` | seven owner-decision packets | `docs/review/owner-packet-1..7`: (1) activation-after-Sunday+Monday · (2) RETAIN `h7_dropped` · (3) E19 minimum = **8** (alt 15) · (4) single-leg opt-in = two NEW draft registry rows + matched controls · (5) TCM N = **15** (alt 10) · (6) taper `[800,1000]` band · (7) greek caps Plan A staged |
| #1292 | `4851ec8d` | single-leg hard veto at the REAL submit seam | `should_submit_to_broker(order=…)` guard at **4 sites**; byte-identity proven against 100% of live rows; VRP second gate; raw-jsonb registry opt-in lookup (**0 / 50 enabled** → veto is dark); two repair cycles fixed stage-route fake signatures that were out of sync |

**Final code main: `4851ec8d`** (this docs PR follows). All services deploy-verified at every
merge.

Note the single-leg wiring correction: the 07-19 owner-decisions run (#1287) recorded reviewer
**R1** — the `execute_order` guard host was DORMANT and the real submit seam is
`should_submit_to_broker`. #1292 lands the veto at that REAL seam (4 sites), and reviewer **C1**
(the unwired VRP citation) is resolved as the veto's VRP second gate. The experiment stays DARK:
`0 / 50` policies opt in, so the veto never fires on the current pool.

## Fleet DRY-RUN (Phase 1, READ-ONLY) — VERIFIED-DB (reads only)

A read-only replication of the activation binding — **not** a service invocation, **not** a
write. Nothing in the DB changed.

- **Registry:** 50 / 50 approved; per-row hashes **recompute-clean** (each stored hash re-derived
  from its row content and matched).
- **Fleet counts BEFORE == AFTER, byte-identical:** 1 fleet (`pending_legacy_terminal`) · 50
  inactive slots · 0 active · 0 policy bindings · 50 `shadow_only` portfolios · 0 activation
  receipts.
- **Binding manifest fingerprint:**
  `6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad`
  (`ORDER BY policy_registration_id ASC`; spot-check anchors at slots 17 / 33 / 50).
- **All 13 replicated checks PASS ⇒ `READY_TO_ACTIVATE`.**
- Artifacts (manifest JSON + dry-run markdown) live in the **ops bundle** (outside the repo — the
  path contains a local username, so it is not recorded here).
- **ACTIVATION REMAINS FORBIDDEN.** There is **no un-activate RPC** — the only reversal is the
  retire path — so activation is irreversible-in-place and stays owner-gated. This dry-run is
  recorded as **read-only replication, not service invocation**.

## States after this run (all dark / observe-only; nothing armed)

- **single-leg experiment: DARK, 0 opt-in** — the veto now owns the REAL submit seam
  (`should_submit_to_broker`, 4 sites) but `0 / 50` registry rows opt in, so it cannot fire.
- **TCM v2: observe-only** — reporting only; the frozen model retains authority (owner picks N;
  the #1294 packet recommends N = 15).
- **tier taper: DARK** — no live consumer, no env flag in live code.
- **greek caps: all four = 0** (no-limit) — counterfactual / headroom evidence only.
- **OI floor: NO gate** — observe-first; floors stay counterfactual until Monday natural rows.
- **E19-2B: BLOCKED** — the frozen protocol's §7 `MINIMUM_DISTINCT_SOURCE_EVENTS` owner value is
  now recommended (8, alt 15) but not yet ratified; execution also waits on the fleet epoch.
- **event-driven model review: inert** — fires on the first scorable close.
- **ZERO broker / DB-write / migration / env / fleet mutations this run.**
- **Operator checkout: clean-behind** at hash `5c6ae8bf…` (no dirty tracked files; strictly
  behind main — a plain fast-forward pull, no reconciliation needed this run).
- **UI: still Palette-owned** — the front-end files remain owned by the parallel Palette PR fleet;
  no UI change here.

## Re-ranked build order (verified outcomes only)

1. **Runtime handoffs (not build slots):** Sunday nightly under the wrapper (verify the
   wrapper-flow run) · Monday natural evidence — now including `h7_subreason`-typed finals,
   exact-leg OI capture, scan-time spot on staged rows, first TCM-v2 stamps, and D3-corrected
   greeks on ratio structures.
2. **Owner decisions (the seven #1294 packets):** fleet **ACTIVATION first**, after Sunday +
   Monday PASS · `h7_dropped` retention · E19 minimum (8 / alt 15) · single-leg opt-in (two new
   draft registry rows) · TCM promotion N (15 / alt 10) · taper band (`[800,1000]`) · greek-cap
   arming (Plan A staged).
3. **⑤ + event-review natural accrual:** accumulate natural scorable outcomes; the #1286
   event-driven review fires on the first scorable close.
4. **Remaining wiring:** single-leg contract selection (the veto guards the seam; contract
   selection for opted-in policies is the next slice) · TCM v2 multi-fill accrual coverage.
5. **Cap / taper / OI / TCM activation decisions per the packets** (each consumes the natural
   evidence from item 1).
6. **E19-2B** after fleet activation (epoch) + the ratified §7 minimum.

## Provenance

- Six merges, each adversarially reviewed, serialized, per-merge all-services deploy SUCCESS.
- The fleet dry-run was a Phase-1 READ-ONLY replication — no writes, no service call, no
  activation.
- This run created NO migrations, made NO production-DB writes, changed NO env, touched NO broker,
  and did NOT mutate the fleet. `ACTIVATE_FLEET` stays `false`; `entries_paused` untouched.
