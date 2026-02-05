## 2024-05-22 - Accessible Custom Progress Bars
**Learning:** Custom progress bar implementations using `div`s (often for specific styling needs like custom colors or heights) are frequently missed during accessibility audits.
**Action:** When inspecting data visualization components like Treemaps or Charts, check for manual bar implementations and ensure `role="progressbar"`, `aria-valuenow`, and `aria-label` are present.
