-- =============================================================================
-- Seed transaction: 4 DRAFT single-leg experiment policy_registrations
-- (effective_epoch = single_leg_experiment_v1)
-- =============================================================================
-- NOT APPLIED BY THIS PR. approval_status = 'draft' on EVERY row. No policy
-- opts in until an operator approves a draft row (a separate, explicit,
-- registry-write step — see docs/review/single-leg-seed-prompt-2026-07-21.md).
--
-- Generated from packages/quantum/policy_lab/single_leg_experiment_design.py
-- (py -3.11 -m packages.quantum.policy_lab.single_leg_experiment_design). Requires
-- the 20260719000000_policy_registrations migration to be applied first.
--
-- config_hash is DERIVED here (never client-invented): the INSERT computes
-- encode(extensions.digest(config_canonical,'sha256'),'hex') inside the
-- transaction. The in-transaction (pre-commit) DO block re-asserts: exactly 4
-- rows for the epoch, 4 distinct hashes, 4 distinct canonical strings,
-- hash==sha256(canonical) for every row, and ZERO non-draft rows — any
-- failure RAISEs and rolls the whole seed back.
--
-- Distinct epoch => UNIQUE(effective_epoch, config_hash) never collides with
-- the seeded small_tier_v1 fleet, even though each control's config (and
-- config_hash) is byte-identical to its approved anchor.
-- =============================================================================

BEGIN;

INSERT INTO policy_registrations (
    policy_registration_id, policy_family, anchor_lineage,
    policy_config, config_canonical, config_hash,
    schema_version, approval_status, effective_epoch,
    changed_axes, design_rationale, created_at, approved_at, created_by
)
SELECT
    v.policy_registration_id, v.policy_family, v.anchor_lineage,
    v.config_canonical::jsonb, v.config_canonical,
    encode(extensions.digest(v.config_canonical, 'sha256'), 'hex'),
    1, 'draft', v.effective_epoch,
    v.changed_axes::jsonb, v.design_rationale, now(), NULL, v.created_by
FROM (VALUES
    ('sl_exp_throughput_v1', 'aggressive', 'aggressive_anchor', '{"budget_cap_pct":0.35,"max_dte_to_enter":45,"max_positions_open":4,"max_risk_pct_per_trade":0.035,"max_suggestions_per_day":4,"min_dte_to_exit":7,"min_score_threshold":30.0,"risk_multiplier":1.2,"single_leg_experiment_enabled":true,"single_leg_max_debit_per_contract":150.0,"single_leg_max_iv_rank":20.0,"single_leg_max_vrp_spread":0.0,"single_leg_min_directional_run":0.03,"sizing_method":"budget_proportional","stop_loss_pct":0.3,"target_profit_pct":0.5}', 'single_leg_experiment_v1', '["single_leg_optin_block"]', 'EXPERIMENTAL throughput arm: aggressive_anchor config + single-leg opt-in block (single_leg_experiment_enabled=true; iv_rank<=20, vrp_spread<=0, min_run>=0.03, max_debit<=$150/contract). highest slot count (max_positions_open=4, max_suggestions_per_day=4) + lowest score gate (min_score_threshold=30) => maximum single-leg SAMPLE THROUGHPUT; base is the most-vetted (live-champion) config. Matched control: sl_ctrl_throughput_v1 (differs on axis A=single_leg_optin_block only). Independent EV: single_leg_adapter@lognormal_v1/1.0.0 (per-candidate runtime; H9-abstains; no scalar stored).', 'single_leg_experiment_design'),
    ('sl_ctrl_throughput_v1', 'aggressive', 'aggressive_anchor', '{"budget_cap_pct":0.35,"max_dte_to_enter":45,"max_positions_open":4,"max_risk_pct_per_trade":0.035,"max_suggestions_per_day":4,"min_dte_to_exit":7,"min_score_threshold":30.0,"risk_multiplier":1.2,"sizing_method":"budget_proportional","stop_loss_pct":0.3,"target_profit_pct":0.5}', 'single_leg_experiment_v1', '[]', 'CONTROL throughput arm: aggressive_anchor config VERBATIM, NO single-leg opt-in block (the generator emits nothing for it — dark by absence). Matched experimental: sl_exp_throughput_v1 (differs on axis A=single_leg_optin_block only). config_hash equals the seeded aggressive_anchor hash by construction (byte-identical config, distinct epoch).', 'single_leg_experiment_design'),
    ('sl_exp_conviction_v1', 'conservative', 'conservative_anchor', '{"budget_cap_pct":0.25,"max_dte_to_enter":45,"max_positions_open":2,"max_risk_pct_per_trade":0.015,"max_suggestions_per_day":2,"min_dte_to_exit":14,"min_score_threshold":70.0,"risk_multiplier":0.8,"single_leg_experiment_enabled":true,"single_leg_max_debit_per_contract":150.0,"single_leg_max_iv_rank":20.0,"single_leg_max_vrp_spread":0.0,"single_leg_min_directional_run":0.03,"sizing_method":"budget_proportional","stop_loss_pct":0.15,"target_profit_pct":0.25}', 'single_leg_experiment_v1', '["single_leg_optin_block"]', 'EXPERIMENTAL conviction arm: conservative_anchor config + single-leg opt-in block (single_leg_experiment_enabled=true; iv_rank<=20, vrp_spread<=0, min_run>=0.03, max_debit<=$150/contract). high-conviction low-volume contrast (max_positions_open=2, max_suggestions_per_day=2, min_score_threshold=70) => tests whether the surrounding cohort''s score gate starves single-leg candidates. Matched control: sl_ctrl_conviction_v1 (differs on axis A=single_leg_optin_block only). Independent EV: single_leg_adapter@lognormal_v1/1.0.0 (per-candidate runtime; H9-abstains; no scalar stored).', 'single_leg_experiment_design'),
    ('sl_ctrl_conviction_v1', 'conservative', 'conservative_anchor', '{"budget_cap_pct":0.25,"max_dte_to_enter":45,"max_positions_open":2,"max_risk_pct_per_trade":0.015,"max_suggestions_per_day":2,"min_dte_to_exit":14,"min_score_threshold":70.0,"risk_multiplier":0.8,"sizing_method":"budget_proportional","stop_loss_pct":0.15,"target_profit_pct":0.25}', 'single_leg_experiment_v1', '[]', 'CONTROL conviction arm: conservative_anchor config VERBATIM, NO single-leg opt-in block (the generator emits nothing for it — dark by absence). Matched experimental: sl_exp_conviction_v1 (differs on axis A=single_leg_optin_block only). config_hash equals the seeded conservative_anchor hash by construction (byte-identical config, distinct epoch).', 'single_leg_experiment_design')
) AS v(
    policy_registration_id, policy_family, anchor_lineage,
    config_canonical, effective_epoch, changed_axes,
    design_rationale, created_by
);

