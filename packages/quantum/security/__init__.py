import os
from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt
from dotenv import load_dotenv
from pathlib import Path
from supabase import create_client, Client
from packages.quantum.security.secrets_provider import SecretsProvider

# Load env from packages/quantum/.env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Initialize Secrets
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()

# --- Encryption Setup ---
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
# Validation handled by security.config.validate_security_config() at startup

if ENCRYPTION_KEY:
    cipher_suite = Fernet(ENCRYPTION_KEY)
else:
    # This branch should rarely be hit if validate_security_config is called,
    # but strictly speaking we might be imported before that check runs in some test scenarios.
    cipher_suite = None

def encrypt_token(token: str) -> str:
    if not cipher_suite:
        raise ValueError("Encryption unavailable: ENCRYPTION_KEY missing")
    return cipher_suite.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    if not cipher_suite:
        raise ValueError("Encryption unavailable: ENCRYPTION_KEY missing")
    return cipher_suite.decrypt(encrypted_token.encode()).decode()

# --- JWT Auth Setup ---
security = HTTPBearer(auto_error=False)
# SUPABASE_JWT_SECRET is loaded dynamically to support testing/env changes
# But validation ensures it exists at startup in production.

def is_localhost(request: Request) -> bool:
    """
    Check if the request originated from localhost.
    Robustly handles requests proxied via Next.js (local rewrites).

    If the direct connection is localhost, we MUST check X-Forwarded-For
    to ensure the original client is also localhost.
    """
    client_host = request.client.host if request.client else ""

    # Check direct connection
    if client_host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        return False

    # If direct connection is local, check for proxy headers
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Get the LAST IP (the one that connected to our trusted proxy)
        # Prevents spoofing where attacker injects IP at start of list
        real_ip = forwarded_for.split(",")[-1].strip()
        return real_ip in ("127.0.0.1", "::1", "localhost", "testclient")

    return True

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
):
    """
    1. Tries to validate a real Supabase JWT (Strict Mode).
    2. Fallback: Dev Header X-Test-Mode-User (Only if enabled, dev env, and localhost).
    """

    # 1. Try JWT Auth
    if credentials:
        token = credentials.credentials

        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        if not jwt_secret:
             # Should be caught by config validation, but defensive coding:
             print("🚨 CRITICAL: Missing SUPABASE_JWT_SECRET in get_current_user!")
             raise HTTPException(status_code=500, detail="Server Configuration Error")

        try:
            # STRICT VERIFICATION
            payload = jwt.decode(
                token,
                jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"require": ["sub", "aud", "exp"]}
            )
            return payload.get("sub")
        except jwt.ExpiredSignatureError:
             raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
             print(f"⚠️ JWT Validation Failed: {e}")
             # Proceed to check fallback (dev mode) only if verified fail?
             # No, if token provided but invalid, we usually reject.
             # But if dev mode is active, user might be trying to switch modes.
             # We will fall through.
             pass

    # 2. Dev Mode Fallback
    # CONDITIONS:
    # - APP_ENV != production
    # - ENABLE_DEV_AUTH_BYPASS == "1"
    # - Origin is Localhost

    app_env = os.getenv("APP_ENV", "development")
    dev_bypass = os.getenv("ENABLE_DEV_AUTH_BYPASS", "0") == "1"

    if app_env != "production" and dev_bypass:
        if is_localhost(request):
            test_user_header = request.headers.get("X-Test-Mode-User")
            if test_user_header:
                # print(f"🔓 Using Dev Header Auth: {test_user_header}")
                return test_user_header

    # 3. Reject
    raise HTTPException(status_code=401, detail="Not authenticated")

def get_current_user_id(user_id: str = Depends(get_current_user)):
    return user_id

# RLS-Aware Client Dependency
def get_supabase_user_client(
    user_id: str = Depends(get_current_user),
    request: Request = None
) -> Client:
    # Check if we have a real Bearer token
    auth_header = request.headers.get("Authorization")
    is_bearer = auth_header and auth_header.startswith("Bearer ")

    if is_bearer:
        token = auth_header.split(" ")[1]
        if supa_secrets.url and supa_secrets.anon_key:
            client = create_client(supa_secrets.url, supa_secrets.anon_key)
            client.postgrest.auth(token)
            return client

    # Bypass Check: Must check bypass explicitly and verify localhost again for safety
    if os.getenv("APP_ENV") != "production" and os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1":
        # If user_id matches header AND we are on localhost
        if request.headers.get("X-Test-Mode-User") == user_id:
             if is_localhost(request):
                 if supa_secrets.jwt_secret:
                     payload = {
                         "sub": user_id,
                         "aud": "authenticated",
                         "role": "authenticated",
                         "exp": 9999999999
                     }
                     fake_token = jwt.encode(payload, supa_secrets.jwt_secret, algorithm="HS256")
                     client = create_client(supa_secrets.url, supa_secrets.anon_key)
                     client.postgrest.auth(fake_token)
                     return client

    # 🛡️ Sentinel: Safe default failure
    # Never fall back to admin client if user context was expected but not established.
    raise HTTPException(status_code=500, detail="Secure Database Context Unavailable")

SENSITIVE_FIELDS = {
    "access_token",
    "public_token",
    "processor_token",
    "item_id",
    "account_number",
    "routing_number",
    "password",
    "secret",
    "api_key",
    "client_secret",
    "refresh_token",
    "private_key",
    "token",
    "secret_key",
    "verification_token",
    "connection_string",
}

def is_sensitive_field(field_name: str) -> bool:
    """Check if a field name is sensitive (case-insensitive)."""
    return field_name.lower() in SENSITIVE_FIELDS

# Kept for backward compatibility if imported elsewhere (though strictly internal)
is_sensitive_token_field = is_sensitive_field

def redact_sensitive_fields(obj):
    if isinstance(obj, dict):
        return {
            k: ("****" if is_sensitive_field(str(k)) else redact_sensitive_fields(v))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [redact_sensitive_fields(v) for v in obj]
    else:
        return obj
