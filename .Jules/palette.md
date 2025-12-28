# Palette's Journal

## 2025-05-22 - Visual Scores and Accessibility
**Learning:** Visual-only indicators like colored progress bars are common but often lack semantic meaning for screen readers. The `TradeScoreCard` used a `div` with a width percentage, which is invisible to AT.
**Action:** Always wrap visual meters in `role="progressbar"` with explicit `aria-valuenow`, `aria-valuemin`, and `aria-valuemax`.

## 2025-05-22 - Suggestion Card Actions
**Learning:** Generic button labels like "Dismiss" or "Stage" in a list of cards are confusing for screen reader users because they lack context.
**Action:** Use `aria-label` to include specific context, e.g., "Dismiss SPY Call Spread", so users know exactly which item they are acting on.