-- Post-insert integrity assertions (fail -> ROLLBACK).
DO $$
DECLARE
    v_count int;
    v_distinct_hash int;
    v_distinct_canonical int;
    v_hash_mismatch int;
    v_non_draft int;
BEGIN
    SELECT count(*) INTO v_count
      FROM policy_registrations WHERE effective_epoch = 'single_leg_experiment_v1';
    IF v_count <> 4 THEN
        RAISE EXCEPTION 'single-leg seed: expected 4 rows, got %', v_count;
    END IF;
    SELECT count(DISTINCT config_hash) INTO v_distinct_hash
      FROM policy_registrations WHERE effective_epoch = 'single_leg_experiment_v1';
    IF v_distinct_hash <> 4 THEN
        RAISE EXCEPTION 'single-leg seed: expected 4 distinct config_hash, got %', v_distinct_hash;
    END IF;
    SELECT count(DISTINCT config_canonical) INTO v_distinct_canonical
      FROM policy_registrations WHERE effective_epoch = 'single_leg_experiment_v1';
    IF v_distinct_canonical <> 4 THEN
        RAISE EXCEPTION 'single-leg seed: expected 4 distinct config_canonical, got %', v_distinct_canonical;
    END IF;
    SELECT count(*) INTO v_hash_mismatch
      FROM policy_registrations
     WHERE effective_epoch = 'single_leg_experiment_v1'
       AND config_hash <> encode(extensions.digest(config_canonical, 'sha256'), 'hex');
    IF v_hash_mismatch <> 0 THEN
        RAISE EXCEPTION 'single-leg seed: % rows have config_hash != sha256(config_canonical)', v_hash_mismatch;
    END IF;
    SELECT count(*) INTO v_non_draft
      FROM policy_registrations
     WHERE effective_epoch = 'single_leg_experiment_v1' AND approval_status <> 'draft';
    IF v_non_draft <> 0 THEN
        RAISE EXCEPTION 'single-leg seed: % rows are not draft (opt-in must never seed approved)', v_non_draft;
    END IF;
END $$;

COMMIT;
