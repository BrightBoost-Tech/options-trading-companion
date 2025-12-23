## 2024-05-24 - Async Button States & Toggle Accessibility
**Learning:** Adding loading states to inline action buttons (like "Generate Suggestions") prevents user frustration and potential double-submissions. Also, simple `aria-pressed` attributes on toggle buttons (like "Deterministic/Random") significantly improve context for screen reader users without requiring complex ARIA patterns.
**Action:** Always implement `disabled` and loading feedback for async actions, and check if group buttons act as toggles that need `aria-pressed`.

## 2025-05-24 - Journal Refresh Feedback
**Learning:** Even minor "refresh" text links can cause user uncertainty if they lack immediate feedback. Converting a static text link to an icon-button with a spinner state (using `RefreshCw`) provides reassurance that the system is responding, especially for background fetch operations.
**Action:** When adding refresh capability to dashboard cards, prefer a standard icon pattern with `animate-spin` over plain text links.

## 2025-05-24 - Accessible Tabs Pattern
**Learning:** Converting `div`-based button groups to proper ARIA tabs (`role="tablist"`, `tab`, `tabpanel`) significantly improves navigation for screen reader and keyboard users. Using a configuration array for tabs reduces code duplication and makes implementing `ArrowLeft`/`ArrowRight` navigation much simpler.
**Action:** When refactoring tab-like interfaces, always use a config array to drive the rendering and handle keyboard navigation index math generically.
