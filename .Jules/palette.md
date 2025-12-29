# Palette's Journal

## 2025-05-22 - Visual Scores and Accessibility
**Learning:** Visual-only indicators like colored progress bars are common but often lack semantic meaning for screen readers. The `TradeScoreCard` used a `div` with a width percentage, which is invisible to AT.
**Action:** Always wrap visual meters in `role="progressbar"` with explicit `aria-valuenow`, `aria-valuemin`, and `aria-valuemax`.

## 2025-05-22 - Suggestion Card Actions
**Learning:** Generic button labels like "Dismiss" or "Stage" in a list of cards are confusing for screen reader users because they lack context.
**Action:** Use `aria-label` to include specific context, e.g., "Dismiss SPY Call Spread", so users know exactly which item they are acting on.

## 2025-06-01 - Disabled Buttons and Context
**Learning:** Disabled buttons are often a "UX dead end" where users don't know *why* an action is unavailable. Simply greying them out isn't enough, especially for important actions like "Apply Rebalance".
**Action:** When an action is permanently disabled (e.g., pending feature), wrap it in a tooltip explaining *why* and *when* it might be available. For accessibility, ensure the disabled element is wrapped in a focusable container (like a `span` with `tabIndex={0}`) so keyboard users can also discover the tooltip.
