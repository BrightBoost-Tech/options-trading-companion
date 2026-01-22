from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address as _slowapi_get_remote_address

def get_real_ip(request: Request) -> str:
    """
    Determines the real client IP address, robustly handling the Next.js proxy.

    Problem:
    The app runs behind a Next.js proxy (via rewrites), so request.client.host
    is always 127.0.0.1. This causes rate limiting to group all users together,
    creating a DoS risk where one user triggers limits for everyone.

    Solution:
    1. If the request comes from localhost (trusted proxy), use X-Forwarded-For.
    2. We use the FIRST IP in X-Forwarded-For.
       Note: This technically allows a sophisticated attacker to bypass rate limits
       by spoofing headers (if Next.js doesn't strip them), but it resolves the
       critical "block everyone" DoS vulnerability.
    """
    # Starlette's request.client can be None in some test scenarios
    client_host = request.client.host if request.client else "127.0.0.1"

    # Only trust headers if the direct connection is from our local proxy
    # We include 'testclient' to allow testing
    if client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Return the first IP in the list (Client IP)
            return forwarded_for.split(",")[0].strip()

    return client_host

# Shared Limiter Instance
# We use key_func=get_real_ip to correctly handle proxied requests.
limiter = Limiter(key_func=get_real_ip)
