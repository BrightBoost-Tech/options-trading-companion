# APPLIED_UNTRACKED Migration-Tracking Operator Packet

- Generated (read-only audit): 2026-07-24
- Repo: `C:\options-trading-companion` (read in place, not modified)
- Migrations dir: `supabase/migrations/` (149 `*.sql` files)
- Production: Supabase `etdlladeorfgdmsopzmz` (SELECT-only via MCP)
- Tracking table: `supabase_migrations.schema_migrations` (59 rows at read time)
- **Zero production writes were performed. Every INSERT in the backfill section is NOT EXECUTED.**

## Counts

| Classification | Files |
|---|---|
| TRACKED | 59 |
| APPLIED_UNTRACKED | 87 |
| NOT_APPLIED | 2 |
| UNKNOWN | 1 |
| **TOTAL** | 149 |

## Packet fingerprint

Fingerprint = SHA-256 of the canonical classification body: one line per repo
file, sorted by filename ASC, format `filename|sha256|classification`, joined by
`\n`, no trailing newline.

**`d39ef69fed7690dc48cb18fe0c443b8217aa80f0e627dcf3c690b9b69c4ab581`**

## Methodology

1. Pulled the full `supabase_migrations.schema_migrations(version,name)` list (59 rows).
2. Inventoried all 149 `supabase/migrations/*.sql` and SHA-256'd each (certutil + python hashlib; agree).
3. **Name-normalized match** (project doctrine: match by NAME, never version prefix):
   strip a leading `\d{14}_` and `.sql` from BOTH the repo filename and the tracking
   `name`, then compare stems. This absorbs (a) tracking rows that store the bare
   descriptive name and (b) tracking rows that store the full `<prefix>_<name>` stem,
   and it tolerates the apply-time version stamp differing from the file's embedded prefix.
4. For every untracked-by-name file, verified object existence in production via
   `information_schema`/`pg_catalog`/`pg_class.relacl`/`pg_get_functiondef` SELECTs to
   split APPLIED_UNTRACKED from NOT_APPLIED; UNKNOWN where object state is indeterminate.
5. Correlated with `risk_alerts` `alert_type='migration_apply'` receipts.

**Version drift is the norm, not a defect.** Essentially every MCP-applied row carries
an apply-time `version` stamp that differs from the file's embedded 14-digit prefix, and
14 rows store the full `<prefix>_<name>` stem while earlier rows store the bare name.
Name-normalized match is authoritative per doctrine.

## APPLIED_UNTRACKED — recent, operator-actionable (evidence per file)

### `20260426000000_add_routing_mode_to_paper_portfolios.sql`
- SHA-256: `54e384aba4bc0221e07cc63adb7bd4ee0295ca56690d53fdaf8a56773b2e63a6`
- Classification: **APPLIED_UNTRACKED**
- Evidence: risk_alerts migration_apply receipt 8353d822 (2026-04-26); routing_mode col+CHECK live in prod; the '07-02 procedure miss'

### `20260721011000_revoke_fleet_receipt_maintain.sql`
- SHA-256: `d3f49cc1130f33c900c1ace294e40bc86a37aa09c62c6a6937ede9ea26b8f9a8`
- Classification: **APPLIED_UNTRACKED**
- Evidence: prod relacl service_role=ar (MAINTAIN gone); Lane B leaves arm; only this file revokes MAINTAIN -> applied

### `20260721190000_single_leg_shadow_experiment_foundation.sql`
- SHA-256: `1164ccfd2736b56c222709ac6bd5f45f62779311271b7980ed0e3b95e08f947d`
- Classification: **APPLIED_UNTRACKED**
- Evidence: 5 tables + 2 guard fns exist. NEVER REAPPLY: unguarded CREATE POLICY (no DROP POLICY IF EXISTS)

### `20260722010000_single_leg_shadow_internal_lifecycle.sql`
- SHA-256: `1aae84521c21c8239eac19cdd9618783348422ca5112879d6e94419a176c4942`
- Classification: **APPLIED_UNTRACKED**
- Evidence: 4 tables + 2 RPCs + guards exist; settlement_deferred CHECK present. NEVER REAPPLY: unguarded CREATE POLICY

### `20260722010100_single_leg_shadow_open_rpc_concurrency_hardening.sql`
- SHA-256: `32059848a1a1aa62d113a39f6adfaf9d66668e7e99aae418202a2e2c891cf207`
- Classification: **APPLIED_UNTRACKED**
- Evidence: deployed rpc_open_single_leg_shadow_position_v1 = file-3 version (numeric SQLSTATE 23001, no named check_violation). Reapply-safe (CREATE OR REPLACE only)

### `20260722020100_single_leg_experiment_portfolio_isolation.sql`
- SHA-256: `45445bc1a088dc2a9e77fd3caaa2924aa84cfa2a0368dce7b100aa50b439c888`
- Classification: **APPLIED_UNTRACKED**
- Evidence: 3 fns + 3 isolation triggers + restrictive policy exist. Reapply-safe (guarded DROP..IF EXISTS) but has a preflight DO block

### Single-leg foundation file numbering (doctrine claim VERIFIED)

| # | File | Tracking | Reapply |
|---|---|---|---|
| 1 | 20260721190000_single_leg_shadow_experiment_foundation | UNTRACKED | **NEVER** (unguarded CREATE POLICY) |
| 2 | 20260722010000_single_leg_shadow_internal_lifecycle | UNTRACKED | **NEVER** (unguarded CREATE POLICY) |
| 3 | 20260722010100_single_leg_shadow_open_rpc_concurrency_hardening | UNTRACKED | safe (CREATE OR REPLACE only) |
| 4 | 20260722020000_single_leg_experiment_control_rpcs | **TRACKED** v=20260723205911, receipt 975... | n/a (tracked) |
| 5 | 20260722020100_single_leg_experiment_portfolio_isolation | UNTRACKED | safe-ish (guarded DROP..IF EXISTS + preflight DO) |

Doctrine claim 'files 1/2/3/5 are APPLIED_UNTRACKED; 1/2 never reapply (unguarded CREATE
POLICY); 4 is tracked' is CONFIRMED against production. File 3's deployed function was
distinguished from file 2's by numeric SQLSTATE `23001` (file 3) vs named `check_violation`/
`restrict_violation` (file 2) in `pg_get_functiondef(rpc_open_single_leg_shadow_position_v1)`.

## NOT_APPLIED (evidence)

- `20260531000000_add_paper_shadow_routing_mode.sql` — SHA `abc838b9e13b879ad805401765f40e1384cc9105e29aece9e10710ef242d984e` — paper_portfolios routing_mode CHECK = {live_eligible,shadow_only} only; 'paper_shadow' NOT present. (The '2 gated paper-shadow files, APPLY-as-unit pre-enable' cohort; both deliberately held.)
- `20260601000000_paper_shadow_pairs.sql` — SHA `b830d6b793609654143594ce295a04522e884bf29211db1ac393b01d85fdf8de` — table paper_shadow_pairs does NOT exist (to_regclass NULL). (The '2 gated paper-shadow files, APPLY-as-unit pre-enable' cohort; both deliberately held.)

## UNKNOWN (evidence)

- `20221127155800_create_trade_journal_table.sql` — SHA `a6b9eb6e676383fccc7f7d39f7a2ff42a73f169d49de9788af0dc2be8af1813a` — pre-tracking-era; object 'trade_journal' ABSENT in prod; cannot distinguish applied-then-dropped from never-applied.

## APPLIED_UNTRACKED — pre-tracking-era cohort

These files predate 2026-04-23 (the first `schema_migrations` row). The 07-02 recon
already established '82 pre-era' untracked; this run reconfirms the boundary. A
representative object sample was verified live (trade_suggestions, scanner_universe,
paper_*, learning_feedback_loops, risk_alerts, policy_lab_cohorts, task_nonces, job_runs,
calibration_adjustments, autotune_history, underlying_iv_points, ops_control, etc. all
present). `trade_executions` is absent because the TRACKED `drop_trade_executions`
dropped it (applied-then-superseded). `create_trade_journal_table` is carved out as
UNKNOWN above. This cohort is NOT included in the proposed backfill (separate, larger,
owner decision; some rows are superseded/dropped objects).

