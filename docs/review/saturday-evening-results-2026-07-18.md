# Saturday-Evening Orchestrator Results — 2026-07-18 (third Sat run)

ORCHESTRATOR=fable · SUBAGENTS=opus (≤6; adversarial review before every merge; two lanes
required FAIL→repair→re-verify cycles) · market CLOSED throughout · ZERO broker writes · ZERO
production DB writes · ZERO migrations created or applied · ZERO fleet actions · operator
worktree byte-identical (`0d3067b4…`).

## Operator checkout pull — BLOCKED_OPERATOR_PULL_CONFLICT

FF-safety check: branch=main ✓, HEAD `f34d5cd` is an ancestor ✓, but the dirty TRACKED file
`audit/ledger.md` (+281 local uncommitted lines) overlaps the HEAD→main change set → the
authorized `git pull --ff-only` was NOT run; everything preserved. Delta exported to bundle
`operator-local-ledger-delta-2026-07-18.patch` (292 lines). **Non-destructive handoff** (also in
`sunday-nightly-audit-verification-2026-07-19.md`): review the patch → `git checkout --
audit/ledger.md` → `git pull --ff-only` → confirm `audit/runner/nightly_runner.py` exists.
**Consequence: tonight's 00:00 CT nightly runs the OLD cmd flow under the NEW task protections
(PT2H limit, restart, wake). The wrapper flow starts only after the operator pull.**

## Merged + deployed (serialized; per-merge all-services SUCCESS + broker/alert checks)

| lane | PR | squash SHA | notes |
|---|---|---|---|
| L1 ⑤ scan-time spot | #1274 | `e2f91ac2` | scanner current_price → candidate → order_json carrier → stage entry_underlying_spot {source:'scan_time', deterministic provider-ts as_of}; legs-only fingerprint proven; review PASS |
| L2 E4/E5 invariant | #1272 | `94a4cdb3` | CONFIRMED + fixed: hard-mode quality-gate deaths now record exactly one final (`h7_dropped` + reason e4/e5 + `sizing_outcome='marketdata_quality_gate'` amendment); soft mode byte-identical; **owner ratification of the value choice recorded as an open item** |
| L5 source mislabel | #1271 | `53e86f53` | one-line fix; field was in-memory only (zero persisted-bytes change) |
| L3 realized cost consumer #3 | #1273 | `9cb3876a` | review FAIL→repair→re-verify PASS: fees provenance corrected per-routing (broker-routed = REAL $0 Alpaca commission via reconciler; internal typed-unavailable); evidence: TCM over-charges commission −1.55 mean on zero-fee options; F-CREDIT-SIGN double-correction definitively refuted (19 pure sign-flips) |
| L6 drift-summary quirk | #1275 | `da70b67e` | test-only; stub proven rescue-not-poison; both collection orders green |
| L4 stress D2 residual | #1276 | `02b2d8b0` | CONFIRMED + fixed: signed accumulation via the canonical `_direction_sign`; clamp byte-preserved; `worst_case ≡ correlation_one` invariant proven → warn surface byte-identical; 5 pins flipped |

**Final code main: `02b2d8b0`** (docs PR follows). All four services deploy-verified at every step.

## Review-cycle catches worth ledgering

- #1273 first review caught an INVERTED fees-provenance claim (live-cohort `fees_usd` is the real
  $0 broker commission, not the TCM estimate) — the repair made commission per-routing honest.
  Reviewer erratum corrected in-flight: the F-CREDIT-SIGN corrections DID execute 07-18 (a stale
  swept report said otherwise); the study is immune either way.
- #1272 second review adjudicated the `h7_dropped` value DEFENSIBLE over the brief's
  `persisted_blocked` (die-before-persist honesty) and got the typed sub-key amendment.
- #1276 reviewer proved the stress warn-surface cannot change behavior (`worst_case ≡
  correlation_one`, payoff-geometry invariant) — measurement-only, as designed.

## ⑤ scorability status

Delta (#1259) + per-leg IV (#1266) + scan-time spot (#1274) now capture at every OPEN stage.
The FIRST closed outcome originating from a post-tonight open becomes scorable by BOTH the
frozen adapter and the lognormal challenger. Historical rows abstain forever (honest).

## Runtime prompts (bundle)

- `sunday-nightly-audit-verification-2026-07-19.md` — start/end markers, heartbeat, manifest,
  snapshot/MCP, structural report, exit, ping, failure artifact; covers old-flow vs wrapper-flow.
- `monday-natural-evidence-check-2026-07-20.md` — extended with tonight's items: quality-gate
  finals (sizing_outcome key), scan-time spot on staged order_json, adapter/challenger first
  scorable outcome, source_used string, realized study usage, signed stress numbers.

## Migrations: NONE created, NONE applied. Owner decisions still blocked

Fleet registration mechanism + which-50 + env window (3 honest identities vs 50) · C2 top-level
taxonomy (now also: ratify `h7_dropped` for quality-gate deaths) · F-BAN · tier cliff ·
single-leg · prequential · UI files · live greek caps · OI floor (until Monday evidence) ·
E19-2B.
