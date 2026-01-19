-- Wave 1.3: Update event_key column comment to document trace-scoped idempotency
-- When idempotency_payload is provided to log_event(), the event_key is computed as:
--   sha256(trace_id:event_name:payload_hash)
-- This enables true idempotency for retried operations without timestamp variance.

COMMENT ON COLUMN analytics_events.event_key IS 'Wave 1.3: event_key may be sha256(trace_id:event_name:payload_hash) for trace-scoped idempotent events when idempotency_payload is provided';
