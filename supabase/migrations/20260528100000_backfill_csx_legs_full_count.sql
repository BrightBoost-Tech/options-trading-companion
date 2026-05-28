-- #3 convention backfill: normalize the lone per-spread historical position row
-- to the pinned full-count convention (legs[].quantity == contract count).
--
-- CSX d077c93d (the closed 2026-05-18 BUG-A position) is the only per-spread row
-- in the 70-row census (69/70 were already full-count). It stored
-- legs[].quantity = 1 against an original 4-contract spread. It is CLOSED and
-- never re-marked, so this does NOT affect any live mark — it makes the table
-- uniformly full-count so future readers/queries see one convention.
--
-- Set each leg's quantity to 4 (the original contract count). Idempotent:
-- re-running sets the same value. Scoped to the single known row by id.

UPDATE paper_positions
SET legs = (
    SELECT jsonb_agg(jsonb_set(leg, '{quantity}', '4'::jsonb))
    FROM jsonb_array_elements(legs) AS leg
)
WHERE id = 'd077c93d-eafd-4174-9554-6f6ca4f24e3d'
  AND legs IS NOT NULL
  AND jsonb_array_length(legs) > 0;
