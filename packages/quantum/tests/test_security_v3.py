import os
import pytest
from fastapi import Request, HTTPException
from packages.quantum.security import get_current_user
import jwt

# Mocks
class MockRequest:
    def __init__(self, headers=None, client_host="127.0.0.1"):
        self.headers = headers or {}
        self.client = type("Client", (), {"host": client_host})

class MockCredentials:
    def __init__(self, token):
        self.credentials = token

@pytest.mark.asyncio
async def test_get_current_user_valid_jwt(monkeypatch):
    secret = "my_super_secret_jwt_key"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)

    token = jwt.encode({"sub": "user_123", "aud": "authenticated", "exp": 9999999999}, secret, algorithm="HS256")
    req = MockRequest()
    creds = MockCredentials(token)

    user = await get_current_user(req, creds)
    assert user == "user_123"

@pytest.mark.asyncio
async def test_get_current_user_invalid_signature(monkeypatch):
    secret = "correct_secret"
    monkeypatch.setenv("SUPABASE_JWT_SECRET", secret)

    # Sign with wrong secret
    token = jwt.encode({"sub": "user_123", "aud": "authenticated", "exp": 9999999999}, "wrong_secret", algorithm="HS256")
    req = MockRequest()
    creds = MockCredentials(token)

    with pytest.raises(HTTPException) as excinfo:
        await get_current_user(req, creds)
    assert excinfo.value.status_code == 401

@pytest.mark.asyncio
async def test_dev_bypass_success(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret") # Needed to avoid 500

    req = MockRequest(headers={"X-Test-Mode-User": "dev_user"}, client_host="127.0.0.1")
    user = await get_current_user(req, None)
    assert user == "dev_user"

@pytest.mark.asyncio
async def test_dev_bypass_fail_remote_ip(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")

    # Remote IP
    req = MockRequest(headers={"X-Test-Mode-User": "dev_user"}, client_host="192.168.1.50")

    with pytest.raises(HTTPException) as excinfo:
        await get_current_user(req, None)
    assert excinfo.value.status_code == 401

@pytest.mark.asyncio
async def test_dev_bypass_fail_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENABLE_DEV_AUTH_BYPASS", "1")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "secret")

    req = MockRequest(headers={"X-Test-Mode-User": "dev_user"}, client_host="127.0.0.1")

    with pytest.raises(HTTPException) as excinfo:
        await get_current_user(req, None)
    assert excinfo.value.status_code == 401

@pytest.mark.asyncio
async def test_missing_jwt_secret_fails_securely(monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    req = MockRequest()
    creds = MockCredentials("some.token.here")

    with pytest.raises(HTTPException) as excinfo:
        await get_current_user(req, creds)
    # Expect 500 config error
    assert excinfo.value.status_code == 500
