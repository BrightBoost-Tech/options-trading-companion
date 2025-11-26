# packages/quantum/database.py
import os
from supabase import create_client, Client
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get Supabase credentials from environment
url: str = os.environ.get("NEXT_PUBLIC_SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

# Basic validation
if not url or not key:
    print("❌ FATAL: Supabase URL and Key must be set in the environment.")
    # In a real app, you might raise an exception or handle this more gracefully
    # For now, we'll allow it to proceed but Supabase calls will fail.
    supabase = None
else:
    try:
        supabase: Client = create_client(url, key)
        print("✅ Supabase client initialized successfully.")
    except Exception as e:
        print(f"❌ FATAL: Failed to initialize Supabase client: {e}")
        supabase = None
