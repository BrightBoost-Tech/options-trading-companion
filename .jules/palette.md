## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2024-05-27 - Dynamic Labels for Icon-Only Toggles
**Learning:** Static labels (e.g., "Toggle theme") on state-switching buttons often fail to communicate the *outcome* of the action. Users benefit more from knowing what will happen (e.g., "Switch to dark mode") rather than what the button represents.
**Action:** When implementing icon-only toggle buttons, use dynamic `aria-label` and tooltips that describe the pending action, not the current state.
