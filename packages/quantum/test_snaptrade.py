import unittest
from unittest.mock import MagicMock, patch
from snaptrade_client import SnapTradeClient

class TestSnapTradeClient(unittest.TestCase):

    def setUp(self):
        self.client = SnapTradeClient()
        # Force mock mode off to test logic, but we will mock requests
        self.client.is_mock = False
        self.client.client_id = "TEST_CLIENT_ID"
        self.client.consumer_key = "TEST_CONSUMER_KEY"

    @patch('requests.post')
    def test_register_user(self, mock_post):
        mock_response = MagicMock()
        mock_response.json.return_value = {"userId": "snap_123", "userSecret": "secret_123"}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        result = self.client.register_user("internal_user_1")
        self.assertEqual(result["userId"], "snap_123")
        mock_post.assert_called_once()

    @patch('requests.get')
    def test_get_accounts(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = [{"id": "acc_1", "name": "Robinhood"}]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        result = self.client.get_accounts("snap_123", "secret_123")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "acc_1")

    def test_normalize_holdings(self):
        snap_holdings = [
            {
                "symbol": {"symbol": "AAPL", "description": "Apple Inc"},
                "units": 10,
                "price": 150.0,
                "average_purchase_price": 100.0
            }
        ]
        # Test with explicit institution name
        normalized = self.client.normalize_holdings(snap_holdings, "acc_1", account_name="Robinhood")
        self.assertEqual(len(normalized), 1)
        h = normalized[0]
        self.assertEqual(h.symbol, "AAPL")
        self.assertEqual(h.quantity, 10.0)
        self.assertEqual(h.source, "snaptrade")
        self.assertEqual(h.account_id, "acc_1")
        self.assertEqual(h.institution_name, "Robinhood")

        # Test fallback institution name
        normalized_default = self.client.normalize_holdings(snap_holdings, "acc_1")
        self.assertEqual(normalized_default[0].institution_name, "SnapTrade")

if __name__ == '__main__':
    unittest.main()
