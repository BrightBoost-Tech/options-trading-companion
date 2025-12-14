## 2024-05-23 - [Critical Privilege Escalation in API Dependency]
**Vulnerability:** The `get_supabase_user_client` dependency in `packages/quantum/api.py` defaulted to returning the `supabase_admin` (service role) client if authentication checks failed or fell through due to misconfiguration (e.g., missing `SUPABASE_ANON_KEY`).
**Learning:** Default fallbacks in security-sensitive dependency injection functions can silently upgrade privileges. Never use an administrative client as a "default" return value.
**Prevention:** Always follow the "Fail Securely" principle. Explicitly raise an exception (e.g., 401 or 500) at the end of authentication functions if no valid credentials or safe state can be established.
