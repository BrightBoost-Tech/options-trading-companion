-- #62a-D1: align policy_lab_cohorts.promoted_at with operator intent.
--
-- Pre-migration state (operator manual UPDATE on 2026-04-02 21:28Z,
-- predating the 2026-05-12 intent clarification):
--   aggressive   — promoted_at = NULL
--   conservative — promoted_at = NULL
--   neutral      — promoted_at = 2026-04-02 21:28Z  ← misaligned
--
-- Post-migration target state (matches operator intent confirmed
-- 2026-05-12: aggressive is the starting champion; conservative +
-- neutral are shadow challengers):
--   aggressive   — promoted_at = NOW()
--   conservative — promoted_at = NULL  (verified, not assumed)
--   neutral      — promoted_at = NULL
--
-- This migration is paired with code changes in fork.py (read
-- promoted_at via new get_current_champion helper) and the two
-- silent-failure `is_champion` query sites in paper_autopilot_service
-- and paper_exit_evaluator that have been rewritten to use the
-- promoted_at lookup. The code includes a defensive fallback to
-- "aggressive" when no promoted cohort is found, so deploy order
-- (code-before-migration vs migration-before-code) does not matter.
--
-- See docs/cohort_architecture.md "DB state misalignment" subsection
-- for the archeology, and docs/loud_error_doctrine.md H12 entry for
-- the doctrine this PR codifies.

-- Promote aggressive (the live champion per operator intent).
UPDATE policy_lab_cohorts
   SET promoted_at = NOW()
 WHERE cohort_name = 'aggressive'
   AND user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587'
   AND is_active = true;

-- Demote the stale neutral promotion. Reading from current DB at
-- migration-author time confirmed only neutral has a non-NULL
-- promoted_at value; this UPDATE is the corrective.
UPDATE policy_lab_cohorts
   SET promoted_at = NULL
 WHERE cohort_name = 'neutral'
   AND user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587'
   AND is_active = true;

-- Conservative should already be NULL; verify in the apply
-- procedure rather than overwriting blindly. If a future state
-- ever sets conservative as promoted, this migration would NOT
-- demote it — by design. The post-apply check below catches drift.
--
-- Post-apply verification (run manually after the UPDATEs land):
--
--   SELECT cohort_name, promoted_at
--     FROM policy_lab_cohorts
--    WHERE user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587'
--      AND is_active = true
--    ORDER BY cohort_name;
--
-- Expected: aggressive has a non-NULL promoted_at; conservative and
-- neutral both NULL. Exactly one row with promoted_at set.
