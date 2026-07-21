# H7 disposition taxonomy — canonical, ratified

**Status:** RATIFIED 2026-07-19 (owner decision
`H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON`). This is the durable, living
reference for the `h7_dropped` disposition and its typed sub-taxonomy. It
records the owner ratification and pins the contract so documentation drift
fails a test (`packages/quantum/tests/test_h7_taxonomy_doc_contract.py`).

Verify live values on their sources, never on this file (CLAUDE.md §1). This
doc records a *ratified contract*, not a runtime value.

---

## 1. The ratified decision

**RETAIN `h7_dropped` as the backward-compatible PARENT disposition**, with a
mandatory typed `detail->>'h7_subreason'` giving a queryable sub-taxonomy. The
rejected alternative was a NEW top-level disposition value (which would have
required a CHECK-widening migration + writer change + contract-test change and
would break every existing `WHERE disposition='h7_dropped'` reader).

- **Approval token:** `H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON` (retain).
- **Packet (recommendation):** `docs/review/owner-packet-2-h7-ratification.md`.
- **Ratification record:** `docs/review/owner-ratifications-2026-07-19.md` §2.
- **Shipped by:** #1281 (squash `4c12dafa`); the opt-in DB backstop CHECK by
  migration `supabase/migrations/20260719010000_h7_subreason_check.sql`
  (`ctd_h7_subreason_required`, applied — receipt `6c49ce87…`; NEVER REAPPLY).

**Ratifying merged code — no later code step.** RETAIN means no CHECK
widening, no writer change, no contract-test change. Every existing
`WHERE disposition='h7_dropped'` reader stays valid.

---

## 2. Parent disposition — `h7_dropped` (unchanged)

The parent value `h7_dropped` lives in the 10-value disposition enum CHECK in
`supabase/migrations/20260717100000_candidate_terminal_dispositions.sql`
(`disposition IN (...)`) and in the writer's `DISPOSITIONS` frozenset
(`packages/quantum/services/candidate_disposition.py`). Both are **untouched**
by the subreason work — the sub-taxonomy is a jsonb-`detail` CHECK only, never
a new top-level value.

`h7_dropped` is DELIBERATELY overloaded: it is the capital/priceability-fit
family between candidate selection and persist (the active H7 pre-filter,
sized-to-zero, risk-budget exhaustion, and the unpriceable-candidate death).
Backward-compatible parent queries are unchanged:

```sql
-- all H7 gate deaths (backward-compatible; never splits the historical series)
WHERE disposition = 'h7_dropped'
```

---

## 3. Canonical subreasons (5) — the queryable sub-taxonomy

Every `h7_dropped` final MUST carry EXACTLY ONE canonical
`detail->>'h7_subreason'`. The canonical set is the writer's `H7_SUBREASONS`
frozenset (`candidate_disposition.py`), set-equal-pinned to the DB CHECK
allowlist by `test_h7_subreason_migration_contract.py`, and set-equal-pinned to
THIS doc by `test_h7_taxonomy_doc_contract.py`:

<!-- H7_SUBREASONS_CANONICAL:START -->
    roundtrip_bp | quality_gate | sizing_zero | risk_budget | account_capacity
<!-- H7_SUBREASONS_CANONICAL:END -->

| subreason | meaning | orchestrator call site (`workflow_orchestrator.py`) |
|---|---|---|
| `roundtrip_bp` | H7 pre-filter active drop (`collateral + close_bp × safety > deployable_capital`). | ~:2868 |
| `quality_gate` | marketdata quality-gate HARD-mode E4/E5 drops AND the unpriceable-candidate death E1 (`suggested_entry <= 0`) — a data/priceability death, same family as the gate, NOT capital-fit. | ~:3347 (E1), ~:3830 / ~:3886 (E4/E5) |
| `sizing_zero` | the dominant death: sizing engine returns `contracts == 0` (E3). Its root causes stay in `detail.reason` / `detail.sizing_outcome`. | ~:4151 |
| `risk_budget` | per-candidate risk budget exhausted (`final_risk_dollars <= 0`, E2). | ~:3590 |
| `account_capacity` | RESERVED — kept canonical for a future account/tier-capacity death that lands in the h7 family. No current call site maps here. | — |

