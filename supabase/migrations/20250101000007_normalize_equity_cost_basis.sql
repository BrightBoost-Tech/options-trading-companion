-- Normalize equity cost_basis from total cost to per-unit cost
DO $$
BEGIN
  -- Ensure required columns exist before attempting update
  IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'positions' AND column_name = 'cost_basis'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'positions' AND column_name = 'quantity'
    )
    AND EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_name = 'positions' AND column_name = 'asset_type'
    ) THEN

    UPDATE positions
    SET cost_basis = cost_basis / NULLIF(quantity, 0)
    WHERE asset_type = 'EQUITY'
      AND quantity > 0
      AND cost_basis > 0;
  ELSE
    RAISE NOTICE 'Positions table missing required columns; skipping cost basis normalization.';
  END IF;
END $$;
