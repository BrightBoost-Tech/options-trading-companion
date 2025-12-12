## 2024-05-23 - Table Accessibility
**Learning:** Tables in the dashboard were missing `scope="col"` attributes on header cells, making column associations ambiguous for screen reader users.
**Action:** Always verify `th` elements have appropriate `scope` attributes (`col` or `row`) during component creation.
