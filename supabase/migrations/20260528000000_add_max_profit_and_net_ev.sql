-- D1 surfacing: persist trade economics the system already computes but dropped.
--
-- `max_profit_total`  — total max profit (USD) across the position. Mirrors the
--                       existing `max_loss_total` column. Computed at emission
--                       from the honest bounded per-contract value
--                       (_compute_risk_primitives_usd: (width - debit) * 100 for
--                       debit spreads, credit * 100 for credit/IC) × contracts.
--                       NOT the calculate_ev() display max_gain (which carries a
--                       10x UNBOUNDED_GAIN_CAP_MULT for single-leg longs) — see
--                       docs/loud_error_doctrine.md H15.
-- `net_ev`            — edge-after-execution-cost (USD), promoted from the
--                       multi_strategy JSONB blob (net_ev = total_ev -
--                       expected_execution_cost) to a first-class column.
--
-- Both are informational/additive: no decision/sizing/ranking code reads these
-- columns (all such consumers read sizing_metadata JSONB). Historical rows stay
-- NULL (no backfill — synthetic backfill would fabricate values that were never
-- computed for those rows).

ALTER TABLE trade_suggestions
  ADD COLUMN IF NOT EXISTS max_profit_total NUMERIC;

ALTER TABLE trade_suggestions
  ADD COLUMN IF NOT EXISTS net_ev NUMERIC;

-- Notify PostgREST to pick up the new columns immediately
NOTIFY pgrst, 'reload schema';
