
import os
import requests
import time
import subprocess
import signal
import sys
import threading

def test_endpoints():
    base_url = "http://127.0.0.1:8000"

    print("\n--- Testing Auth Debug ---")
    # Use a valid UUID format for PostgreSQL compatibility
    test_uuid = "75ee12ad-b119-4f32-aeea-19b4ef55d587"
    headers = {"X-Test-Mode-User": test_uuid}
    try:
        resp = requests.get(f"{base_url}/__auth_debug", headers=headers)
        print(f"Status: {resp.status_code}")
        print(f"Body: {resp.json()}")

        if resp.status_code == 200:
             data = resp.json()
             if data.get("resolved_user_id") == test_uuid:
                 print("✅ User ID resolved correctly via Bypass")
             else:
                 print("❌ User ID mismatch")

             if data.get("is_localhost"):
                 print("✅ Localhost detected")
             else:
                 print("❌ Localhost NOT detected")
        else:
            print("❌ Debug endpoint failed")

    except Exception as e:
        print(f"❌ Exception: {e}")

    print("\n--- Testing Strategies Endpoint (requires valid Supabase client) ---")
    try:
        resp = requests.get(f"{base_url}/strategies", headers=headers)
        print(f"Status: {resp.status_code}")
        # We expect 200 OK with empty list if user works
        # If 500, then get_supabase_user_client failed to create context
        if resp.status_code == 200:
            print("✅ Strategies returned 200 OK")
            print(resp.json())
        elif resp.status_code == 500:
            print("❌ Strategies returned 500 Internal Server Error (Context Failed)")
            print(resp.text)
        else:
            print(f"⚠️ Strategies returned {resp.status_code}")
            print(resp.text)

    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_endpoints()
