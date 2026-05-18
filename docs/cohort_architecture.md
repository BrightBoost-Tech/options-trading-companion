# Cohort architecture

Current state as of 2026-05-12 (last sub-investigation review). This document is a single coherent description of how the cohort subsystem works today — not a diff against an earlier framing.

## Three cohorts, two subsystems, one un-wired seam

The system has three cohorts (`conservative`, `neutral`, `aggressive`) in `policy_lab_cohorts` per user. There are two complete subsystems that touch cohorts:

1. **Champion/challenger evaluator** — `policy_lab/evaluator.py`, `policy_lab/scoring.py`, scheduled job `policy_lab_eval`. Fully built; runs daily; scores all 3 cohorts via 7 promotion gates (≥3 days, ≥10 trades, no -20% drawdown, ≥15% utility margin, ≥70% posterior probability, drawdown not worse than champion, 2-day cooldown). On promotion: writes `UPDATE policy_lab_cohorts SET promoted_at = NOW()` AND inserts a `policy_lab_promotions` audit row. 4 successful runs to date; 0 promotions (either no qualifying challenger or gates miscalibrated — empirical signal needed).

2. **Live route hardcode** — `packages/quantum/policy_lab/fork.py:67`. Hardcodes `cohort_name = "aggressive"` regardless of `promoted_at`. Source suggestions emerge from the orchestrator's `SmallAccountCompounder.rank_and_select` call at `packages/quantum/services/workflow_orchestrator.py:2049-2094` and are tagged with that hardcoded value. Fully built since 2026-03-20 (commit `f396334f`).

**The integration seam is the bug.** The evaluator writes `promoted_at`; the live route ignores `promoted_at`. Nothing currently reads `promoted_at` for routing. Each subsystem works correctly in isolation; the wire between them is missing.

This is the first concrete instance of "parallel architectures without integration" in this codebase — adjacent to but distinct from the H9 wrapper-drift class in `docs/loud_error_doctrine.md`. Worth design-review discussion alongside the #62a-D1 architectural PR.

## What IS wired today

- **Decision logging** (`policy_decisions` table) is live: every cycle records accept/reject decisions for all 3 cohorts. 189 decisions in the 30 days preceding 2026-04-25 (45 outcomes backfilled). Latest observed activity 2026-05-18.
- **Daily scoring** (`policy_daily_scores`) is functional as of 2026-04-26: PR #807 fixed the ImportError that prevented the endpoint from running; PR #808 fixed the schema drift that prevented writes. First successful canary populated 3 rows; subsequent scheduler-driven fires continued to land cleanly.
- `check_promotion` runs daily. Promotion eligibility resumes once `policy_daily_scores` accumulates a meaningful window of cohort data.

## What ISN'T wired

- **`promoted_at` → live routing.** The evaluator's promotion output is advisory until #62a-D1's architectural PR rewires `fork.py:67` to read champion via `promoted_at` lookup. `POLICY_LAB_AUTOPROMOTE` stays OFF (C-1 endpoint chosen) until evaluator gates have empirical track record.
- **Legacy `policy_lab_daily_results` table** has zero writers and zero consumers post-PR #808; cleanup tracked as backlog #73.

## Silent-failure `is_champion` query sites (bugs)

Two sites query a non-existent column `is_champion = True`, wrapped in `try/except: pass`, returning `None` on exception:

- `packages/quantum/services/paper_autopilot_service.py:867` — `_get_champion_portfolio`
- `packages/quantum/services/paper_exit_evaluator.py:892` — cohort fallback

Authored when someone assumed an earlier migration's `is_champion=true` INSERT intent would land as a column. Both are fixed (or deleted, if redundant) as part of #62a-D1's architectural PR — they should query via `promoted_at` instead.

## DB state misalignment (pending correction)

`promoted_at` is currently set on `neutral` (operator manual UPDATE on 2026-04-02 21:28Z, predating the intent clarification). It should be on `aggressive` per operator intent confirmed 2026-05-12 (aggressive = starting champion; conservative + neutral are shadow challengers). The DB flip ships in #62a-D1 alongside the routing rewire.

## Sizing duality (documented intent, not bug)

Two sizing layers operate on different blast surfaces:

- **Layer 1 — live aggressive trades:** sized via `SmallAccountCompounder` + `RiskBudgetEngine` (micro tier: 90% × regime_mult, one trade at a time). See CLAUDE.md "Risk per trade math".
- **Layer 2 — shadow cohort clones (conservative + neutral portfolios):** sized via `cohort.policy_config.max_risk_pct_per_trade × risk_multiplier` in `fork.py:196-201`. These trades execute against separate `paper_portfolio_id`s for shadow comparison.

These are intentionally separate sizing layers. Layer 1 drives live execution; Layer 2 drives shadow comparison data. Reconciliation is deferred until 30+ days of `policy_lab_daily_scores` accumulate to inform which layer's math correlates with better outcomes.

## Architectural PR #62a-D1 (queued)

Scope:

- DB: flip `promoted_at` from neutral to aggressive.
- Fix the 2 silent-failure `is_champion` query sites (or delete if redundant).
- Modify `fork.py:67` to read current champion via `promoted_at` lookup instead of hardcoding `"aggressive"`.

Effort: ~half day. No live trading behavior change at the moment of wire-up (aggressive stays live; this is mechanical correctness, not a param change). Tracked as #62a-D1 in `docs/backlog.md`.

## Roadmap

Backlog #65 covers reviving `policy_lab_eval` if the evaluator's gate calibration proves load-bearing for the autopromote decision. Without revival, the system runs single-strategy (aggressive only) with no learning loop on cohort comparisons — which is the current state.
