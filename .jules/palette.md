## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2024-05-26 - Progress Bar Component Consistency
**Learning:** I found another custom `<div role="progressbar">` implementation in `DisciplineSummary.tsx`. It's important to be vigilant for these legacy elements, as replacing them with the standard `Progress` component (`@/components/ui/progress`) ensures consistency across the UI, simplifes the code, and utilizes standard accessibility patterns. We can still apply custom color styling to the indicator via the `[&>div]:bg-color` trick.
**Action:** Always replace stray `<div role="progressbar">` elements with the shared `Progress` component to ensure consistent UI and accessibility semantics across the platform.
