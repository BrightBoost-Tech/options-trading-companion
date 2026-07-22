# Single-Leg Shadow Experiment v1 — guarded enablement runbook

**Scope:** independent one-contract `long_call` / `long_put` research only.
**Routing:** `shadow_only`. **Execution:** `internal_paper`. **Broker:** impossible.
**Fleet:** not used. **Existing `small_tier_v1` policies:** untouched.

This runbook intentionally separates migration application, draft-policy seed,
disabled setup, no-write replay, approval, and enablement. Never collapse these
steps into one transaction or enable before the prior receipt is verified.

## Preconditions

- Market closed.
- Broker positions and open orders independently verified flat.
- BE, worker, and worker-background on one reviewed main SHA.
- No merge/deploy/migration is in flight.
- Foundation migration `20260721190000_single_leg_shadow_experiment_foundation.sql`
  is already applied.
- The following code is merged and deployed:
  - independent scheduler-only child scan;
  - internal-paper open/expiry custody;
  - deterministic reader and no-write replay.
- `single_leg_experiment_v1` currently has zero policy rows, epoch rows,
  bindings, runs, attempts, orders, positions, outcomes, and cash events.
- The target user already has at least one established `live_eligible`
  `paper_portfolios` row created before this experiment. The setup RPC creates
  two *new* shadow-only portfolios; it must never become the user's first/default
  paper-portfolio surface. Stop if no live-eligible portfolio exists.
- Existing Policy Lab cohort mappings, if used, resolve only through
  `policy_lab_cohorts.portfolio_id`; do not reuse either experiment portfolio as
  a Policy Lab cohort portfolio.

Use one immutable target user UUID as `:USER_ID`. Never paste credentials into
SQL, reports, or prompts.

Before any setup write, capture the existing portfolio baseline:

```sql
select id, name, routing_mode, cash_balance, net_liq, created_at
from paper_portfolios
where user_id = ':USER_ID'::uuid
order by created_at, id;
```

Required: at least one pre-existing `live_eligible` row and zero rows named
`Single Leg Throughput v1` / `Single Leg Conviction v1`. Preserve this result
with the setup receipt.

## Phase 1 — apply lifecycle migrations in order

Apply exactly once:

```text
20260722010000_single_leg_shadow_internal_lifecycle.sql
20260722010100_single_leg_shadow_open_rpc_concurrency_hardening.sql
```

Then verify all four tables and both RPCs exist:

```sql
select
  to_regclass('public.single_leg_shadow_orders') as orders,
  to_regclass('public.single_leg_shadow_positions') as positions,
  to_regclass('public.single_leg_shadow_outcomes') as outcomes,
  to_regclass('public.single_leg_shadow_cash_events') as cash_events;

select proname, oidvectortypes(proargtypes) as args
from pg_proc
where proname in (
  'rpc_open_single_leg_shadow_position_v1',
  'rpc_close_single_leg_shadow_position_v1'
)
order by proname, args;
```

Expected: one overload per RPC. Verify zero business rows:

```sql
select
  (select count(*) from single_leg_shadow_orders) as orders,
  (select count(*) from single_leg_shadow_positions) as positions,
  (select count(*) from single_leg_shadow_outcomes) as outcomes,
  (select count(*) from single_leg_shadow_cash_events) as cash_events;
```

Expected: `0 | 0 | 0 | 0`.

## Phase 2 — apply control-RPC migration

Apply exactly once:

```text
20260722020000_single_leg_experiment_control_rpcs.sql
```

This migration creates functions only. It must not create policies, portfolios,
bindings, or enable the epoch.

Verify one overload per control function and `service_role`-only execution:

```sql
select proname, oidvectortypes(proargtypes) as args, prosecdef
from pg_proc
where proname in (
  'single_leg_experiment_expected_policies_v1',
  'single_leg_experiment_current_fingerprint_v1',
  'rpc_setup_single_leg_experiment_v1',
  'rpc_approve_single_leg_experiment_v1',
  'rpc_enable_single_leg_experiment_v1',
  'rpc_pause_single_leg_experiment_v1'
)
order by proname, args;
```

