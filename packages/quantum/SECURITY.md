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
- Legacy `CRON_SECRET` support during migration (gated by `ALLOW_LEGACY_CRON_SECRET=1`)

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
| `ALLOW_LEGACY_CRON_SECRET` | Allow legacy auth during migration: `1` or `0` |

### Legacy (Migration Period)
| Variable | Purpose |
|----------|---------|
| `CRON_SECRET` | Legacy task authentication (deprecated) |

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
- [ ] `ALLOW_LEGACY_CRON_SECRET` is `0` (after migration)
- [ ] `ADMIN_USER_IDS` contains only trusted users
- [ ] CORS origins are properly configured

### During Development
- [ ] Use `APP_ENV=development`
- [ ] Use `ENABLE_DEV_AUTH_BYPASS=1` only for local testing
- [ ] Use `X-Test-Mode-User` header for testing user-scoped endpoints

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
