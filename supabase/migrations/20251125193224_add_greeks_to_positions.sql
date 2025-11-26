-- Add Greeks columns to positions table
ALTER TABLE positions
ADD COLUMN greeks JSONB DEFAULT '{"delta": 0, "gamma": 0, "theta": 0, "vega": 0}',
ADD COLUMN iv_rank NUMERIC DEFAULT 0,
ADD COLUMN expiry_date DATE;
