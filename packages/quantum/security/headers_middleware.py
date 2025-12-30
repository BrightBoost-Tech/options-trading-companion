import os
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send
from fastapi import Request

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        self.app_env = os.getenv("APP_ENV", "development")

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # 🛡️ Sentinel: Add standard security headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 🛡️ Sentinel: Content Security Policy (CSP)
        # We start with a relatively permissive policy for API compatibility but restrict object-src and base-uri.
        # In a real frontend-serving app, we'd be stricter, but for an API, this prevents it from being used in XSS chains.
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self';"

        # 🛡️ Sentinel: Permissions Policy
        # Disable powerful features that the API definitely doesn't need to use.
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=(), payment=(), usb=()"

        # 🛡️ Sentinel: HSTS only for non-development environments to avoid localhost issues
        if self.app_env != "development":
            # 1 year = 31536000 seconds
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        return response
