# E19-2B — Preregistered Analysis Protocol (FROZEN, v3)

    PROTOCOL_ID:        e19_2b_preregistration
    PROTOCOL_VERSION:   e19_2b_protocol_v3
    STATUS:             FROZEN — immutable once merged
    EXECUTION_STATUS:   BLOCKED
    EXECUTE_E19_2B:      false
    MINIMUM_DISTINCT_SOURCE_EVENTS = 8   (owner-ratified 2026-07-19; owner-packet-3)
    AUTHORED_AT:        2026-07-18 (v1, pre-market, RTH-closed, docs-only)
    RE-FROZEN_AT:        2026-07-18 (v2 — arm B pinned by CONTENT after #1279 merged)
    RE-FROZEN_AT_V3:     2026-07-20 (v3 — §7 minimum DEFINED = 8; nothing else changed)
    BASE_SHA:           79f4ba76 (branch feat/e19-2b-preregistration; science-freeze base — UNCHANGED in v3)
    V3_AUTHORING_SHA:   94aa6528 (origin/main at v3 re-freeze; provenance only, not a science re-pin)
    PREDECESSOR:        e19_2b_protocol_v2 (LF-normalized SHA-256
                        50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c —
                        HISTORICAL, IMMUTABLE, preserved unchanged; see §0)

> **Why this document exists.** E19-2B is the backlogged full counterfactual
> experiment: compare decision outcomes across a comparable fleet epoch (the
> 50-slot `small_tier_v1` shadow fleet — provisioned/activated later). The
> analysis MUST NOT be designed after the data is seen. This document freezes
> the versioned analysis plan NOW, before any fleet account is activated and
> before a single comparable outcome exists, so the eventual analysis cannot be
> p-hacked (arm selection, metric selection, stopping-time, or dedup chosen to
> flatter a result). It is preregistration in the scientific sense: the frozen
> plan is the contract; deviations are visible diffs, not silent choices.
>
> **This document DECIDES NOTHING and RUNS NOTHING.** It authorizes no trade,
> no promotion, no flag, no migration, no fleet provisioning or activation. It
> is a plan pinned to a hash. Execution remains BLOCKED (see §10).

---

## 0. Immutability convention (READ FIRST)

- This file is **frozen once merged**. Its byte content is pinned by SHA-256 in
  `packages/quantum/tests/test_e19_2b_preregistration.py` (constant
  `FROZEN_PROTOCOL_V3_SHA256`). Any edit changes the hash and FAILS that test —
  a deliberate, reviewable diff is the only way to change a frozen protocol.
- **v2 is preserved, immutable, and untouched.** This v3 is a NEW versioned
  artifact ALONGSIDE the frozen v2 file
  (`docs/specs/e19_2b_preregistered_protocol.md`, LF-normalized SHA-256
  `50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c`). The v2
  file's bytes, its `PROTOCOL_VERSION: e19_2b_protocol_v2`, and its
  `FROZEN_PROTOCOL_SHA256` pin are NOT edited or deleted — both hashes are
  pinned in the test, and a change to EITHER fails. A change to the analysis
  plan is **a new version** (a new file, as here), never an in-place rewrite of
  a decided section. The pinned hash and `PROTOCOL_VERSION` move together in one
  reviewed commit. This mirrors the #1051 "rollback = revert PR + owner
  sign-off" no-silent-mutation convention and CLAUDE.md §9's anti-#1126 rule
  (the wiring test exercises the real artifact, never a reimplementation).
- The doc pins UPSTREAM artifacts (module content hashes, migration ids, epoch
  identity — §12). The test pins THIS doc. The doc never embeds its own hash
  (that self-reference is impossible to compute); the doc-hash lives only in the
  test. That is the whole immutability chain.

### Version record (preregistration integrity)

- **v1 (2026-07-18):** initial freeze. Arm B (the 50 fleet policies) was defined
  by SHAPE only (50 slots) because the 50-policy manifest did not yet exist.
- **v2 (2026-07-18):** arm B pinned by CONTENT after PR **#1279** (squash
  `78c71a8e`) merged `docs/specs/fleet_policy_design_50.md` +
  `packages/quantum/policy_lab/fleet_policy_design.py` to main. Changes: §2 arm-B
  wording, §10 gate 2 (now SATISFIED), §12 (manifest content SHA-256 + the
  50-policy config-hash-set fingerprint replace the former PENDING block). **No
  metric, unit, censoring, dedup, stopping rule, promotion prohibition, or the
  §7 minimum-source-event adjudication changed** — the scientific plan is
  unchanged; only the previously-undefined arm-B identity became pinnable. The
  §7 minimum remained UNDEFINED and execution remained BLOCKED. v2 is
  HISTORICAL and IMMUTABLE (§0).
