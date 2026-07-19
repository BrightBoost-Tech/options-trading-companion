# Sunday-Implementation Orchestrator Results — 2026-07-19

ORCHESTRATOR=fable · SUBAGENTS=opus (adversarial review before every merge; serialized) ·
market CLOSED throughout · **ZERO broker writes · ZERO production-DB writes · ZERO migrations ·
ZERO env changes · ZERO fleet mutations this run** · `ACTIVATE_FLEET` / `entries_paused`
untouched.

Evidence labels: **VERIFIED-GITHUB** (merged squash SHA on main) · **VERIFIED-DEPLOYMENT**
(Railway per-merge deploy SUCCESS + container start) · **VERIFIED-DB** (Supabase read /
recompute — this run made NO writes). Verify all live flag VALUES on Railway per CLAUDE.md §1 —
never trust this file for a value.

## Merged + deployed (five; serialized; per-merge all-services SUCCESS + broker/alert checks)

Each lane carried an adversarial (Fable central) review before merge. **VERIFIED-GITHUB +
VERIFIED-DEPLOYMENT** for every row. Serialized merge order: #1296 → #1299 → #1297 → #1298 →
#1300.

| PR | squash SHA | lane | state / notes |
|---|---|---|---|
| #1296 | `8a7908f1` | ⑤ scorable-outcome join readiness | end-to-end producer→consumer contract test; **COMPLETE verdict — no join gap** (the challenger-scorable spine is proven wired end to end); both spot source labels pinned (scan-time capture vs typed-unavailable) |
| #1299 | `fdf5b55c` | TCM v2 multi-fill realized accrual | side-flip boundary handled; per-side **all-or-unavailable** sums (a partial-known side is typed UNAVAILABLE, never silently summed as partial); AMD proof `$1.30` true vs `$0.65` prior undercount; observe-only |
| #1297 | `df87fe93` | single-leg one-contract selection | deterministic tie-breaker **EV → delta → debit → lexical**; **DARK, 0 opt-in, zero production callers** (contract selection for opted-in policies is the next slice; nothing selects today) |
| #1298 | `4ffca2b1` | owner ratifications v1 | **7 decisions RECORDED, none activated**; the frozen **E19 protocol hash is UNTOUCHED** (`test_e19_2b_preregistration.py` stays green); **taper band conflict recorded** — the merged engine carries `[900,1100]` (`BAND_PCT=0.10`) while the owner ratified `[800,1000]`; per the conflict rule the engine is NOT altered, reconciliation is a **later code step** |
| #1300 | `27204bd0` | Monday consolidated evidence reader | 12 natural-evidence sections, **four-state honesty** per section (`OK` / `HONEST-EMPTY` / `FAILED-FETCH` / `NOT-FETCHED` — a failed fetch is never scored as zero, H9); operator prompt `docs/review/monday-evidence-operator-prompt-2026-07-20.md`; read-only, pure function of its payload |

**Final code main: `27204bd0`** (this docs PR follows). All services deploy-verified at every
merge.

## Phase 1 — Sunday nightly under the wrapper: **WRAPPER_PARTIAL**

The 07-19 00:00 CT shim launched the new nightly runner and a **VALID FULL audit report was
produced** (SHA-pinned `17141967`, **0 critical / 0 high**). BUT the runner's contract markers
did **not** land in the operator `cron.log`:

- the runner's **start/end markers**, **heartbeats**, **fresh-worktree path**, and **completion
  ping** are absent from the operator cron log;
- the run manifest shows `workspace.path = '.'` — **no `%LOCALAPPDATA%` fresh worktree** was
  materialized; the runner ran with `cwd='.'` semantics.

⇒ **the nightly-runner reliability P1 stays OPEN.** The audit itself ran and is clean; the
wrapper *contract* (fresh worktree + markered lifecycle + ping) did not complete — hence
PARTIAL, not PASS.

**Morning items (operator):**

1. Fix the marker / fresh-worktree wiring — the runner executed with `cwd='.'` instead of a
   `%LOCALAPPDATA%` worktree, so start/end markers + heartbeats never reached the cron log.
2. **Check the 07-19 dead-man ping at the provider** — the completion ping did not land in the
   cron log, so confirm at the provider whether the ping fired (a silent DOWN there is the
   APScheduler/BE/RQ/worker-died signal, not merely a log gap).

**New finding — F-RUNNER-BROKER-CREDS.** The scrubbed broker snapshot came back
`available: false` — broker creds are **unset in the shim env**. The snapshot is scrubbed and
non-blocking by design, but the runner's shim environment does not carry the broker read creds,
so the snapshot section is empty-by-config, not empty-by-market. Recorded for the morning
wiring fix (not a trading-control issue).

