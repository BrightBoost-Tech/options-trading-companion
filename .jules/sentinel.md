## 2025-05-23 - [Exposed Secrets in Root Directory]
**Vulnerability:** Found `.key` (encryption key) and `env.txt` (environment variables including API keys) committed to the repository root.
**Learning:** These files were likely created during local development or startup scripts and accidentally added to git because they were not in `.gitignore`. The `env.txt` file is not a standard pattern, suggesting it was a manual dump or output of a script.
**Prevention:**
1. Added `.key` and `env.txt` to `.gitignore`.
2. Removed them from git tracking.
3. Future: Ensure all setup scripts do not create files in the root that are not gitignored. Use standard `.env` patterns.

## 2025-05-23 - [Timing Attack in Public Tasks]
**Vulnerability:** The `verify_cron_secret` function used a standard `!=` string comparison for validating the cron secret header.
**Learning:** This introduces a timing attack vulnerability where an attacker could deduce the secret by measuring response times. While `hmac.compare_digest` was used elsewhere, this public endpoint was overlooked.
**Prevention:**
1. Replaced with `secrets.compare_digest` for constant-time comparison.
2. Added defensive null checks before comparison.
