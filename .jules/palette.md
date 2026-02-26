## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2024-05-25 - Explaining Disabled States
**Learning:** Simply disabling checkboxes for blocked actions (like in Trade Inbox) is confusing without context. Wrapping them in a Tooltip explains *why* the action is unavailable.
**Action:** When disabling interactive elements based on complex conditions (e.g., quality gates), always wrap them in a Tooltip with the specific reason, and use `cursor-not-allowed` on the wrapper to ensure the tooltip triggers.
