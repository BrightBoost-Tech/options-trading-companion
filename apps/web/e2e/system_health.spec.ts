
import { test, expect } from '@playwright/test';

// Mock response matching the new structure
const MOCK_HEALTH_RESPONSE = {
  status: "Data-Limited",
  provider_health: {
    polygon: {
      state: "OPEN",
      failures: 12,
      rate_limits: 5
    }
  },
  cache_stats: {
    total_entries: 1500,
    active_entries: 450
  },
  veto_rate_7d: 5.2,
  veto_rate_30d: 4.8,
  active_constraints: [
    { constraint: "min_liquidity", count: 15 }
  ],
  not_executable_pct: 1.2,
  partial_outcomes_pct: 0.5
};

// Mock response missing new fields (backwards compatibility/robustness)
const MOCK_LEGACY_RESPONSE = {
  status: "Normal",
  veto_rate_7d: 2.1,
  veto_rate_30d: 1.9,
  active_constraints: [],
  not_executable_pct: 0.0,
  partial_outcomes_pct: 0.0
};

test.describe('SystemHealthPanel', () => {
  test('renders full health metrics including provider status', async ({ page }) => {
    // Mock the API endpoint
    await page.route('**/system/health', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_HEALTH_RESPONSE)
      });
    });

    await page.goto('http://localhost:3000/dashboard');

    // Check for provider health visibility
    // The component renders "Polygon Breaker Open" when state is OPEN
    await expect(page.getByText('Provider Breaker Open')).toBeVisible();

    // The component renders "{rate_limits} RL / {failures} Err"
    // So for 5 rate limits, it renders "5 RL"
    await expect(page.getByText('5 RL')).toBeVisible();

    // Check cache stats
    // The component renders "{active} / {total}" inside a span
    // For 450 active and 1500 total, it renders "450 / 1500"
    await expect(page.getByText('450 / 1500')).toBeVisible();
  });

  test('renders safely with missing provider/cache fields', async ({ page }) => {
    await page.route('**/system/health', async route => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_LEGACY_RESPONSE)
      });
    });

    await page.goto('http://localhost:3000/dashboard');

    // Should still see basic metrics
    await expect(page.getByText('System Health')).toBeVisible();
    await expect(page.getByText('Veto Rate')).toBeVisible();

    // Should NOT crash or show broken UI
    // Checking that specific new elements are NOT present
    await expect(page.getByText('Polygon')).not.toBeVisible();
    await expect(page.getByText('Cache')).not.toBeVisible();
  });
});