- **v3 (2026-07-20):** the §7 minimum is now **DEFINED = 8** distinct source
  decision events, adopting the value the owner RATIFIED on 2026-07-19
  (`docs/review/owner-ratifications-2026-07-19.md` decision 3;
  `docs/review/owner-packet-3-e19-minimum.md` — the #1051 8-close convergence
  convention, as a first-verdict floor with a standing note to re-review before
  a second verdict). **This is the ONLY substantive change v2 → v3.** Metrics
  (§4), arms (§2), the experimental unit / identity (§1), censoring (§5), dedup
  (§6), the stopping/optional-stopping rule (§8), the promotion prohibition
  (§9), the selection-bias note (§11), and the pinned upstream artifacts (§12,
  the frozen science, carried VERBATIM at the same science-freeze base
  `79f4ba76`) are all UNCHANGED from v2 — carried verbatim. Execution remains
  BLOCKED: v3 changes the §7 threshold VALUE only, not the block. The block now
  reads gated-on-threshold (§10 gate 4: value defined, threshold not yet met)
  and stays additionally gated on §10 gate 1 (fleet activated at a clean legacy
  boundary) and §10 gate 3 (capital-basis parity). No metric, arm, unit,
  censoring, dedup, or stopping rule changed. No E19-2B run is triggered by this
  document.

---

## 1. Experimental unit — the source decision-event identity

**The unit of analysis is the immutable market decision event, NOT a
micro-account row and NOT a suggestion clone.** Fifty accounts evaluating the
same source candidate is ONE decision event with fifty policy responses.

- **Identity column:** `policy_decisions.decision_event_id` (uuid, `NOT NULL`),
  defined `= suggestion_id` and made immutable by trigger
  `policy_decision_event_identity`. Source:
  `supabase/migrations/20260716060000_small_tier_shadow_fleet.sql:99-156`
  (applied to production 2026-07-17 05:22Z, tracked by NAME as
  `20260717052208 small_tier_shadow_fleet`). The column comment is doctrine:
  *"Immutable source suggestion UUID; COUNT(DISTINCT ...) is the evidence n."*
  (migration `:188-189`).
- **Canonical helpers (side-effect-free contract):**
  `packages/quantum/policy_lab/shadow_fleet.py`
  — `DECISION_EVENT_BASIS = "source_suggestion_id"` (`:26`),
  `normalize_decision_event_id()` (`:216-224`, fails closed on missing/invalid
  — never fabricates an id), `count_unique_decision_events()` (`:227-230`,
  docstring: *"Evidence n: unique market decisions, never account-row count."*).
  The module docstring (`:7-9`) states the sampling doctrine verbatim.

**Provenance fields that qualify a decision event for inclusion** (an
experimental unit is admitted only when its provenance is complete and typed —
never inferred):

