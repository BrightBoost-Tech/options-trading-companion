# Owner Packet 4 — Single-leg experiment OPT-IN designation

> **RATIFIED 2026-07-19** → see owner-ratifications-2026-07-19.md

**Decision:** designate which policies opt into the one-contract shadow-only
single-leg (long_call / long_put) experiment (PR #1287, DARK). Today **0**
policies opt in (verified DB) so the generator emits nothing. **This packet
executes nothing and mutates no registry row** — it recommends candidates and
states the mechanic by which an opt-in is created.

**Recommendation:** create **two** new opt-in draft registry rows —
`aggressive_anchor` config + flag (throughput arm) and `conservative_anchor`
config + flag (conviction arm) — and use their already-seeded, un-flagged
twins (`aggressive_anchor`, `conservative_anchor`) as the matched **controls**.
Rationale + disable criteria below.

---

## 1. The opt-in mechanic (state this first — it is load-bearing)

The single-leg generator is DARK by construction; a candidate is emitted only
if the policy's `policy_config` carries **`single_leg_experiment_enabled=true`**
AND routing is `shadow_only` AND all entry conditions pass AND exactly one
contract (`single_leg_experiment.py:9-28`, opt-in check `:230-236`, live-routing
refusal `:457-470`).

**The registry is IMMUTABLE post-approval.** All 50 rows are
`approval_status='approved'` (verified Supabase 2026-07-18) and their
`policy_config` is frozen — the provisioning trigger was hardened to
one-way-draft after review (#1279, owner-decisions-implementation-2026-07-19
§Merged). No existing `policy_config` can be edited to add the opt-in key.

Therefore **an opt-in requires NEW registry rows**: a `draft` row is authored
with the chosen anchor config **plus** `single_leg_experiment_enabled=true`
(and optionally the bounded keys `single_leg_max_iv_rank`,
`single_leg_min_directional_run`, `single_leg_max_debit_per_contract`),
carried through the draft→approve flow. This mints a distinct `config_hash`
(the flag changes the canonical config) — so the new opt-in row and its
un-flagged twin are naturally separated in the registry. **No existing row is
mutated.**

## 2. What the policy actually controls (honest scoping)

The experiment's discriminating gates — **low-IV** (`iv_rank < 20`, the
guardrails BUY convention), **strong directional** (signed 20-day run-up),
**no earnings** (14-day window), **strict liquidity** (spread guardrail +
OI/volume), **priceable capped debit**, and an **independent EV** — all live in
the generator, not the policy (`single_leg_experiment.py:30-48, 297-408`). The
policy chooses only: opt in or not, and the three bounded thresholds
(defaults: iv_rank ≤ 20, min run 0.03, max debit $150/contract).

So "which policy opts in" does **not** change whether low-IV/direction/liquidity
hold — the generator enforces those identically for every opt-in policy. What
the policy choice changes is **sample throughput** (`max_positions_open`,
`max_suggestions_per_day`) and **conviction filtering** (`min_score_threshold`)
of the surrounding cohort, i.e. how many single-leg candidates get a slot. The
candidates below are chosen on that basis.

## 3. Best two opt-in candidates + one control

Anchors from `docs/specs/fleet_policy_design_50.md` (§Anchors, VERIFIED-DB):

| role | base config | max_positions | max_sugg/day | min_score | why |
|---|---|---|---|---|---|
| **opt-in #1 (throughput arm)** | `aggressive_anchor` + flag | 4 | 4 | 30 | highest slot count + lowest score gate ⇒ maximum single-leg sample volume; base is the live champion config, so the experiment rides the most-vetted parameter set. Shadow-only routing keeps it off the live pool by construction (`:457-470`). |
| **opt-in #2 (conviction arm)** | `conservative_anchor` + flag | 2 | 2 | 70 | high-conviction, low-volume contrast — tests whether the surrounding cohort's score gate starves single-leg candidates the generator would otherwise pass. Two arms differing on throughput/conviction give a within-experiment contrast on one axis. |
| **control** | `aggressive_anchor` + `conservative_anchor` (already-seeded, **no** flag) | — | — | — | the 50 seeded rows all lack the opt-in key (verified: `single_leg_optin=0`), so they are controls by construction. Pairing each opt-in row with its un-flagged twin isolates the flag's effect — same config, single-leg emission is the only difference. |

Why each satisfies the experiment assumptions:
- **Low-IV / direction / liquidity:** satisfied identically by the generator
  for both opt-in rows (they are policy-independent gates) — so the two arms
  are directly comparable on those axes.
- **Shadow-only isolation:** both anchors' fleet routing is `shadow_only`;
  the generator's `LIVE_ROUTING_FORBIDDEN` structural guard (`:457-470`) plus
  the execution-seam guard `execution_router.assert_single_leg_shadow_only`
  make a live emission impossible regardless of the flag.
- **One contract:** every emitted candidate is `contracts==1` by invariant
  (`SingleLegCandidate`, `:140-162`) — capital is not the variable; sample
  count is, which is exactly what the two arms vary.

Keeping the two opt-in arms anchored (not variant configs) also keeps the
experiment legible: the anchors are verbatim `policy_lab_cohorts.policy_config`
values, so a single-leg result is attributable to a named, existing cohort
shape rather than a one-off variant.

## 4. Disable-evidence criteria (when to turn the experiment off)

Disable (drop the opt-in draft, or revert to 0 opt-in policies) on any of:

1. **Structural breach:** a `LIVE_ROUTING_FORBIDDEN` rejection ever fires on a
   policy the operator believed shadow-only, OR any single-leg order reaches
   `execution_router` broker-submit — the shadow-only invariant is the
   experiment's licence; a breach ends it immediately.
2. **No honest signal:** the injected EV estimator abstains
   (`EV_UNAVAILABLE` / `EV_ESTIMATOR_UNAVAILABLE`) on a large majority of
   otherwise-qualifying candidates over a review window — H9 says an
   unpriceable leg rejects, but a persistent estimator dark means the
   experiment can produce no evidence and should pause, not accumulate empty
   cycles.
3. **Adverse shadow economics:** once shadow single-leg round-trips
   accumulate, if realized debit-decay bleed on the shadow book is
   consistently worse than the cohort's spread structures on a
   basis-normalized read (`docs/specs/shadow_fill_realism.md` caveats apply —
   shadow fills are fiction at 5–17× size; compare labels, not raw P&L), the
   historical DON'T-BUILD verdict (commits `9f002e3e` / `0ddb3fea`) stands and
   the experiment is retired.

## 5. Not done here

No registry row is created, mutated, approved, or opted-in by this packet. The
recommendation is a design; authoring the draft rows, approving them, and the
future production wiring that supplies the independent EV estimator
(reviewer note R1: the real submit seam is `should_submit_to_broker`; C1: the
VRP citation is still unwired — owner-decisions-implementation-2026-07-19
§#1287) are separate owner-gated steps.

---

## APPROVAL TOKEN

> **`SINGLE_LEG_OPT_IN=aggressive_anchor+flag, conservative_anchor+flag;
> CONTROLS=aggressive_anchor, conservative_anchor`** — authorizes authoring
> TWO new `draft` `policy_registrations` rows (the two anchor configs plus
> `single_leg_experiment_enabled=true`) through the draft→approve flow, with
> their un-flagged seeded twins as matched controls. No existing registry row
> is mutated (the registry is immutable post-approval); the experiment stays
> shadow-only and DARK until an approved opt-in row exists.
