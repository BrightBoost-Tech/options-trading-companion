## 2024-05-14 - TableRow role overriding
**Learning:** Adding `role="link"` to a `TableRow` component (which renders as a `<tr>`) breaks the semantic structure of the table for screen readers. Overriding the implicit `row` role prevents screen readers from correctly navigating columns and rows.
**Action:** When making interactive table rows keyboard accessible, use `tabIndex={0}` and an `onKeyDown` handler (for 'Enter' and 'Space'), but DO NOT override the implicit `row` role. Use CSS `focus-visible` classes for visual focus.

## 2024-05-14 - Playwright E2E Mocking
**Learning:** When mocking API responses in Playwright E2E tests (e.g., using `page.route`), ensure the URL pattern accurately matches the client-side fetch paths, including the API prefix (e.g., `**/api/v1/system/health` instead of `**/system/health`), or the mock will fail to intercept.
**Action:** Always verify the actual network requests being made by the application in the browser network tab to ensure the Playwright `page.route` pattern matches exactly.
