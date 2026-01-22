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

## 2026-01-21 - [Fix] Admin Auth Bypass via Forged JWT
**Vulnerability:** The admin authorization check (`verify_admin_access`) decoded the JWT to check for the `role="admin"` claim without verifying the signature. In development environments (or if `ENABLE_DEV_AUTH_BYPASS` was set), an attacker could bypass authentication using `X-Test-Mode-User` and then escalate privileges to Admin by supplying a self-signed or invalid JWT with the admin role.
**Learning:** Checking claims in a JWT without verifying the signature is dangerous, even if the user identity was established via another method (like a dev bypass). Authentication (Who are you?) and Authorization (Are you Admin?) often rely on the same token, but if they are decoupled, the authorization step must still verify the integrity of its proof.
**Prevention:** Always use `jwt.decode` with the secret key to verify signatures before trusting any claims, especially for privileged roles. Never use `json.loads(base64...)` on a JWT for security decisions.

## 2026-02-12 - [Fix] Rate Limiting Bypass in Proxied Architecture
**Vulnerability:** The backend (`packages/quantum`) used `request.client.host` for rate limiting. Since the app uses Next.js rewrites to proxy API requests to the backend, all requests originated from `127.0.0.1`. This caused the rate limiter to group all users together, meaning one active user could exhaust the rate limit for the entire platform (DoS).
**Learning:** In a reverse proxy setup (Next.js -> FastAPI), the backend sees the proxy's IP. Standard IP-based rate limiting libraries (`slowapi`) default to the direct connection IP unless configured to inspect `X-Forwarded-For`.
**Prevention:** Implemented a custom key function `get_real_ip` that inspects `X-Forwarded-For` headers **only** when the request comes from a trusted proxy (localhost). This distinguishes users correctly while preventing external spoofing attacks.
