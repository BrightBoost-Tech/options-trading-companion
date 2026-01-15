# Sentinel Journal

## 2024-10-24 - [Enhancement] Strengthening Content Security Policy
**Vulnerability:** The existing CSP was good (`default-src 'self'`) but lacked explicit `form-action` restriction and `block-all-mixed-content`.
**Learning:** `form-action` is distinct from `default-src` and governs where forms can submit. Missing it could theoretically allow form hijacking if an attacker could inject a form.
**Prevention:** Explicitly set `form-action 'self'` to ensure forms only submit to the origin.
