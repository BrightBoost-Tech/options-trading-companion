# E19 Protocol Supersession Governance — upstream-hash staleness & the execution-refusal gate

    GOVERNANCE_ID:     e19_protocol_supersession
    STATUS:            ACTIVE (docs/schema/tests only — DEFINES a procedure,
                       RUNS nothing, changes no live control)
    APPLIES_TO:        the frozen E19-2B preregistered analysis protocol chain
                       (v2 `50e7e237…`, v3 `cfdcfc9e…`)
    EXECUTION_STATUS:  E19-2B remains BLOCKED — this document adds a gate, it
                       does not clear any.
    AUTHORED_AT:       2026-07-21 (RTH; docs/schema/tests only; no E19 run)

> **What this document is.** A frozen preregistered protocol
> (`e19_2b_preregistered_protocol_v3.md`) pins, in its §12, the exact content
> hash of every upstream module its identity, metrics, and dedup depend on. But
> the protocol doc is itself FROZEN — its own SHA-256 is pinned in
> `test_e19_2b_preregistration.py`, so §12 can never be re-pinned in place. The
> §12 hashes therefore bind only **transitively** (through the doc's overall
> hash): the protocol asserts the modules *had* those hashes at freeze time, but
> nothing RE-CHECKS the live modules. When upstream science drifts, the frozen
> doc keeps asserting the stale hashes, silently.
>
> This document DEFINES how upstream code/config/science changes **invalidate or
> supersede** a frozen E19 protocol **without rewriting the immutable protocol**.
> It DECIDES nothing about trading and RUNS nothing. It authorizes no trade, no
> promotion, no flag, no migration, no fleet activation. It adds one machine-
> checkable gate to a protocol that is, and stays, BLOCKED.

---

## 0. The immutability line (READ FIRST)

Two things are frozen and MUST NOT change as a result of this governance:

1. **v3** — `docs/specs/e19_2b_preregistered_protocol_v3.md`, LF-normalized
   SHA-256 **`cfdcfc9e7fc7c4d1fd56a5b3ec98d910c5093c2d8e39e4ac7121c51a847903c6`**.
2. **v2** — `docs/specs/e19_2b_preregistered_protocol.md`, LF-normalized SHA-256
   **`50e7e237436f1bc43d9679c1081eb1e8218048640fb1b325885fd2cf0bc3b76c`**.

Both are pinned in `packages/quantum/tests/test_e19_2b_preregistration.py`, and
this governance's own tests (`test_e19_upstream_hash_registry.py`) re-assert both
against the real doc bytes. **Never edit the frozen protocol to "fix" a drift.**
Drift is RESOLVED by freezing a NEW protocol version (v4…), never by mutating v3
or v2. This mirrors the #1051 rollback convention (revert-PR + owner
sign-off, never a silent mutation) and CLAUDE.md §9's anti-#1126 rule (the wiring
test exercises the real artifact, never a reimplementation).

The registry this governance introduces is a **faithful mirror** of the frozen
v3 §12 pins, not a second source of truth: its freeze hashes are the §12 values
verbatim, and a test asserts registry == the §12 block parsed from the real doc,
so the two can never silently diverge.

---

## 1. Why a frozen §12 goes stale — the transitive-pin gap

- The v3 §12 hashes were computed at the **science-freeze base
  `79f4ba76`** (the v2 authoring base `ed5d6f48` carried byte-identical upstream
  content). v3 deliberately carried §12 **VERBATIM** — re-pinning at the v3
  authoring base would have changed the frozen science, which a re-version of the
  §7 *threshold value only* must not do.
- Between the v2/v3 science base and current `origin/main`, upstream modules
  **drifted**. As of registry authoring base `04b376b5`, exactly **two** of the
  eight §12 modules differ from their freeze hash (§4).
- Nothing in the frozen doc can catch this: §12 is immutable text asserting old
  hashes. The gap is structural, not a bug in v3 — it is the price of freezing
  science by transitive reference. This governance closes it with an EXTERNAL,
  re-checkable registry + a typed gate.

---

## 2. The versioned supersession procedure (the only sanctioned response to drift)

When the live hash of any §12 upstream module differs from the protocol's recorded
freeze hash, the protocol is **STALE**. A stale protocol MUST be handled as
follows — and no other way:

1. **Do not edit the frozen protocol.** v3 (and v2) stay byte-identical. Their
   pins keep biting.
