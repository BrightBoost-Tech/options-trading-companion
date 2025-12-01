from playwright.sync_api import Page, expect, sync_playwright, Route
import time

def verify_trade_suggestion_card(page: Page):
    # Intercept the request for morning suggestions and return a mock response with NULL values
    # to trigger the potential crash or verify the fix.

    def handle_suggestions(route: Route):
        print(f"Intercepting {route.request.url}")
        route.fulfill(
            status=200,
            content_type="application/json",
            body="""
            {
                "suggestions": [
                    {
                        "id": "mock-suggestion-1",
                        "symbol": "SPY",
                        "strategy": "Credit Spread",
                        "type": "option",
                        "score": 85,
                        "badges": ["High Prob", "Liquid"],
                        "rationale": "Testing null values in TradeSuggestionCard",
                        "metrics": {
                            "expected_value": null,
                            "probability_of_profit": 75.5
                        },
                        "price": null,
                        "strike_price": null,
                        "entry_price": null,
                        "underlying_price": 450.0,
                        "width": 5,
                        "window": "morning_limit",
                        "order_json": {
                            "limit_price": null,
                            "quantity": 10
                        },
                        "sizing_metadata": {
                            "stop_loss": null
                        },
                        "ev": null
                    }
                ]
            }
            """
        )

    # Intercept any call to suggestions endpoint
    page.route("**/suggestions?window=morning_limit", handle_suggestions)

    # Go to the dashboard
    page.goto("http://localhost:3000/dashboard")

    # Wait for the page to load
    time.sleep(5)

    # Scroll down to reveal the SuggestionTabs
    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    time.sleep(2)

    # Check if the mock suggestion is rendered
    # We look for "SPY" and "Testing null values"
    try:
        expect(page.get_by_text("Testing null values in TradeSuggestionCard")).to_be_visible(timeout=5000)
        print("Mock suggestion rendered successfully!")

        # Verify that null values are rendered as "N/A" or safe fallbacks
        # "Limit Price: $N/A" (or -- depending on implementation)
        # In renderMorningContent: Limit Price: ${typeof order.limit_price === 'number' ? safeFixed(order.limit_price) : 'N/A'}

        expect(page.get_by_text("Limit Price: $N/A")).to_be_visible()
        print("Verified safe rendering of null limit price.")

        # EV is null, so the badge "EV: ..." should NOT be visible?
        # In render:
        # {typeof evValue === 'number' && ( ... Badge ... )}
        # So "EV:" badge should NOT appear for this card.
        # But wait, there might be other badges.

        # Taking a screenshot to confirm
        page.screenshot(path="verification/dashboard_with_nulls.png")
        print("Screenshot saved to verification/dashboard_with_nulls.png")

    except Exception as e:
        print(f"Verification failed: {e}")
        page.screenshot(path="verification/error_nulls.png")
        raise e

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_trade_suggestion_card(page)
        except Exception as e:
            print(f"Verification failed: {e}")
        finally:
            browser.close()