Pre-era APPLIED_UNTRACKED files (81):

| File | SHA-256 |
|---|---|
| 20240101000000_initial_schema.sql | `9322bfa87f55da77c1b252eedb3d7a8950cad35b28d95e535a6faddb13f59bb5` |
| 20240101000001_rls_policies.sql | `93dccb528e39cfe35f7e0e6ef4cedc198a01099ba77ab7a3938cc5620c8b9158` |
| 20240101000002_seed_data.sql | `4a8a463fd18284ee3c8bfa817bb5977da3a270c6d9186951b760220062d514ca` |
| 20240523120000_add_snaptrade_users.sql | `18788740830003d62c6aba69c90c13d2bf90b21d36e4e59baaa377c2d564eebc` |
| 20240524000000_add_nested_learning_tables.sql | `062fc416c0b21247ff23be7f05819427e2b4c4f176e95182748ad4a1e20cac66` |
| 20240525000000_add_scanner_universe.sql | `7f54f5dd5de64a8cd7998e6da2fc222775a164406ef4a9b2f5f4a6191aeddccb` |
| 20241231235958_create_trade_suggestions.sql | `dcf5987d0076c549d14aace02418a6675e5ab3573496952e63c57f9dd397ac6d` |
| 20241231235959_analytics_observability.sql | `0ae0e749179af8e7cea8c5172538cde6868e31c923e97480df000d96a047c0a4` |
| 20250101000003_add_progress_engine.sql | `7358dd62ea242b5e2b32ee0016d710f1c807cc7d90e41016a64ba50d526a0395` |
| 20250101000004_strategy_profiles.sql | `c91d514d97627a6c78976485b6d04b1dafd0bf8e3e6d508dfcf1f7027e422bef` |
| 20250101000005_rls_hardening.sql | `e486f2e352fe3ac2842f839a83b91327e4e3239c086a9e7e872843cfe0300668` |
| 20250101000006_holdings_intelligence.sql | `8eddc6b0eff7aaa100de4941052665712a54bf009a356afbd0bca77bf7a242e9` |
| 20250101000007_normalize_equity_cost_basis.sql | `cd3da62637ce006bbde1cd259e0ae9155274c25a0ec09b422f760e7c58ef0604` |
| 20250101000008_add_historical_stats_to_trade_suggestions.sql | `35cb06c08c9d8b487a177651a0dee0740261d9887e4f55794bb0e1ca9ab279ea` |
| 20250101000009_paper_trading.sql | `9557f608d9918052cfdc48dfd904471bcccc106e46c950d689905dce735d6984` |
| 20250101000010_add_strategy_fields_to_learning_feedback_loops.sql | `413c14b8acf2d8b1e9547c327bd3a44d9eff9118726df1965c89e59e078b6ef7` |
| 20250101000011_execution_v3.sql | `de02b21f0b3ff86907cd3ccd0361462892882ee4ada262f02242e63a1664a526` |
| 20250107000000_create_underlying_iv_points.sql | `f6e38213dc4897523d31db9f995a23e9e130bdb9b5b892ecc007f0bf00ae0155` |
| 20250117000000_backtest_v3.sql | `549a694595c519adc780c78e8465ec8da8f697e21be70e6586e9d8a8388f77df` |
| 20251209021157_paper_orders_add_suggestion_id.sql | `bb5e015cef9b1f3d3a63e90c8ef80664797ea7fc3eda3dd9f1fc7025649e3645` |
| 20251211000000_learning_feedback_loops_strategy_window_and_aggregate_support.sql | `60654d9923faaba38acd5f73d4b275322de70a760da96f0ebdef3cf82d9ea375` |
| 20251212000000_observability_v3.sql | `e43439454d70848557896d0cefd42339e3ae02c5717b7b343d95c94f838dc5ed` |
| 20251214000001_risk_budgets_v3.sql | `53607dcaa223298fbf88eb0030533b34ea5a807c1993c41f5b501c256947b678` |
| 20251216000000_idempotent_suggestions.sql | `0b9fda095cf27a586042278a331de00890be72c57c6c8bddd657ff43da91ed40` |
| 20251220000001_job_runs_db_queue.sql | `05de07c8b65db1b9112669cfebbeb90110599a91dcf70ce1cc82a85893fa6da0` |
| 20251221000000_decision_logging.sql | `09a45a7b6047f21936210111b9f61a21e5b14c45fb70523df8b6b8a526a9ac28` |
| 20251221000001_quant_agents_v3.sql | `95cda2364363147a11b9c8a98fe07b21397c4f97f8384c117de936c03f37cdeb` |
| 20251222000000_add_legs_fingerprint.sql | `9052a2d831426d1f3fdaf0811c9add0bb7cf9d6b23d95df76d0028574659a61b` |
| 20251222000001_add_counterfactual_to_outcomes.sql | `dcd8d4794d6f803f3f3855c10c6c99d683f7e9ea02f4250805738d285dd77457` |
| 20251222000002_add_status_to_outcomes.sql | `8c96f52470f16fcb6b05689e65fc94ed11d3742efda58295c7518b321a512e69` |
| 20251223000000_add_decision_lineage.sql | `13ab9e879a42d6b7a5a1db121b14ea51adb308219779de3cbd832bf30aa3f458` |
| 20251224000000_enhance_trade_executions.sql | `2bfb20bc4520bea0b2073c68aa30a922af974fbea8f120d01580514dcb16ea87` |
| 20251224000001_ensure_snapshot_holdings.sql | `6405cdc4b0ac475fbd268934e1b9ae4b1a1f9a9a730ab65a4af4e69350e40777` |
| 20260106000000_v3_go_live_validation.sql | `d90c8c4f675646aabe05b1f5af7d0adb97612f73643c09e4b86db2ac38d89d71` |
| 20260116000000_task_nonces.sql | `8d0bd1a5b71c5c3c9f8ecdcc870047131bf70520b9e9b126d783c9a60a1c8868` |
| 20260118000000_v4_observability.sql | `895966e1483dab656c3ce791a19c660ea5e558e2fd2601a2e0ba3401ba7cb4d2` |
| 20260118000001_v4_observability_wave1_1.sql | `136e701719d498eb7eb40bfdb765d23e1ce3f193cb63f9aba7a9cda4d34cd1fd` |
| 20260118000002_v4_analytics_idempotency.sql | `d3f8a67ebba73e1e8c66c03af042721158f1c92f1c201334b99266123644f1f0` |
| 20260118000003_v4_trace_scoped_analytics_key.sql | `f2c55bb4808e4f7bf07622d9f0bcdeb901fb87428300dca368de049e700be5fd` |
| 20260118000004_v4_fingerprint_integrity.sql | `581db3abdbd10dd8953785ac192cb74e7dcb02cc73795c4731ddfd8419479bac` |
| 20260118000005_v4_fingerprint_integrity_fix.sql | `837d70143d0a19e9c3abdab7103e292361962750599261dde9be460b6658ee99` |
| 20260119000000_ops_control.sql | `68fc4dcbb754433807dde9e924359e654be13704e21fad51b77e8a07f6c47f07` |
| 20260120000000_replay_feature_store.sql | `24d008e5e902a76f8595db249c4d5ff38a27d2c13e5a23390855d3053ff04151` |
| 20260121000000_replay_atomic_commit_rpc.sql | `64e62ea1373e364ce1a9b39090bbbefc8c5a3312319bfddbcb66a6dc43dbfc0f` |
| 20260121100000_backtest_config_hash.sql | `ba07b99c62caeceee63daa2399ee6322706fd6ce807f66fca1c66f7642e52fcb` |
| 20260121120000_promotion_gate.sql | `fa87ebade8ca7d46cfd23cf10f50ca4c4b0ebc0e60b690709b50805e01ce4ef2` |
| 20260121200000_paper_ledger_structured_events.sql | `d7a58dc2d24a3688693363d0b6c320d7aa90efa0985d3623bd08871136b87268` |
| 20260121200001_v3_go_live_state_rolling_streak.sql | `ff4d4e72aa1f06ba5b3cebd2649bc89be5c1afbb64253004ad9350db08f7678a` |
| 20260121210000_add_paper_checkpoint_fields.sql | `08a1a89596d5eb9759e0cc864a3edc49021efb4f174ee238b93c0f8eda57acf7` |
| 20260122000000_fix_learning_trade_outcomes_is_paper.sql | `447f3557de2e2ddf6e9410062203187ee92bb57ce5be69857e3c85684ac0dbfb` |
| 20260122100000_shadow_cohort_daily.sql | `accfb2bcb2a092e50471ef6df5eccd52dced8691c9f11a2eb2379de8264c07af` |
| 20260122100001_paper_forward_policy_overrides.sql | `e2e4544be32edd76b4273c69720c03ce14ada519d56198d4db34344bf982bed2` |
| 20260123000000_create_execution_drift_logs.sql | `56081728a15775b1ea0531f493e6a5be085f1f51ecfad31e2f335bdaea6a2c8e` |
| 20260123100000_execution_v3_paper_orders_fixup.sql | `6f349eb07ab21258c1d916b4b7c0f9c3aea3379958a2f39a92251d16e464aa04` |
| 20260201000000_v4_accounting_ledger.sql | `90537a11298d098faaa3d17cded1b80c8b03db4d70491d43434e01e184a8eb16` |
| 20260201100000_v4_ledger_fill_action_fix.sql | `49b0d16da6d6cffc0a73ec924a01298d0fbc83ec6128f140a083f76e18d403d3` |
| 20260201200000_v4_ledger_marks_unrealized.sql | `7dc4d09f8727aa614facdedd9be70c36e08cae237f21cd5625c2e3c4014e1262` |
| 20260201300000_v4_pnl_hardening.sql | `b3a9df5ec135aaf61f5492693ad36ad17f20258b1cff1e237801c2a0e322e848` |
| 20260201400000_v4_ops_rpc_and_cadence.sql | `ca6389fc11c3a50c946e8ff3d81f79fb25e39f2b14410f367a5af9fdfb4b0069` |
| 20260310000000_paper_mark_to_market.sql | `08e63ce543fa32b8ab3369e3b86293cdcac99f39123045b28b85a97a2208949e` |
| 20260310100000_backfill_paper_positions_exit_fields.sql | `f9318d7b52a1622e7866febf675ec85d52a59b85ae7fe0c1a2220f48bf91b80f` |
| 20260311100000_job_runs_completed_at.sql | `a012b14e40c310c41dee8af4ee5bbb11a8aa8967ccc39c18d32a2e63f193a001` |
| 20260312100000_restore_deleted_positions.sql | `1ada628ae59e58aa047d88349546e6f7a7a55f3b18a18107aff4124f5879b65c` |
| 20260317000000_backfill_lfl_pnl_from_positions.sql | `cfbbefbf6d08bce7c63152f4a13b1c771d2d5cd042d75b7c5ef6933e94e22ed8` |
| 20260318100000_add_paper_green_day_fields.sql | `e70ff9e7e31ed5be0d48264dfb58ce75504b523e0bd0d445efffec483a535124` |
| 20260320000000_policy_lab.sql | `653a01f33cc7856ace94099360ceba66ab8d0e218f69f7234b2ca6ebcd4222dd` |
| 20260323000000_pdt_day_trade_log.sql | `e2ce126348207e012f9093519845bb29ecb3edaea4bfc4cf1947bd5010770c74` |
| 20260323100000_policy_decision_logging.sql | `d20557c6dbac437830066c03e4b60e043314c1a49d940670e24db9cb4f592fbb` |
| 20260325000000_alpaca_broker_integration.sql | `622e9510ed416c49f28a834759c79702b06dde434a12555ebd2e4e5fe27cedeb` |
| 20260326000000_add_risk_adjusted_ev.sql | `46ec27d5b1aad9315f306b2c4563ae20e1133157c8a774f19ad23f8ff28a9349` |
| 20260326100000_calibration_adjustments.sql | `cb510ac7d1ad80acc9beeea0af05430d3880fc6cafba750bab3f33d34530f4a8` |
| 20260326200000_autotune_history.sql | `b2f03f798f91f1f9468367447b72cd040acb7e457d376b950b5ba85ae0c52fb9` |
| 20260327000000_go_live_progression.sql | `f385da02931d025f8a3944940a735830fa8006a5f341f2cdd5a5b51d93c3166f` |
| 20260402000000_small_account_cohorts.sql | `41b0dfeef969c5f9381f681dcf5fc4ea3b0b71a4d2147e6693f9d9cebf87b538` |
| 20260403000000_unique_constraint_exclude_dismissed.sql | `beb95b92a01fb3046423d956e7da0191ff57565ae2bde00529bd4d6bf9673219` |
| 20260404000000_reset_green_days.sql | `8c134eec4f96750d965ad9f50fdbfeec63203dd686c5b2cf3f9a7c02a37f1a0f` |
| 20260406200000_add_sector_and_cancelled_columns.sql | `dd67906314099d1d03113a10d75cd575aff48f1492db476e803c5e97bd0b9f95` |
| 20260407000000_add_cohort_id_to_paper_positions.sql | `63da3dde87193f7ae202278306131a1d1a42927af3be21972484abfc6e6df1e5` |
| 20260409000000_add_risk_alerts.sql | `85256071352396fbfb4678af3c09651d476eee58aec637c0f34e2c9b5f5aced7` |
| 20260410000000_add_agent_tables.sql | `9b6ebf75e38cf53c0a3d9f471f4a9c3aa20235b66f6355200dcc7721bd7c90b1` |
| 20260411000000_add_ev_raw_and_entry_dte.sql | `3fdae0c32773cdaad0ef6abb738a6d0d4cd89631df3d76de75c001a31ed712d3` |