2. **Author a NEW protocol version** (v4 = a NEW file,
   `e19_2b_preregistered_protocol_v4.md`), exactly as v3 was authored alongside
   v2. The new version re-pins §12 at the new science base and records, in its
   version block, WHICH upstream modules changed and WHY (the causal PR/SHA), so
   the science delta is a visible, reviewed diff — never a silent carry-forward.
3. **Re-pin in one reviewed commit.** Add the new doc's frozen hash to
   `test_e19_2b_preregistration.py` and add a new registry tuple
   (`E19_2B_V4_UPSTREAM_REGISTRY`) to `e19_upstream_registry.py`, pointing
   `PROTOCOL_VERSION` at v4. The prior version's doc pin and registry stay
   asserted (a change to EITHER fails), so history is preserved.
4. **Owner sign-off**, exactly as a measurement-correction rollback (#1051). No
   flag silently promotes a new frozen protocol over a stale one.
5. **Re-evaluate the §10 execution gates against the new science.** A re-freeze
   is NOT an unblock: the fleet-activation, capital-parity, and threshold-met
   gates are re-checked under v4. Superseding the STALE marker clears only the
   staleness refusal (§4), never the protocol's own blocks.

A schema migration, a merged PR, or an owner design approval is **not** a
supersession. Supersession is: new versioned doc + new frozen hash + new registry
tuple + owner sign-off, in one reviewed commit. Until that lands, the stale
protocol's execution stays refused (§4).

---

## 3. The upstream-hash registry (machine-checkable mirror of §12)

`packages/quantum/tests/e19_upstream_registry.py` is the registry. It is
side-effect free (reads files, hashes bytes; creates/activates/writes nothing).

> **Why it lives in the tests tree.** The registry names the paths of the
> observe-only `terminal_distribution` package (to hash them). The import-lock
> guardrail (`test_terminal_distribution_import_lock.py`) forbids ANY production
> module under `packages/quantum` from even referencing the string
> `terminal_distribution`, and excludes the tests tree precisely because
> preregistration/integrity verification legitimately references it. The
> registry imports nothing from the package — it only reads bytes — so it lives
> with the verification tooling, honestly, rather than obfuscating the path in a
> production module. The execution-refusal gate it defines is a contract for the
> (unbuilt, BLOCKED) E19 executor, which is itself observe-only experiment
> tooling, not a live-economics module.

- **`E19_2B_V3_UPSTREAM_REGISTRY`** — an ordered tuple of `UpstreamModulePin`
  (`logical_name`, `repo_relative_path`, `freeze_hash`), one per §12 upstream
  module. The `freeze_hash` values are the §12 pins VERBATIM.
- **Hash basis — CRLF-normalized, platform-independent.** The §12 pins were
  authored on a Windows checkout (`core.autocrlf=true`), so each is the SHA-256
  of the module with **CRLF** line endings. To reproduce those pins IDENTICALLY
  on a Linux CI checkout (LF) and a Windows checkout (CRLF), the registry
  canonicalizes every module to CRLF before hashing (`content_hash` →
  `_crlf_normalized`: collapse any CRLF/CR/LF to LF, then expand to CRLF —
  idempotent). This is the same exact-content, EOL-independent discipline the
  doc-hash test uses (it normalizes to LF); the module registry normalizes to
  CRLF solely because that is the basis §12 was pinned on. A test
  (`test_content_hash_reproduces_a_section12_pin`) proves the basis reproduces a
  §12 pin from raw bytes.
- **Faithfulness is enforced.** `test_registry_freeze_hashes_equal_doc_section12`
  parses the §12 block out of the real frozen v3 doc and asserts every registry
  freeze hash equals its doc pin, and `test_registry_covers_exactly_section12_
  modules` asserts the module SET matches. The registry cannot drift from the
  doc it mirrors.

---

## 4. Stale-protocol detection (typed) + the recorded KNOWN delta

`evaluate_staleness()` re-hashes each registry module from disk and compares to
its freeze hash, returning a typed `StalenessReport`:

- Per module: `ModuleHashStatus` ∈ {`MATCH`, `DRIFTED`, `MISSING`}. `MISSING`
  (unreadable module) is DISTINCT from `DRIFTED` — a read failure can never
  masquerade as fresh or as a content change (H9 / loud-error doctrine).
- `report.is_stale` is `True` iff any module drifted OR any module is missing.
  Fresh requires EVERY §12 module present and byte-identical to freeze.

**Current state at `04b376b5` — the honest KNOWN stale delta.** Exactly two §12
modules have drifted; the other six are byte-identical to freeze:

| §12 module | freeze hash (§12) | current hash | status |
|---|---|---|---|
| `contract.py` | `4523a81c…` | `fd1a7098…` | **DRIFTED** |
| `terminal_distribution/__init__.py` | `b983a31e…` | `216f1ca8…` | **DRIFTED** |
| `evaluator.py` | `d0ecb19e…` | (same) | MATCH |
| `payoff.py` | `6e119d0b…` | (same) | MATCH |
| `challenger_lognormal.py` | `0c5cc23d…` | (same) | MATCH |
| `baselines.py` | `c3f2977b…` | (same) | MATCH |
| `policy_lab/shadow_fleet.py` | `670e8f34…` | (same) | MATCH |
| `policy_lab/fork.py` | `1f1d2386…` | (same) | MATCH |

**Provenance of the drift:** PR **#1287** (squash `9b63dcc1`, single-leg
generation, DARK) added surface to the terminal_distribution `contract.py` and
package `__init__.py` between the v2 authoring base (`ed5d6f48`) and the v3
authoring base (`94aa6528`). The change is additive, but it is a change to the
frozen science's **contract** module — exactly the class of upstream drift this
registry exists to surface. Under §2, resolving it requires a v4 re-freeze; it is
**not** resolved by editing v3.

