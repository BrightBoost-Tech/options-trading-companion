
import os
from playwright.sync_api import sync_playwright

def verify_dark_mode():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Create context with dark mode color scheme preference
        context = browser.new_context(color_scheme='dark')
        page = context.new_page()

        # Try to navigate to the root page
        try:
            page.goto("http://localhost:3000/", timeout=10000)
            page.wait_for_load_state("networkidle")
        except Exception as e:
            print(f"Navigation error: {e}")
            # Continue anyway to screenshot what we have (maybe an error page)

        # Force dark mode class on html just in case system preference isn't picked up
        # Shadcn typically uses 'dark' class on HTML or body.
        page.evaluate("document.documentElement.classList.add('dark')")

        # Take a screenshot of the login page (likely)
        page.screenshot(path="verification/dashboard_dark_mode.png", full_page=True)

        # If there are specific elements we expect to be dark, we could check styles,
        # but visual verification is requested.

        browser.close()

if __name__ == "__main__":
    verify_dark_mode()
