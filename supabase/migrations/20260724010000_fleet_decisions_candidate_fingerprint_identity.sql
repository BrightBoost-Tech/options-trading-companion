-- Fleet candidate-universe v2: complete immutable scan-candidate source.
--
-- ADDITIVE-ONLY evolution of fleet_policy_decisions so a per-candidate
-- disposition can be recorded for EVERY fully-constructed scan candidate — the
-- EMITTED set AND the ones REJECTED before trade_suggestions — keyed by the
-- immutable candidate_fingerprint (compute_legs_fingerprint = td_scan_envelopes.
-- candidate_fingerprint = trade_suggestions.legs_fingerprint). A pre-persistence
-- reject has NO source suggestion UUID, so the suggestion-uuid identity columns
-- become NULLABLE and the fingerprint becomes the durable candidate identity.
--
-- Adds the `data_unavailable` CANDIDATE disposition: a policy that needs a field
-- absent from the envelope (a rejected candidate has no routing score / no
-- canonical max-loss basis) returns a typed data_unavailable — never a fabricated
-- score, never a merit rejection, never a champion-row fallback.
--
-- Applied BY THE ORCHESTRATOR at merge time, by exact name (migration-before-
-- merge). This migration REGISTERS no policy, ACTIVATES no fleet, BINDS no
-- micro-account, and WRITES no decision row. fleet_policy_decisions holds 0 rows
-- (fleet is pending_legacy_terminal / dark), so every ALTER validates against an
-- empty table.

-- 1. Immutable candidate identity (present for EVERY candidate, emitted OR reject).
ALTER TABLE fleet_policy_decisions
    ADD COLUMN IF NOT EXISTS candidate_fingerprint text;

-- 2. Relax the suggestion-UUID identity to NULLABLE (rejects carry no suggestion).
--    The pre-existing CHECK (candidate_suggestion_id = decision_event_id) is
--    preserved verbatim: both NULL -> NULL (passes); emitted both equal (passes).
ALTER TABLE fleet_policy_decisions
    ALTER COLUMN decision_event_id DROP NOT NULL;
ALTER TABLE fleet_policy_decisions
    ALTER COLUMN candidate_suggestion_id DROP NOT NULL;

-- 3. Add the data_unavailable candidate disposition (field-absent, never fabricated).
ALTER TABLE fleet_policy_decisions
    DROP CONSTRAINT IF EXISTS fleet_policy_decisions_disposition_check;
ALTER TABLE fleet_policy_decisions
    ADD CONSTRAINT fleet_policy_decisions_disposition_check
    CHECK (disposition IN (
        'selected',
        'policy_rejected',
        'capital_rejected',
        'data_unavailable'
    ));

-- 4. Every v2 decision row carries SOME durable identity. Enforce it going forward
--    (0 legacy rows): the fingerprint (always) or, for the emitted subset, the
--    suggestion UUID.
ALTER TABLE fleet_policy_decisions
    DROP CONSTRAINT IF EXISTS fleet_policy_decisions_identity_present_check;
ALTER TABLE fleet_policy_decisions
    ADD CONSTRAINT fleet_policy_decisions_identity_present_check
    CHECK (candidate_fingerprint IS NOT NULL OR decision_event_id IS NOT NULL);

-- 5. Per-(event, micro) candidate dedup keyed on the immutable fingerprint. run_id
--    is 1:1 with (source_decision_id, micro-account), so (run_id,
--    candidate_fingerprint) is exactly one decision per candidate per event per
--    micro — and, unlike the suggestion-UUID unique, it ALSO dedups rejected
--    candidates (whose decision_event_id is NULL). Idempotent replay of a
--    candidate is a 23505 the writer ACKs, never a second row.
CREATE UNIQUE INDEX IF NOT EXISTS uq_fleet_decisions_run_fingerprint
    ON fleet_policy_decisions (run_id, candidate_fingerprint)
    WHERE candidate_fingerprint IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fleet_decisions_fingerprint
    ON fleet_policy_decisions (candidate_fingerprint);

COMMENT ON COLUMN fleet_policy_decisions.candidate_fingerprint IS
    'Immutable candidate identity (compute_legs_fingerprint) = td_scan_envelopes.candidate_fingerprint = trade_suggestions.legs_fingerprint. Present for EVERY candidate (emitted AND rejected-before-persistence). Statistical n over the complete universe = COUNT(DISTINCT candidate_fingerprint).';
COMMENT ON COLUMN fleet_policy_decisions.decision_event_id IS
    'Source suggestion UUID for an EMITTED candidate matched to a persisted row; NULL for a pre-persistence reject (never fabricated). Retained as provenance for the emitted subset; COUNT(DISTINCT decision_event_id) is the emitted-subset n.';