The two drifted modules and their live hashes are recorded in
`KNOWN_STALE_MODULES`. `test_known_stale_current_hashes_match_recorded_snapshot`
asserts each drifted module's live hash equals the recorded snapshot, so any
**further** upstream change (drift beyond the recorded delta) fails loudly rather
than being absorbed silently. `test_stale_detection_fires_on_simulated_upstream_
change` mutates a currently-MATCHING module via an injected reader and confirms it
is detected as `DRIFTED` — the mechanism is not hardcoded to the known two.

---

## 5. The execution-refusal gate (contract)

`assert_upstream_fresh_for_execution()` is the gate the E19 executor MUST call.
It is an ADDITIONAL, independent gate on top of the protocol's own
`EXECUTION_STATUS: BLOCKED` and its §10 gates:

- It computes `evaluate_staleness()` and, if `is_stale`, **raises
  `E19UpstreamStaleError`** naming the drifted/missing modules. There is no
  "run anyway" return path — the gate is fail-closed.
- It returns the fresh `StalenessReport` ONLY when every §12 module is present
  and byte-identical to freeze.

**Contract for the (unbuilt) executor.** The real E19-2B executor is BLOCKED and
unbuilt. When it is built, its entrypoint MUST call
`assert_upstream_fresh_for_execution()` before any analysis, and MUST NOT catch
`E19UpstreamStaleError` into a soft path. Given the current KNOWN delta (§4), the
gate REFUSES today: even if every §10 gate were cleared, E19-2B could not run
against v3 while `contract.py`/`__init__.py` diverge from the frozen science —
the protocol would first have to be superseded by a v4 that re-pins §12 (§2).

This gate changes no live control. It defines refusal for a job that does not
run.

---

## 6. What this governance is NOT

- **Not an unblock.** E19-2B stays BLOCKED. This adds a refusal condition; it
  clears none of §10's gates.
- **Not a v4.** It defines the supersession PROCEDURE; it does not author a
  successor protocol. Authoring v4 (re-pinning §12 at a new science base) is a
  separate, owner-gated step, and it is not required by anything here — the
  protocol is blocked regardless.
- **Not a control/flag/threshold/schedule change.** Reconciliation/governance
  work never authorizes a live flag, gate, threshold, stop, universe, width,
  cadence, migration, or broker action (CLAUDE.md §9 / backlog closure
  discipline).
- **Not fleet activation.** No fleet slot is provisioned, activated, or bound.

---

## 7. Files

- Registry + detection + gate: `packages/quantum/tests/e19_upstream_registry.py`
  (verification tooling — in the tests tree by the import-lock guardrail; see §3)
- Tests: `packages/quantum/tests/test_e19_upstream_hash_registry.py`
- Immutable protocols (unchanged): `docs/specs/e19_2b_preregistered_protocol_v3.md`
  (`cfdcfc9e…`), `docs/specs/e19_2b_preregistered_protocol.md` (`50e7e237…`)
- Protocol immutability pins (unchanged): `packages/quantum/tests/test_e19_2b_preregistration.py`
