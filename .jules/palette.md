## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.

## 2024-05-24 - Standardizing Metrics Visualization
**Learning:** Replaced text-based percentages with standard `Progress` components in dashboard cards. This not only improves visual scanning but ensures consistent accessibility traits (roles, values) inherited from the design system component.
**Action:** When finding lists of metric/percentage pairs, propose upgrading them to visual `Progress` bars to enhance the "dashboard" feel and readability.

## 2025-06-07 - Accessible Table Rows as Links
**Learning:** Interactive table rows (`<TableRow>`) used for navigation are invisible to keyboard and screen reader users unless manually enhanced. Simply adding `cursor-pointer` and an `onClick` handler is insufficient.
**Action:** When a table row functions as a navigation link, always add `tabIndex={0}`, `role="link"`, an `onKeyDown` handler for 'Enter' and 'Space' keys, and `focus-visible` classes (e.g., `focus-visible:ring-2`) to ensure full accessibility.
