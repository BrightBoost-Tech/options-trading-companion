# Saturday-Night Orchestrator Results — 2026-07-18 (second Sat run)

ORCHESTRATOR=fable · SUBAGENTS=opus (≤6; builders in isolated worktrees, adversarial review
before every merge) · market CLOSED throughout · ZERO broker writes · ZERO production DB
writes (no insert/update/delete/RPC) · ZERO migrations created or applied · ZERO fleet
actions · operator worktree byte-identical start-to-finish (`0d3067b4…`). One authorized
LOCAL change: the nightly-audit Task Scheduler task (backup + rollback preserved).

## Merged + deployed (serialized; each: adversarial review PASS → update-branch → current-head CI → squash → all-services deploy SUCCESS → broker/alert check)

| lane | PR | squash SHA | notes |
|---|---|---|---|
| L1 nightly-audit runner reliability | #1264 | `592a267a` | all six failure-class findings VERIFIED; wrapper (wake lock, single-instance, heartbeat, timeout→kill, unconditional end marker, atomic report), fresh audit worktree at origin/main, GET-only scrubbed broker snapshot, completion contract |
| L3 cost consumer #2 | #1265 | `35836cdc` | scanner_estimate + scanner_unified_final bases now AVAILABLE in the disposition artifact; wall-clock-free capture (determinism regression caught in-lane) |
| L4A canonical greeks wiring | #1263 | `a558de7e` | normalize_leg auto-sources persisted stage greeks; sign applied exactly once; observe-only canonical_greeks in envelope output |
| L4B D2 signed aggregate | #1269 (re-landing of reviewed #1267 after stacked-squash conflict; content identical) | `fdcaf644` | D2 CONFIRMED in check_greeks unsigned add → fixed via canonical `_direction_sign`; four defect-pins flipped to pin the fix (audited); caps stay 0/dormant |
| L2 ⑤ spot/IV capture | #1266 | `851416a0` | per-leg IV captured same-fetch; entry spot honestly typed-unavailable (no same-fetch source). Review FAIL→repair→re-verify PASS: STUDY_SQL close-contamination fixed (marker-gated open-order LATERAL — `entry_underlying_spot` has exactly one writer, the OPEN path; geometry always suggestion legs) |
| C1 startup flag echo | #1268 | `76757684` | 27-flag registry pointing at REAL parsers; wired BE + both workers; allowlist-scrubbed. Repair in-lane: the wiring TEST was itself a sys.modules polluter (broke rebalance contract tests on CI) → subprocess-isolated route tests |

**Local Task Scheduler change (authorized, applied by Fable after review PASS):** nightly-audit
task re-registered from the reviewed XML — deltas exactly {ExecutionTimeLimit PT2H ·
RestartOnFailure 2×PT10M · StopOnIdleEnd=false · WorkingDirectory pinned}; trigger/principal/
command unchanged; read-back verified; next run Sun 00:00 CT. Backup + one-line rollback:
bundle `nightly-audit-task-backup-2026-07-18.xml` / `nightly-audit-task-APPLY-ROLLBACK.md`.
Wrapper self-test run post-merge: exit 0, contract met=True, ping correctly no-op'd.
**⚠ Operator action: `git pull` in C:\options-trading-companion before Sun 00:00 CT** — the
task still invokes run-nightly.cmd there; until pulled, the old flow runs (under the new
task-level protections). Byte-preservation forbade the orchestrator pulling it.

## Read-only packets (bundle `otc-friday-post-close-2026-07-17\`)

- **L5 fleet manifest**: honest policy identities = **3** (aggressive/conservative/neutral
  cohorts) vs **50 required — gap 47**; all three manifest options gap-stated, NOT padded;
  smallest registration design specced (operator-owned `policy_registrations` table, or config
  file variant — owner chooses WHICH 50 parameterizations); new provisioning + activation
  operator prompts via the STRICT endpoint (`fleet-manifest-*-2026-07-18.*`). The older
  `fleet-provisioning-operator-prompt.md` (direct-RPC route) is SUPERSEDED — it bypassed the
  env gate.
- **C2 sizing-loop taxonomy packet** (`sizing-loop-disposition-taxonomy-packet-2026-07-18.md`):
  9 record_final sites + 2 transforms inventoried; recommendation = Option C staged (detail
  sub-taxonomy now, no migration; defer top-level split). **Two real defects found:**
  E4/E5 — quality-gate HARD mode (`MIDDAY_QUALITY_GATE_MODE=hard`, non-default) drops a
  selected candidate with NO disposition record (invariant hole, latent bug); E3e/E3f —
  invalid-max-loss and lifecycle-veto deaths mislabeled `h7_dropped` (detail.reason preserves
  truth). Owner decides.
- **Monday check**: `monday-natural-evidence-check-2026-07-20.md` (natural dispositions/
  provenance/cost-artifacts/greeks-iv rows + writer counters; OI floor stays blocked until
  reviewed).

## New findings (ledgered)

1. **Flag-parser strictness quartet** (C1, VERIFIED-CODE): `CALIBRATION_ENABLED`,
   `SCHEDULER_ENABLED`, `RISK_ENVELOPE_ENFORCE` are strict `== "1"` (a `true` value would
   DISABLE calibration — footgun); `RISK_UTILIZATION_GATE_ENABLED` is strict too;
   `IV_RANK_NONE_ROUTING_ENABLED` accepts 1/true/yes but NOT on; `LIVE_ENABLED` true/1 only,
   no strip. §3's blanket "lenient variants" wording corrected. The echo now prints effective
   values at every process start.
2. **E4/E5 disposition invariant hole** (C2) — latent behind non-default hard mode; fix lane
   queued (reuse persisted_blocked + detail).
3. `options_scanner.py:4213` pre-existing mislabel: `execution_cost_source_used` filled from
   `execution_cost_samples_used` (LOW; the #1265 capture reads the correct raw keys).
4. **Stress-model unsigned-add residual** (`compute_stress_scenarios`) — D2 pattern remains
   there; payoff-clamped so bounded-safe; future stress-D2 lane.
5. **⑤ scorability path**: with #1266+#1259, the delta-only frozen adapter becomes scorable on
   future rows; the lognormal challenger still needs an honest spot source — reviewer-endorsed
   follow-up: thread the scanner's scan-time `current_price` (options_scanner.py:2989/3345)
   as `{source:'scan_time', as_of}` through the capture.

## Migrations: NONE created, NONE applied tonight. Owner decisions still blocked

F-BAN · tier cliff · single-leg · prequential · UI (Palette) · live greek caps · OI floor ·
E19-2B · fleet: registration mechanism + which-50 + env window · C2 taxonomy option.

## Natural Monday checks (do not manufacture)

First candidate_terminal_dispositions + option_quote_provenance rows (with cost_reconciliation
including scanner bases) · first stage rows carrying greeks+IV (+typed-unavailable spot) ·
writer error counters ≈0 · first live-open preflight if exercised · first natural 'partial'
job_runs row · Sunday 00:00 CT nightly run under the new task config (wrapper flow requires the
operator pull; watch cron.log end marker + dead-man ping either way).
