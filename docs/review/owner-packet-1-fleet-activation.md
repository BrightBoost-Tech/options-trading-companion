# Owner Packet 1 — Shadow Fleet ACTIVATION (`small_tier_v1`)

> **RATIFIED 2026-07-19** → see owner-ratifications-2026-07-19.md

**Decision:** authorize activation of the 50 × $2,000 `small_tier_v1` shadow
fleet. **This packet decides nothing and executes nothing** — activation
remains forbidden to the loop and to every agent; only the operator, via the
env opt-in + confirm literal + attestation below, may activate. Verify every
value on its source (Supabase / Railway) — never trust this file for a value
(CLAUDE.md §1).

**Recommendation:** activation is technically READY. Recommend authorizing it
**only after** the natural-evidence prerequisites below (a Sunday wrapper
nightly PASS and, ideally, one Monday natural-runtime cycle) clear — there is
no capital or safety cost to waiting one cycle, and the fleet is inert while
`pending_legacy_terminal`.

---

## 1. What is being activated

The provisioned-but-inactive fleet. Live-verified state (Supabase, queried
2026-07-18):

| field | value | source |
|---|---|---|
| fleet id | `b8b1ea1f-dea4-45da-a9f8-0def01648fb6` | `shadow_fleets` |
| epoch | `small_tier_v1` | `shadow_fleets.epoch_name` |
| status | `pending_legacy_terminal` | `shadow_fleets.status` |
| `legacy_terminal_verified_at` | `NULL` (set at activation) | `shadow_fleets` |
| `effective_at` | `NULL` (set at activation) | `shadow_fleets` |
| slots | 50, all `inactive`, 0 bound | `shadow_micro_accounts` |
| portfolios | 50 × $2,000, all `shadow_only` (never `live_eligible`) | `paper_portfolios` |
| approved registry rows | 50 (`approval_status='approved'`, epoch `small_tier_v1`) | `policy_registrations` |

The fleet is a shadow-only research instrument: 50 isolated $2,000 books, no
real capital, no live routing. It is the E19-2B arm-B fleet
(`docs/specs/e19_2b_preregistered_protocol.md` §2–§3).

## 2. Binding rule — fingerprint-pinned

Slots bind to policies at activation from the 50 approved registry ids by the
rule **`ORDER BY policy_registration_id ASC`** (slot 1 ← the alphabetically
first id, … slot 50 ← the last). The 3 anchors land at fixed slots — verified
live (Supabase 2026-07-18):

| slot | policy_registration_id | lineage |
|---|---|---|
| 17 | `aggressive_anchor` | aggressive (live champion config) |
| 33 | `conservative_anchor` | conservative (shadow-only) |
| 50 | `neutral_anchor` | neutral (shadow-only) |

Binding manifest fingerprint (the frozen slot→policy assignment):

    6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad

The operator-supplied `p_policy_registrations` payload (slot→id, all 50) must
reproduce this manifest. Any id not `approved` for this epoch is rejected
(`POLICY_NOT_REGISTERED` / `POLICY_NOT_APPROVED`,
`shadow_fleet_activation.py:282-340`) — never invented or defaulted.

## 3. Readiness — dry-run 2026-07-19

The dry-run (`plan_activation`, zero writes) returned **`READY_TO_ACTIVATE`**,
clearing all 13 readiness outcomes in `READINESS_OUTCOMES`
(`shadow_fleet_activation.py:67-81`): none of the 11 blocking outcomes
(`schema_unavailable`, `legacy_*_not_terminal`, `policy_registration_*`,
`policy_not_registered/approved`, `slot_count_invalid`,
`capital_contract_invalid`, `already_*`) fired. Bundle:
`fleet-activation-dry-run-2026-07-19.md`.

Legacy-terminal precondition, live-verified (Supabase 2026-07-18) — the RPC
re-checks this **inside** the activation transaction regardless:

- `paper_orders`: 0 non-terminal (statuses present: `cancelled` 318, `filled`
  189, `watchdog_cancelled` 20, `manual_close_complete` 1 — all on the
  allowlist).
- `paper_positions`: 0 non-terminal (all `closed`, 86 rows).

> ⚠ **Discrepancy to reconcile before activating.**
> `migration-results-2026-07-18.md` recorded **SEVEN** activation blockers (6
> `submitted` 2026-04-09 + 1 `needs_manual_review` 2026-05-11). The live book
> now shows **zero** non-terminal legacy rows — those seven have since been
> reconciled/cleared. This is doc-lag, not an averaging problem: the RPC's
> in-transaction re-verification (allowlist, fail-closed) is the authoritative
> check at activation time, so a stale doc cannot cause an unsafe activation.
> Confirm the reconciliation receipts (§4) before issuing the token.

## 4. Attestation payload (operator-supplied, never defaulted)

`validate_attestation` (`shadow_fleet_activation.py:194-225`) and the RPC
(`20260717090000_shadow_fleet_activation_rpc.sql:247-267`) both require:

