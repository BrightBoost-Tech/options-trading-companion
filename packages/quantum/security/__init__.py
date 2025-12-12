import os
from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, Request, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt
from dotenv import load_dotenv
from pathlib import Path

# Load env from packages/quantum/.env
env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# --- Encryption Setup ---
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    # We raise an error, but for the sake of not crashing immediately if just importing,
    # we might want to be careful. However, the requirement is strict.
    # To allow import without crashing if env is missing (e.g. during build), we can check at runtime,
    # but the snippet provided by user raises ValueError immediately.
    # I will stick to the user's snippet.
    # NOTE: If this crashes the app on start, it's expected behavior for missing config.
    pass

if ENCRYPTION_KEY:
    cipher_suite = Fernet(ENCRYPTION_KEY)
else:
    # Fallback to prevent import error, but functions will fail.
    # Actually, the user code said: raise ValueError("ENCRYPTION_KEY missing from .env")
    # I will respect that, but I'll add a check to see if we are running in a context where we can fail.
    # If I just raise, and I don't have the key in my .env, I can't verifying anything.
    # I'll create a dummy key if missing just for the purpose of not crashing my own exploration if I were to run it.
    # But since I am writing the file for the user, I must include the check.
    # I will assume the user has the key or will generate one.
    raise ValueError("ENCRYPTION_KEY missing from .env")

def encrypt_token(token: str) -> str:
    return cipher_suite.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token: str) -> str:
    return cipher_suite.decrypt(encrypted_token.encode()).decode()

# --- JWT Auth Setup ---
# Use auto_error=False so we can handle missing tokens manually (for Dev fallback)
security = HTTPBearer(auto_error=False)
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security)
):
    """
    1. Tries to validate a real Supabase JWT.
    2. If missing, and in DEV mode, accepts X-Test-Mode-User header.
    """
    # 1. Try JWT Auth (Production Standard)
    if credentials:
        try:
            token = credentials.credentials
            # If secret is set, verify signature. If not (local dev), decode unverified.
            if SUPABASE_JWT_SECRET:
                payload = jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")
            else:
                # 🛡️ SECURITY FIX: Prevent insecure JWT decoding in Production
                if os.getenv("APP_ENV", "development") == "production":
                     print("🚨 CRITICAL: Attempted to decode JWT without secret in Production!")
                     raise HTTPException(status_code=500, detail="Server Configuration Error: Missing JWT Secret in Production")

                # WARNING: Dev only. Accepts any token format.
                payload = jwt.decode(token, options={"verify_signature": False})

            return payload.get("sub")
        except Exception as e:
            print(f"⚠️ JWT Validation Failed: {e}")
            # Don't raise yet, check for fallback.
            # However, if we raised 500 above, it will be caught here and logged.
            # We should re-raise the 500 if it was a config error.
            if isinstance(e, HTTPException) and e.status_code == 500:
                raise e

    # 2. Dev Mode Fallback (The "Test User" Header)
    # Only allow this if we are NOT in production
    if os.getenv("APP_ENV", "development") != "production":
        test_user_header = request.headers.get("X-Test-Mode-User")
        if test_user_header:
            # print(f"🔓 Using Dev Header Auth: {test_user_header}")
            return test_user_header

    # 3. If both fail, Reject.
    raise HTTPException(status_code=401, detail="Not authenticated. Log in or use Dev Header.")

def get_current_user_id(user_id: str = Depends(get_current_user)):
    """
    Dependency that returns the user ID from the JWT token.
    This can be injected into route handlers.
    """
    return user_id

SENSITIVE_TOKEN_FIELDS = {
    "access_token",
    "public_token",
    "processor_token",
    "item_id",
    "account_number",
    "routing_number",
}

def is_sensitive_token_field(field_name: str) -> bool:
    return field_name in SENSITIVE_TOKEN_FIELDS

def redact_sensitive_fields(obj):
    """
    Recursively walk dict/list structures and redact sensitive fields.
    Returns a new sanitized structure.
    """
    if isinstance(obj, dict):
        return {
            k: ("****" if is_sensitive_token_field(k) else redact_sensitive_fields(v))
            for k, v in obj.items()
        }
    elif isinstance(obj, list):
        return [redact_sensitive_fields(v) for v in obj]
    else:
        return obj
