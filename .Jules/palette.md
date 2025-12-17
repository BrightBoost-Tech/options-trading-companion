## 2024-05-24 - Async Button States & Toggle Accessibility
**Learning:** Adding loading states to inline action buttons (like "Generate Suggestions") prevents user frustration and potential double-submissions. Also, simple `aria-pressed` attributes on toggle buttons (like "Deterministic/Random") significantly improve context for screen reader users without requiring complex ARIA patterns.
**Action:** Always implement `disabled` and loading feedback for async actions, and check if group buttons act as toggles that need `aria-pressed`.
