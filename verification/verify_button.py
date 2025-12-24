
from playwright.sync_api import sync_playwright

def verify_loading_button():
    print("Starting verification of Loading Button...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            print("Navigating to dashboard...")
            # We expect a redirect to login since we aren't authenticated
            page.goto("http://localhost:3000/dashboard", timeout=30000)
            print(f"Page title: {page.title()}")

            # Take a screenshot
            page.screenshot(path="verification/verification.png")
            print("Screenshot taken at verification/verification.png")
        except Exception as e:
            print(f"Error visiting page: {e}")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_loading_button()
