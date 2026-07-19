# Owner-Decisions Orchestrator Results — 2026-07-19

ORCHESTRATOR=fable · SUBAGENTS=opus (adversarial review before every merge; serialized) ·
market CLOSED throughout · production-DB writes limited to the three migration-procedure actions
below (receipts in `risk_alerts`) + the fleet PROVISION (inactive) · ZERO broker writes · ZERO
fleet ACTIVATION · `ACTIVATE_FLEET` / `entries_paused` untouched.

Evidence labels: **VERIFIED-GITHUB** (merged squash SHA on main) · **VERIFIED-DEPLOYMENT**
(Railway per-merge deploy SUCCESS + container start) · **VERIFIED-DB** (Supabase row/receipt).
Verify all live flag VALUES on Railway per CLAUDE.md §1 — never trust this file for a value.

## Merged + deployed (serialized; per-merge all-services SUCCESS + broker/alert checks)

Each lane carried an adversarial review before merge. **VERIFIED-GITHUB + VERIFIED-DEPLOYMENT**
for every row.

| PR | squash SHA | lane | state / notes |
|---|---|---|---|
| #1278 | `1d1951d8` | TCM v2 routing-aware dual-run | OBSERVE-ONLY beside the frozen model (frozen model retains authority); promotion packet emitted, owner picks N; no promotion |
| #1280 | `79f4ba76` | F-BAN phantom REMOVED | dead reads / silent `[]` degradation / unfireable enforcement deleted; no-op proven BY CONSTRUCTION; `settings.banned_strategies` drift column ledgered for a later drop |
| #1282 | `3c3874e1` | greek-cap alert-only counterfactual | items 9+11 consolidated; reference caps INVERTED from envelope doctrine; headroom / would-block evidence only, NO enforcement (all caps 0) |
| #1281 | `4c12dafa` | H7 mandatory typed subreason | 5 canonical values + sentinel; E1→`quality_gate` adjudication; **owner ratification of `h7_dropped`-for-gate-deaths remains OPEN** |
| #1279 | `78c71a8e` | versioned policy registry + design | 3-anchor / 47-variant design of the 50; the provisioning trigger was HARDENED to one-way-draft after review |
| #1283 | `ed5d6f48` | continuous tier taper w/ hysteresis | DARK dual-run observe-only (no live consumer, no env flag in live code); activation packet `docs/specs/tier_taper_activation_packet.md`; conservative `[800,1000]` band offered as an alternative |
| #1284 | `7d95f143` | E19-2B preregistered protocol v2 | FROZEN (hash `50e7e237…`); execution BLOCKED — §7 `MINIMUM_DISTINCT_SOURCE_EVENTS` UNDEFINED in E19 doctrine, owner packet emitted; arm B content-pinned (manifest hash + config-hash-set fingerprint) |
| #1285 | `e161714f` | exact-leg OI capture + floor counterfactuals | observe-first, NO gate; floors: 100 code-anchored / 1000 doc-anchored / 250–500 labeled UNANCHORED |
| #1287 | `9b63dcc1` | single-leg one-contract shadow-only experiment | DARK (0 opt-in policies; no live pool change). Reviewer notes carried for the future wiring session — **R1:** the `execute_order` guard host is currently DORMANT; the real submit seam is `should_submit_to_broker`. **C1:** the VRP citation is UNWIRED |
| #1286 | `cef4e600` | event-driven model review | inert until the first scorable close; the quarantine-helper route was corrected after a CI catch; SQL-mirror fixture gaps noted for Phase-3 volume |

**Final code main: `cef4e600`** (this docs PR follows). All services deploy-verified at every step.

## Ledger reconciliation (Phase 1) — VERIFIED-GITHUB

The operator checkout's dirty `audit/ledger.md` (+281 local lines vs main) was adjudicated by a
three-way matrix (local vs main vs bundle): **verdict 0 PRESERVE / 4 REJECT**. The +281 was PURE
LAG — three sections byte-identical to main, one fully superseded. Disposition:

- Operator checkout **restored + fast-forwarded to main**. The blocking untracked reports were
  proven byte-identical to main's tracked copies, preserved, then replaced.
- The reconciliation-branch step was recorded as a **NO_SECTIONS_APPROVED no-op** (nothing to
  carry forward).
- Preservation archive lives **outside the repo, timestamped `20260718T2310Z`** (path contains a
  local username → not recorded here).
- **The nightly wrapper is now LIVE** for tonight's 00:00 CT run (the first wrapper-flow run;
  prior runs used the old cmd flow under the new task protections).

## DB actions — applied via the migration procedure, VERIFIED-DB (receipts in `risk_alerts`)

**NEVER REAPPLY.** All three applied from main verbatim via `mcp apply_migration` (never
`db push`), market closed.

1. `policy_registrations` migration — receipt `eac6a4b9…`.
2. **50-row approved seed in ONE fingerprinted transaction** — receipt `14ca10ab…`:
   50 rows / 50 distinct hashes / 0 mismatches / lineage 17-17-16 / 0 bindings.
3. `h7_subreason_check` constraint — `NOT VALID` then `VALIDATE`d — receipt `6c49ce87…`.

## Fleet PROVISIONED INACTIVE — VERIFIED-DB

- Fleet `b8b1ea1f…`, status **`pending_legacy_terminal`**.
- **50 inactive `$2,000` slots · 50 `shadow_only` portfolios · 0 policy bindings** (binding is
  activation's job — slots bind at activation from the 50 approved registry ids).
- **Idempotency PROVEN**: a re-run returns `already_provisioned` with 0 writes.
- 1 provision receipt · 0 activation receipts.
- **`ACTIVATE_FLEET` remains `false` — the fleet is NOT activated.**

## Dark / live states (explicit)

| capability | state |
|---|---|
| tier taper | DARK (no env flag in live code) |
| greek caps | counterfactual-only (all caps 0) |
| TCM v2 | observe-only (frozen model keeps authority) |
| single-leg experiment | DARK (0 opt-in policies) |
| exact-leg OI | observe-first, NO gate |
| E19-2B | BLOCKED (§7 minimum undefined) |
| event-driven model review | inert until the first natural scorable-close trigger |
| UI | BLOCKED_UI_FILE_OWNERSHIP (40 Palette PRs own the files) |

## Owner decisions still OPEN

1. E19 §7 `MINIMUM_DISTINCT_SOURCE_EVENTS` value.
2. `h7_dropped`-for-gate-deaths ratification.
3. **Fleet ACTIVATION authorization** (+ attestation; slots bind at activation from the 50
   approved registry ids) — the only remaining owner-gated fleet step; all other prerequisites met.
4. Single-leg opt-in policy designation.
5. TCM promotion N.
6. Tier-taper activation band choice.
7. Greek-cap arming.

## Migrations / broker / fleet-activation summary

Migrations APPLIED: three (above) — **NEVER REAPPLY**. Broker writes: ZERO. Fleet ACTIVATION:
NONE (`ACTIVATE_FLEET=false`, `entries_paused` untouched). Every SHA, flag value, and receipt in
this file is a POINTER — verify on GitHub / Railway / Supabase, never trust this file for a value.