1. **Run-origin provenance (#1251, squash `08e250d9`)** —
   `packages/quantum/jobs/origin.py`. Every `job_runs` row carries a typed
   `payload.origin` object stamped at enqueue time with a closed taxonomy
   (`scheduler` · `operator_signed_endpoint` · `internal_retry` · `manual_cli`
   · `replay` · `unknown_legacy`; `VALID_ORIGINS` `:60-67`). E19-2B admits ONLY
   decision events produced by a `scheduler`-origin production cycle; `replay`,
   `manual_cli`, and `unknown_legacy` events are excluded (they are not the live
   scheduled pipeline). The origin object also carries `code_sha` (`:132`) and
   `created_at` known-at semantics (`:133`).
2. **Ranking/cost + code provenance (#1231, migration
   `20260716155023_add_ranking_costs_to_trade_suggestions.sql`)** — each source
   suggestion (and every cohort clone) carries `ranking_costs` (the cost basis
   that travels with `risk_adjusted_ev`) and `code_sha` (the version that
   produced the row). Cloner writes both:
   `packages/quantum/policy_lab/fork.py:815-816`. Decision-tape deployment SHA
   is written full (Railway-authoritative) on the `decision_runs` path via
   `packages/quantum/services/replay/decision_context.py` +
   `packages/quantum/observability/lineage.get_code_sha`
   (pinned by `packages/quantum/tests/test_decision_git_provenance.py`).

**Admission rule (frozen):** a decision event enters the E19-2B sample iff it
has (a) a non-null immutable `decision_event_id`, (b) a `scheduler` run-origin,
and (c) a resolvable `code_sha` on the producing row. Any event missing any of
these is EXCLUDED and COUNTED as `provenance_incomplete` — never silently
dropped, never patched with a default (H9).

---

## 2. Comparison arms

The arms are **existing design families**, not invented policies. Exactly three
arm classes are compared, all on the SAME set of admitted decision events:

- **ARM A — CHAMPION (live-promoted policy).** The currently promoted cohort per
  `policy_lab_cohorts.promoted_at`, resolved by
  `packages/quantum/policy_lab/champion.py get_current_champion`. This is the
  reference arm: the policy the live account actually followed.
- **ARM B — FLEET CHALLENGERS (`small_tier_v1` pre-registered policies).** Each
  activated micro-account's assigned policy
  (`shadow_micro_accounts.policy_registration_id`,
  `supabase/migrations/20260716060000_small_tier_shadow_fleet.sql:47-77`). The
  fleet design is **50 isolated slots** (`shadow_fleet.MICRO_ACCOUNT_COUNT = 50`,
  `:21`); each activated slot contributes one policy response per decision event.
  The 50-policy parameterization is FIXED and pinned by CONTENT (§12): **3
  anchors** (aggressive/neutral/conservative, verbatim from
  `policy_lab_cohorts.policy_config`) **+ 47 single-/two-axis variants** inside
  the 3-anchor convex hull — `docs/specs/fleet_policy_design_50.md` +
  `packages/quantum/policy_lab/fleet_policy_design.py` (#1279, squash
  `78c71a8e`). See §5 for the epoch identity.
- **ARM C — BASELINE AUTHORITY (frozen production math).** The frozen baseline
  adapters `packages/quantum/analytics/terminal_distribution/baselines.py` —
  "the thing challengers must beat" — which reproduce current production EV/PoP
  verbatim (including the visible `CREDIT_IDENTITY_DEFECT`). Any probability/EV
  claim in an arm is scored against this baseline, never against a re-derived or
  hindsight number.

**Frozen comparison discipline:** the only fair cross-arm comparison is on the
JOINT scored set (records BOTH arms scored) via
`terminal_distribution/evaluator.head_to_head` (`evaluator.py:321-365`). Arms
are never compared on their own private coverage sets. Cross-arm capital-basis
normalization is REQUIRED before any raw-dollar comparison — shadow ledgers fill
at 5–17× live size (`docs/specs/shadow_fill_realism.md`;
F-SHADOW-CAPITAL-PARITY): thesis/accuracy labels are notional-invariant, but
realized-net, capacity, and sizing arms are basis-broken until the promotion-time
normalization (#1124 discount, and the versioned-epoch fix) is applied.

---

## 3. Fleet / policy epoch identity

The experiment is scoped to a single, explicitly-named epoch. Cross-epoch mixing
is prohibited.

- **Fleet epoch:** `small_tier_v1` (`shadow_fleet.FLEET_EPOCH`, `:18`;
  DB-enforced `CHECK (epoch_name = 'small_tier_v1')`, migration `:30`).
- **Legacy epoch (excluded, preserved):** `legacy_100k`
  (`shadow_fleet.LEGACY_EPOCH`, `:19`). No `legacy_100k` outcome enters the
  E19-2B comparison — the epochs are different strategies (capital basis
  `fixed_small_tier` vs the $100k legacy basis).
- **Capital basis:** `fixed_small_tier` = 50 × $2,000 = $100,000 ADMINISTRATIVE
  total, which is reporting-only and NEVER a sizing or loss-recovery balance
  (`shadow_fleet.py:113-117`; migration `:20-21` generated column;
  `shared_capital_enabled = false` CHECK `:35`).
- **Registry epoch pin:** the fleet row (`shadow_fleets`) is uniquely keyed
  `(user_id, epoch_name)` with an activation gate: `status='active'` requires
  BOTH `legacy_terminal_verified_at` and `effective_at` set
  (migration `:29,38-44`; mirrored in
  `shadow_fleet.SmallTierFleetPlan.activation_status` `:126-132`). E19-2B reads
  outcomes ONLY from decision events whose producing account was `active` under
  a single `effective_at` epoch boundary. The activation event stamps the epoch;
  the analysis window opens at `effective_at`, never before.

---

## 4. Metrics (existing evaluation vocabulary — no new metrics invented)

All metrics are the terminal-distribution evaluator's existing vocabulary,
`packages/quantum/analytics/terminal_distribution/evaluator.py`
(`EVALUATOR_VERSION = evaluator@1.0.0`, `:48`). No metric outside this module is
admitted.

| Metric | Definition | Source |
|---|---|---|
| **Brier score** | mean squared (pop − realized_win) over scored rows | `evaluator.py:210` |
| **EV-RMSE** | sqrt(mean((expected_value − realized_pnl)²)) | `evaluator.py:211-213` |
| **Realized net** | Σ realized_pnl over scored rows | `evaluator.py:214` |
| **Coverage** | scored / eligible; `None` when eligible = 0 | `evaluator.py:206` |
| **Calibration** | 5 fixed buckets (`_BUCKET_EDGES`), or typed `InsufficientSamples` below floor | `evaluator.py:139,216-239` |
| **Per-segment** | Brier / EV-RMSE / realized-net keyed on (strategy, regime, dte_bucket) | `evaluator.py:241-258` |

- **Head-to-head (the charter comparison):** metrics recomputed on the JOINT
  scored set only — `evaluator.head_to_head` (`:321-365`). This is the sole
  admissible cross-arm number.
- **Raw vs calibrated are SEPARATE reports.** Models emit `basis="raw"`.
  A calibrated view is produced only by READ-ONLY application of a production
  multiplier (`with_production_multipliers`, `:280-318`), labeled
  `basis="calibrated"`, never overwriting the raw result. Both bases are
  reported side by side; neither is dropped.
- **Winner rule (frozen, directional):** an arm "beats" another only if it is
  better (lower Brier, lower EV-RMSE, higher realized-net on the joint set) —
  the backlog charter phrasing: *"baseline wins on Brier, EV-RMSE, and net
  outcome unless the challenger proves better"* (`docs/backlog.md:305-308`). Ties
  and single-metric wins are NOT wins.

---

## 5. Censoring rules (existing conventions — evaluator + challenger)

Censoring is EXPLICIT and COUNTED; nothing is coerced to a neutral value
(evaluator docstring `:15-19`).

- **Censored** — outcome `status != "resolved"` (open / unresolved). EXCLUDED
  from every metric, counted in `censored` (`evaluator.py:167-170`).
- **Malformed** — resolved but missing/`non-finite` a realized field. EXCLUDED,
  counted SEPARATELY in `malformed`, never coerced to 0
  (`evaluator.py:142-149,171-173`).
- **Abstained (abstention is a result)** — the model returns a typed
  `Unavailable`; counted in `abstained`, drives the coverage rate, and is NEVER
  scored as 0.5 (`evaluator.py:175-189`; contract `Unavailable`
  `terminal_distribution/contract.py:112-124`). The challenger abstains on
  missing `known_at` or any leg missing IV — never defaulting
  (`challenger_lognormal.py:131-148`).
- **Prequential discipline:** each record is scored on its own `known_at` inputs
  only; the evaluator never feeds an outcome back into a model, and records are
  ordered `(known_at, record_id)` for byte-deterministic reports
  (`evaluator.py:13-14,161`; `DistributionInputs.known_at`
  `contract.py:101-109`).

---

## 6. Deduplication

- **Per decision event:** the evidence n is `COUNT(DISTINCT decision_event_id)`
  via `shadow_fleet.count_unique_decision_events` (`:227-230`). Fifty account
  responses to one candidate collapse to ONE unit — account rows are never the n.
- **Per (cohort, decision event) response:** at most one verdict per pair.
  `policy_decisions` carries `UNIQUE(cohort_id, suggestion_id)` (verified live
  schema; `fork.py:846-852`) and the fork's idempotent, fail-CLOSED clone
  lookup/insert reconciles uniqueness races rather than double-counting
  (`fork.py:1066-1120`). "Could not prove absence" never becomes "insert
  another row."
- **Per experiment version:** clones embed `EXPERIMENT_VERSION =
  "e19_prerejection_v1"` (`fork.py:853`); a future experiment version produces
  DISTINCT clone rows so versions never silently comingle. NOTE (honest
  narrowing, `fork.py:846-852`): the stored verdict is version-BLIND on the
  live `UNIQUE(cohort_id, suggestion_id)` constraint, so it represents the
  LATEST version only; making verdict history version-aware needs a migration
  (owner adjudication — out of scope here).

---

## 7. Minimum distinct source-event requirement — DEFINED (v3)

**VERDICT: DEFINED = 8 distinct source decision events.**
`MINIMUM_DISTINCT_SOURCE_EVENTS = 8`. Owner-ratified 2026-07-19
(`docs/review/owner-ratifications-2026-07-19.md` decision 3;
`docs/review/owner-packet-3-e19-minimum.md`). No number is invented here — the
value is the owner's recorded decision, adopted into this frozen plan via the
protocol's OWN §13 change procedure (re-version + re-pin in one reviewed commit).

> In v1/v2 this number was recorded as undecided-in-E19-doctrine, and execution
> stayed blocked on it (no threshold was ever fabricated). v3 adopts the
> owner-ratified value; the block stays (threshold not yet MET, and §10 gates 1
> + 3 not yet clear). This is a threshold-VALUE change only.

What the E19 evidence unit is (frozen since v1, UNCHANGED):
- the evidence **unit** — distinct `decision_event_id`
  (`shadow_fleet.py:216-230`; migration `:188-189`);
- the evidence n is `COUNT(DISTINCT decision_event_id)`, never account rows.

**The threshold (v3):** the first E19-2B §4 head-to-head verdict may be READ
only at the first review AFTER `COUNT(DISTINCT decision_event_id) ≥ 8` (admitted
per §1, accrued under the `small_tier_v1` epoch post-`effective_at`). Below 8
distinct admitted events, only census counts (§8) may be read — NO arm
comparison.

### 7.1 Rationale for 8 (owner packet 3, RATIFIED)

`MINIMUM_DISTINCT_SOURCE_EVENTS = 8` is the **#1051 8-close convergence
convention** — the system's canonical "enough live evidence to stop deferring"
number, governed by the same epoch-gated, live-only discipline that governs
calibration's raw-mode exit (`MIN_CALIBRATION_TRADES = 8`). It is the smallest
system-native threshold that still meaningfully gates (the evaluator's
`min_calibration_n = 5` is a calibration-bucket-integrity floor, not a
decision-sufficiency floor). It is adopted as a **first-verdict floor with a
standing note to re-review before a second verdict**: 8 distinct decision events
is a small joint set, so a head-to-head Brier/EV-RMSE at n = 8 is DIRECTIONAL,
not conclusive — but §8 forbids optional stopping and §9 forbids promotion, so an
early, honest, single read at 8 is a hypothesis generator, not an action trigger.

The candidate conventions considered (owner-packet-3 §2; NONE auto-qualified —
each governs a DIFFERENT quantity than distinct decision events for a
head-to-head, and the E19 unit is coarser than "live closes"/"fills"):

| Candidate | Value | Native scope | Citation |
|---|---|---|---|
| Evaluator calibration-bucket floor | `min_calibration_n = 5` | below → typed `InsufficientSamples` (calibration only) | `evaluator.py:158,216-219` |
| **Calibration raw-mode exit (#1051) — ADOPTED** | **8** | live post-epoch closes before live multipliers | CLAUDE.md §4 #1051 |
| Phase-3 fills gate (#1102) | 10–15 | close-fill instrumentation | CLAUDE.md §4 #1100–#1102 |
| Promotion Gate-2 | 10 / 7d | champion promotion churn | ledger 07-03 |

The honest alternative the owner recorded was `MINIMUM_DISTINCT_SOURCE_EVENTS =
15` (top of the Phase-3 fills band — a less-noisy first read, at the cost of a
longer wait under the thin ~4-events/active-day decision stream). The owner
selected **8**; 15 is preserved here as the recorded alternative, not adopted.

---

## 8. Stopping and review boundaries

- **No optional stopping.** The verdict is READ exactly once, at the first
  review AFTER `COUNT(DISTINCT decision_event_id) ≥ MINIMUM_DISTINCT_SOURCE_EVENTS`
  (§7 — now DEFINED = 8; no read is permitted below 8). Peeking at head-to-head
  metrics before the threshold is a protocol violation; interim reads are limited
  to census counts (admitted n, censored/malformed/abstained tallies) which
  carry no arm comparison.
- **Fixed analysis window.** The window opens at the fleet `effective_at` epoch
  boundary (§3) and is defined by the pre-registered event threshold, not by a
  calendar date chosen after seeing results.
- **Deterministic recomputation.** Because the evaluator is byte-deterministic
  (§5), the same admitted row set yields the same report — a review is
  reproducible from the pinned artifacts (§12) and the row set.
- **Human review is READ-ONLY.** Per the audit-loop contract (CLAUDE.md §7), the
  analysis produces a report; it never merges, flips a flag, or trades.

---

## 9. Promotion prohibition (absolute)

**E19-2B NEVER promotes anything by itself.** It is an observational comparison.

- No E19-2B verdict changes `policy_lab_cohorts.promoted_at`, arms a control,
  widens the resting-TP pilot, modifies capital assignment, or activates a fleet
  slot. Champion promotion remains owned by the policy-lab evaluator's 7 gates
  and the operator, on the separately-normalized basis (F-SHADOW-CAPITAL-PARITY).
- `shadow_micro_accounts.promotion_eligible` defaults `false`
  (migration `:57`); E19-2B does not set it.
- A "challenger looks better" result is a hypothesis for a SEPARATE, owner-gated
  promotion decision with its own capital-basis normalization — never an action
  emitted by this experiment. This mirrors CLAUDE.md §9: never loosen/act on a
  control on outcome or hindsight.

---

## 10. Execution status — BLOCKED

`EXECUTION_STATUS: BLOCKED`. `EXECUTE_E19_2B: false`. E19-2B may not run until
ALL of the following are simultaneously true (each is an independent gate):

1. **Fleet activated at a clean legacy boundary** — `small_tier_v1` fleet
   `status='active'` with `legacy_terminal_verified_at` + `effective_at` set,
   `legacy_100k` positions and working orders proven terminal
   (`shadow_fleet.activate` `:142-178`; migration `:38-44`). Authorization alone
   is not runtime parity (backlog `:411-412`). **NOT YET CLEAR** — the fleet is
   provisioned INACTIVE (`pending_legacy_terminal`); activation is a separate
   owner-gated, irreversible-in-place step.
2. **50-policy manifest authored — SATISFIED.** The arm-B policy set is defined
   and pinned by CONTENT (§12): `docs/specs/fleet_policy_design_50.md` (50/50
   distinct config hashes) merged in #1279 (squash `78c71a8e`). This gate is MET.
   The migration/seed (`20260719000000_policy_registrations.sql` +
   `policy_registrations_seed_50.sql`) are APPLIED (07-19, receipts in
   `risk_alerts`; the 50 approved rows are registered) — registration into
   `policy_registrations` is complete, and the design CONTENT is frozen and
   pinned. (This gate was already MET in v2; the applied-seed status is a
   provenance note, not a science change.)
3. **Capital-basis parity applied** — cross-arm raw-dollar comparisons
   normalized (F-SHADOW-CAPITAL-PARITY / #1124), or the comparison restricted to
   notional-invariant metrics. **NOT YET CLEAR.**
4. **`MINIMUM_DISTINCT_SOURCE_EVENTS` defined AND the threshold met.** The value
   is now DEFINED = 8 by the owner (§7). The threshold being MET
   (`COUNT(DISTINCT decision_event_id) ≥ 8` accrued under the epoch) is **NOT
   YET TRUE** — no fleet decision events have accrued (the fleet is not active).
   Defining the value moves this gate from "undefined → no read permitted" to
   "gated-on-threshold"; it does NOT unblock execution.

This document is the frozen plan for when those gates clear. It is not a request
to clear them. v3 defines the §7 value only; gates 1, 3, and the gate-4
threshold-met condition remain open, so `EXECUTION_STATUS` stays BLOCKED.

---

## 11. Selection-bias note (inherited from E19-2A)

E19-2A shipped NARROW as `raw_candidate_eligibility_only` (#1200, `bef2cdd`) —
NOT selection, execution, fill, P&L, thesis, capacity, or joint-ranking evidence
(ledger 07-14 ③). E19-2B is the full counterfactual selector: joint
normal-vs-prerejection ranking + capacity/slot accounting
(`max_positions_open` / `max_suggestions_per_day`, `fork.py:610-611`) + selection
semantics. The pre-rejection source (calibrated-rejected candidates,
`status='NOT_EXECUTABLE' AND blocked_reason='edge_below_minimum'`,
`fork.py:105-118`) is admitted on the SAME executable-side / H9 discipline: a leg
dark at decision time is UNMARKABLE and excluded by construction (§7 area8), never
resurrected with a hindsight quote.

---

## 12. Pinned artifacts (provenance hashes)

**Carried VERBATIM from v2 — the frozen science is UNCHANGED in v3.** Content
SHA-256 of every module this protocol's identity, metrics, and dedup depend on,
computed at the science-freeze base `BASE_SHA 79f4ba76` (NOT re-pinned at the v3
authoring base — re-pinning would change the frozen science, which v3 does not
do). A change to any of these modules changes the science and MUST re-open this
protocol (new version + owner review).

    contract.py            4523a81c220bbfc4b534249ff7bd428b59cf9556084f83c27edb1e96bc970cd0
    evaluator.py           d0ecb19ed70b96801e30a77c1541d719bf2e3a081cc6e6ed69de4e5fc292b49f
    payoff.py              6e119d0b1551b0099a1665d8010d7afc165394f8600658f8ef53a91a80ac7cb6
    challenger_lognormal.py 0c5cc23de8f7b320847a2c32ac51cdf6701657cc2e6383b5d654caf837b5d572
    baselines.py           c3f2977b05836c5bb48016080650fa631e670ffc6b2296ea59881caf2ca42bcc
    terminal_distribution/__init__.py b983a31e7419086dd51e92ae02f4fd7fc75776ad469641f8152aecac70169575
    policy_lab/shadow_fleet.py        670e8f34be67982f995d3f9f936cb3b3b0822bc1732d380c4b25a51df2bb9b46
    policy_lab/fork.py                1f1d238682efb2889a4699413d7082fc7690be0ad2640f1479d07e119c67cdeb

Contract versions (self-declared, carried in provenance):

    terminal_distribution CONTRACT_VERSION   1.0.0      (contract.py:46)
    terminal_distribution EVALUATOR_VERSION  evaluator@1.0.0 (evaluator.py:48)
    fork EXPERIMENT_VERSION                  e19_prerejection_v1 (fork.py:853)
    origin PROVENANCE_VERSION                1          (jobs/origin.py:77)

Schema / migration identity:

    fleet schema        supabase/migrations/20260716060000_small_tier_shadow_fleet.sql
                        (applied 2026-07-17 05:22Z; tracked NAME 20260717052208)
    fleet activation RPC supabase/migrations/20260717090000_shadow_fleet_activation_rpc.sql
                        (applied 2026-07-18 ~03:34Z; MIGRATION APPLIED — do not reapply)
    ranking-costs prov  supabase/migrations/20260716155023_add_ranking_costs_to_trade_suggestions.sql (#1231)

Git provenance (context, not a content hash):

    BASE_SHA          79f4ba76  (science-freeze base; UNCHANGED in v3)
    CURRENT_MAIN_SHA  ed5d6f48  (origin/main at v2 re-freeze)
    V3_AUTHORING_SHA  94aa6528  (origin/main at v3 re-freeze; provenance only)
    FLEET_MANIFEST    78c71a8e  (#1279 squash — arm-B design on main)

ARM B — 50-POLICY DESIGN, PINNED BY CONTENT (#1279, squash 78c71a8e):

    manifest file    docs/specs/fleet_policy_design_50.md
    manifest sha256  5cb76f9981ee12a34204dec63368c918de802f71a99f5766410aa34638d8922c
                     (CRLF->LF normalized — same convention as this doc's pin)
    generator        packages/quantum/policy_lab/fleet_policy_design.py
    migration        supabase/migrations/20260719000000_policy_registrations.sql   (APPLIED 07-19)
    seed             supabase/migrations/policy_registrations_seed_50.sql          (APPLIED 07-19)

    FLEET CONFIG-HASH SET FINGERPRINT
    18766a1e882e36a46d708add8d3e5c258ea117607954210a8d142fc8844a9a39

    Recipe (reproducible): take the 50 config_hash values from the manifest's
    "## config_hash" table (50/50 distinct, lowercase hex), sort ascending, join
    with a single LF ("\n", no trailing newline), UTF-8 encode, SHA-256. This
    fingerprint IS arm B's frozen identity: changing ANY of the 50 policy configs
    changes a config_hash -> changes this fingerprint -> MUST re-open this
    protocol (new version + owner review). The 3 anchors are verbatim
    policy_lab_cohorts.policy_config (aggressive = live champion); the 47 variants
    lie inside the 3-anchor convex hull, so no variant is looser than the loosest
    anchor (e.g. stop_loss_pct hull max 0.30 never widens the live loss stop —
    manifest "Bounds derivation"; CLAUDE.md §5 / NEVER-DO).

Both the manifest SHA-256 (`5cb76f99…`) and the config-hash-set fingerprint
(`18766a1e…`) were re-verified at the v3 authoring base `94aa6528` and reproduce
IDENTICALLY — arm B's frozen identity is unchanged from v2.

---

## 13. Change procedure (the only way to alter a frozen protocol)

1. Author a NEW version block or file (as v3 is a new file
   `e19_2b_preregistered_protocol_v3.md`); do not silently rewrite a decided
   section, and do not edit or delete a prior frozen version (v2 stays immutable).
2. Update `packages/quantum/tests/test_e19_2b_preregistration.py` with the new
   SHA-256 in the SAME commit — the diff of the pinned hash is the visible,
   reviewed record that the frozen plan changed. The prior version's pin
   (`FROZEN_PROTOCOL_SHA256`, v2) stays asserted so a change to EITHER version
   fails.
3. Owner sign-off, exactly as a measurement-correction rollback (#1051
   convention). No flag silently toggles a frozen protocol.
