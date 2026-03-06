## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2025-03-09 - Standardizing Trade Score Meter
**Learning:** Replaced the div-based progress bar in `TradeScoreCard.tsx` with the standardized Radix UI `Progress` component (`@/components/ui/progress`). To retain the conditional scoring colors (`bg-green-500`, `bg-yellow-500`, `bg-red-500`), literal `[&>div]:bg-color` classes were used as Tailwind JIT doesn't support dynamic string interpolation for utility classes.
**Action:** Always prefer the design system `Progress` component for score meters over custom `div` implementations to guarantee accessibility (e.g. `role="progressbar"`, `aria-label`). Handle dynamic colors by passing full literal tailwind class strings instead of interpolated strings.
