import pytest
from packages.quantum.security import redact_sensitive_fields, is_sensitive_field

def test_redaction_basic():
    data = {
        "username": "user",
        "password": "supersecretpassword",
        "email": "user@example.com"
    }
    redacted = redact_sensitive_fields(data)
    assert redacted["username"] == "user"
    assert redacted["password"] == "****"
    assert redacted["email"] == "user@example.com"

def test_redaction_nested():
    data = {
        "user": {
            "profile": {
                "api_key": "123456",
                "name": "John"
            },
            "credentials": {
                "password": "secret"
            }
        }
    }
    redacted = redact_sensitive_fields(data)
    assert redacted["user"]["profile"]["api_key"] == "****"
    assert redacted["user"]["profile"]["name"] == "John"
    assert redacted["user"]["credentials"]["password"] == "****"

def test_redaction_case_insensitive():
    data = {
        "API_KEY": "secret123",
        "Access_Token": "token123",
        "Password": "pass"
    }
    redacted = redact_sensitive_fields(data)
    assert redacted["API_KEY"] == "****"
    assert redacted["Access_Token"] == "****"
    assert redacted["Password"] == "****"

def test_redaction_list():
    data = [
        {"id": 1, "token": "sometoken"},
        {"id": 2, "secret": "shhh"}
    ]
    redacted = redact_sensitive_fields(data)
    assert redacted[0]["token"] == "****"
    assert redacted[0]["id"] == 1
    assert redacted[1]["secret"] == "****"
    assert redacted[1]["id"] == 2

def test_redaction_new_fields():
    # Test fields added in the enhancement
    fields = [
        "refresh_token", "private_key", "secret_key", "verification_token", "connection_string"
    ]
    data = {field: "value" for field in fields}
    redacted = redact_sensitive_fields(data)
    for field in fields:
        assert redacted[field] == "****"

def test_is_sensitive_field():
    assert is_sensitive_field("password")
    assert is_sensitive_field("PASSWORD")
    assert is_sensitive_field("Access_Token")
    assert not is_sensitive_field("username")
    assert not is_sensitive_field("email")

if __name__ == "__main__":
    pytest.main([__file__])
