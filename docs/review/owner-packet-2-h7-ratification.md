# Owner Packet 2 — H7 disposition ratification

**Decision:** ratify how a round-trip-BP / gate death (E4/E5 class) is recorded
in `candidate_terminal_dispositions` — **retain** the current
`h7_dropped`-parent + typed subreason, **or** promote gate deaths to a new
**top-level disposition value**. **This packet executes nothing** — it
recommends; the constraint and writer already shipped (#1281). Verify the live
CHECK and writer on their sources.

**Recommendation:** **RETAIN** `H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON`. It is
already live, query-compatible, and self-guarding; the top-level-parent
alternative buys a marginal query convenience at the cost of a CHECK-widening
migration, a writer change, a contract-test change, and breaking every
existing `WHERE disposition='h7_dropped'` query.

---

## 1. Current state (shipped #1281, squash `4c12dafa`)

The parent disposition stays `h7_dropped`; every `h7_dropped` final must carry
exactly one typed `detail->>'h7_subreason'`. The five canonical subreasons are
the writer's frozenset (`candidate_disposition.py`):

    roundtrip_bp | quality_gate | sizing_zero | risk_budget | account_capacity

plus the honest soft-fail sentinel `unspecified`. E1 (the round-trip-BP / gate
death adjudication) maps to `quality_gate`. The `sizing_outcome` key carries
the sizing detail alongside.

Enforcement is layered:
- **Writer (active control):** strict-raise in dev/test (every shipped call
  site is CI-verified to carry a canonical subreason), fail-soft + counted
  (`writer_taxonomy_violation`, stamps `unspecified` +
  `h7_subreason_violation=true`) in production —
  `candidate_disposition.py`.
- **DB backstop (opt-in):** `ctd_h7_subreason_required` CHECK,
  `supabase/migrations/20260719010000_h7_subreason_check.sql` (`NOT VALID`
  then `VALIDATE`d; receipt `6c49ce87…`). The 10-value disposition CHECK in
  `20260717100000_candidate_terminal_dispositions.sql` is **untouched**.
- **Contract test:** `test_h7_subreason_migration_contract.py` pins the
  allowlist set-equal to the writer's frozenset (anti-drift).

History: #1272 introduced the typed-disposition table; #1281 added the
mandatory typed subreason + owner adjudication `E1→quality_gate`. Owner
decision label already recorded in the migration:
`H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON`.

## 2. The two options

### Option A — RETAIN (current): parent `h7_dropped` + typed subreason

- **Migration cost:** none (shipped).
- **Writer cost:** none (shipped).
- **Query for "all H7 gate deaths":** `WHERE disposition='h7_dropped'`
  (unchanged; backward-compatible).
- **Query for a specific cause:**
  `WHERE disposition='h7_dropped' AND detail->>'h7_subreason'='quality_gate'`.
- **Invariant safety:** the `unspecified` sentinel is allow-listed on purpose
  so the writer's demote-then-retry fallback can never leave an identity with
  zero active finals (proven on live PG by the #1281 reviewer,
  migration `:26-30`). The one-final-per-candidate invariant always wins.

### Option B — NEW top-level disposition value (e.g. `roundtrip_gate_dropped`)

- **Migration cost:** widen the 10-value disposition CHECK in
  `20260717100000_candidate_terminal_dispositions.sql` (`NOT VALID` → soak →
  `VALIDATE`) — a new operator migration.
- **Writer cost:** re-map the E4/E5 branch to emit the new value; retire or
  re-scope the `h7_dropped`+`quality_gate` path; re-touch the
  one-final-per-identity fallback so the sentinel logic still holds under the
  new value.
- **Contract-test cost:** update `test_h7_subreason_migration_contract.py`
  (and the disposition allowlist contract test) to the new value set.
- **Query compatibility:** **breaks** every existing
  `WHERE disposition='h7_dropped'` reader — gate deaths would split across two
  parents; any historical `h7_dropped` row keeps the old shape while new rows
  use the new value, so a union query is needed to span the boundary.

## 3. Query compatibility — both ways

| question | Option A (retain) | Option B (new parent) |
|---|---|---|
| all H7 gate deaths | `disposition='h7_dropped'` | `disposition IN ('h7_dropped','roundtrip_gate_dropped')` across the migration boundary |
| just quality-gate deaths | `+ detail->>'h7_subreason'='quality_gate'` | `disposition='roundtrip_gate_dropped'` (new rows only) |
| historical rows pre-change | already typed | remain `h7_dropped` — split identity |
| segment learning readers | one parent, typed detail | must learn the second parent |

Option B's only advantage is a one-column `disposition=` filter for the single
`quality_gate` cause; Option A gets the same with one extra `AND` and never
splits the historical series.

## 4. Recommendation

**RETAIN.** The typed-subreason design already gives per-cause queryability
without a second parent, keeps `WHERE disposition='h7_dropped'` stable, needs
zero new migration/writer/test churn, and its sentinel guarantees the
one-final invariant. Adopt a new top-level value only if a future consumer
genuinely needs `disposition`-level (not `detail`-level) partitioning of gate
deaths — no such consumer exists today.

---

## APPROVAL TOKEN

> **`H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON`** (retain) — ratifies the current
> `h7_dropped` parent + mandatory typed `h7_subreason`
> (`quality_gate` for the E1 gate-death class); no CHECK widening, no writer
> change. *(Alternative, NOT recommended:
> `H7_NEW_TOP_LEVEL_DISPOSITION=<value>` — authorizes the CHECK-widening
> migration + writer + contract-test changes in §2 Option B.)*
