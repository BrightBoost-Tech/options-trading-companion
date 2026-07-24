from packages.quantum.security.masking import sanitize_message

def test_masking():
    cases = [
        (
            "Connection failed to postgres://user:SUPER_SECRET_PASSWORD@db.host:5432/db",
            "Connection failed to postgres://user:****@db.host:5432/db"
        ),
        (
            "Invalid key sk-proj-1234567890abcdef1234567890",
            "Invalid key sk-proj****"
        ),
        (
            "Token eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig expired",
            "Token eyJhbGciOiJIU**** expired"
        ),
        (
            "AWS Error AKIAIOSFODNN7EXAMPLE",
            "AWS Error AKIAIOSF****"
        )
    ]

    for original, expected in cases:
        sanitized = sanitize_message(original)
        assert sanitized == expected, f"Failed: {original}\nExpected: {expected}\nGot: {sanitized}"


def test_masking_generic_url_credentials():
    """Generic scheme://user:password@host masking (Lane B redaction fix): an
    rq/redis enqueue error embeds the full broker URL — the scheme-specific
    postgres patterns did NOT catch redis/rediss/amqp/mongodb creds."""
    cases = [
        # The exact reviewer specimen.
        (
            "Error 111 connecting to redis://default:AbCdEf123456TOKEN@monorail.proxy.rlwy.net:12345",
            "Error 111 connecting to redis://default:****@monorail.proxy.rlwy.net:12345",
        ),
        (
            "TLS broker rediss://default:s3cr3tPassTOKEN@cache.host:6380 unreachable",
            "TLS broker rediss://default:****@cache.host:6380 unreachable",
        ),
        (
            "amqp://guest:guestpw@rabbit:5672 refused",
            "amqp://guest:****@rabbit:5672 refused",
        ),
        (
            "mongodb://admin:MyMongoPw@mongo.host:27017/db",
            "mongodb://admin:****@mongo.host:27017/db",
        ),
        # No credential (no user:pass@) → untouched.
        (
            "GET https://api.polygon.io/v3/reference/options ok",
            "GET https://api.polygon.io/v3/reference/options ok",
        ),
    ]
    for original, expected in cases:
        sanitized = sanitize_message(original)
        assert sanitized == expected, (
            f"Failed: {original}\nExpected: {expected}\nGot: {sanitized}"
        )


def test_masking_url_credential_at_symbol_past_truncation():
    """The password is fully masked even when the credential's '@' sits far past
    a naive truncation point — provided redaction runs on the FULL string first
    (the redact-then-truncate contract the observer seam relies on)."""
    long_pad = "x" * 400
    original = f"rq enqueue failed {long_pad} redis://default:TOKENSECRET@h:6379"
    sanitized = sanitize_message(original)
    assert "TOKENSECRET" not in sanitized
    assert "redis://default:****@h:6379" in sanitized


if __name__ == "__main__":
    test_masking()
    test_masking_generic_url_credentials()
    test_masking_url_credential_at_symbol_past_truncation()
