import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from packages.quantum.security.headers_middleware import SecurityHeadersMiddleware

def test_security_headers():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/")
    def read_root():
        return {"Hello": "World"}

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-XSS-Protection"] == "1; mode=block"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"

    # Check new headers
    assert "Content-Security-Policy" in response.headers
    assert response.headers["Content-Security-Policy"] == "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self';"

    assert "Permissions-Policy" in response.headers
    assert response.headers["Permissions-Policy"] == "geolocation=(), microphone=(), camera=(), payment=(), usb=()"

    # Check HSTS (should differ by env, but default in middleware is "development" if not set in os.environ)
    assert "Strict-Transport-Security" not in response.headers
