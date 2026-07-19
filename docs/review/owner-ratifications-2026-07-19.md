# Owner Ratifications — 2026-07-19 (v1)

**Document version:** v1 (first record; supersede only by a higher-versioned
record in a reviewed commit).

**What this is:** a durable RECORD of the owner's decisions on the seven
Phase-4 owner packets (`docs/review/owner-packet-1..7`). **This document
RECORDS; it ACTIVATES nothing.** No flag is flipped, no migration is applied,
no registry row is inserted or mutated, no env var is set, no broker order is
placed, no frozen protocol is edited. Every decision below names the **later,
separately-gated activation/code step** that actually enacts it — and every
such step remains operator-only (forbidden to the audit loop and to every
agent, CLAUDE.md §1). Verify all live values on their sources
(Supabase / Railway / Alpaca), never on this file (CLAUDE.md §1 Truth
Doctrine).

**Scope guard (why nothing here is an activation):** the frozen E19-2B
protocol (`docs/specs/e19_2b_preregistered_protocol.md`, `PROTOCOL_VERSION:
e19_2b_protocol_v2`, LF-normalized SHA-256
`50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c`) is **NOT
modified by this record** — the immutability pin
(`packages/quantum/tests/test_e19_2b_preregistration.py`) stays green, which
is itself the proof that recording decision 3's number here did not silently
reshape the preregistration.

---

## Decision matrix (at a glance)

