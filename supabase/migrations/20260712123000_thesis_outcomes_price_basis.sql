-- PR-⓪ (2026-07-12, F-A9-THESIS-BASIS): disclose WHICH price source graded each
-- thesis row. thesis_tracker._underlying_at_expiry silently falls back to the last
-- bar ≤7d before expiry and persists a TERMINAL hit/miss; the row must record
-- whether the price was the exact expiry close, a ≤7d fallback bar, unknown, or a
-- non-scoring state — so the thesis metric's own evidence quality is queryable
-- forever (born-honest before the first authoritative fill). Nullable, forward-only.
ALTER TABLE position_thesis_outcomes ADD COLUMN IF NOT EXISTS price_basis text;
