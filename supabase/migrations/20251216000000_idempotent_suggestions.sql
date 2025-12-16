ALTER TABLE trade_suggestions ADD COLUMN IF NOT EXISTS cycle_date date;

UPDATE trade_suggestions SET cycle_date = created_at::date WHERE cycle_date IS NULL;

ALTER TABLE trade_suggestions ALTER COLUMN cycle_date SET NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS unique_suggestion_per_cycle ON trade_suggestions (user_id, window, cycle_date, ticker, strategy);
