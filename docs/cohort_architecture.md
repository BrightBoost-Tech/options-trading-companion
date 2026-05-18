# Cohort architecture

Current state as of 2026-05-18 (post-#62a-D1 closure). This document is a single coherent description of how the cohort subsystem works today.

## Three cohorts, two subsystems, integration seam closed

The system has three cohorts (`conservative`, `neutral`, `aggressive`) in `policy_lab_cohorts` per user. Two subsystems touch cohorts:

1. **Champion/challenger evaluator** — `policy_lab/evaluator.py`, `policy_lab/scoring.py`, scheduled job `policy_lab_eval`. Fully built; runs daily; scores all 3 cohorts via 7 promotion gates (≥3 days, ≥10 trades, no -20% drawdown, ≥15% utility margin, ≥70% posterior probability, drawdown not worse than champion, 2-day cooldown). On promotion: writes `UPDATE policy_lab_cohorts SET promoted_at = NOW()` AND inserts a `policy_lab_promotions` audit row. 4 successful runs as of 2026-05-12; 0 promotions (either no qualifying challenger or gates miscalibrated — empirical signal needed).

2. **Live route reads `promoted_at`** — `packages/quantum/policy_lab/fork.py` now calls `get_current_champion(user_id, supabase)` from `policy_lab/champion.py`. The helper queries `promoted_at IS NOT NULL ORDER BY promoted_at DESC LIMIT 1` and returns the most-recently-promoted cohort_name. Defensive fallback to `"aggressive"` when no cohort is promoted (transition windows, fresh DBs). Source suggestions emerge from the orchestrator's `SmallAccountCompounder.rank_and_select` call at `packages/quantum/services/workflow_orchestrator.py:2049-2094` and are tagged with the resolved champion's `cohort_name`.

**Integration seam closure (#62a-D1, 2026-05-18).** Pre-PR, the evaluator wrote `promoted_at` and the live route hardcoded `"aggressive"` — nothing read what the evaluator wrote, nothing wrote what the consumer read. The hardcode is removed; the helper is the seam. See `docs/loud_error_doctrine.md` H13 — Parallel architectures without integration for the codified doctrine that the #62a-D1 incident originated.

`POLICY_LAB_AUTOPROMOTE` stays OFF (manual promotion only). The seam is wired; whether the evaluator's gates produce trustworthy promotions is a separate empirical question still under observation.

## What IS wired today

- **Decision logging** (`policy_decisions` table) is live: every cycle records accept/reject decisions for all 3 cohorts. 189 decisions in the 30 days preceding 2026-04-25 (45 outcomes backfilled). Latest observed activity 2026-05-18.
- **Daily scoring** (`policy_daily_scores`) is functional as of 2026-04-26: PR #807 fixed the ImportError that prevented the endpoint from running; PR #808 fixed the schema drift that prevented writes. First successful canary populated 3 rows; subsequent scheduler-driven fires continued to land cleanly.
- `check_promotion` runs daily. Promotion eligibility resumes once `policy_daily_scores` accumulates a meaningful window of cohort data.

## What ISN'T wired

- **`POLICY_LAB_AUTOPROMOTE` stays OFF** until the evaluator's gates have empirical track record. The seam is wired (#62a-D1, 2026-05-18); whether to flip the auto-promote env var is a separate decision pending observation of evaluator output over the next several weeks.
- **Legacy `policy_lab_daily_results` table** has zero writers and zero consumers post-PR #808; cleanup tracked as backlog #73.

## Resolved historical state (preserved for archeology)

### Silent-failure `is_champion` query sites — RESOLVED 2026-05-18

Two sites had been authored against an assumed-but-never-built `is_champion` column on `policy_lab_cohorts`. Each queried `is_champion = True`, wrapped in `try/except: pass`, returning `None` on every call:

- `packages/quantum/services/paper_autopilot_service.py:867` — `_get_champion_portfolio`
- `packages/quantum/services/paper_exit_evaluator.py:935-948` — `_resolve_position_cohort` path 3 (champion fallback)

#62a-D1 rewrote both to query `promoted_at IS NOT NULL ORDER BY promoted_at DESC LIMIT 1`. The silent `try/except: pass` is removed at both sites; exceptions now either log a warning (autopilot site, where None is a legitimate caller-expected value) or feed the existing `_resolution_failures` list that drives the loud `paper_exit_cohort_resolve_exhausted` alert (exit-evaluator site).

### DB state misalignment — RESOLVED 2026-05-18

Pre-PR: `promoted_at` set on `neutral` (operator manual UPDATE on 2026-04-02 21:28Z, predating the intent clarification). Post-migration (`20260518000001_promote_aggressive_cohort.sql`): `promoted_at` set on `aggressive`; `neutral` and `conservative` both NULL. Migration is operator-applied per `docs/migration_procedure.md`; the code's defensive fallback to `"aggressive"` ensures correctness across any deploy-vs-apply ordering.

## Sizing duality (documented intent, not bug)

Two sizing layers operate on different blast surfaces:

- **Layer 1 — live aggressive trades:** sized via `SmallAccountCompounder` + `RiskBudgetEngine` (micro tier: 90% × regime_mult, one trade at a time). See CLAUDE.md "Risk per trade math".
- **Layer 2 — shadow cohort clones (conservative + neutral portfolios):** sized via `cohort.policy_config.max_risk_pct_per_trade × risk_multiplier` in `fork.py:196-201`. These trades execute against separate `paper_portfolio_id`s for shadow comparison.

These are intentionally separate sizing layers. Layer 1 drives live execution; Layer 2 drives shadow comparison data. Reconciliation is deferred until 30+ days of `policy_lab_daily_scores` accumulate to inform which layer's math correlates with better outcomes.

## Architectural PR #62a-D1 — SHIPPED 2026-05-18

Scope (all three landed in one PR):

- DB: migration `supabase/migrations/20260518000001_promote_aggressive_cohort.sql` flips `promoted_at` from neutral to aggressive (operator-applied per `docs/migration_procedure.md`).
- The 2 silent-failure `is_champion` query sites rewritten to query `promoted_at`. Both eliminate the H9 anti-pattern (`try/except: pass`).
- `fork.py` reads the current champion via `get_current_champion(user_id, supabase)` helper in `policy_lab/champion.py`. Defensive fallback to `"aggressive"` preserves pre-PR behavior across any deploy-vs-DB-apply ordering.
- H13 doctrine entry codified in `docs/loud_error_doctrine.md` — Parallel architectures without integration.

No live trading behavior change at the moment of wire-up (aggressive stays the live champion; this was mechanical correctness, not a param change).

## Roadmap

Backlog #65 covers reviving `policy_lab_eval` if the evaluator's gate calibration proves load-bearing for the autopromote decision. Without revival, the system runs single-strategy (aggressive only) with no learning loop on cohort comparisons — which is the current state.
