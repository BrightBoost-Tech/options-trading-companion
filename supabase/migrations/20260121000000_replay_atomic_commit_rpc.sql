-- =============================================================================
-- Replay Feature Store v4.1: Atomic Commit RPC
-- =============================================================================
-- This migration adds an RPC function for atomic decision commit:
-- - Inserts decision_runs, decision_inputs, decision_features in single transaction
-- - Prevents partial writes on failure
-- - Supports status update for existing decision_id on retry
-- =============================================================================

-- =============================================================================
-- RPC Function: rpc_commit_decision_v4
-- =============================================================================
-- Atomically commits a decision with its inputs and features.
-- If decision_id already exists, updates status instead of inserting.
--
-- Parameters:
--   p_decision_id: UUID - decision identifier
--   p_strategy_name: TEXT - strategy/job name
--   p_as_of_ts: TIMESTAMPTZ - decision timestamp
--   p_user_id: UUID (optional) - user context
--   p_git_sha: TEXT (optional) - git commit
--   p_status: TEXT - "ok" or "failed"
--   p_error_summary: TEXT (optional) - error message if failed
--   p_input_hash: TEXT (optional) - aggregate hash of inputs
--   p_features_hash: TEXT (optional) - aggregate hash of features
--   p_duration_ms: INT (optional) - cycle duration
--   p_inputs: JSONB - array of {blob_hash, key, snapshot_type, metadata}
--   p_features: JSONB - array of {symbol, namespace, features, features_hash}
--
-- Returns: TABLE with status and counts

CREATE OR REPLACE FUNCTION rpc_commit_decision_v4(
    p_decision_id UUID,
    p_strategy_name TEXT,
    p_as_of_ts TIMESTAMPTZ,
    p_user_id UUID DEFAULT NULL,
    p_git_sha TEXT DEFAULT NULL,
    p_status TEXT DEFAULT 'ok',
    p_error_summary TEXT DEFAULT NULL,
    p_input_hash TEXT DEFAULT NULL,
    p_features_hash TEXT DEFAULT NULL,
    p_duration_ms INT DEFAULT NULL,
    p_inputs JSONB DEFAULT '[]'::jsonb,
    p_features JSONB DEFAULT '[]'::jsonb
)
RETURNS TABLE (
    commit_status TEXT,
    decision_id UUID,
    inputs_inserted INT,
    features_inserted INT,
    was_update BOOLEAN
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_inputs_count INT := 0;
    v_features_count INT := 0;
    v_was_update BOOLEAN := FALSE;
    v_existing_status TEXT;
BEGIN
    -- Check if decision already exists
    SELECT status INTO v_existing_status
    FROM decision_runs dr
    WHERE dr.decision_id = p_decision_id;

    IF FOUND THEN
        -- Decision exists - update status (idempotent retry handling)
        v_was_update := TRUE;

        UPDATE decision_runs
        SET
            status = p_status,
            error_summary = COALESCE(p_error_summary, error_summary),
            input_hash = COALESCE(p_input_hash, input_hash),
            features_hash = COALESCE(p_features_hash, features_hash),
            duration_ms = COALESCE(p_duration_ms, duration_ms)
        WHERE decision_runs.decision_id = p_decision_id;

        -- Return early - don't re-insert inputs/features
        RETURN QUERY SELECT
            'updated'::TEXT,
            p_decision_id,
            0,
            0,
            TRUE;
        RETURN;
    END IF;

    -- Insert decision_runs header
    INSERT INTO decision_runs (
        decision_id,
        strategy_name,
        as_of_ts,
        user_id,
        git_sha,
        status,
        error_summary,
        input_hash,
        features_hash,
        inputs_count,
        features_count,
        duration_ms
    ) VALUES (
        p_decision_id,
        p_strategy_name,
        p_as_of_ts,
        p_user_id,
        p_git_sha,
        p_status,
        LEFT(p_error_summary, 500),
        p_input_hash,
        p_features_hash,
        jsonb_array_length(p_inputs),
        jsonb_array_length(p_features),
        p_duration_ms
    );

    -- Insert decision_inputs from JSONB array
    IF jsonb_array_length(p_inputs) > 0 THEN
        INSERT INTO decision_inputs (decision_id, blob_hash, key, snapshot_type, metadata)
        SELECT
            p_decision_id,
            (elem->>'blob_hash')::TEXT,
            (elem->>'key')::TEXT,
            (elem->>'snapshot_type')::TEXT,
            COALESCE(elem->'metadata', '{}'::jsonb)
        FROM jsonb_array_elements(p_inputs) AS elem;

        GET DIAGNOSTICS v_inputs_count = ROW_COUNT;
    END IF;

    -- Insert decision_features from JSONB array
    IF jsonb_array_length(p_features) > 0 THEN
        INSERT INTO decision_features (decision_id, symbol, namespace, features, features_hash)
        SELECT
            p_decision_id,
            (elem->>'symbol')::TEXT,
            (elem->>'namespace')::TEXT,
            elem->'features',
            (elem->>'features_hash')::TEXT
        FROM jsonb_array_elements(p_features) AS elem;

        GET DIAGNOSTICS v_features_count = ROW_COUNT;
    END IF;

    RETURN QUERY SELECT
        'inserted'::TEXT,
        p_decision_id,
        v_inputs_count,
        v_features_count,
        FALSE;
END;
$$;

-- Add comment for documentation
COMMENT ON FUNCTION rpc_commit_decision_v4(UUID, TEXT, TIMESTAMPTZ, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, INT, JSONB, JSONB) IS
    'Atomically commits a decision run with its inputs and features in a single transaction. '
    'Prevents partial writes and supports idempotent retries. '
    'Part of Replay Feature Store v4.1 write safety improvements.';

-- Grant execute to service role (for job handlers)
-- Note: Supabase automatically grants execute to authenticated role