## Phase 3 — seed the four exact DRAFT registrations

Review the merged file, then execute exactly once:

```text
supabase/seed-transactions/policy_registrations_single_leg_experiment.sql
```

Post-check:

```sql
select
  policy_registration_id,
  approval_status,
  effective_epoch,
  config_hash,
  policy_config->>'single_leg_experiment_enabled' as opt_in
from policy_registrations
where effective_epoch = 'single_leg_experiment_v1'
order by policy_registration_id collate "C";
```

Expected:

| policy | status | opt-in |
|---|---|---|
| `sl_ctrl_conviction_v1` | `draft` | `NULL` |
| `sl_ctrl_throughput_v1` | `draft` | `NULL` |
| `sl_exp_conviction_v1` | `draft` | `true` |
| `sl_exp_throughput_v1` | `draft` | `true` |

No other row may exist in the epoch.

## Phase 4 — T1 disabled setup

Re-run the portfolio-baseline query from Preconditions. Stop if the target has
no pre-existing `live_eligible` portfolio or if an experiment-named portfolio
already exists without a matching disabled binding receipt.

Call the setup RPC with the exact user and fixed `$2,000` experimental capital:

```sql
select rpc_setup_single_leg_experiment_v1(
  p_user_id := ':USER_ID'::uuid,
  p_starting_capital := 2000,
  p_created_by := 'operator-2026-07-22'
);
```

Save the returned full `setup_fingerprint`; do not shorten it. Expected receipt:

```text
status = disabled_setup_ready
policy_rows = 4
experimental_bindings = 2
enabled_bindings = 0
starting_capital = 2000
```

Verify:

```sql
select epoch_name, state, routing_mode, max_contracts, live_submit_allowed,
       config_hash, version
from single_leg_experiment_epochs
where epoch_name = 'single_leg_experiment_v1';

select b.policy_registration_id, b.role, b.enabled, b.routing_mode,
       b.execution_mode, pp.name, pp.cash_balance, pp.net_liq,
       pp.routing_mode as portfolio_routing, pp.created_at
from single_leg_experiment_bindings b
join paper_portfolios pp on pp.id = b.portfolio_id
where b.epoch_name = 'single_leg_experiment_v1'
  and b.user_id = ':USER_ID'::uuid
order by b.policy_registration_id collate "C";
```

Expected: epoch `disabled`; exactly two experimental bindings; both disabled;
both portfolios `shadow_only`, `cash_balance=net_liq=2000`, and both created
after the pre-existing live-eligible default portfolio.

At this point the natural parent scan still performs zero child provider calls
and writes zero experiment rows.

## Phase 5 — mandatory no-write replay

Choose the latest complete natural scheduler-origin `suggestions_open`
`decision_id` for `:USER_ID`. Do not use an operator-forced scan.

Run:

```bash
python scripts/analytics/single_leg_shadow_dry_run.py \
  --user-id :USER_ID \
  --decision-id :DECISION_ID \
  --json-out single-leg-dry-run.json
```

Required proof:

```text
write_mode = NO-WRITE
database_write_attempts = 0
provider_calls = 0
broker_calls = 0
data_source = stored_decision_tape
policies_evaluated = 2
policy IDs = sl_exp_conviction_v1 + sl_exp_throughput_v1
attempts = contexts × 2
all candidates contracts=1, routing=shadow_only, lifecycle_state=experimental
```

`HONEST-EMPTY` is acceptable when typed rejections explain all evaluated
contexts. Stop on hash/config/schema drift, incomplete or non-OK tape, wrong
strategy/user/decision identity, zero replayable contexts, incomplete outcome
coverage, candidate-invariant failure, failed read, or any attempted database
write/RPC/provider/broker action.