| field | requirement | value / pointer |
|---|---|---|
| `stale_order_reconciliation_receipt` | non-blank; references the stale-order reconciliation | stale-orders receipt fp `04317fc1…` (6 rows) **+** seventh-row (the `needs_manual_review` adjudication) fp `5d5cd9fc…` |
| `legacy_terminal_verified_at` | **tz-aware** ISO-8601; written verbatim to `shadow_fleets.legacy_terminal_verified_at` | operator-supplied timestamp (must be tz-aware — a naive ts is rejected, `:219-220`) |
| `attested_by` | non-blank operator identity | operator |

`legacy_terminal_verified_at` comes ONLY from this payload — it is never
invented server-side (RPC `:262-267`).

## 5. The exact activation transaction

`execute_activation` (`shadow_fleet_activation.py:729-788`) makes ONE
`supabase.rpc(...)` call — a single server-side plpgsql transaction. No client
transactions exist, so no partially-visible activation can exist.

    rpc_shadow_fleet_activate(
        p_user_id,
        p_idempotency_key,          -- required, non-blank
        p_policy_registrations,     -- {"1": id, …, "50": id}: 50 slots, unique, approved
        p_attestation               -- §4 fields
    )

Inside the transaction (`20260717090000_shadow_fleet_activation_rpc.sql:193-435`),
in order: advisory-lock the fleet → re-verify 50-slot / $2k contract →
re-verify legacy orders + positions terminal (allowlist, fail-closed) →
validate the 50 registrations (exactly 50, slots 1–50, unique, non-blank) →
capture **`effective_at := now()` once** (DB time, never client-supplied) →
`UPDATE` all 50 slots to `state='active'` with their `policy_registration_id`
+ `activated_at` → **`GET DIAGNOSTICS`: if the update count ≠ 50, RAISE** (the
50-binding atomic gate — no partial activation) → flip `shadow_fleets.status`
to `active` with `legacy_terminal_verified_at` + `effective_at` → write one
`shadow_fleet_activated` info receipt. Any RAISE rolls the whole step back.

**Idempotency:** a re-invocation on an already-active fleet returns
`already_active` with **zero writes** (RPC `:233-241`; service `:754-761`).

## 6. Pre / post counts

| table | pre (now, verified) | post (activation) |
|---|---|---|
| `shadow_fleets` status | `pending_legacy_terminal` | `active` (`effective_at`, `legacy_terminal_verified_at` set) |
| `shadow_micro_accounts` active | 0 | 50 |
| slots with `policy_registration_id` | 0 | 50 (bound per §2) |
| `paper_portfolios` `shadow_only` | 50 | 50 (unchanged; never `live_eligible`) |
| `shadow_fleet_activated` receipts | 0 | 1 |
| broker orders / positions | 0 / 0 | 0 / 0 (shadow-only — zero broker writes) |

## 7. Reversal — retire path (NO un-activate RPC)

There is **no `rpc_shadow_fleet_deactivate`**. `shadow_fleets.status='active'`
can move only to `retired` (the RPC treats `retired` as terminal,
`:243-245`). Un-activating in place would need a **separate operator-owned
migration** (a new RPC or a manual `UPDATE` under the migration procedure) —
documented here as not-yet-built. Because the fleet is shadow-only with zero
broker exposure, retire (stop accruing new decision responses; freeze the
epoch) is the intended reversal, not rollback of the activation write.

## 8. Natural-evidence prerequisites (recommended before authorizing)

Activation authorization is not runtime parity (E19-2B protocol §10 gate 1;
backlog `:411-412`). Recommend, in order, before the token:

1. **Sunday wrapper nightly PASS** — the first wrapper-flow nightly ran
   tonight (owner-decisions-implementation-2026-07-19 §Phase-1); confirm it
   produced a clean dated report.
2. **Monday natural rows** — one `2026-07-20` scheduler-origin scan cycle
   producing natural `candidate_terminal_dispositions` +
   `option_quote_provenance` rows (migration-results-2026-07-18 item 6),
   confirming the runtime pipeline is healthy before the fleet starts
   consuming decision events.
3. Re-run the dry-run (`plan_activation`) that morning; confirm it still reads
   `READY_TO_ACTIVATE` and the attestation validates.

Decision-event volume context (Supabase 2026-07-18): recent cycles emit
~0–10 source suggestions/day (mean 3.93/active day over the last 30 days) —
the fleet will accrue distinct decision events slowly; there is no urgency
that outweighs one clean natural cycle first.

---

## APPROVAL TOKEN

> **`FLEET_ACTIVATION_AUTHORIZED`** — to authorize, the operator sets
> `FLEET_ACTIVATION_AUTHORIZED=1` (strict `=1`) on **both** workers, then
> calls `execute_activation` with the confirm literal
> **`EXECUTE-SHADOW-FLEET`**, an idempotency key, the 50-slot
> `p_policy_registrations` payload reproducing manifest
> `6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad`, and the
> §4 attestation (receipts `04317fc1…` + `5d5cd9fc…`, tz-aware
> `legacy_terminal_verified_at`, `attested_by`). Absent the token, dry-run is
> the only available surface. **Activation stays forbidden to the loop and to
> agents — operator-only.**
