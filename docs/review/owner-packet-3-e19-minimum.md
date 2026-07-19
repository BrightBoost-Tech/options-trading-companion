# Owner Packet 3 — E19-2B `MINIMUM_DISTINCT_SOURCE_EVENTS`

**Decision:** set the one missing number in the FROZEN E19-2B protocol
(`docs/specs/e19_2b_preregistered_protocol.md` §7) — the minimum
`COUNT(DISTINCT decision_event_id)` that must accrue under the `small_tier_v1`
epoch before an E19-2B head-to-head verdict may be READ. **Until set,
`EXECUTION_STATUS` stays BLOCKED; this packet executes nothing** and invents no
number (§7 VERDICT: UNDEFINED → BLOCKED). Setting it re-versions the protocol
to a reviewed commit (protocol §13) — an owner-gated step, not done here.

**Recommendation:** **`MINIMUM_DISTINCT_SOURCE_EVENTS = 8`** (the #1051
8-close convergence convention) as the first-verdict floor — the smallest
system-native threshold that still gates, with a standing note to re-review
before the second verdict. Rationale + the honest alternative below.

---

## 1. What the unit is (already frozen, not in question)

The evidence unit is the **distinct market decision event**
(`policy_decisions.decision_event_id` = `suggestion_id`, immutable by
trigger). 50 fleet accounts responding to one source candidate collapse to
**one** decision event — account rows are never the n
(`shadow_fleet.count_unique_decision_events`, protocol §1, §6). The number in
question is the minimum COUNT of these distinct events.

## 2. Candidate conventions (protocol §7.1 — cited, none auto-qualifies)

| candidate | value | native scope | citation |
|---|---|---|---|
| evaluator calibration-bucket floor | 5 | below → typed `InsufficientSamples` (calibration only) | `evaluator.py:158,216-219` |
| calibration raw-mode exit (#1051) | **8** | live post-epoch closes before live multipliers | CLAUDE.md §4 #1051 |
| Phase-3 fills gate (#1102) | 10–15 | close-fill instrumentation | CLAUDE.md §4 #1100–#1102 |
| promotion Gate-2 | 10 / 7d | champion promotion churn | ledger 07-03 |

Each governs a **different quantity** than "distinct decision events for a
head-to-head", and the E19 unit is coarser than "live closes"/"fills", so
borrowing any of them is a category stretch — hence none is adopted by
doctrine. The owner selects (and may reference one).

## 3. Historical decision-event rate — queried honestly (Supabase 2026-07-18)

Source suggestions (= decision events by identity) per day:

| window | events | active days | mean / active day |
|---|---|---|---|
| last 30 days | 59 | 15 | **3.93** |
| last 60 days | 89 | 26 | 3.42 |

Recent daily counts: `07-17`=1, `07-16`=2, `07-15`=4, `07-14`=9, `07-13`=6,
`07-08`=6, `07-07`=10 — the **~0–10/day** range the orchestrator flagged. The
distinct-decision-event stream is thin: even the busiest recent day produced
10. Corroborating small-n context: the challenger study
(`challenger-study-2026-07-18.md` §2) counted **8 total broker-live closes**
in all history.

**Accrual estimate under the fleet epoch** (events accrue only from
`scheduler`-origin cycles admitted post-`effective_at`, protocol §1): at
~4 distinct events/active day, a threshold of 8 is ~2 active days of clean
post-activation flow; 10–15 is ~3–4 active days; 20 is ~1 trading week. None
is long in calendar terms, but the epoch clock only starts at activation, and
a quiet stretch (see `07-02`=1, `07-10`=2) can stall it.

## 4. The two defensible values

### Recommended — 8 (`#1051` convergence)

- **Why:** it is the system's canonical "enough live evidence to stop
  deferring" number; the same epoch-gated, live-only discipline that governs
  calibration governs this fleet. It is the smallest convention that still
  meaningfully gates (5 is a calibration-bucket integrity floor, not a
  decision floor).
- **Cost:** 8 distinct decision events is a **small** joint set; a
  head-to-head Brier/EV-RMSE on ~8 events is directional, not conclusive. The
  protocol already forbids optional stopping (§8) and forbids promotion (§9),
  so an early, honest, single read at 8 is a hypothesis generator, not an
  action trigger — acceptable.

### Alternative — 15 (top of the Phase-3 fills band)

- **Why:** a larger joint set → a less noisy first head-to-head; aligns with
  the fill-quality gate the operator already trusts for "enough closes."
- **Cost:** at ~4 events/active day plus quiet stretches, 15 could take ~a
  week-plus of post-activation flow to reach — the E19-2B verdict would sit
  unread longer. Given learning-mode (correctness > velocity), this is a
  legitimate owner preference.

Both are honest. 10 (promotion Gate-2) is a reasonable middle if the owner
wants a round number; it is a churn gate, not an evidence-sufficiency gate, so
it is offered but not recommended over 8 or 15.

## 5. What setting it does (mechanics)

Per protocol §7.1 + §13: the owner picks the value; the document is
re-versioned (`e19_2b_protocol_v3` block or file) with the number **and its
rationale**; `test_e19_2b_preregistration.py`'s SHA-256 pin is updated **in the
same reviewed commit** (the hash diff is the visible record that the frozen
plan changed). `EXECUTION_STATUS` then moves from BLOCKED to gated-on-threshold
(still also gated on activation §10 gate 1 + capital-basis parity §10 gate 3).
No flag silently toggles a frozen protocol.

---

## APPROVAL TOKEN

> **`MINIMUM_DISTINCT_SOURCE_EVENTS=8`** — sets the E19-2B first-verdict floor
> to 8 distinct `decision_event_id`s under the `small_tier_v1` epoch (with a
> standing note to re-review before a second verdict). *(Alternative:
> `MINIMUM_DISTINCT_SOURCE_EVENTS=15` per §4.)* Execution stays BLOCKED until
> this value is chosen **and** the protocol is re-versioned in a reviewed
> commit **and** §10 gates 1 + 3 (fleet activated, capital-basis parity) also
> clear. No number is invented; no E19-2B run happens here.
