## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2024-07-21 - Accessible Collapsible Sections
**Learning:** Custom collapsible sections using native `<button>` elements for toggling often lack the required WAI-ARIA disclosure pattern (`aria-expanded`, `aria-controls`) and visible focus states, which makes them inaccessible to screen readers and keyboard users.
**Action:** When implementing custom collapsible sections or accordions, ensure the toggle button uses `aria-expanded` and `aria-controls`, that the content region has a matching `id`, and that explicit `focus-visible` classes are applied to the button.
