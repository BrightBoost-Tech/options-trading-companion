-- Wave 1.3.2: Fix trigger documentation to match actual behavior
--
-- The original migration (00004) had a comment claiming "grandfathers existing rows
-- created before 2026-01-20" but the trigger did not actually check created_at.
--
-- This migration corrects the documentation to accurately describe the behavior:
-- - NULL legs_fingerprint is BLOCKED for all production INSERT operations
-- - Bypass is ONLY allowed via:
--   1. window IN ('paper', 'legacy', 'test')
--   2. source = 'legacy'
--
-- Existing rows in the database are NOT affected (trigger only fires on INSERT).
-- This is the correct "grandfathering" - existing data stays, new production data is strict.

-- Recreate the enforcement function with corrected comments
CREATE OR REPLACE FUNCTION enforce_legs_fingerprint()
RETURNS TRIGGER AS $$
BEGIN
    -- Wave 1.3.2: Enforce legs_fingerprint for production suggestions
    --
    -- This trigger BLOCKS insertion of suggestions with NULL legs_fingerprint
    -- unless explicitly bypassed via window or source field.
    --
    -- Bypass conditions (any one allows NULL fingerprint):
    --   1. window IN ('paper', 'legacy', 'test') - non-production windows
    --   2. source = 'legacy' - explicit legacy data import
    --
    -- NOTE: Existing rows in the database are unaffected (trigger only fires on INSERT).
    -- This provides implicit grandfathering - old data stays, new production data must comply.

    IF NEW.legs_fingerprint IS NULL THEN
        -- Bypass 1: Non-production windows
        IF NEW.window IN ('paper', 'legacy', 'test') THEN
            RETURN NEW;
        END IF;

        -- Bypass 2: Explicit legacy source marker
        IF NEW.source = 'legacy' THEN
            RETURN NEW;
        END IF;

        -- Block: Production suggestions require fingerprint
        RAISE EXCEPTION 'legs_fingerprint is required for new trade suggestions. '
            'Position fingerprint must be computed from option legs. '
            'Bypass options: set window to ''paper''/''legacy''/''test'', or set source=''legacy''.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Recreate trigger (DROP + CREATE to ensure clean state)
DROP TRIGGER IF EXISTS trg_enforce_legs_fingerprint ON trade_suggestions;
CREATE TRIGGER trg_enforce_legs_fingerprint
    BEFORE INSERT ON trade_suggestions
    FOR EACH ROW
    EXECUTE FUNCTION enforce_legs_fingerprint();

-- Update comments to accurately describe behavior
COMMENT ON TRIGGER trg_enforce_legs_fingerprint ON trade_suggestions IS
    'Wave 1.3.2: Blocks INSERT of suggestions with NULL legs_fingerprint. '
    'Bypass via window IN (paper,legacy,test) or source=legacy. '
    'Existing rows unaffected (implicit grandfathering).';

COMMENT ON FUNCTION enforce_legs_fingerprint() IS
    'Wave 1.3.2: Enforcement function for legs_fingerprint requirement on INSERT. '
    'Raises exception if fingerprint is NULL unless bypassed by window or source. '
    'Does NOT check created_at - grandfathering is implicit (trigger only fires on INSERT).';
