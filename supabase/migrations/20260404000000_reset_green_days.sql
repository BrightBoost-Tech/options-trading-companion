-- Reset green_days to 0: previous counts included internal fills
-- that should not have counted toward Alpaca paper progression.

UPDATE go_live_progression
SET alpaca_paper_green_days = 0,
    alpaca_paper_last_green_date = NULL,
    updated_at = now()
WHERE user_id = '75ee12ad-b119-4f32-aeea-19b4ef55d587';

-- Log the reset
INSERT INTO go_live_progression_log (user_id, event_type, details)
VALUES (
    '75ee12ad-b119-4f32-aeea-19b4ef55d587',
    'manual_override',
    '{"action": "reset_green_days", "reason": "internal fills were miscounted as alpaca", "reset_to": 0}'
);
