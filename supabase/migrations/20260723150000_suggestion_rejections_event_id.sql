-- P1-1 (2026-07-23): durable per-rejection event identity for append-only,
-- idempotent persistence of suggestion_rejections.
--
-- Incident (scan 2a98d35d, 2026-07-23 14:03Z): the scanner persist retry
-- re-inserts an IDENTICAL payload with NO idempotency marker. A
-- response-lost-after-commit retry can therefore silently DUPLICATE a row
-- (2 historical tuples on high-retry cycles are consistent with this and are
-- unprovable without a marker), while a genuinely-lost transient row partials
-- the job. There is no natural unique key: a natural key on
-- (cycle_date, symbol, strategy_key, reason) is DISQUALIFIED because it would
-- collapse ~4,009 LEGITIMATE repeat tuples (multi-strategy same-symbol
-- rejections + cross-cycle same-day repeats).
--
-- Fix: a surrogate per-event UUID (event_id) generated ONCE before the first
-- insert and reused verbatim across every retry. The UNIQUE PARTIAL INDEX
-- below (WHERE event_id IS NOT NULL) makes a re-insert of the same event_id a
-- unique violation, which the persistence code catches and classifies as a
-- duplicate_ack -- an INSERT that no-ops, NEVER an UPDATE, so an existing row
-- is never modified. Two DISTINCT legitimate rejections get DIFFERENT
-- event_ids and both persist, so legitimate repeats stay distinguishable.
--
-- Historical rows (event_id NULL) are UNTOUCHED: the partial index ignores
-- NULLs, so the 14,217 pre-2026-07-23 rows coexist with zero backfill and zero
-- rewrite. Purely additive + idempotent (IF NOT EXISTS on both statements):
-- safe to APPLY BEFORE the code merges (migration-before-merge) and safe to
-- re-run. See packages/quantum/options_scanner.py RejectionStats.

ALTER TABLE public.suggestion_rejections
  ADD COLUMN IF NOT EXISTS event_id uuid;

CREATE UNIQUE INDEX IF NOT EXISTS suggestion_rejections_event_id_key
  ON public.suggestion_rejections (event_id)
  WHERE event_id IS NOT NULL;

COMMENT ON COLUMN public.suggestion_rejections.event_id IS
  'Per-rejection surrogate identity (uuid4), generated once before the first '
  'insert and reused verbatim across retries so a response-lost-after-commit '
  'retry collapses to a duplicate (unique-violation ack) -- never a second '
  'row and never an UPDATE. NULL on pre-2026-07-23 historical rows; the '
  'partial unique index (WHERE event_id IS NOT NULL) ignores those NULLs. '
  'Populated by options_scanner.RejectionStats._persist_rejection.';