## Proposed operator-executed tracking backfill (NOT EXECUTED)

**These are NAME-ONLY tracking-row INSERTs. They DO NOT run any migration SQL — every
object already exists in production. The operator runs these; this audit did not.**

> DANGER: Do NOT re-apply the migration FILES. Files 1 & 2
> (single_leg_shadow_experiment_foundation, single_leg_shadow_internal_lifecycle) contain
> unguarded `CREATE POLICY` and would ERROR ('policy already exists') on re-apply. The
> backfill only inserts a bookkeeping row so the CLI stops considering them pending.

`version` = the file's embedded 14-digit prefix; `name` = the full basename (minus
`.sql`), matching the recent full-stem naming convention. None of these versions collide
with an existing `schema_migrations.version`. Operator may instead choose apply-time
stamps; the invariant that matters is a unique `version` PK and the exact `name`.

```sql
-- READ-ONLY AUDIT ARTIFACT — NOT EXECUTED. Operator review + run required.
BEGIN;
INSERT INTO supabase_migrations.schema_migrations (version, name) VALUES
  ('20260426000000', '20260426000000_add_routing_mode_to_paper_portfolios'),
  ('20260721011000', '20260721011000_revoke_fleet_receipt_maintain'),
  ('20260721190000', '20260721190000_single_leg_shadow_experiment_foundation'),
  ('20260722010000', '20260722010000_single_leg_shadow_internal_lifecycle'),
  ('20260722010100', '20260722010100_single_leg_shadow_open_rpc_concurrency_hardening'),
  ('20260722020100', '20260722020100_single_leg_experiment_portfolio_isolation')
ON CONFLICT (version) DO NOTHING;
-- Verify 6 rows now present, then COMMIT (or ROLLBACK if the count is wrong):
SELECT version, name FROM supabase_migrations.schema_migrations
  WHERE version IN ('20260426000000','20260721011000','20260721190000',
                    '20260722010000','20260722010100','20260722020100')
  ORDER BY version;
COMMIT;
```