| # | Packet | Owner decision (RECORDED) | Enacted now? | The later activation / code step |
|---|---|---|---|---|
| 1 | `owner-packet-1-fleet-activation.md` | Authorize `small_tier_v1` 50×$2,000 shadow-fleet activation — **but blocked** until the Sunday wrapper nightly PASS + a clean Monday natural-runtime cycle, then a separate explicit token | **No** — fleet stays `pending_legacy_terminal` | Operator issues token `FLEET_ACTIVATION_AUTHORIZED=1` (both workers) + `execute_activation` with confirm literal `EXECUTE-SHADOW-FLEET`, idempotency key, the 50-slot payload reproducing the binding manifest, and the §4 attestation — after both evidence gates PASS |
| 2 | `owner-packet-2-h7-ratification.md` | **RETAIN** `h7_dropped` parent + typed `h7_subreason` (`H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON`) | Already the shipped state | **None** — ratifies merged code (#1281 `4c12dafa`); no CHECK widening, no writer change |
| 3 | `owner-packet-3-e19-minimum.md` | `E19_MINIMUM_DISTINCT_SOURCE_EVENTS = 8` (first-verdict floor; re-review before a second verdict) | **No** — the frozen protocol is untouched; `EXECUTION_STATUS` stays BLOCKED | Adopt the number into the protocol via the protocol's OWN change procedure (§13): re-version to v3 + re-freeze (new doc `PROTOCOL_VERSION` + updated SHA-256 pin in the same reviewed commit) |
| 4 | `owner-packet-4-single-leg-optin.md` | Two draft single-leg opt-in policy designs (`aggressive_anchor`+flag throughput arm, `conservative_anchor`+flag conviction arm) + their un-flagged seeded twins as matched controls | **No** — registry immutable; **0/50** opt-in rows unchanged; generator stays DARK | Author TWO NEW `draft` `policy_registrations` rows through the draft→approve flow (no existing row mutated); experiment stays shadow-only + DARK until an approved opt-in row exists |
| 5 | `owner-packet-5-tcm-promotion.md` | `TCM_V2_PROMOTION_N = 15` (conservative) + packet-5 coverage requirements (≥2 strategies, ≥1 qty>1, $0-commission premise unbroken, reviewed dry-run) | **No** — dual-run stays observe-only; `ENABLE_LIVE_TCM_MODEL=false` | Promotion review after **15** broker-routed realized entries meeting all coverage conditions, THEN operator flips `ENABLE_LIVE_TCM_MODEL=1` |
| 6 | `owner-packet-6-tier-taper.md` | **PREFER** the conservative never-loosen review band **`[800, 1000]`** | **No** — engine unchanged; taper stays DARK; `ENABLE_LIVE_TIER_TAPER` unset | ⚠ Conflict: the MERGED engine's band is symmetric ±10% **`[900, 1100]`** (`tier_taper.py` `BAND_PCT=0.10`). Per the conflict rule the engine is **NOT** altered here; activation requires the **band-reconciliation code step first** (change band edges to `[800,1000]` + `ENGINE_VERSION` bump), then the DARK observation window, then `ENABLE_LIVE_TIER_TAPER=1` |
| 7 | `owner-packet-7-greek-caps.md` | **Plan A** staged (alert-only 2wks → soft-size → never-block) | **No** — caps stay **0**; `ENABLE_LIVE_GREEK_CAPS=false` | Populate greeks on legs at stage time + meet §3 minimum coverage (complete coverage, 0 sign_mismatch, vertical+condor+mixed evidence); each stage past A0 armed only by `ENABLE_LIVE_GREEK_CAPS=1` |

---

## 1 — Shadow-fleet activation: AUTHORIZED-IN-PRINCIPLE, EVIDENCE-BLOCKED

**Packet:** `owner-packet-1-fleet-activation.md`.

**Recorded decision.** The owner authorizes activation of the provisioned-
but-inactive `small_tier_v1` 50×$2,000 shadow fleet **in principle**, but
holds it **blocked** until the natural-evidence prerequisites clear, in order:

1. **Sunday wrapper nightly PASS** — the first wrapper-flow nightly produces a
   clean dated report.
2. **Monday natural-runtime cycle** — one `2026-07-20` scheduler-origin scan
   cycle producing natural `candidate_terminal_dispositions` +
   `option_quote_provenance` rows, confirming the runtime pipeline is healthy
   before the fleet starts consuming decision events.
3. **Re-run the dry-run** (`plan_activation`) that morning; confirm it still
   reads `READY_TO_ACTIVATE` and the attestation validates.

**Enacted now?** No. The fleet stays `pending_legacy_terminal`; it is inert
while shadow-only with zero broker exposure. The 2026-07-19 dry-run already
read `READY_TO_ACTIVATE` (packet §3), but readiness is not authorization.

**Later activation step (operator-only, a separate explicit token).** After
gates 1–3 PASS, the operator sets `FLEET_ACTIVATION_AUTHORIZED=1` (strict
`=1`) on **both** workers and calls `execute_activation` with the confirm
literal `EXECUTE-SHADOW-FLEET`, an idempotency key, the 50-slot
`p_policy_registrations` payload reproducing the binding manifest fingerprint,
and the §4 attestation (stale-order reconciliation receipts + a tz-aware
`legacy_terminal_verified_at` + `attested_by`). Absent the token, dry-run is
the only available surface. **Activation stays forbidden to the loop and to
agents.** Confirm the §3 legacy-terminal reconciliation receipts (the packet
notes a doc-lag discrepancy — the RPC's in-transaction re-verification is the
authoritative check) before issuing the token.

---

## 2 — H7 disposition: RETAIN `h7_dropped` + typed subreason

**Packet:** `owner-packet-2-h7-ratification.md`.

**Recorded decision.** `H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON` — retain the
current parent disposition `h7_dropped` with a mandatory typed
`detail->>'h7_subreason'` (`quality_gate` for the E1 round-trip-BP / gate-death
class). The top-level-new-parent alternative is **NOT** adopted.

**Enacted now?** This decision ratifies the ALREADY-MERGED state (#1281,
squash `4c12dafa`): the writer emits the typed subreason, the opt-in DB
backstop CHECK (`ctd_h7_subreason_required`) is live, and the contract test
pins the allowlist to the writer's frozenset. The 10-value disposition CHECK
in `20260717100000_candidate_terminal_dispositions.sql` is untouched.

**Later code step: NONE.** Retain means no CHECK widening, no writer change,
no contract-test change; every existing `WHERE disposition='h7_dropped'`
reader stays valid. (The alternative — a new top-level disposition value —
would have required a CHECK-widening migration + writer + contract-test change
and would break those readers; it is recorded here only as the rejected
option.)

---

## 3 — E19-2B minimum distinct source events = 8 (RECORDED, protocol NOT re-versioned)

**Packet:** `owner-packet-3-e19-minimum.md`.

**Recorded decision.** `MINIMUM_DISTINCT_SOURCE_EVENTS = 8` — the first-verdict
floor for the minimum `COUNT(DISTINCT decision_event_id)` that must accrue
under the `small_tier_v1` epoch before an E19-2B head-to-head verdict may be
READ, chosen as the #1051 8-close convergence convention (the smallest
system-native threshold that still meaningfully gates), **with a standing note
to re-review before a second verdict.**

