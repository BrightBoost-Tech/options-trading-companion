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
