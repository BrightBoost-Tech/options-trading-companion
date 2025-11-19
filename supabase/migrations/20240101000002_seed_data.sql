-- 20240101000002_seed_data.sql
-- Minimal seed to make the UI render in dev.

INSERT INTO market_features (symbol, spot, spread_bps, iv_rank, iv_percentile, rv_1m, vix_level, days_to_earnings, oi_median)
VALUES
  ('SPY', 480.50, 5, 0.45, 0.48, 0.12, 15.5, 45, 5000),
  ('QQQ', 420.30, 8, 0.52, 0.55, 0.18, 15.5, 30, 3500),
  ('IWM', 205.80, 12, 0.38, 0.40, 0.15, 15.5, 60, 2000);
