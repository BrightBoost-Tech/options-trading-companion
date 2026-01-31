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

## 2025-05-28 - CSS-Only Accessible Custom Inputs
**Learning:** We can create fully accessible, custom-styled checkboxes without heavy JS libraries by using the `:checked` pseudo-class and sibling selectors (`peer-checked`). This keeps the bundle size small while maintaining native keyboard navigation and form behavior.
**Action:** Prefer CSS-driven state styling for simple form controls over complex controlled components when possible.

## 2024-05-22 - [Copy Symbol Pattern]
**Learning:** Users often need to copy symbols to external tools (trading platforms, research sites). A hidden-on-hover copy action reduces noise while keeping the utility accessible.
**Action:** When displaying financial identifiers (Tickers, ISINs, Contract IDs), wrap them in a group that reveals a copy action on hover, and confirm with a toast.

## 2025-05-29 - [Inconsistent Focus Indicators]
**Learning:** Mixing raw HTML inputs with design system components creates a jarring experience for keyboard users because focus rings differ (browser default vs. custom ring).
**Action:** Audit forms for raw `<input>` tags and replace them with design system components to ensure uniform `focus-visible` styles.

## 2025-05-30 - Styling Links as Buttons
**Learning:** Using 'Button asChild' with Next.js 'Link' can sometimes cause runtime errors if children structure isn't perfect. The 'buttonVariants' helper is a more robust alternative for styling navigation links as buttons.
**Action:** Prefer 'className={buttonVariants({ variant: ... })}' on 'Link' components over wrapping them in 'Button asChild'.

## 2025-05-30 - Interactive Table Rows
**Learning:** Interactive table rows (clickable `tr` elements) are common in dashboards but often inaccessible. They need `tabIndex="0"` to be focusable and an `onKeyDown` handler (for Enter/Space) to be operable by keyboard.
**Action:** When adding `onClick` to a `tr`, always add `tabIndex="0"`, a matching `onKeyDown` handler, and visible focus styles (e.g. `focus-visible:ring`).

## 2025-05-30 - Dynamic DOM & Theming
**Learning:** Manually creating DOM elements in hooks (like custom toasts) often bypasses CSS variables if styles are hardcoded, breaking Dark Mode support.
**Action:** Use Tailwind semantic classes (`bg-background`, `text-foreground`) instead of inline styles for dynamically created elements to ensure they inherit the active theme automatically.

## 2025-05-30 - Landing Page Consistency
**Learning:** Landing pages often drift from the main app design system because they are built as 'one-offs' with raw CSS. Applying system tokens (like 'buttonVariants') to landing pages restores visual cohesion and ensures accessibility features (focus rings) are present from the very first interaction.
**Action:** Audit landing pages for raw CSS buttons and replace them with design system components or variants.

## 2025-06-01 - Preventing Double Spinners in Buttons
**Learning:** Using the `loading` prop on the `Button` component automatically prepends a spinner. If the button also contains a static icon (like `RefreshCw` or `Save`), this results in two icons when loading.
**Action:** Always wrap the static icon in a conditional check (`{!loading && <Icon />}`) when using the `loading` prop to ensure a clean state transition.

## 2025-06-02 - Multi-line Buttons
**Learning:** The design system's `Button` component centers content and has a fixed height by default, breaking layout for list items containing titles and descriptions.
**Action:** When using `Button` for multi-line content, apply `h-auto` and `flex-col items-start` classes to override default centering and height constraints while maintaining accessibility features.

## 2025-06-03 - Custom Tabs Accessibility
**Learning:** Custom tab implementations using raw `<button>` elements often lack focus rings, making them invisible to keyboard navigation. Using `focus-visible` utility classes restores accessibility without disrupting the mouse user experience.
**Action:** When building custom tabs or navigation lists, explicitly add `focus-visible:ring-2` and `focus-visible:outline-none` to ensure keyboard focus is visible.

## 2025-06-03 - Standardizing Loading States
**Learning:** Custom buttons often implement ad-hoc loading states (e.g. manually disabling and changing text), leading to inconsistent UI. The design system's `Button` component handles `loading` prop uniformly (spinner + text preservation or replacement).
**Action:** When refactoring legacy buttons, switch to `Button` component and map custom loading logic to the `loading` prop to ensure consistent behavior.