Re-run the database zero census after the dry-run. It must remain zero in runs,
attempts, events, orders, positions, outcomes, and cash events.

## Phase 6 — T2 approve exact policy rows

Only after the no-write replay passes, repeat the disabled custody check:

```sql
select
  count(*) as binding_count,
  count(*) filter (where b.enabled) as enabled_bindings,
  count(*) filter (
    where b.role = 'experimental'
      and b.routing_mode = 'shadow_only'
      and b.execution_mode = 'internal_paper'
      and pp.routing_mode = 'shadow_only'
      and pp.cash_balance = 2000
      and pp.net_liq = 2000
  ) as exact_disabled_custody
from single_leg_experiment_bindings b
join paper_portfolios pp on pp.id = b.portfolio_id
where b.epoch_name = 'single_leg_experiment_v1'
  and b.user_id = ':USER_ID'::uuid;
```

Expected before approval: `binding_count=2`, `enabled_bindings=0`,
`exact_disabled_custody=2`. Also verify no normal `paper_orders` or
`paper_positions` references either experiment portfolio. Stop on any mismatch.

Then call:

```sql
select rpc_approve_single_leg_experiment_v1(
  p_user_id := ':USER_ID'::uuid,
  p_setup_fingerprint := ':FULL_SETUP_FINGERPRINT',
  p_approved_by := 'operator-2026-07-22'
);
```

Expected: four exact rows approved; epoch remains disabled; both bindings remain
disabled. Verify all existing `small_tier_v1` rows are unchanged.

## Phase 7 — T3 enable shadow-only accrual

Only after approval, deployment checks, flat-book recheck, a deterministic
reader baseline, and another exact-custody query returning `2 / 0 / 2`:

```sql
select rpc_enable_single_leg_experiment_v1(
  p_user_id := ':USER_ID'::uuid,
  p_setup_fingerprint := ':FULL_SETUP_FINGERPRINT',
  p_enabled_by := 'operator-2026-07-22'
);
```

Expected receipt:

```text
status = enabled
routing_mode = shadow_only
execution_mode = internal_paper
max_contracts = 1
live_submit_allowed = false
enabled_bindings = 2
```

Do **not** manually run `suggestions_open` or the child job. The first evidence
must come from the next natural scheduler-origin parent cycle.

## Phase 8 — natural runtime proof

After the next natural scan, run:

```bash
python scripts/analytics/single_leg_shadow_report.py \
  --user-id :USER_ID \
  --json-out single-leg-shadow-report.json \
  --markdown-out single-leg-shadow-report.md
```

Verify:

- one idempotent child per source decision;
- exactly two experimental policies evaluated;
- controls create no single-leg attempts;
- every evaluated context has a typed attempt or candidate;
- any order has one contract, `shadow_only`, `internal_paper`, and
  `live_submit_allowed=false`;
- broker order count remains zero;
- existing champion/default suggestion output is unchanged;
- no fleet, calibration, TCM, promotion, E19, or live-learning row consumes the
  experimental outcome.

A zero-candidate first run is `HONEST-EMPTY`, not failure, when attempts are
complete.

## Immediate rollback / pause

The persisted kill switch is:

```sql
select rpc_pause_single_leg_experiment_v1(
  p_user_id := ':USER_ID'::uuid,
  p_reason := 'operator_pause'
);
```

This disables all epoch bindings and stops new child generation while
preserving attempts, open positions, and outcomes. Open internal-paper positions
remain eligible for safe expiry settlement. Pausing never deletes evidence and
never affects the normal live/default or Policy Lab clone path.

## Absolute exclusions

This procedure does not authorize:

- broker orders;
- fleet provisioning or activation;
- edits to any `small_tier_v1` policy;
- live single-leg routing;
- manual scan/job triggers;
- OI-floor, taper, Greek-cap, TCM, E19, calibration, H7, liquidity, DTE, width,
  sizing, or risk-control changes;
- historical data backfills;
- F-REDATE correction.
