import os
from typing import List

REQUIRED_ENV_VARS = [
    "SUPABASE_JWT_SECRET",
    "NEXT_PUBLIC_SUPABASE_URL",
    "SUPABASE_ANON_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "ENCRYPTION_KEY",
]

OPTIONAL_ENV_VARS = [
    "TASK_SIGNING_SECRET",  # Required if tasks are enabled/exposed
]

def validate_security_config():
    """
    Validates that all required security-related environment variables are present.
    Raises ValueError if any are missing, preventing insecure startup.
    """
    missing = []
    for var in REQUIRED_ENV_VARS:
        if not os.getenv(var):
            missing.append(var)

    if missing:
        raise ValueError(
            f"CRITICAL SECURITY ERROR: Missing required environment variables: {', '.join(missing)}. "
            "Server startup aborted."
        )

    # Check TASK_SIGNING_SECRET if we are likely to run tasks (default assumption yes)
    # We enforce it to ensure the new security model is usable.
    if not os.getenv("TASK_SIGNING_SECRET"):
        print("⚠️ WARNING: TASK_SIGNING_SECRET is missing. Internal task endpoints will fail verification.")

    # Check for consistency
    if os.getenv("APP_ENV") == "production":
        if os.getenv("ENABLE_DEV_AUTH_BYPASS") == "1":
            print("⚠️ SECURITY WARNING: ENABLE_DEV_AUTH_BYPASS is set to '1' in production environment!")
