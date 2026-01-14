## 2025-02-18 - Path Disclosure in Health Endpoint
**Vulnerability:** The `/health` endpoint in `api.py` was returning `str(env_path)`, which exposed the absolute file system path of the server's `.env` file (e.g., `/home/user/repo/packages/quantum/.env`). It also exposed the `SUPABASE_STATUS` dictionary, which could potentially contain sensitive error messages or keys if connection exceptions occurred.
**Learning:** Development helpers (like printing where env vars are loaded from) often get left in production endpoints, creating easy reconnaissance opportunities for attackers.
**Prevention:**
1. Never return raw file paths in API responses; return booleans (e.g., `is_loaded: true`) instead.
2. Explicitly construct "safe" response objects for public endpoints instead of dumping internal state dictionaries.

## 2025-02-18 - Missing Security Headers
**Vulnerability:** The application lacked `Content-Security-Policy` and `Permissions-Policy` headers, leaving it vulnerable to XSS and data injection attacks, and allowing unnecessary browser feature access.
**Learning:** Default middleware configurations often prioritize compatibility over security. Explicitly adding these headers is necessary for a robust defense-in-depth strategy.
**Prevention:**
1. Enforce a strict `default-src 'self'` CSP policy by default for API services.
2. Explicitly disable powerful browser features (camera, mic, geolocation) via `Permissions-Policy` for non-UI endpoints.

## 2025-02-18 - API Key Leakage in Error Responses
**Vulnerability:** The `refresh_quote` endpoint returned unsanitized exception messages (`str(e)`) to the client. When underlying HTTP clients (like `requests`) raised errors, the exception message included the request URL, which contained the API key as a query parameter (e.g., `?apiKey=sk_...`).
**Learning:** Convenience in error handling (passing backend errors to frontend) directly conflicts with security. Exception messages from HTTP clients are often verbose and sensitive.
**Prevention:**
1. Never return `str(e)` or `repr(e)` in HTTP 500/502 responses.
2. Log the full error server-side, but return a static, generic error message (e.g., "Provider Error") to the client.
## 2025-02-18 - Sensitive Data Leakage in Exception Handling
**Vulnerability:** Plaid API endpoints were returning raw exception strings (`str(e)`) in HTTP 400/500 responses. This could leak sensitive configuration details or upstream API response bodies containing PII/keys in production environments.
**Learning:** Framework default behavior (returning exception details) and convenience for developers (seeing errors in frontend) often conflicts with production security requirements.
**Prevention:**
1. Implement a dedicated error parsing helper (like `parse_plaid_error`) that sanitizes upstream errors.
2. Use an environment check (e.g., `APP_ENV != "production"`) to conditionally reveal detailed error messages only in safe environments.
3. Mask `ValueError` and similar configuration exceptions with generic "Configuration Error" messages in production.

## 2025-02-18 - Signature Leakage in Auth Logs
**Vulnerability:** The internal task authentication logic (`packages/quantum/security/task_auth.py`) was logging the `expected_signature` when a signature mismatch occurred. This potentially allows an attacker with log access to forge signatures for future requests (within the TTL window) or analyze the HMAC generation for weaknesses.
**Learning:** Debug logs that print "Expected vs Got" values are dangerous for cryptographic secrets. Logging the "Expected" secret essentially reveals the correct answer to anyone who can read the logs.
**Prevention:**
1. Never log the expected value of a cryptographic check (HMAC, hash, token) on failure.
2. Only log "Signature verification failed" or at most the *provided* (potentially malicious) signature for forensic analysis, but never the *correct* one.
