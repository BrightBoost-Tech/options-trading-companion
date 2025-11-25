import os
from cryptography.fernet import Fernet
from fastapi import HTTPException, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
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
security = HTTPBearer()
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") # Get this from Supabase Dashboard -> API -> JWT Settings

def get_current_user(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Validates the Supabase JWT sent by the frontend.
    Returns the user_id (sub) from the token.
    """
    try:
        # In production, verifying the signature is crucial.
        # For Supabase, we use the project JWT secret.
        if not SUPABASE_JWT_SECRET:
             # Fallback for dev if secret isn't set (NOT RECOMMENDED FOR PROD)
             # Note: This is dangerous, but following user snippet.
             payload = jwt.decode(credentials.credentials, options={"verify_signature": False})
        else:
             payload = jwt.decode(credentials.credentials, SUPABASE_JWT_SECRET, algorithms=["HS256"], audience="authenticated")

        return payload.get("sub") # The UUID
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid authentication credentials")
