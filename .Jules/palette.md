## 2024-05-24 - Accessibility for Complex Cards
**Learning:** Complex cards with multiple interactive elements (selection, dismissal, charts) often have "hidden" accessibility gaps. Icon-only buttons and selection checkboxes within lists are frequent offenders.
**Action:** Audit all list-based cards for: 1) selection checkboxes (need dynamic labels), 2) icon-only actions (need `aria-label`), and 3) decorative vs. informative SVGs (need `role="img"`).

## 2025-05-27 - Contextual Actions in List Views
**Learning:** In dashboard grids where the same action (e.g., "Dismiss", "Stage") appears on multiple cards, generic labels like "Dismiss" are insufficient for screen reader users navigating by focus. They need context (e.g., "Dismiss SPY").
**Action:** Always inject the unique identifier (Ticker/Symbol) into the `aria-label` of repetitive action buttons in list views.

## 2025-05-27 - Standardizing Interactive Elements
**Learning:** Custom interactive elements (like raw `<button>` tags with Tailwind classes) often miss critical states like `focus-visible`. This creates an inconsistent keyboard navigation experience where some elements have clear focus rings and others don't.
**Action:** Replace custom buttons with the design system's `Button` component to inherit standard focus states and interactivity patterns automatically.

## 2025-05-27 - Semantic Table Structure
**Learning:** Using `th scope='row'` and `th scope='rowgroup'` adds critical navigation context for screen readers in complex data tables without breaking visual layouts (as long as `text-left` is applied).
**Action:** Audit all data tables for row headers and grouping headers.
