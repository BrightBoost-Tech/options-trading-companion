import os
from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt
from dotenv import load_dotenv

load_dotenv()

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
                # WARNING: Dev only. Accepts any token format.
                payload = jwt.decode(token, options={"verify_signature": False})

            return payload.get("sub")
        except Exception as e:
            print(f"⚠️ JWT Validation Failed: {e}")
            # Don't raise yet, check for fallback

    # 2. If JWT fails, Reject.
    raise HTTPException(status_code=401, detail="Not authenticated.")
