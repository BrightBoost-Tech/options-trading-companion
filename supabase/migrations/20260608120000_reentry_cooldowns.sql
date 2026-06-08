-- Just-stopped re-entry cooldown — HARD LOCKOUT, durable in Postgres.
--
-- Shared state between the intraday risk monitor (WRITER, on a per-symbol loss
-- envelope stop) and the scanner/autopilot entry path (READER, two gates). PG
-- (not in-process memory or RQ Redis) BECAUSE every merge recycles the worker —
-- memory-wipe-on-recycle is the exact zero-shared-state bug this fixes.
--
-- APPEND-ONLY: never UPDATE/DELETE. Active = EXISTS a row for (cohort_id,
-- symbol) with cooldown_until > now(). A symbol stopped by the per-symbol loss
-- envelope is benched for that cohort until the next session open.
--
-- Apply per docs/migration_procedure.md (migrations do not auto-apply on merge).

CREATE TABLE IF NOT EXISTS reentry_cooldowns (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    cohort_id               text,
    symbol                  text NOT NULL,
    cooldown_until          timestamptz NOT NULL,
    created_at              timestamptz NOT NULL DEFAULT now(),
    reason                  text,
    triggering_position_id  text,        -- audit (nullable)
    realized_loss           numeric      -- trigger-time symbol loss (audit, nullable)
);

-- Active-cooldown lookup: (cohort_id, symbol, cooldown_until DESC).
CREATE INDEX IF NOT EXISTS idx_reentry_cooldowns_lookup
    ON reentry_cooldowns (cohort_id, symbol, cooldown_until DESC);
