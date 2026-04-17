# Security Model v4

This document describes the security architecture for the Options Trading Companion backend.

## Overview

The security model follows the principle of least privilege with multiple layers of defense:

1. **Authentication**: JWT-based user authentication with Supabase
2. **Authorization**: Role-based access control with admin/user separation
3. **Request Signing**: HMAC-signed requests for internal task endpoints
4. **Production Hardening**: Strict separation between dev and prod environments
5. **Secrets Management**: Centralized secrets with blast radius control

---

## Authentication Layers

### User Authentication (`security/__init__.py`)
- Uses Supabase JWT tokens
- Validates JWT signature with `SUPABASE_JWT_SECRET`
- Extracts user ID from token `sub` claim
- Fallback for development: `ENABLE_DEV_AUTH_BYPASS=1` with `X-Test-Mode-User` header

### Task Endpoint Authentication (`security/task_signing_v4.py`)
- HMAC-SHA256 request signing with scoped access
- Payload format: `v4:{timestamp}:{nonce}:{method}:{path}:{body_hash}:{scope}`
- Timestamp validation (5-minute TTL)
- Nonce replay protection (optional, Supabase-backed)
- Key rotation support via `TASK_SIGNING_KEYS`

### Admin Authentication (`security/admin_auth.py`)
- JWT role claim verification (`role=admin`)
- Admin user ID allowlist (`ADMIN_USER_IDS` env var)
- Audit logging for all admin actions
- **No CRON_SECRET fallback** (removed privilege escalation risk)

---

## Authorization Model

### User Endpoints (`/holdings`, `/portfolio`, etc.)
- Require valid user JWT
- User can only access their own data (enforced by RLS)
- Rate limited per user

### Task Endpoints (`/tasks/*`)
- Internal endpoints for scheduled jobs
- Require v4 HMAC signature with specific scope
- Example scopes: `tasks:suggestions_open`, `tasks:validation_eval`
- Legacy `CRON_SECRET` endpoint was removed 2026-04-09. The
  `ALLOW_LEGACY_CRON_SECRET` env var is vestigial and scheduled for
  deletion from Railway.

### Admin Endpoints (`/jobs/*`)
- Require admin access (JWT role or allowlist)
- All actions are audit logged
- No CRON_SECRET access

### Debug Endpoints (`/dev/*`, `/__auth_debug`)
- Only registered when `ENABLE_DEBUG_ROUTES=1`
- Disabled by default in production
- Require localhost access even when enabled

---

## Environment Variables

### Required (Server won't start without these)
| Variable | Purpose |
|----------|---------|
| `SUPABASE_JWT_SECRET` | JWT signature verification |
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | User-scoped operations |
| `SUPABASE_SERVICE_ROLE_KEY` | Admin operations (bypasses RLS) |
| `ENCRYPTION_KEY` | Token encryption (Fernet) |

### Task Signing (Required for `/tasks/*` endpoints)
| Variable | Purpose |
|----------|---------|
| `TASK_SIGNING_SECRET` | Single signing key (fallback) |
| `TASK_SIGNING_KEYS` | Key rotation: `kid1:secret1,kid2:secret2` |
| `TASK_V4_TTL_SECONDS` | Request timestamp validity (default: 300) |
| `TASK_NONCE_PROTECTION` | Enable replay protection: `1` or `0` |

### Admin Access
| Variable | Purpose |
|----------|---------|
| `ADMIN_USER_IDS` | Comma-separated list of admin user UUIDs |

### Production Hardening
| Variable | Purpose |
|----------|---------|
| `APP_ENV` | Environment: `development`, `test`, or `production` |
| `ENABLE_DEV_AUTH_BYPASS` | Dev mode: `1` or `0` (hard failure if `1` in production) |
| `ENABLE_DEBUG_ROUTES` | Register debug routes: `1` or `0` |

### Legacy (removed)
- `CRON_SECRET` and `ALLOW_LEGACY_CRON_SECRET` — removed 2026-04-09.
  No longer read by production code; scheduled for removal from Railway.

---

## Security Constraints

### Hard Failures (Server won't start)
1. Missing required environment variables
2. `ENABLE_DEV_AUTH_BYPASS=1` in production

### Soft Warnings
1. Missing `TASK_SIGNING_SECRET`
2. Using `NEXT_PUBLIC_*` vars instead of `SUPABASE_*`
3. Legacy `CRON_SECRET` usage (deprecated)

---

## Request Flow Examples

### User Request
```
Client -> JWT in Authorization header
     -> get_current_user() validates JWT
     -> RLS enforces user_id match
     -> Response
```

### Task Request (v4)
```
Scheduler -> Sign request with HMAC
         -> Include X-Task-* headers
         -> verify_task_signature() validates
         -> Nonce replay check
         -> Execute task
```

### Admin Request
```
Admin UI -> JWT with role=admin claim
        -> verify_admin_access() validates
        -> Audit log entry
        -> Execute admin action
```

---

## Key Rotation

### Task Signing Keys
```bash
# Current setup (single key)
TASK_SIGNING_SECRET=old-key

# Migration (both keys active)
TASK_SIGNING_KEYS=new:new-secret-key,old:old-key

# After migration (remove old)
TASK_SIGNING_KEYS=new:new-secret-key
```

### Process
1. Add new key to `TASK_SIGNING_KEYS` with unique key ID
2. Update all callers to use new key ID
3. Monitor for old key usage (audit logs)
4. Remove old key after migration period

---

## Audit Trail

