from packages.quantum.core.rate_limiter import get_real_ip

# Mock Request object for Starlette/FastAPI
class MockClient:
    def __init__(self, host):
        self.host = host

class MockRequest:
    def __init__(self, client_host, headers):
        self.client = MockClient(client_host)
        self.headers = headers

def test_get_real_ip_spoofing():
    """
    Simulates a request coming from localhost (e.g. Next.js proxy)
    where the attacker has injected a spoofed IP in X-Forwarded-For.

    Attacker sends: X-Forwarded-For: 1.2.3.4 (spoofed)
    Connection from: 5.6.7.8 (real)
    Next.js appends real IP.
    Result header: "1.2.3.4, 5.6.7.8"
    """

    # Header format: "client, proxy1, proxy2"
    # In this case: "spoofed, real"
    headers = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}

    # Request appears to come from localhost (the proxy)
    req = MockRequest(client_host="127.0.0.1", headers=headers)

    ip = get_real_ip(req)
    print(f"Extracted IP: {ip}")

    # The secure implementation should return the LAST IP (5.6.7.8), which is the one Next.js saw.
    # The insecure implementation returns the FIRST IP (1.2.3.4), allowing spoofing.
    assert ip == "5.6.7.8", f"Expected real IP 5.6.7.8 but got {ip}"

def test_get_real_ip_no_spoofing():
    """
    Simulates a normal request without spoofing.
    Header: "5.6.7.8" (added by Next.js)
    """
    headers = {"X-Forwarded-For": "5.6.7.8"}
    req = MockRequest(client_host="127.0.0.1", headers=headers)

    ip = get_real_ip(req)
    assert ip == "5.6.7.8"

def test_get_real_ip_direct_access():
    """
    Simulates a request NOT from localhost (e.g. dev mode or misconfig).
    Should ignore headers and return client host.
    """
    headers = {"X-Forwarded-For": "1.2.3.4"}
    req = MockRequest(client_host="192.168.1.5", headers=headers)

    ip = get_real_ip(req)
    assert ip == "192.168.1.5"
