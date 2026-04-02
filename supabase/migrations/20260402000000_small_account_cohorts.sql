-- Reconfigure Policy Lab cohorts for $500 account.
-- Tighter targets for faster capital rotation.
-- Neutral is the active/promoted cohort (champion).
-- Each cohort gets its own paper_portfolio starting at $500.

DO $$
DECLARE
  _user_id UUID := '75ee12ad-b119-4f32-aeea-19b4ef55d587';
  _port_conservative UUID;
  _port_neutral UUID;
  _port_aggressive UUID;
BEGIN
  -- Create portfolios for each cohort (skip if they already exist via the cohort)
  INSERT INTO paper_portfolios (user_id, cash_balance, net_liq)
  VALUES (_user_id, 500.00, 500.00)
  RETURNING id INTO _port_conservative;

  INSERT INTO paper_portfolios (user_id, cash_balance, net_liq)
  VALUES (_user_id, 500.00, 500.00)
  RETURNING id INTO _port_neutral;

  INSERT INTO paper_portfolios (user_id, cash_balance, net_liq)
  VALUES (_user_id, 500.00, 500.00)
  RETURNING id INTO _port_aggressive;

  -- Upsert cohorts with portfolio references
  INSERT INTO policy_lab_cohorts (user_id, cohort_name, portfolio_id, is_active, is_champion, policy_config)
  VALUES
    (_user_id, 'conservative', _port_conservative, true, false, '{
      "max_risk_pct_per_trade": 0.015,
      "risk_multiplier": 0.8,
      "sizing_method": "budget_proportional",
      "budget_cap_pct": 0.25,
      "max_suggestions_per_day": 2,
      "min_score_threshold": 70.0,
      "max_positions_open": 2,
      "stop_loss_pct": 0.15,
      "target_profit_pct": 0.25,
      "max_dte_to_enter": 45,
      "min_dte_to_exit": 14
    }'),
    (_user_id, 'neutral', _port_neutral, true, true, '{
      "max_risk_pct_per_trade": 0.025,
      "risk_multiplier": 1.0,
      "sizing_method": "budget_proportional",
      "budget_cap_pct": 0.30,
      "max_suggestions_per_day": 3,
      "min_score_threshold": 50.0,
      "max_positions_open": 3,
      "stop_loss_pct": 0.20,
      "target_profit_pct": 0.35,
      "max_dte_to_enter": 45,
      "min_dte_to_exit": 10
    }'),
    (_user_id, 'aggressive', _port_aggressive, true, false, '{
      "max_risk_pct_per_trade": 0.035,
      "risk_multiplier": 1.2,
      "sizing_method": "budget_proportional",
      "budget_cap_pct": 0.35,
      "max_suggestions_per_day": 4,
      "min_score_threshold": 30.0,
      "max_positions_open": 4,
      "stop_loss_pct": 0.30,
      "target_profit_pct": 0.50,
      "max_dte_to_enter": 45,
      "min_dte_to_exit": 7
    }')
  ON CONFLICT (user_id, cohort_name)
  DO UPDATE SET
    policy_config = EXCLUDED.policy_config,
    is_active = EXCLUDED.is_active,
    is_champion = EXCLUDED.is_champion,
    portfolio_id = EXCLUDED.portfolio_id;
END $$;

NOTIFY pgrst, 'reload schema';
