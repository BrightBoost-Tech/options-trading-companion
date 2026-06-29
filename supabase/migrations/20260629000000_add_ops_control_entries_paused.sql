-- Migration: 20260629000000_add_ops_control_entries_paused.sql
-- Entries-only break-glass halt for ops_control.
--
-- The only live no-deploy halt today is `ops_control.paused`, which gates
-- EVERY job (including the intraday risk monitor + exit/close jobs) — so
-- flipping it ALSO halts loss-protection. This adds an ENTRIES-ONLY signal
-- that blocks NEW position entry while LEAVING the monitor + exit jobs
-- running. DB row is the operator interface (flippable with NO deploy).
--
-- Polarity: default FALSE (entries allowed). Read DEFENSIVELY at runtime —
-- absent column / read error → treat as NOT halted (entries allowed), never
-- crash, never accidentally halt. Independent of the global `paused` gate.
--
-- Idempotent: safe to re-run (ADD COLUMN IF NOT EXISTS).

ALTER TABLE public.ops_control
    ADD COLUMN IF NOT EXISTS entries_paused BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE public.ops_control
    ADD COLUMN IF NOT EXISTS entries_pause_reason TEXT NULL;

COMMENT ON COLUMN public.ops_control.entries_paused IS
    'Entries-only break-glass halt: TRUE blocks NEW position entry at the '
    'autopilot entry seam while LEAVING the intraday risk monitor + exit/'
    'close jobs running (loss-protection unaffected). Default FALSE. '
    'Independent of `paused` (which halts every job). Read defensively — '
    'absent/error fails OPEN (entries allowed).';