### Admin Actions (`[AUDIT]` logs)
- All admin access attempts (granted/denied)
- All admin mutations (retry, etc.)
- Structured JSON format for aggregation

### Trade Events (Observability)
- Suggestion generation
- Execution decisions
- Trace IDs for full lineage

---

## Security Checklist

### Before Deployment
- [ ] All required env vars set
- [ ] `ENABLE_DEV_AUTH_BYPASS` is NOT `1`
- [ ] `ENABLE_DEBUG_ROUTES` is NOT `1` (unless needed)
- [ ] `ADMIN_USER_IDS` contains only trusted users
- [ ] CORS origins are properly configured

### During Development
- [ ] Use `APP_ENV=development`
- [ ] Use `ENABLE_DEV_AUTH_BYPASS=1` only for local testing
- [ ] Use `X-Test-Mode-User` header for testing user-scoped endpoints

---

## Calling /tasks/* Endpoints

### Required Headers (v4 Signing)

Every request to `/tasks/*` endpoints must include these headers:

| Header | Description |
|--------|-------------|
| `X-Task-Ts` | Unix timestamp (seconds) |
| `X-Task-Nonce` | Random 16-byte hex string |
| `X-Task-Scope` | Required scope (e.g., `tasks:suggestions_open`) |
| `X-Task-Signature` | HMAC-SHA256 signature |
| `X-Task-Key-Id` | (Optional) Key ID for rotation |

### Signature Generation

```python
from packages.quantum.security.task_signing_v4 import sign_task_request

headers = sign_task_request(
    method="POST",
    path="/tasks/suggestions/open",
    body=b'{"user_id": "optional-uuid"}',
    scope="tasks:suggestions_open",
    secret=os.environ["TASK_SIGNING_SECRET"],
    key_id="primary"  # Optional
)
# Returns: {"X-Task-Ts": "...", "X-Task-Nonce": "...", ...}
```

### Task Scopes

| Endpoint | Scope | Schedule |
|----------|-------|----------|
| `/tasks/universe/sync` | `tasks:universe_sync` | Manual |
| `/tasks/morning-brief` | `tasks:morning_brief` | Manual |
| `/tasks/midday-scan` | `tasks:midday_scan` | Manual |
| `/tasks/weekly-report` | `tasks:weekly_report` | Manual |
| `/tasks/validation/eval` | `tasks:validation_eval` | Manual |
| `/tasks/suggestions/close` | `tasks:suggestions_close` | 8 AM Chicago |
| `/tasks/suggestions/open` | `tasks:suggestions_open` | 11 AM Chicago |
| `/tasks/learning/ingest` | `tasks:learning_ingest` | 4:10 PM Chicago |
| `/tasks/strategy/autotune` | `tasks:strategy_autotune` | Manual |

---

## Local Development

### `.env.local` Setup

```bash
# Task signing (pick one)
TASK_SIGNING_SECRET=dev-secret-at-least-32-characters-long

# Or for key rotation testing
TASK_SIGNING_KEYS=dev:dev-secret-at-least-32-characters-long

# API base URL
BASE_URL=http://localhost:8000

# Optional: run for specific user
USER_ID=your-user-uuid
```

### Running Tasks Locally

```bash
# Run a task
python scripts/run_signed_task.py suggestions_close

# Dry run (validate without sending)
DRY_RUN=1 python scripts/run_signed_task.py suggestions_open

# Skip time gate (run anytime)
python scripts/run_signed_task.py learning_ingest --skip-time-gate

# For specific user
python scripts/run_signed_task.py suggestions_close --user-id abc-123

# List all tasks
python scripts/run_signed_task.py --list
```

---

## GitHub Actions Setup

### Required Secrets

Add these to your repository secrets (Settings > Secrets and variables > Actions):

| Secret | Description |
|--------|-------------|
| `TASK_SIGNING_KEYS` | Format: `kid1:secret1,kid2:secret2` |
| `QUANTUM_BASE_URL` | API base URL (e.g., `https://api.example.com`) |
| `TASK_USER_ID` | (Optional) Run tasks for specific user |

### Generating a Signing Key

```bash
# Generate a secure 64-character hex string
python -c "import secrets; print(secrets.token_hex(32))"
```

### Workflow Files

| Workflow | Purpose |
|----------|---------|
| `.github/workflows/trading_tasks.yml` | Scheduled trading tasks (8 AM, 11 AM, 4:10 PM Chicago) |
| `.github/workflows/security_v4_smoketest.yml` | Manual smoke test for signing validation |

### Manual Dispatch

1. Go to Actions > Trading Tasks (v4 Signed)
2. Click "Run workflow"
3. Select task, optionally enable dry-run or skip time gate
4. Click "Run workflow"

---

## Migration Cutover (completed 2026-04-09)

The legacy `CRON_SECRET` endpoint and `ALLOW_LEGACY_CRON_SECRET` gate were
both removed on 2026-04-09. All `/tasks/*` and `/internal/tasks/*`
endpoints require v4 HMAC signatures. Historical cutover plan preserved
in git history (commits before 2026-04-09).

---

## Files Reference

| Module | Purpose |
|--------|---------|
| `security/__init__.py` | User JWT authentication |
| `security/config.py` | Startup validation, env detection |
| `security/task_signing_v4.py` | HMAC request signing for tasks |
| `security/admin_auth.py` | Admin access control |
| `security/supabase_config.py` | Unified Supabase client config |
| `security/secrets_provider.py` | Centralized secrets access |
| `security/cron_auth.py` | Legacy CRON_SECRET (deprecated) |
| `scripts/run_signed_task.py` | CLI tool for calling signed endpoints |