Per-cause query:

```sql
WHERE disposition = 'h7_dropped'
  AND detail->>'h7_subreason' = 'quality_gate'
```

---

## 4. `unspecified` — the writer soft-fail sentinel (NOT canonical)

`unspecified` is NOT a canonical subreason. It is the writer's honest soft-fail
marker: when a (buggy, un-typed) PRODUCTION call site slips past the strict
dev/test raise, the writer counts a `writer_taxonomy_violation`, stamps
`h7_subreason='unspecified'` + `h7_subreason_violation=true`, and STILL writes
the row. The DB CHECK allow-lists the sentinel ON PURPOSE so the
one-final-per-candidate invariant genuinely always wins (a rejected soft-fail
write would, via the writer's demote-then-retry path, strand a candidate with
zero active finals). Violations stay fully queryable and are 0 in normal
operation:

```sql
WHERE detail->>'h7_subreason_violation' = 'true'   -- a call-site bug
WHERE detail->>'h7_subreason'           = 'unspecified'
```

The DB CHECK allowlist is therefore the 5 canonical values **plus** the
sentinel (SIX total). Enforcement layers: writer (active, strict-raise in
dev/test, fail-soft + counted in production) → DB CHECK
`ctd_h7_subreason_required` (opt-in backstop, `NOT VALID` then `VALIDATE`) →
contract + predicate tests.

---

## 5. `sizing_outcome` is SEPARATE — it is NOT an h7 subreason

`sizing_outcome` is a distinct free-text `detail` discriminator that carries
the exact sizing/gate cause UNDERNEATH the typed subreason. It is **not** a
member of `H7_SUBREASONS`, is **not** in the CHECK allowlist, and must never be
folded into the subreason. It lives alongside `h7_subreason` in the same
`detail` object — for example the marketdata quality-gate death stamps both
`h7_subreason='quality_gate'` AND `sizing_outcome='marketdata_quality_gate'`
(`workflow_orchestrator.py` ~:3830-3835, ~:3886-3888), which keeps
capital-fit queries able to exclude marketdata deaths without parsing reason
strings:

```sql
-- inside h7_subreason='quality_gate': the real marketdata gate (E4/E5)
WHERE disposition = 'h7_dropped'
  AND detail->>'h7_subreason'  = 'quality_gate'
  AND detail->>'sizing_outcome' = 'marketdata_quality_gate'
```

---

## 6. Sources (verify before trusting this doc)

- Writer + frozenset: `packages/quantum/services/candidate_disposition.py`
  (`H7_SUBREASONS`, `H7_SUBREASON_UNSPECIFIED`, `record_final`).
- Parent enum CHECK (untouched):
  `supabase/migrations/20260717100000_candidate_terminal_dispositions.sql`.
- Sub-taxonomy DB backstop CHECK:
  `supabase/migrations/20260719010000_h7_subreason_check.sql`.
- Contract test (CHECK ↔ frozenset):
  `packages/quantum/tests/test_h7_subreason_migration_contract.py`.
- Predicate + writer-output parity:
  `packages/quantum/tests/test_h7_subreason_check_predicate.py`.
- Doc ↔ frozenset drift pin (this file):
  `packages/quantum/tests/test_h7_taxonomy_doc_contract.py`.

## Reversal / correction

Docs-only record. To correct or supersede, author a higher-versioned
ratification record (or amend in a reviewed commit) — never by editing a live
control, a migration, or the applied CHECK. Changing the canonical set is a
code change to `H7_SUBREASONS` (which the drift pins force to move together
with this doc and the CHECK), an owner decision in its own right.
