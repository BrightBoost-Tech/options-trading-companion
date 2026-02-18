## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2024-05-27 - Dynamic Labels for Icon Toggles
**Learning:** Icon-only toggle buttons (like theme switchers) often have static `aria-label`s (e.g., "Toggle theme") which forces users to guess the current state.
**Action:** Always implement dynamic `aria-label`s and tooltips that describe the *action* (e.g., "Switch to dark mode") rather than the component's purpose.
