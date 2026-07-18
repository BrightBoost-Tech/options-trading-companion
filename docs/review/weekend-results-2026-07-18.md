# Weekend Orchestrator Results — 2026-07-18 (Sat)

ORCHESTRATOR=fable · SUBAGENTS=opus (≤6 parallel; reviews read-only, builders isolated worktrees)
· market CLOSED throughout (broker clock; next open Mon 07-20 09:30 ET) · production writes
Fable-serialized, one at a time, broker/alert checkpoint after each · zero broker writes · zero
fleet writes · operator worktree byte-preserved (baseline hash `0d3067b4…` re-pinned at Phase 0
after attributing drift to the nightly audit's untracked 07-18 report).

## Wave 1 — serialized production data corrections (all four committed + verified)

1. **F-CREDIT-SIGN historical correction** (fp `b780271c…`; opus revalidation exact-PASS from
   primary facts; single transaction, row-locked, gate-checked, rollback-on-mismatch):
   19 orders → magnitude fills + audit metadata · 18 positions → truthful realized
   (aggregate **−14,367.00**) · 19 compensating `paper_ledger` adjustments (cash **−16,971.00**:
   Main Paper −8,895 / Aggressive −3,432 / Neutral −4,644) · 20 learning rows · 9 policy rows.
   Two win→loss flips: QQQ `c1c9ad04` → **−224.04**, AMD `75204e83` → **−242.00**. Post-commit
   census re-run: **0 remaining**. All rows shadow/internal (`is_paper=true`) — streak breaker
   (live-only) unaffected. Original history preserved (compensating entries; no fill rewrites).
2. **Six stale 04-09 orders** (fp `04317fc1…`; opus revalidation PASS — all six never-sent/
   broker-rejected, no broker ids exist): → `cancelled` (4× `broker_reject_at_submit_never_accepted`,
   2× `local_validation_reject_never_sent`), originals preserved in `reconciliation_audit`.
   `still_submitted=0` after.
3. **Seventh blocker row** `a94a2761` (needs_manual_review since 05-11): opus investigation
   CONCLUSIVE (CSX credit-close sign-bug pre-submit rejection ×3, never routed; position `1f77f6af`
   manually dashboard-closed at the broker 8m23s BEFORE staging, realized −161 broker-corroborated)
   + second adversarial opus review **PASS-WITH-AMENDMENT** (codebase convention: `'rejected'` is
   never persisted; exact-class 04-09 precedent) → amended plan fp `5d5cd9fc…` executed:
   → `cancelled` / `local_validation_reject_never_sent`, prior state preserved. Position untouched.
4. **Five orphan job_runs** (fp `40258ba9…`; opus revalidation PASS incl. successor-run existence
   and fresh container-uptime guard): all five → `cancelled`/`stranded_nonterminal_status` with
   verbatim originals in `error.reconciliation`; CAS guards all hit UPDATE 1. Non-terminal
   job_runs now **0**.

**Result: the legacy-terminal activation boundary is fully clean** — 0 non-terminal orders,
0 non-closed positions, 0 non-terminal job_runs. Broker 0/0 and zero new critical/high at every
checkpoint; `entries_paused=false` throughout.

## Wave 2/4 — code lanes (all six merged with opus adversarial review PASS + current-head CI + per-merge deploy verification)

| lane | PR | squash SHA | deploy |
|---|---|---|---|
| 2E test-infra landmine (capital-basis sys.modules + collection-order regression) | #1257 | `4b311180` | SUCCESS |
| 2A job_runs `'partial'` CHECK (+ migration, see below) | #1256 | `25d0f494` | SUCCESS |
| 2C multi-basis consumer #1 — observe-only cost-reconciliation artifact on dispositions | #1258 | `72f689c0` | SUCCESS |
| 2D stage-time leg greeks population (typed, observe-only, no caps) | #1259 | `7f393580` | SUCCESS |
| 2B ⑤ challenger study runner + dated report | #1260 | `264b720d` | SUCCESS |
| 2F check_greeks null-safe + typed `greeks_coverage` (dormancy byte-proven) | #1261 | `e0a1584` | **BE FAILED** (see below) |

**Migration applied** (authorized): `job_runs_status_check_partial` — history `20260718144818`
(by name; file `20260718150000_…`, sha `eeacd9b6…`), preflight ABSENT_CLEAN, constraint = six
originals + `'partial'`, **zero job rows changed** (14,544 / max_updated byte-identical), receipt
risk_alerts `38e5ecd9…`. The 'partial' writer already shipped (F-A4-1) — the latent 23514
requeue-storm class is closed.

**⑤ evidence verdict (PR #1260 report `docs/review/challenger-study-2026-07-18.md`):**
**INSUFFICIENT_EVIDENCE** — over all 82 corrected closed outcomes (8 live / 74 shadow), the
lognormal challenger and frozen adapter abstain on 100% (per-leg IV/spot/delta never persisted);
head-to-head n_joint=0. Blocker is stage-seam data capture, not model quality. Frozen baseline
on live n=8: Brier 0.3105, EV-RMSE $69.31, net −$178 (reported, below all decision floors).
Never promoted; nothing scheduled.

## Wave 3 — fleet: BLOCKED_FLEET_PROVISION (zero fleet writes)

Boundary now clean, RPCs present, tables empty — but provisioning is blocked on two independent
grounds (bundle `fleet-readiness-2026-07-18.md`): (1) `execute_provision` requires
`FLEET_ACTIVATION_AUTHORIZED=1` (shadow_fleet_activation.py:93,149-164,590) — an env change,
forbidden tonight (CONDITIONAL_NO_ENV_CHANGE fails; direct-RPC bypass would violate the
strict-endpoint condition); (2) **no set of 50 pre-registered policy identities exists** — owner
selection manifest produced (policy source options a/b/c + env-window + attestation inputs).
Activation forbidden and untouched. Fleet counts 0/0/0, receipts 0.

## Deployment state at close — MIXED BACKEND (flagged, unresolved by code)

The #1261 merge (`e0a1584`) deployed SUCCESS on worker, worker-background, FE; **BE FAILED at
Railway despite a clean container start** (build pushed; deploy log shows full scheduler
registration + "Application startup complete" + Uvicorn serving — no crash, no restart; cause
NOT-PROVEN from logs, consistent with healthcheck/infra-side failure, not code). BE continues
serving the previous SUCCESS deploy `264b720d`. Behavioral risk: nil while dormant (#1261 is
null-safety + typed coverage with byte-proven dormancy; market closed; zero open positions).
Manual redeploy/restart is forbidden tonight — the docs-final merge triggers the standard
auto-deploy hook; its outcome adjudicates transient-vs-deterministic. **Morning ritual: verify
BE SHA converged; if BE failed again, treat as a deterministic BE-only deploy defect and
diagnose before Monday open.**

## Owner decisions still blocked (no action taken)

F-BAN build/remove · tier cliff · single-leg experimental · prequential scheduling · UI honesty
(Palette file ownership) · fleet: 50-policy selection + env window (new manifest).

## Natural falsifiers still pending (do not manufacture)

candidate_terminal_dispositions + option_quote_provenance first natural rows (Mon 07-20 scan
cycle) · first live-open preflight · first internal credit close post-#1240 · #1228 reader ·
#1229 (09-07) · challenger scorability (needs stage-seam iv/spot/delta capture — new P1 feeder)
· first natural `'partial'` job_runs row (constraint now accepts it).

## New findings for the ledger

- **Nightly audit runner died 07-16 and 07-17** (from the swept 07-18 report: two scheduled
  Task-Scheduler runs never produced reports; 07-18 ran broker-blind/headless). Runner
  reliability + headless-mode Alpaca MCP absence = new P1 ops item.
- BE deploy FAILED on clean start (above) — watch item.
- job_runs terminal vocabulary (orchestrator erratum): `cancelled`/`dead_lettered` are terminal;
  a NOT-IN filter must use the real six-status set, not completed/failed guesses.
