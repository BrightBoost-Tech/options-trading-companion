import pytest
import jwt
import os
from fastapi import Request, HTTPException
from packages.quantum.security.admin_auth import verify_admin_access

# Mock Request
class MockRequest:
    def __init__(self):
        self.url = type('obj', (object,), {'path': '/jobs/test'})
        self.method = "POST"
        self.client = type('obj', (object,), {'host': '127.0.0.1'})

@pytest.mark.asyncio
async def test_admin_bypass_with_forged_token_is_prevented():
    # 1. Simulate Dev Bypass Success
    user_id = "test-user-123"

    # 2. Forge a JWT with role="admin" but WRONG signature
    payload = {
        "sub": user_id,
        "role": "admin",
        "exp": 9999999999
    }
    fake_secret = "attacker-secret-key"
    forged_token = jwt.encode(payload, fake_secret, algorithm="HS256")

    auth_header = f"Bearer {forged_token}"

    mock_request = MockRequest()

    # 3. Call verify_admin_access
    # It SHOULD raise HTTPException(403) because the token signature is invalid.

    print("\nAttempting admin access with forged token...")

    with pytest.raises(HTTPException) as excinfo:
        await verify_admin_access(
            request=mock_request,
            user_id=user_id,
            authorization=auth_header
        )

    assert excinfo.value.status_code == 403
    assert "Admin access required" in excinfo.value.detail
    print("✅ Security Check Passed: Forged token was rejected (403 Forbidden).")