**Enacted now? No — and this is the load-bearing distinction.** The frozen
E19-2B protocol (`docs/specs/e19_2b_preregistered_protocol.md`,
`PROTOCOL_VERSION: e19_2b_protocol_v2`, LF-normalized SHA-256
`50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c`) is **NOT
modified by this record.** The protocol still reads `MINIMUM_DISTINCT_SOURCE_
EVENTS` as UNDEFINED in E19 doctrine and `EXECUTION_STATUS: BLOCKED`; the
immutability pin (`test_e19_2b_preregistration.py`) stays green. This record
notes the ratified number; it does not write it into the frozen plan.

**Later code step: protocol re-version to v3 (its OWN change procedure).**
Adopting the value into the protocol is an owner-gated re-freeze per the
protocol's §13 change procedure: re-version the doc to a `v3` block/file
carrying the number **and its rationale**, and update
`FROZEN_PROTOCOL_SHA256` + `PROTOCOL_VERSION` in
`test_e19_2b_preregistration.py` in the **same reviewed commit** (the hash diff
is the visible record that the preregistration changed). Only then does
`EXECUTION_STATUS` move from BLOCKED to gated-on-threshold — and it remains
also gated on §10 gate 1 (fleet activated, decision 1 above) and §10 gate 3
(capital-basis parity). No number is invented and no E19-2B run happens by
this record.

---

## 4 — Single-leg opt-in: two draft designs + matched controls (NO row inserted)

**Packet:** `owner-packet-4-single-leg-optin.md`.

**Recorded decision.** Two single-leg (long_call / long_put) shadow-only
experiment opt-in **designs**:

