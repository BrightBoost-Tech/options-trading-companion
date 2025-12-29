-- Add counterfactual columns to outcomes_log for No-Action analysis
ALTER TABLE outcomes_log
ADD COLUMN IF NOT EXISTS counterfactual_pl_1d float8,
ADD COLUMN IF NOT EXISTS counterfactual_available boolean DEFAULT false;
