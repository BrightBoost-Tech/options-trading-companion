## 2024-05-24 - Accessibility for Complex Cards
**Learning:** Complex cards with multiple interactive elements (selection, dismissal, charts) often have "hidden" accessibility gaps. Icon-only buttons and selection checkboxes within lists are frequent offenders.
**Action:** Audit all list-based cards for: 1) selection checkboxes (need dynamic labels), 2) icon-only actions (need `aria-label`), and 3) decorative vs. informative SVGs (need `role="img"`).
