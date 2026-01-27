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

if __name__ == "__main__":
    test_masking()
