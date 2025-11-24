from playwright.sync_api import sync_playwright, expect
import time

def verify_dashboard():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Mock the portfolio snapshot endpoint
        page.route("**/portfolio/snapshot", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body="""{
                "user_id": "test-user-123",
                "created_at": "2023-10-27T10:00:00.000Z",
                "snapshot_type": "on-sync",
                "holdings": [
                    {
                        "symbol": "AMZN251219C00100000",
                        "quantity": 1,
                        "cost_basis": 500.0,
                        "current_price": 550.0,
                        "source": "plaid",
                        "currency": "USD"
                    },
                    {
                        "symbol": "AAPL",
                        "quantity": 10,
                        "cost_basis": 150.0,
                        "current_price": 175.0,
                        "source": "plaid",
                        "currency": "USD"
                    },
                    {
                        "symbol": "CUR:USD",
                        "quantity": 1000.0,
                        "cost_basis": 1.0,
                        "current_price": 1.0,
                        "source": "plaid",
                        "currency": "USD"
                    }
                ],
                "risk_metrics": {},
                "optimizer_status": "ready"
            }"""
        ))

        # Mock other endpoints to prevent errors
        page.route("**/scout/weekly", lambda route: route.fulfill(status=200, body='{"top_picks": []}'))
        page.route("**/journal/stats", lambda route: route.fulfill(status=200, body='{"stats": {}, "patterns": {}, "rules": []}'))

        try:
            print("Navigating to dashboard...")
            # Use 3002
            page.goto("http://localhost:3002/dashboard")

            # Wait for the table to appear
            page.wait_for_selector("table", timeout=10000)

            # Check for headers
            print("Checking for headers...")
            expect(page.get_by_text("🎯 Option Plays")).to_be_visible()
            expect(page.get_by_text("📈 Long Term Holds")).to_be_visible()
            expect(page.get_by_text("💵 CASH")).to_be_visible()

            print("Taking screenshot...")
            page.screenshot(path="verification/dashboard_grouped.png", full_page=True)
            print("Screenshot saved to verification/dashboard_grouped.png")

        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="verification/error.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_dashboard()
