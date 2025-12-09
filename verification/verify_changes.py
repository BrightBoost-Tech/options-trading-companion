import time
from playwright.sync_api import sync_playwright

def verify_frontend():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            print("Navigating to Paper Trading page...")
            page.goto("http://127.0.0.1:3000/paper", timeout=60000)

            # Wait a bit
            time.sleep(5)

            # Check if redirected to login
            if "login" in page.url:
                print("Redirected to login. Attempting to bypass or log in.")
                # We can't easily login without a real user in the local supabase instance.
                # However, the frontend might allow access if we mock the session?
                # Or we can just verify the Login page loads, but that doesn't verify my changes.
                # My changes are on /paper and /dashboard (Protected).

                # If the app redirects to login, it means there's no session.
                # I'll try to set a fake local storage or cookie if that helps, but Supabase usually checks network.
                pass

            page.screenshot(path="verification/paper_page.png")
            print(f"Screenshot saved to verification/paper_page.png (URL: {page.url})")

            # Try to find Reset button
            try:
                # Wait for button
                reset_btn = page.wait_for_selector('button:has-text("Reset Account")', timeout=5000)
                if reset_btn:
                    print("Found Reset button. Clicking...")
                    reset_btn.click()
                    time.sleep(2)
                    page.screenshot(path="verification/reset_modal.png")
                    print("Screenshot saved to verification/reset_modal.png")
                else:
                    print("Reset button selector found but element falsy?")
            except Exception as e:
                print(f"Reset button not found or not clickable: {e}")

            print("Navigating to Dashboard...")
            page.goto("http://127.0.0.1:3000/dashboard", timeout=60000)
            time.sleep(5)
            page.screenshot(path="verification/dashboard_page.png")
            print(f"Screenshot saved to verification/dashboard_page.png (URL: {page.url})")

        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="verification/error.png")

        finally:
            browser.close()

if __name__ == "__main__":
    verify_frontend()