- **opt-in #1 (throughput arm):** `aggressive_anchor` config + `single_leg_
  experiment_enabled=true` (highest slot count, lowest score gate → maximum
  single-leg sample volume; base is the live-champion config).
- **opt-in #2 (conviction arm):** `conservative_anchor` config + the same flag
  (high-conviction, low-volume contrast).
- **controls:** the already-seeded, un-flagged `aggressive_anchor` and
  `conservative_anchor` twins — controls by construction (they lack the opt-in
  key), pairing each opt-in row with its un-flagged twin to isolate the flag's
  effect.

**Enacted now? No — the registry is immutable and nothing is inserted.** All
50 registry rows are `approval_status='approved'` with frozen `policy_config`
(the provisioning trigger is one-way-draft since #1279). Today **0/50**
policies carry the opt-in key, so the single-leg generator emits nothing and
stays DARK. **This record mutates no registry row.**

**Later code step: author NEW draft registry rows.** Because the registry is
immutable post-approval, an opt-in requires **NEW `draft` `policy_
registrations` rows** (each anchor config **plus** `single_leg_experiment_
enabled=true`, optionally the bounded keys) carried through the draft→approve
flow — which mints a distinct `config_hash` and naturally separates the opt-in
row from its un-flagged twin. No existing row is mutated. The experiment stays
shadow-only (structural `LIVE_ROUTING_FORBIDDEN` guard + execution-seam guard)
and DARK until an approved opt-in row exists. The production EV-estimator
wiring (reviewer notes R1/C1) is a further separate owner-gated step. Disable
criteria (structural breach / no honest EV signal / adverse shadow economics)
are in packet §4.

---

## 5 — TCM v2 promotion threshold N = 15 (RECORDED; promotion is a later review)

**Packet:** `owner-packet-5-tcm-promotion.md`.

**Recorded decision.** `TCM_V2_PROMOTION_N = 15` (the conservative threshold):
the routing-aware commission model may be promoted into the decision path only
when **all** hold — **≥ 15** broker-routed realized entries with known
commission, spanning **≥ 2 distinct strategies**, with **≥ 1 fill qty > 1**,
the **$0-commission premise unbroken** (0 broker-routed options fills with
non-zero `fees_usd`), and a **reviewed decision-impact dry-run**.

**Enacted now?** No. The TCM v2 dual-run stays observe-only (PR #1273/#1278
merged); the frozen `TransactionCostModel` keeps sole authority;
`ENABLE_LIVE_TCM_MODEL=false`. Recording N does not promote anything. (N
counts realized broker-routed entries joined at close — not shadow, not
internal, which are typed UNAVAILABLE; the current live realized pool is
small, so reaching 15 implies accruing more live fills first — consistent with
learning-mode.)

**Later activation step (operator-only).** After **15** qualifying realized
examples meet all coverage conditions, a promotion review confirms the gate,
THEN the operator flips `ENABLE_LIVE_TCM_MODEL=1` (strict `=1`, behavioral
opt-in) on both workers. Only commission changes; slippage/spread carry from
the frozen model unchanged. Rollback: unset the flag → frozen fee instantly.
If by N the strategy-mix or qty>1 coverage is unmet, do **not** promote on
count alone.

---

## 6 — Tier taper: PREFER `[800, 1000]` — engine NOT altered, reconciliation required first

**Packet:** `owner-packet-6-tier-taper.md`.

**Recorded decision.** The owner PREFERS the **conservative never-loosen
review band `[800, 1000]`** for the $1,000 micro↔small cliff taper — proposed
≤ current everywhere (no `would_loosen` region), landing exactly on small's
0.85 at $1,000.

**⚠ Conflict with merged code — the engine is NOT altered by this record.**
The MERGED tier-taper engine (`packages/quantum/services/analytics/
tier_taper.py`, shipped DARK #1283) currently carries the **symmetric ±10%
band `[900, 1100]`** (`BAND_PCT = 0.10` → `BAND_LO = 900.0`, `BAND_HI =
1100.0`; hysteresis inner band `[950, 1050]`; `ENGINE_VERSION =
"tier_taper.v1"`). Per the conflict rule (CLAUDE.md: do not alter the engine
to match a doc; the disagreement IS the finding), this record **does not touch
the engine** — it records the owner's preferred band and the fact that it
differs from the shipped band.

**Enacted now?** No. The taper is DARK / observe-only (no live sizing
consumer, no live env flag); `ENABLE_LIVE_TIER_TAPER` is unset. Recording the
preference changes no sizing.

**Later code step: band reconciliation FIRST, then observation, then arm.**
Activation of the owner's preferred band requires, in order: (1) a
**band-reconciliation code step** — change the engine's band edges from
`[900,1100]` to `[800,1000]` (a one-line band change) with an `ENGINE_VERSION`
bump (the monotonicity proof and tests carry over; endpoints 720 → 850 stay
monotone); (2) a live sizing consumer built; (3) ≥1–2 weeks of DARK
`cycle_metadata.tier_taper` observation confirming the payload tracks equity
as the before/after matrix predicts; (4) operator flips
`ENABLE_LIVE_TIER_TAPER=1` (strict, default-OFF) — no market-hours
activation. Until the reconciliation code step ships, the shipped band remains
`[900,1100]` and the two must not be conflated.

---

## 7 — Greek caps: Plan A staged (caps stay 0 tonight)

**Packet:** `owner-packet-7-greek-caps.md`.

**Recorded decision.** `GREEK_CAPS_STAGED_PLAN = A` — the staged path:
alert-only for ≥2 weeks → **soft-size** (warn + down-weight toward cap
headroom) → **never hard-block** (soft-size is the terminal ceiling behavior).
Plan B (hard-block the single tightest row) is recorded as the rejected
alternative.

**Enacted now? No — caps stay 0.** The greek-cap surface shipped alert-only /
observe-only (PR #1282): it arms nothing, blocks no entry, scales no size,
writes no `risk_alerts` row, reads no cap flag. `ENABLE_LIVE_GREEK_CAPS=false`.
The greek envelope is DOUBLE-dormant (no leg jsonb has ever carried a `greeks`
key AND all four caps default 0), so today every reference row reads
`would_block=None` (unavailable) — there is no honest greek exposure to cap
(H9: arming against fabricated zeros is forbidden).

**Later code step: populate greeks + meet minimum coverage, then arm per
stage.** The binding prerequisite is populating greeks on legs at stage time
(from the snapshots that already carry them). Arm nothing until, over a review
window: `greeks_coverage.complete = true` on real books; **0 `sign_mismatch`**
between `portfolio_greeks` and the canonical signed aggregate; and structural
evidence across **vertical + condor + mixed** books. Each stage past A0 is
armed only by `ENABLE_LIVE_GREEK_CAPS=1` (strict `=1`, default-OFF,
behavioral) and is instantly reversible by unsetting it. Nothing is armed by
this record.

---

## Reversal / correction of this record

This is a docs-only record. To correct or supersede a recorded decision,
author a higher-versioned ratification record (or amend in a reviewed commit)
— never by editing a live control, a migration, or the frozen protocol. None
of the seven later steps above is authorized by this document; each remains
its own operator-gated action.
