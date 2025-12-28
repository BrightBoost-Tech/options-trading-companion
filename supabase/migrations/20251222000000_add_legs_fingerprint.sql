-- Add legs_fingerprint to trade_suggestions and update unique constraint

-- 1. Add column
ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS legs_fingerprint text DEFAULT 'legacy';

-- 2. Drop old index
DROP INDEX IF EXISTS unique_suggestion_per_cycle;

-- 3. Create new index including legs_fingerprint
-- We use COALESCE or a default to handle legacy rows or ensure the column is populated.
-- Since we added a default 'legacy', existing rows will not conflict unless they are duplicates on the old key.
-- But we want to allow MULTIPLE 'legacy' rows if they differ by other means? No, legacy rows are already deduplicated by the old key.
-- So (user_id, window, cycle_date, ticker, strategy, 'legacy') will still enforce the old constraint effectively for legacy rows.
-- New rows will have unique hashes.

CREATE UNIQUE INDEX IF NOT EXISTS unique_suggestion_per_cycle_v2
ON trade_suggestions (user_id, window, cycle_date, ticker, strategy, legs_fingerprint);
