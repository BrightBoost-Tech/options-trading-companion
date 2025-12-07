import pytest
from unittest.mock import MagicMock, patch
from packages.quantum.plaid_service import fetch_and_normalize_holdings

# Minimal mock for Holding to avoid importing complex models if they have deps
class MockHolding:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)

def test_fetch_and_normalize_holdings_cost_basis():
    # Mock Plaid response
    mock_item = {
        'security_id': 'sec123',
        'quantity': 46.425907,
        'cost_basis': 282.13,
        'institution_price': 100.0,
        'iso_currency_code': 'USD',
        'account_id': 'acc123'
    }
    mock_security = {
        'security_id': 'sec123',
        'ticker_symbol': 'VTSI',
        'name': 'VTSAX',
        'close_price': 100.0
    }

    with patch('packages.quantum.plaid_service.client') as mock_client:
        mock_response = {
            'holdings': [mock_item],
            'securities': [mock_security]
        }
        mock_client.investments_holdings_get.return_value = MagicMock(
            get=lambda k, d=None: mock_response.get(k, d)
        )

        # Mock dependencies to isolate logic
        with patch('packages.quantum.plaid_service.get_polygon_price', return_value=6.0):
            with patch('packages.quantum.plaid_service.PLAID_SECRET', "dummy_secret"):
                with patch('packages.quantum.plaid_service.PLAID_CLIENT_ID', "dummy_id"):
                    # Mock Holding constructor/validation if needed, or rely on real one if simple
                    # Here we rely on real Holding model but patch dependencies

                    holdings = fetch_and_normalize_holdings("dummy_token")

                    assert len(holdings) == 1
                    h = holdings[0]

                    # Expected per-share cost: 282.13 / 46.425907 ≈ 6.07699
                    expected_cost = 282.13 / 46.425907
                    assert abs(h.cost_basis - expected_cost) < 0.0001
                    assert h.quantity == 46.425907
