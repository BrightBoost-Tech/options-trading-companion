from playwright.sync_api import sync_playwright

def verify_login_page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to login page
        try:
            page.goto("http://127.0.0.1:3000/login", timeout=30000)
            print("Navigated to login page")

            # Wait for content to load
            page.wait_for_selector("form")

            # Fill in dummy data
            page.fill("input[type='email']", "test@example.com")
            page.fill("input[type='password']", "password123")

            # Click sign in to trigger loading state (though it might fail fast without backend)
            # We mostly want to see the UI layout and components

            # Take a screenshot
            page.screenshot(path="verification/login_page.png")
            print("Screenshot saved to verification/login_page.png")

        except Exception as e:
            print(f"Error: {e}")
            # Take screenshot anyway if possible
            try:
                page.screenshot(path="verification/login_error.png")
            except:
                pass
        finally:
            browser.close()

if __name__ == "__main__":
    verify_login_page()
