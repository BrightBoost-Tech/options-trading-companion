-- P0-B book-scaling (2026-07-11): persist per-position risk basis as TOTALS.
-- Forward-only; legacy rows stay NULL (honest unknown, never fabricated — H9).
-- ⚠ UNIT IN THE NAME: these are POSITION-LEVEL TOTALS (already × contracts ×
-- 100), NOT per-contract. RBE._estimate_risk_usage_usd keys the legacy
-- max_loss as PER-CONTRACT and multiplies by qty — a consumer reading
-- max_loss_total must NOT × qty again (the double-scaling trap). The _total
-- suffix makes that contract legible at every touchpoint.
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS cost_basis_total NUMERIC;
ALTER TABLE paper_positions ADD COLUMN IF NOT EXISTS max_loss_total   NUMERIC;

COMMENT ON COLUMN paper_positions.cost_basis_total IS
  'Position-level TOTAL entry cost = |avg_entry_premium| x 100 x |contracts| (premium basis, PortfolioAllocator convention). NULL for legacy rows.';
COMMENT ON COLUMN paper_positions.max_loss_total IS
  'Position-level TOTAL defined-risk max loss (already x contracts x 100), reused from trade_suggestions.max_loss_total (_compute_risk_primitives_usd). NULL when unlinked/unpopulated (H9). Consumers must NOT multiply by qty again.';
