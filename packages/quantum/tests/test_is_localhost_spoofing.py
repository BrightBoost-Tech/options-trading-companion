import pytest
from fastapi import Request
from packages.quantum.security import is_localhost

# Mock classes
class MockClient:
    def __init__(self, host):
        self.host = host

class MockRequest:
    def __init__(self, client_host, headers):
        self.client = MockClient(client_host)
        self.headers = headers

def test_is_localhost_spoofing_attempt():
    """
    Simulate an attacker trying to spoof localhost via X-Forwarded-For.

    Attacker IP: 6.6.6.6
    Attacker sends: "X-Forwarded-For: 127.0.0.1"
    Trusted Proxy (Next.js) sees connection from 6.6.6.6 and appends it.
    Final Header: "127.0.0.1, 6.6.6.6"

    The backend sees the request coming from the Proxy (127.0.0.1).
    It checks X-Forwarded-For.

    Vulnerable logic: Checks first IP ("127.0.0.1") -> Returns True (INSECURE)
    Secure logic: Checks last IP ("6.6.6.6") -> Returns False (SECURE)
    """

    # Header as received by backend from proxy
    headers = {"X-Forwarded-For": "127.0.0.1, 6.6.6.6"}

    # Request comes from local proxy
    req = MockRequest(client_host="127.0.0.1", headers=headers)

    # Assert that it is NOT considered localhost
    assert is_localhost(req) is False, "Security Vulnerability: is_localhost allowed spoofed IP!"

def test_is_localhost_valid_proxied():
    """
    Simulate a valid localhost request proxied through Next.js.

    User IP: 127.0.0.1 (Local developer)
    Next.js appends 127.0.0.1.
    Final Header: "127.0.0.1" (or just one entry if no prior header)
    """
    headers = {"X-Forwarded-For": "127.0.0.1"}
    req = MockRequest(client_host="127.0.0.1", headers=headers)

    assert is_localhost(req) is True

def test_is_localhost_direct_connection():
    """
    Simulate a direct connection without X-Forwarded-For (e.g. running python api.py directly)
    """
    headers = {}
    req = MockRequest(client_host="127.0.0.1", headers=headers)

    assert is_localhost(req) is True

def test_is_localhost_remote_direct():
    """
    Simulate direct connection from remote IP (should fail)
    """
    headers = {}
    req = MockRequest(client_host="192.168.1.50", headers=headers)

    assert is_localhost(req) is False
