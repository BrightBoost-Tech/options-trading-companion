-- Add last_marked_at column to paper_positions for staleness observability.
--
-- Populated by paper_mark_to_market_service.refresh_marks on successful
-- per-position write. Enables queries like:
--
--   SELECT id, symbol, last_marked_at
--   FROM paper_positions
--   WHERE status = 'open'
--     AND (last_marked_at IS NULL OR last_marked_at < NOW() - INTERVAL '30 minutes');
--
-- Discovery context — 2026-05-12 CSX situation: DB showed -$8 unrealized
-- while Alpaca showed -$196 because the option-snapshot path silently
-- skipped marking on incomplete leg quote data. Both intraday-critical
-- readers (paper_exit_evaluator, intraday_risk_monitor) called refresh
-- BEFORE evaluating but the refresh wrapper degraded silently
-- (Anti-pattern 2 / H9 wrapper-drift class). Staleness had ZERO
-- observability — `paper_positions.updated_at` conflates MTM writes with
-- any other row update, so operators couldn't distinguish "successfully
-- marked at $value" from "marked Friday EOD, untouched since."
--
-- See: MTM-staleness diagnostic in conversation history; PR-1 of two-PR
-- fix (this column + alerts on silent-skip). PR-2 (tomorrow) adds
-- broker-authoritative fallback via Alpaca.get_all_positions() to
-- eliminate the silent-skip path entirely.
--
-- Intentionally NOT backfilling existing rows. NULL = unknown timestamp
-- is honest — no clean way to derive the original mark timestamp from
-- existing data. The next successful refresh fires (this afternoon's
-- 15:30 CT scheduled job OR PR-2's broker fallback, whichever lands
-- first) will populate it.

ALTER TABLE public.paper_positions
ADD COLUMN IF NOT EXISTS last_marked_at TIMESTAMPTZ;

COMMENT ON COLUMN public.paper_positions.last_marked_at IS
  'Timestamp of last successful MTM refresh (unrealized_pl + current_mark write). NULL if never marked OR last refresh attempt was a silent skip (look for mtm_refresh_partial alerts to identify skipped positions).';