Pre-era cohort backfill is intentionally OMITTED (separate owner decision; includes
superseded/dropped objects and one UNKNOWN).

## Open uncertainties

- `revoke_fleet_receipt_maintain` (file's own header says 'NOT APPLIED BY THIS PR') is
  classified APPLIED_UNTRACKED purely from ACL state (`service_role=ar`, MAINTAIN absent),
  which exactly matches its post-apply intent and cannot be produced by Lane B alone
  (Lane B leaves `arm`). A manual out-of-band `REVOKE MAINTAIN` would look identical; no
  receipt or tracking row exists to distinguish. HIGH confidence, but state is inferred
  from effect, not from a durable apply record.
- `create_trade_journal_table` (UNKNOWN): object absent, pre-tracking-era, no receipt —
  applied-then-dropped vs never-applied is indeterminate. Do NOT backfill.
- Pre-era cohort is classified APPLIED_UNTRACKED by boundary + representative sampling,
  not by exhaustive per-file object verification. Individual superseded files (e.g.
  enhance_trade_executions) are not separately proven.
- `add_routing_mode_to_paper_portfolios` receipt exists but no tracking row -> the '07-02
  procedure miss' is STILL untracked as of this read.

## Surprises vs prior ledger

- `revoke_fleet_receipt_maintain` appears APPLIED to production despite its 'NOT APPLIED
  BY THIS PR' header and the CLAUDE.md 07-20 'residual MAINTAIN' framing — production ACL
  shows MAINTAIN already revoked (`service_role=ar`). Newly surfaced exact-name apply.
- The single-leg control-RPCs file (#4, 20260722020000) is the ONLY single-leg file that
  got both a tracking row AND a receipt; foundation files 1/2/3/5 got neither.
- `add_routing_mode_to_paper_portfolios` remains untracked (receipt-only) — confirms the
  known 07-02 procedure miss was never backfilled.

## Appendix — full classification table (all 149 files, sorted by filename)

This is the human-readable render of the fingerprinted canonical body
(`filename|sha256|classification`). Column `detail` is annotation only and is NOT
part of the fingerprint input.

| # | File | Class | SHA-256 | Detail |
|---|---|---|---|---|
| 1 | 20221127155800_create_trade_journal_table.sql | UNKNOWN | `a6b9eb6e676383fccc7f7d39f7a2ff42a73f169d49de9788af0dc2be8af1813a` | pre-tracking-era; object 'trade_journal' ABSENT in prod; cannot distinguish applied-then-dropped from never-applied |
| 2 | 20240101000000_initial_schema.sql | APPLIED_UNTRACKED | `9322bfa87f55da77c1b252eedb3d7a8950cad35b28d95e535a6faddb13f59bb5` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 3 | 20240101000001_rls_policies.sql | APPLIED_UNTRACKED | `93dccb528e39cfe35f7e0e6ef4cedc198a01099ba77ab7a3938cc5620c8b9158` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 4 | 20240101000002_seed_data.sql | APPLIED_UNTRACKED | `4a8a463fd18284ee3c8bfa817bb5977da3a270c6d9186951b760220062d514ca` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 5 | 20240523120000_add_snaptrade_users.sql | APPLIED_UNTRACKED | `18788740830003d62c6aba69c90c13d2bf90b21d36e4e59baaa377c2d564eebc` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 6 | 20240524000000_add_nested_learning_tables.sql | APPLIED_UNTRACKED | `062fc416c0b21247ff23be7f05819427e2b4c4f176e95182748ad4a1e20cac66` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 7 | 20240525000000_add_scanner_universe.sql | APPLIED_UNTRACKED | `7f54f5dd5de64a8cd7998e6da2fc222775a164406ef4a9b2f5f4a6191aeddccb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 8 | 20241231235958_create_trade_suggestions.sql | APPLIED_UNTRACKED | `dcf5987d0076c549d14aace02418a6675e5ab3573496952e63c57f9dd397ac6d` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 9 | 20241231235959_analytics_observability.sql | APPLIED_UNTRACKED | `0ae0e749179af8e7cea8c5172538cde6868e31c923e97480df000d96a047c0a4` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 10 | 20250101000003_add_progress_engine.sql | APPLIED_UNTRACKED | `7358dd62ea242b5e2b32ee0016d710f1c807cc7d90e41016a64ba50d526a0395` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 11 | 20250101000004_strategy_profiles.sql | APPLIED_UNTRACKED | `c91d514d97627a6c78976485b6d04b1dafd0bf8e3e6d508dfcf1f7027e422bef` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 12 | 20250101000005_rls_hardening.sql | APPLIED_UNTRACKED | `e486f2e352fe3ac2842f839a83b91327e4e3239c086a9e7e872843cfe0300668` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 13 | 20250101000006_holdings_intelligence.sql | APPLIED_UNTRACKED | `8eddc6b0eff7aaa100de4941052665712a54bf009a356afbd0bca77bf7a242e9` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 14 | 20250101000007_normalize_equity_cost_basis.sql | APPLIED_UNTRACKED | `cd3da62637ce006bbde1cd259e0ae9155274c25a0ec09b422f760e7c58ef0604` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 15 | 20250101000008_add_historical_stats_to_trade_suggestions.sql | APPLIED_UNTRACKED | `35cb06c08c9d8b487a177651a0dee0740261d9887e4f55794bb0e1ca9ab279ea` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 16 | 20250101000009_paper_trading.sql | APPLIED_UNTRACKED | `9557f608d9918052cfdc48dfd904471bcccc106e46c950d689905dce735d6984` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 17 | 20250101000010_add_strategy_fields_to_learning_feedback_loops.sql | APPLIED_UNTRACKED | `413c14b8acf2d8b1e9547c327bd3a44d9eff9118726df1965c89e59e078b6ef7` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 18 | 20250101000011_execution_v3.sql | APPLIED_UNTRACKED | `de02b21f0b3ff86907cd3ccd0361462892882ee4ada262f02242e63a1664a526` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 19 | 20250107000000_create_underlying_iv_points.sql | APPLIED_UNTRACKED | `f6e38213dc4897523d31db9f995a23e9e130bdb9b5b892ecc007f0bf00ae0155` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 20 | 20250117000000_backtest_v3.sql | APPLIED_UNTRACKED | `549a694595c519adc780c78e8465ec8da8f697e21be70e6586e9d8a8388f77df` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 21 | 20251209021157_paper_orders_add_suggestion_id.sql | APPLIED_UNTRACKED | `bb5e015cef9b1f3d3a63e90c8ef80664797ea7fc3eda3dd9f1fc7025649e3645` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 22 | 20251211000000_learning_feedback_loops_strategy_window_and_aggregate_support.sql | APPLIED_UNTRACKED | `60654d9923faaba38acd5f73d4b275322de70a760da96f0ebdef3cf82d9ea375` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 23 | 20251212000000_observability_v3.sql | APPLIED_UNTRACKED | `e43439454d70848557896d0cefd42339e3ae02c5717b7b343d95c94f838dc5ed` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 24 | 20251214000001_risk_budgets_v3.sql | APPLIED_UNTRACKED | `53607dcaa223298fbf88eb0030533b34ea5a807c1993c41f5b501c256947b678` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 25 | 20251216000000_idempotent_suggestions.sql | APPLIED_UNTRACKED | `0b9fda095cf27a586042278a331de00890be72c57c6c8bddd657ff43da91ed40` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 26 | 20251220000001_job_runs_db_queue.sql | APPLIED_UNTRACKED | `05de07c8b65db1b9112669cfebbeb90110599a91dcf70ce1cc82a85893fa6da0` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 27 | 20251221000000_decision_logging.sql | APPLIED_UNTRACKED | `09a45a7b6047f21936210111b9f61a21e5b14c45fb70523df8b6b8a526a9ac28` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 28 | 20251221000001_quant_agents_v3.sql | APPLIED_UNTRACKED | `95cda2364363147a11b9c8a98fe07b21397c4f97f8384c117de936c03f37cdeb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 29 | 20251222000000_add_legs_fingerprint.sql | APPLIED_UNTRACKED | `9052a2d831426d1f3fdaf0811c9add0bb7cf9d6b23d95df76d0028574659a61b` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 30 | 20251222000001_add_counterfactual_to_outcomes.sql | APPLIED_UNTRACKED | `dcd8d4794d6f803f3f3855c10c6c99d683f7e9ea02f4250805738d285dd77457` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 31 | 20251222000002_add_status_to_outcomes.sql | APPLIED_UNTRACKED | `8c96f52470f16fcb6b05689e65fc94ed11d3742efda58295c7518b321a512e69` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 32 | 20251223000000_add_decision_lineage.sql | APPLIED_UNTRACKED | `13ab9e879a42d6b7a5a1db121b14ea51adb308219779de3cbd832bf30aa3f458` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 33 | 20251224000000_enhance_trade_executions.sql | APPLIED_UNTRACKED | `2bfb20bc4520bea0b2073c68aa30a922af974fbea8f120d01580514dcb16ea87` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 34 | 20251224000001_ensure_snapshot_holdings.sql | APPLIED_UNTRACKED | `6405cdc4b0ac475fbd268934e1b9ae4b1a1f9a9a730ab65a4af4e69350e40777` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 35 | 20260106000000_v3_go_live_validation.sql | APPLIED_UNTRACKED | `d90c8c4f675646aabe05b1f5af7d0adb97612f73643c09e4b86db2ac38d89d71` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 36 | 20260116000000_task_nonces.sql | APPLIED_UNTRACKED | `8d0bd1a5b71c5c3c9f8ecdcc870047131bf70520b9e9b126d783c9a60a1c8868` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 37 | 20260118000000_v4_observability.sql | APPLIED_UNTRACKED | `895966e1483dab656c3ce791a19c660ea5e558e2fd2601a2e0ba3401ba7cb4d2` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 38 | 20260118000001_v4_observability_wave1_1.sql | APPLIED_UNTRACKED | `136e701719d498eb7eb40bfdb765d23e1ce3f193cb63f9aba7a9cda4d34cd1fd` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 39 | 20260118000002_v4_analytics_idempotency.sql | APPLIED_UNTRACKED | `d3f8a67ebba73e1e8c66c03af042721158f1c92f1c201334b99266123644f1f0` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 40 | 20260118000003_v4_trace_scoped_analytics_key.sql | APPLIED_UNTRACKED | `f2c55bb4808e4f7bf07622d9f0bcdeb901fb87428300dca368de049e700be5fd` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 41 | 20260118000004_v4_fingerprint_integrity.sql | APPLIED_UNTRACKED | `581db3abdbd10dd8953785ac192cb74e7dcb02cc73795c4731ddfd8419479bac` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 42 | 20260118000005_v4_fingerprint_integrity_fix.sql | APPLIED_UNTRACKED | `837d70143d0a19e9c3abdab7103e292361962750599261dde9be460b6658ee99` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 43 | 20260119000000_ops_control.sql | APPLIED_UNTRACKED | `68fc4dcbb754433807dde9e924359e654be13704e21fad51b77e8a07f6c47f07` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 44 | 20260120000000_replay_feature_store.sql | APPLIED_UNTRACKED | `24d008e5e902a76f8595db249c4d5ff38a27d2c13e5a23390855d3053ff04151` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 45 | 20260121000000_replay_atomic_commit_rpc.sql | APPLIED_UNTRACKED | `64e62ea1373e364ce1a9b39090bbbefc8c5a3312319bfddbcb66a6dc43dbfc0f` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 46 | 20260121100000_backtest_config_hash.sql | APPLIED_UNTRACKED | `ba07b99c62caeceee63daa2399ee6322706fd6ce807f66fca1c66f7642e52fcb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 47 | 20260121120000_promotion_gate.sql | APPLIED_UNTRACKED | `fa87ebade8ca7d46cfd23cf10f50ca4c4b0ebc0e60b690709b50805e01ce4ef2` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 48 | 20260121200000_paper_ledger_structured_events.sql | APPLIED_UNTRACKED | `d7a58dc2d24a3688693363d0b6c320d7aa90efa0985d3623bd08871136b87268` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 49 | 20260121200001_v3_go_live_state_rolling_streak.sql | APPLIED_UNTRACKED | `ff4d4e72aa1f06ba5b3cebd2649bc89be5c1afbb64253004ad9350db08f7678a` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 50 | 20260121210000_add_paper_checkpoint_fields.sql | APPLIED_UNTRACKED | `08a1a89596d5eb9759e0cc864a3edc49021efb4f174ee238b93c0f8eda57acf7` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 51 | 20260122000000_fix_learning_trade_outcomes_is_paper.sql | APPLIED_UNTRACKED | `447f3557de2e2ddf6e9410062203187ee92bb57ce5be69857e3c85684ac0dbfb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 52 | 20260122100000_shadow_cohort_daily.sql | APPLIED_UNTRACKED | `accfb2bcb2a092e50471ef6df5eccd52dced8691c9f11a2eb2379de8264c07af` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 53 | 20260122100001_paper_forward_policy_overrides.sql | APPLIED_UNTRACKED | `e2e4544be32edd76b4273c69720c03ce14ada519d56198d4db34344bf982bed2` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 54 | 20260123000000_create_execution_drift_logs.sql | APPLIED_UNTRACKED | `56081728a15775b1ea0531f493e6a5be085f1f51ecfad31e2f335bdaea6a2c8e` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 55 | 20260123100000_execution_v3_paper_orders_fixup.sql | APPLIED_UNTRACKED | `6f349eb07ab21258c1d916b4b7c0f9c3aea3379958a2f39a92251d16e464aa04` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 56 | 20260201000000_v4_accounting_ledger.sql | APPLIED_UNTRACKED | `90537a11298d098faaa3d17cded1b80c8b03db4d70491d43434e01e184a8eb16` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 57 | 20260201100000_v4_ledger_fill_action_fix.sql | APPLIED_UNTRACKED | `49b0d16da6d6cffc0a73ec924a01298d0fbc83ec6128f140a083f76e18d403d3` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 58 | 20260201200000_v4_ledger_marks_unrealized.sql | APPLIED_UNTRACKED | `7dc4d09f8727aa614facdedd9be70c36e08cae237f21cd5625c2e3c4014e1262` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 59 | 20260201300000_v4_pnl_hardening.sql | APPLIED_UNTRACKED | `b3a9df5ec135aaf61f5492693ad36ad17f20258b1cff1e237801c2a0e322e848` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 60 | 20260201400000_v4_ops_rpc_and_cadence.sql | APPLIED_UNTRACKED | `ca6389fc11c3a50c946e8ff3d81f79fb25e39f2b14410f367a5af9fdfb4b0069` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 61 | 20260310000000_paper_mark_to_market.sql | APPLIED_UNTRACKED | `08e63ce543fa32b8ab3369e3b86293cdcac99f39123045b28b85a97a2208949e` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 62 | 20260310100000_backfill_paper_positions_exit_fields.sql | APPLIED_UNTRACKED | `f9318d7b52a1622e7866febf675ec85d52a59b85ae7fe0c1a2220f48bf91b80f` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 63 | 20260311100000_job_runs_completed_at.sql | APPLIED_UNTRACKED | `a012b14e40c310c41dee8af4ee5bbb11a8aa8967ccc39c18d32a2e63f193a001` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 64 | 20260312100000_restore_deleted_positions.sql | APPLIED_UNTRACKED | `1ada628ae59e58aa047d88349546e6f7a7a55f3b18a18107aff4124f5879b65c` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 65 | 20260317000000_backfill_lfl_pnl_from_positions.sql | APPLIED_UNTRACKED | `cfbbefbf6d08bce7c63152f4a13b1c771d2d5cd042d75b7c5ef6933e94e22ed8` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 66 | 20260318100000_add_paper_green_day_fields.sql | APPLIED_UNTRACKED | `e70ff9e7e31ed5be0d48264dfb58ce75504b523e0bd0d445efffec483a535124` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 67 | 20260320000000_policy_lab.sql | APPLIED_UNTRACKED | `653a01f33cc7856ace94099360ceba66ab8d0e218f69f7234b2ca6ebcd4222dd` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 68 | 20260323000000_pdt_day_trade_log.sql | APPLIED_UNTRACKED | `e2ce126348207e012f9093519845bb29ecb3edaea4bfc4cf1947bd5010770c74` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 69 | 20260323100000_policy_decision_logging.sql | APPLIED_UNTRACKED | `d20557c6dbac437830066c03e4b60e043314c1a49d940670e24db9cb4f592fbb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 70 | 20260325000000_alpaca_broker_integration.sql | APPLIED_UNTRACKED | `622e9510ed416c49f28a834759c79702b06dde434a12555ebd2e4e5fe27cedeb` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 71 | 20260326000000_add_risk_adjusted_ev.sql | APPLIED_UNTRACKED | `46ec27d5b1aad9315f306b2c4563ae20e1133157c8a774f19ad23f8ff28a9349` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 72 | 20260326100000_calibration_adjustments.sql | APPLIED_UNTRACKED | `cb510ac7d1ad80acc9beeea0af05430d3880fc6cafba750bab3f33d34530f4a8` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 73 | 20260326200000_autotune_history.sql | APPLIED_UNTRACKED | `b2f03f798f91f1f9468367447b72cd040acb7e457d376b950b5ba85ae0c52fb9` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 74 | 20260327000000_go_live_progression.sql | APPLIED_UNTRACKED | `f385da02931d025f8a3944940a735830fa8006a5f341f2cdd5a5b51d93c3166f` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 75 | 20260402000000_small_account_cohorts.sql | APPLIED_UNTRACKED | `41b0dfeef969c5f9381f681dcf5fc4ea3b0b71a4d2147e6693f9d9cebf87b538` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 76 | 20260403000000_unique_constraint_exclude_dismissed.sql | APPLIED_UNTRACKED | `beb95b92a01fb3046423d956e7da0191ff57565ae2bde00529bd4d6bf9673219` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 77 | 20260404000000_reset_green_days.sql | APPLIED_UNTRACKED | `8c134eec4f96750d965ad9f50fdbfeec63203dd686c5b2cf3f9a7c02a37f1a0f` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 78 | 20260406200000_add_sector_and_cancelled_columns.sql | APPLIED_UNTRACKED | `dd67906314099d1d03113a10d75cd575aff48f1492db476e803c5e97bd0b9f95` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 79 | 20260407000000_add_cohort_id_to_paper_positions.sql | APPLIED_UNTRACKED | `63da3dde87193f7ae202278306131a1d1a42927af3be21972484abfc6e6df1e5` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 80 | 20260409000000_add_risk_alerts.sql | APPLIED_UNTRACKED | `85256071352396fbfb4678af3c09651d476eee58aec637c0f34e2c9b5f5aced7` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 81 | 20260410000000_add_agent_tables.sql | APPLIED_UNTRACKED | `9b6ebf75e38cf53c0a3d9f471f4a9c3aa20235b66f6355200dcc7721bd7c90b1` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 82 | 20260411000000_add_ev_raw_and_entry_dte.sql | APPLIED_UNTRACKED | `3fdae0c32773cdaad0ef6abb738a6d0d4cd89631df3d76de75c001a31ed712d3` | pre-tracking-era (no schema_migrations row began until 2026-04-23); cohort sample-verified live |
| 83 | 20260423000001_expand_close_reason_enum_phase1.sql | TRACKED | `eeb196f4945de7b2e077645cba005761ab103b772ec7e6bc3ae2ffdf33bd3386` | track version=20260423022928 name='expand_close_reason_enum_phase1' [version-drift] |
| 84 | 20260424000001_contract_close_reason_enum_phase2.sql | TRACKED | `f31770581bc89393d1a3ac3bf0e7fc68e929cfeac72b7afc4c23a1753e4c9172` | track version=20260425052940 name='contract_close_reason_enum_phase2' [version-drift] |
| 85 | 20260426000000_add_routing_mode_to_paper_portfolios.sql | APPLIED_UNTRACKED | `54e384aba4bc0221e07cc63adb7bd4ee0295ca56690d53fdaf8a56773b2e63a6` | risk_alerts migration_apply receipt 8353d822 (2026-04-26); routing_mode col+CHECK live in prod; the '07-02 procedure miss' |
| 86 | 20260507000000_add_strategy_lifecycle_states.sql | TRACKED | `58424ba5aa2005f323dbd5308eee44bb09b8c888a31810a0547c03cab372ed31` | track version=20260507161012 name='add_strategy_lifecycle_states' [version-drift] |
| 87 | 20260509000000_add_underlying_iv_points_unique_constraint.sql | TRACKED | `a0fd701c53b71e0d76a4d200de905e4d8ec1d903bdb13304781753558c169755` | track version=20260509051647 name='add_underlying_iv_points_unique_constraint' [version-drift] |
| 88 | 20260510000000_drop_trade_executions.sql | TRACKED | `1f296f294b7a32e8369f0c220a2011dbcccccd8cfa38c1ccc680845f3a4cfa8d` | track version=20260510200701 name='drop_trade_executions' [version-drift] |
| 89 | 20260512000000_add_last_marked_at_to_paper_positions.sql | TRACKED | `81b1b30ae9de2bc8c0fdf247c04cc9669d35e287aee3aec0fcf3ba313022eb2e` | track version=20260511152451 name='add_last_marked_at_to_paper_positions' [version-drift] |
| 90 | 20260513000001_symbol_performance_view.sql | TRACKED | `6c61b973bd283f3e5e8e1305a655e8aa2fa1404bdd34d3ffd6d830dd7c43dd37` | track version=20260512215440 name='20260513000001_symbol_performance_view' [version-drift] |
| 91 | 20260513000002_hold_period_buckets_view.sql | TRACKED | `f8633f460d36d0222653c35e981b682056303d99c85a45de431cc1759a7ccacc` | track version=20260512215457 name='20260513000002_hold_period_buckets_view' [version-drift] |
| 92 | 20260513000003_recent_closes_audit_view.sql | TRACKED | `14ee1eb2ea173a33bd4d791a47799bf1c8c73795ea63abc4a4a4123b36f4660b` | track version=20260512215512 name='20260513000003_recent_closes_audit_view' [version-drift] |
| 93 | 20260513000004_hold_period_buckets_v2_relabel.sql | TRACKED | `1a80103f3e8b2af7075ade9bf7e0cad0f4a9f13e37f57b0cce9f7e84dd69c4e5` | track version=20260513013859 name='20260513000004_hold_period_buckets_v2_relabel' [version-drift] |
| 94 | 20260513000005_suggestion_rejections_table.sql | TRACKED | `669b3aeff5e5181804daca94ce65a2e25b204763cc97507c9cf6e3b88ac2b9dd` | track version=20260513035015 name='20260513000005_suggestion_rejections_table' [version-drift] |
| 95 | 20260513000006_rejection_patterns_view.sql | TRACKED | `7a0e4804dcd7ba38c1a9608b1ad2316db2a110c6597ad591346f563404add267` | track version=20260513035027 name='20260513000006_rejection_patterns_view' [version-drift] |
| 96 | 20260518000001_promote_aggressive_cohort.sql | TRACKED | `07d46a5c0a2efd51eac2d2a06274a3b73db9cf4897b4ddd6b667f6c23d7c17ff` | track version=20260518202040 name='promote_aggressive_cohort' [version-drift] |
| 97 | 20260519000001_universe_selection_log.sql | TRACKED | `b7e21f2111af62bb07b877998b3f34bfeaa8cd1ce7e2588e4a3a80041e679113` | track version=20260519205730 name='20260519000001_universe_selection_log' [version-drift] |
| 98 | 20260528000000_add_max_profit_and_net_ev.sql | TRACKED | `47ad981e969c5c86369088df28a5d0a9034968f894ebdadc10704751ba6a5a2b` | track version=20260528213728 name='add_max_profit_and_net_ev' [version-drift] |
| 99 | 20260528100000_backfill_csx_legs_full_count.sql | TRACKED | `10a6c123c7209875da07547cd614f3a4379dd27fde29dc5227b964246321b2ec` | track version=20260528232135 name='backfill_csx_legs_full_count' [version-drift] |
| 100 | 20260528200000_shadow_exit_decisions.sql | TRACKED | `ec14de479487b97d9c2723c0a064042e06d0e9c2e0147725ab087044910130f2` | track version=20260528235156 name='shadow_exit_decisions' [version-drift] |
| 101 | 20260528300000_momentum_observations.sql | TRACKED | `e12840d762895a82a1bf18d1f250d5996416ddfcf3de611992f8f13d952a7408` | track version=20260529001131 name='momentum_observations' [version-drift] |
| 102 | 20260531000000_add_paper_shadow_routing_mode.sql | NOT_APPLIED | `abc838b9e13b879ad805401765f40e1384cc9105e29aece9e10710ef242d984e` | paper_portfolios routing_mode CHECK = {live_eligible,shadow_only} only; 'paper_shadow' NOT present |
| 103 | 20260601000000_paper_shadow_pairs.sql | NOT_APPLIED | `b830d6b793609654143594ce295a04522e884bf29211db1ac393b01d85fdf8de` | table paper_shadow_pairs does NOT exist (to_regclass NULL) |
| 104 | 20260601010000_regime_filter_observations.sql | TRACKED | `ce5130effa94f24aaf7cfc8be521ed09df76eacb6f894bd446e42900527e0bc0` | track version=20260602203813 name='20260601010000_regime_filter_observations' [version-drift] |
| 105 | 20260602000000_option_liquidity_observations.sql | TRACKED | `3cf80c06e913916d659054265c201b3ffe589192374a5a30ae8e90f9089b82c8` | track version=20260602203759 name='20260602000000_option_liquidity_observations' [version-drift] |
| 106 | 20260607000000_vol_signal_observations.sql | TRACKED | `4ec8596f650b1beb89f042981f487da4e171aa698d6a185b6317b827aa6711c9` | track version=20260607060500 name='vol_signal_observations' [version-drift] |
| 107 | 20260608000000_exit_mark_corroboration_observations.sql | TRACKED | `04e748f37e9f088e4d7f8e4f48e87ac6664469a16c8b277a83a0ca026869ce38` | track version=20260608161053 name='exit_mark_corroboration_observations' [version-drift] |
| 108 | 20260608120000_reentry_cooldowns.sql | TRACKED | `77d75313fdbd4d30a3dc5e4e6c80db13b53498003d57dee4f0dc3b11ce2768f1` | track version=20260608203423 name='reentry_cooldowns' [version-drift] |
| 109 | 20260618000000_create_learning_performance_summary_v3.sql | TRACKED | `03cfaa48f8b42c7b79cfb791b109b27eb0644da287c5ed446493c0f3a6f17ea0` | track version=20260618223947 name='create_learning_performance_summary_v3' [version-drift] |
| 110 | 20260623000000_add_vrp_inputs_to_trade_suggestions.sql | TRACKED | `5f78eebc5786cd99633f94b72244b4e9b3abb815bea6abd216ef07041c9e31f5` | track version=20260624002451 name='add_vrp_inputs_to_trade_suggestions' [version-drift] |
| 111 | 20260623010000_add_a4_outcome_vol_fields.sql | TRACKED | `2f6dbf26478d8e95a590eb2a306a3a0e51a665dc4e0dcbc7bf7ecc6cabab0586` | track version=20260624002911 name='add_a4_outcome_vol_fields' [version-drift] |
| 112 | 20260629000000_add_ops_control_entries_paused.sql | TRACKED | `e2993a4eaf38a534755307809b238685b196003845c4185db545392d31cebfe6` | track version=20260629233239 name='add_ops_control_entries_paused' [version-drift] |
| 113 | 20260702100000_add_corroborated_mark_fields.sql | TRACKED | `f6b1b3fa87eccce2eaeedc18533a3bf7f9df373f6ed84bd032c657cd5fe8fcb5` | track version=20260702092230 name='add_corroborated_mark_fields' [version-drift] |
| 114 | 20260702110000_signal_accuracy_rolling_view.sql | TRACKED | `52516e73d82cbfe3a1f20279a80c04ae6790a313f1b0c8cb2443e612ca011298` | track version=20260702095845 name='signal_accuracy_rolling_view' [version-drift] |
| 115 | 20260707221500_ops_control_streak_breaker_state.sql | TRACKED | `65d46d727da82f35c5d5288e41a52427728432ab94041b2d12cde4a88dab108e` | track version=20260707221213 name='20260707221500_ops_control_streak_breaker_state' [version-drift] |
| 116 | 20260711143151_paper_orders_client_order_id.sql | TRACKED | `cfc15b1131ae610d7bb4339b0b176592cc55c3975d5d20dceaa9bc261c199c08` | track version=20260711143151 name='paper_orders_client_order_id' |
| 117 | 20260711224226_position_thesis_outcomes.sql | TRACKED | `edf82535ff096bd652f654cd0dd78ff473de8a90f285969ed6e0fb430a09bb2e` | track version=20260711224226 name='position_thesis_outcomes' |
| 118 | 20260711225359_signal_accuracy_rename_realized_win_rate.sql | TRACKED | `c1632ab313ed47b21d6722829af29249c3b942306972bfa3ff00f77d39c9ab74` | track version=20260711225359 name='signal_accuracy_rename_realized_win_rate' |
| 119 | 20260711233113_paper_positions_risk_basis_totals.sql | TRACKED | `e655b75bbf73d732aeee8b42dfc469a7e16ffa654c34657798b37c257f112f57` | track version=20260711233113 name='paper_positions_risk_basis_totals' |
| 120 | 20260711234336_restore_ev_raw_coalesce_in_v3_view.sql | TRACKED | `e111df19e9a7ebe207b27d97fc5b26f1a18f94e4c48897b34fb78613302ebf82` | track version=20260711234336 name='restore_ev_raw_coalesce_in_v3_view' |
| 121 | 20260712011627_trade_suggestions_decision_id.sql | TRACKED | `98026e61c9442d3153d18a0b59f261b01ae343b006ae6d93e98836bd670bb37d` | track version=20260712011627 name='trade_suggestions_decision_id' |
| 122 | 20260712123000_thesis_outcomes_price_basis.sql | TRACKED | `6be4b2e417302aa7e4a106dc9ec1f13c471ea6397d729241b3e5d288055416cc` | track version=20260712120301 name='20260712123000_thesis_outcomes_price_basis' [version-drift] |
| 123 | 20260713200500_decision_runs_tape_integrity.sql | TRACKED | `ff85e8e40ce704cd7947a65512199bc186999893caef39e29ba400e12caf72c7` | track version=20260713200333 name='decision_runs_tape_integrity' [version-drift] |
| 124 | 20260716060000_small_tier_shadow_fleet.sql | TRACKED | `424a1641811ce27699b87c0b6fbd97ef2410ac1b9997188fe6ad9bc499e2994b` | track version=20260717052208 name='small_tier_shadow_fleet' [version-drift] |
| 125 | 20260716155023_add_ranking_costs_to_trade_suggestions.sql | TRACKED | `492470b04a20576994ab2749eca045211e3cf5f263d621a4cca73a1adb677406` | track version=20260716155023 name='add_ranking_costs_to_trade_suggestions' |
| 126 | 20260717090000_shadow_fleet_activation_rpc.sql | TRACKED | `98e1b285ac949c508def3e72e5f6b0e33f732d519c250230a6ef053634fbb486` | track version=20260718033415 name='shadow_fleet_activation_rpc' [version-drift] |
| 127 | 20260717100000_candidate_terminal_dispositions.sql | TRACKED | `6fac6ce59958815c5885eea3c901ef537edcd59911aa5fdab38b1b1cbc7151b3` | track version=20260718033912 name='candidate_terminal_dispositions' [version-drift] |
| 128 | 20260717120000_option_quote_provenance.sql | TRACKED | `e365ae726b84bbee79a14c6f20a6fb0b150b36fb9e8f0240999b86c9e383e3ed` | track version=20260718034013 name='option_quote_provenance' [version-drift] |
| 129 | 20260718150000_job_runs_status_check_partial.sql | TRACKED | `ec37d1c7e99fdc1b99a922c721a583e7d4b93ff388e7fe0bee3ccdc1bf9263fe` | track version=20260718144818 name='job_runs_status_check_partial' [version-drift] |
| 130 | 20260719000000_policy_registrations.sql | TRACKED | `199a2feec08b96fe0a496fe11befa32d3f39a01fbd9da4c4b8820c9f12575672` | track version=20260719001630 name='policy_registrations' [version-drift] |
| 131 | 20260719010000_h7_subreason_check.sql | TRACKED | `57dfa7698c068185c9161e432c2a9764f8469711d566f034d4769d363d088f8b` | track version=20260719001859 name='h7_subreason_check' [version-drift] |
| 132 | 20260719020000_harden_shadow_fleet_activation_rpc.sql | TRACKED | `134f1bf35e2715532d64e17a8da4d54df70d0e6e13348355bbeb779fdb5f0de9` | track version=20260719231412 name='20260719020000_harden_shadow_fleet_activation_rpc' [version-drift] |
| 133 | 20260719180000_rpc_commit_internal_close_v1.sql | TRACKED | `efe0b65d9a6fbcf2e6b2c93a0f6089a220d78f53cd65105921a47720182ca31b` | track version=20260719215826 name='20260719180000_rpc_commit_internal_close_v1' [version-drift] |
| 134 | 20260720120000_rpc_commit_internal_close_v1_guard_hardening.sql | TRACKED | `bd9833ab30b5e77933b5ce8be6bc4afc3da3a543ce2e97223802cc7dbf04e146` | track version=20260720234940 name='20260720120000_rpc_commit_internal_close_v1_guard_hardening' [version-drift] |
| 135 | 20260720140000_fleet_reconciliation_receipts.sql | TRACKED | `b94e199584d2f97934e60eb9a11775bc209a16feca5a4d3b9032e8745f931cd1` | track version=20260721002415 name='20260720140000_fleet_reconciliation_receipts' [version-drift] |
| 136 | 20260720150000_bind_fleet_activation_to_receipts.sql | TRACKED | `d758ec4298c200005e33c0398c24855975619bcea78dbf1106cf7dc3564a9011` | track version=20260721002709 name='20260720150000_bind_fleet_activation_to_receipts' [version-drift] |
| 137 | 20260721010000_rpc_issue_fleet_reconciliation_receipt_v1.sql | TRACKED | `8387ac4d4f2583a04d30b1efae34ef376207a4b3dcae45eac7401393894d106d` | track version=20260721025419 name='20260721010000_rpc_issue_fleet_reconciliation_receipt_v1' [version-drift] |
| 138 | 20260721010500_harden_fleet_receipt_privileges.sql | TRACKED | `d498c81aae75f62c4eb901a797b1449908dfdd3ed4376e4ab10116a3c6bc04c8` | track version=20260721025452 name='20260721010500_harden_fleet_receipt_privileges' [version-drift] |
| 139 | 20260721011000_revoke_fleet_receipt_maintain.sql | APPLIED_UNTRACKED | `d3f49cc1130f33c900c1ace294e40bc86a37aa09c62c6a6937ede9ea26b8f9a8` | prod relacl service_role=ar (MAINTAIN gone); Lane B leaves arm; only this file revokes MAINTAIN -> applied |
| 140 | 20260721190000_single_leg_shadow_experiment_foundation.sql | APPLIED_UNTRACKED | `1164ccfd2736b56c222709ac6bd5f45f62779311271b7980ed0e3b95e08f947d` | 5 tables + 2 guard fns exist. NEVER REAPPLY: unguarded CREATE POLICY (no DROP POLICY IF EXISTS) |
| 141 | 20260722010000_single_leg_shadow_internal_lifecycle.sql | APPLIED_UNTRACKED | `1aae84521c21c8239eac19cdd9618783348422ca5112879d6e94419a176c4942` | 4 tables + 2 RPCs + guards exist; settlement_deferred CHECK present. NEVER REAPPLY: unguarded CREATE POLICY |
| 142 | 20260722010100_single_leg_shadow_open_rpc_concurrency_hardening.sql | APPLIED_UNTRACKED | `32059848a1a1aa62d113a39f6adfaf9d66668e7e99aae418202a2e2c891cf207` | deployed rpc_open_single_leg_shadow_position_v1 = file-3 version (numeric SQLSTATE 23001, no named check_violation). Reapply-safe (CREATE OR REPLACE only) |
| 143 | 20260722020000_single_leg_experiment_control_rpcs.sql | TRACKED | `740e13e153cb8eb16c9239e2f511999ed8a183971d0dd92b76d190e2c18d3788` | track version=20260723205911 name='20260722020000_single_leg_experiment_control_rpcs' [version-drift] |
| 144 | 20260722020100_single_leg_experiment_portfolio_isolation.sql | APPLIED_UNTRACKED | `45445bc1a088dc2a9e77fd3caaa2924aa84cfa2a0368dce7b100aa50b439c888` | 3 fns + 3 isolation triggers + restrictive policy exist. Reapply-safe (guarded DROP..IF EXISTS) but has a preflight DO block |
| 145 | 20260723150000_suggestion_rejections_event_id.sql | TRACKED | `dd67a7fd8b7f27114b49a14ecea1e7118ff68ffc273bdadef4bc7a1e3ca91fe9` | track version=20260723204135 name='20260723150000_suggestion_rejections_event_id' [version-drift] |
| 146 | 20260723160000_fleet_policy_decision_foundation.sql | TRACKED | `559ce90e48a1700b0ccd12cc85e9cd3bd89761c00198791f5c84007ebebec4cd` | track version=20260724003507 name='20260723160000_fleet_policy_decision_foundation' [version-drift] |
| 147 | 20260723160000_regime_v4_comparisons.sql | TRACKED | `2221fbec8e1b4f92f55bd0971082864a7acb36e0c3031218b9e9d3c231c13e77` | track version=20260723234851 name='20260723160000_regime_v4_comparisons' [version-drift] |
| 148 | 20260723160000_td_scan_observe_tables.sql | TRACKED | `2cca2cd13b975edfb8e2ecfb74e9b153a27d6e861ecd29f882d95fd6c5fcc073` | track version=20260723232856 name='20260723160000_td_scan_observe_tables' [version-drift] |
| 149 | 20260723170000_fleet_shadow_internal_lifecycle.sql | TRACKED | `38accb72ffde46574c3b782384609316ead54b57bc024494804793e3a4f483cd` | track version=20260724004315 name='20260723170000_fleet_shadow_internal_lifecycle' [version-drift] |
