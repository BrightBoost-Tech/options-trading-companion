-- Wave 1.3.1: Enforce legs_fingerprint for new suggestions
--
-- This migration adds a trigger to prevent new trade_suggestions from being
-- inserted without a legs_fingerprint. This eliminates ambiguity in forensic
-- traces and ensures proper position identification.
--
-- Existing rows are grandfathered in (NULL fingerprint allowed for rows
-- created before 2026-01-20). New production suggestions require fingerprint.

-- Create the enforcement function
CREATE OR REPLACE FUNCTION enforce_legs_fingerprint()
RETURNS TRIGGER AS $$
BEGIN
    -- Only enforce for new rows (created after enforcement date)
    -- This grandfathers in existing data while preventing future issues
    IF NEW.legs_fingerprint IS NULL THEN
        -- Allow legacy/paper windows to bypass (if applicable in your system)
        IF NEW."window" IN ('paper', 'legacy', 'test') THEN
            RETURN NEW;
        END IF;

        -- Allow rows explicitly marked as legacy source
        IF NEW.source = 'legacy' THEN
            RETURN NEW;
        END IF;

        -- Block new production suggestions without fingerprint
        RAISE EXCEPTION 'legs_fingerprint is required for new trade suggestions. '
            'Position fingerprint must be computed from option legs. '
            'If this is a legacy import, set source=''legacy'' or window=''legacy''.';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Create the trigger (only fires on INSERT, not UPDATE)
DROP TRIGGER IF EXISTS trg_enforce_legs_fingerprint ON trade_suggestions;
CREATE TRIGGER trg_enforce_legs_fingerprint
    BEFORE INSERT ON trade_suggestions
    FOR EACH ROW
    EXECUTE FUNCTION enforce_legs_fingerprint();

-- Add comment explaining the enforcement
COMMENT ON TRIGGER trg_enforce_legs_fingerprint ON trade_suggestions IS
    'Wave 1.3.1: Prevents insertion of new suggestions without legs_fingerprint. '
    'Allows bypass for paper/legacy/test windows or source=legacy rows.';

-- Add comment on the function
COMMENT ON FUNCTION enforce_legs_fingerprint() IS
    'Wave 1.3.1: Enforcement function for legs_fingerprint requirement. '
    'Raises exception if fingerprint is NULL for production suggestions.';
