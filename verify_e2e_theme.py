import socket
import time
from playwright.sync_api import sync_playwright

def wait_for_port(port, timeout=30):
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(('localhost', port))
            return True
        except (ConnectionRefusedError, socket.timeout):
            time.sleep(1)
    return False

if not wait_for_port(3000):
    print("Server failed to start")
    exit(1)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('http://localhost:3000/dashboard')
    page.wait_for_selector('button[aria-label="Switch to light mode"]')
    print("Theme toggle button found successfully with new dynamic aria-label.")
    browser.close()