## Phase 2 — Fleet activation dry-run (signed replication): **SIGNED_DRY_RUN_PASS**

A read-only, zero-write replication of the activation binding — **not** a service invocation.

- **`plan_activation` is proven zero-write / no-env by CODE** (`:639-685`) — it reads and
  plans; it opens no write transaction and reads no activation env.
- **Fingerprint replicated two independent ways to the SAME hash:**
  `6f8d1499…` recomputed from the ops-bundle manifest **AND** rebuilt from pure DB truth (the
  50 approved registry rows re-derived) — both produce the identical binding fingerprint.
- **350 / 350 binding field-cells match** between the bundle manifest and the DB-truth rebuild.
- **Fleet counts byte-identical before / after:** 1 fleet (`pending_legacy_terminal`) · 50
  inactive · 0 active · 0 bindings · 50 `shadow_only` · **0 activation receipts**.
- **ACTIVATION REMAINS FORBIDDEN.** Activation needs the Monday natural-evidence PASS **and** a
  separate explicit operator token per **ratification decision 1**
  (`FLEET_ACTIVATION_AUTHORIZED=1` on both workers + `execute_activation` with the confirm
  literal + idempotency key + the 50-slot payload + §4 attestation). Readiness is not
  authorization; this run recorded read-only replication only.

## States after this run (all dark / observe-only; nothing armed)

- **single-leg experiment: DARK, 0 / 50 opt-in** — deterministic one-contract selection now
  exists (#1297) but nothing selects: no registry row carries the opt-in key, zero production
  callers.
- **TCM v2: observe-only** — multi-fill accrual coverage extended (#1299); the frozen model
  keeps sole authority; owner ratified promotion **N = 15** (a later review, not this run).
- **tier taper: DARK** — **band reconciliation pending**: engine ships `[900,1100]`, owner
  ratified `[800,1000]`; the engine is unaltered until the reconciliation code step.
- **greek caps: all four = 0** (no-limit) — counterfactual only; Plan A staged (ratification 7).
- **OI floor: NO gate** — observe-first; counterfactual until Monday natural rows.
- **E19-2B: BLOCKED** — the ratified `MINIMUM_DISTINCT_SOURCE_EVENTS = 8` **awaits protocol v3
  re-freeze** (its own §13 change procedure: new `PROTOCOL_VERSION` + updated hash pin in one
  reviewed commit); execution also still waits on the fleet epoch.
- **UI: BLOCKED_UI_FILE_OWNERSHIP** — the front-end files remain owned by the parallel Palette
  PR fleet; no UI change here.
- **ZERO migration / production-DB-write / broker / env / fleet mutations this run.**
- **Operator checkout: hash `ddb9e073`** — the only drift from main is the **nightly's own
  artifacts** (the untracked dated report + the runner's local outputs), not a code divergence.

## Re-ranked build order (verified outcomes only)

1. **nightly-runner marker / worktree / ping fix + ping-provider check** (P1, morning) — fix the
   fresh-worktree + markered-lifecycle wiring so the wrapper contract completes; confirm the
   07-19 dead-man ping at the provider; also carry F-RUNNER-BROKER-CREDS (shim broker creds
   unset).
2. **Monday ≥ 17:45Z** — run `monday_evidence_reader` (operator prompt) → review → **fleet
   activation decision** (packet 1 + ratification 1; standing = `READY_TO_ACTIVATE`).
3. **⑤ + event-review natural accrual** — the scorable-outcome join is proven ready (#1296); the
   first scorable close auto-triggers the model review.
4. **Later code steps from the ratifications** — taper band reconciliation (`[900,1100]` →
   `[800,1000]` + `ENGINE_VERSION` bump) · E19 protocol v3 re-freeze (adopt minimum 8) ·
   single-leg draft policy rows (two NEW `draft` registrations) · TCM promotion review at N = 15.
5. **UI** — when the Palette PR fleet clears the front-end file ownership.

## Provenance

- Five merges, each adversarially (Fable-central) reviewed, serialized, per-merge all-services
  deploy SUCCESS.
- Phase 1 = **WRAPPER_PARTIAL** (valid clean audit report `17141967`, 0 crit/high; wrapper
  markers/worktree/ping did not complete — nightly-runner P1 stays OPEN).
- Phase 2 = **SIGNED_DRY_RUN_PASS** (fingerprint `6f8d1499…` recomputed two ways to one hash;
  350/350 field-cells; counts byte-identical; ACTIVATION still forbidden).
- This run created NO migrations, made NO production-DB writes, changed NO env, touched NO
  broker, and did NOT mutate the fleet. `ACTIVATE_FLEET` stays `false`; `entries_paused`
  untouched.
