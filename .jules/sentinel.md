# Sentinel Journal

## 2024-10-24 - [Enhancement] Strengthening Content Security Policy
**Vulnerability:** The existing CSP was good (`default-src 'self'`) but lacked explicit `form-action` restriction and `block-all-mixed-content`.
**Learning:** `form-action` is distinct from `default-src` and governs where forms can submit. Missing it could theoretically allow form hijacking if an attacker could inject a form.
**Prevention:** Explicitly set `form-action 'self'` to ensure forms only submit to the origin.

## 2025-05-18 - [Fix] Exception Leak in Discrete Optimizer
**Vulnerability:** The `/optimize/discrete` endpoint was catching generic `Exception` and returning `str(e)` in the 500 response. This could leak sensitive internal states or secrets if they were part of the exception message.
**Learning:** Python exceptions (e.g., `ValueError("Invalid password")`) carry the message in their string representation. Returning this directly to the client bypasses "stack trace suppression" mechanisms.
**Prevention:** Catch-all exception handlers in API endpoints must never return `str(e)`. Always return a generic message (e.g., "Internal Server Error") and log the specific error on the server side (masked if necessary).

## 2025-05-24 - [Enhancement] Missing Frontend Security Headers
**Vulnerability:** The Next.js frontend (`apps/web`) lacked standard HTTP security headers (HSTS, X-Frame-Options, X-XSS-Protection), leaving it potentially vulnerable to Clickjacking and XSS despite backend protections.
**Learning:** In a proxied architecture (Next.js -> FastAPI), backend middleware headers often don't cover the frontend's static assets or initial HTML document delivery. The frontend server (Next.js) must strictly define its own security headers.
**Prevention:** Always configure `headers()` in `next.config.js` to enforce `SAMEORIGIN`, `HSTS`, and `nosniff` at the edge/application layer, independent of backend API security.

## 2025-05-25 - [Fix] Exception Leak in Historical Simulation
**Vulnerability:** The `/historical/run-cycle` endpoint was catching generic `Exception` and returning `str(e)` in the 500 response, similar to the previous optimizer issue.
**Learning:** Repeating the same pattern of returning `str(e)` in exception handlers leaks implementation details.
**Prevention:** Applied consistent error masking in `packages/quantum/historical_endpoints.py` to return "Internal Server Error" in production.
