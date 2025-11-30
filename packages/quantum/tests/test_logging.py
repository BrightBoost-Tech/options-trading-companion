import unittest
from unittest.mock import patch, MagicMock
import uuid
import sys
import os

# Ensure we can import modules from packages.quantum
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.nested_logging import log_inference

class TestLogging(unittest.TestCase):

    @patch('packages.quantum.nested_logging._get_supabase_client')
    def test_log_inference_success(self, mock_get_client):
        # Mock the Supabase client and insert call
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_insert = mock_client.table.return_value.insert.return_value.execute

        trace_id = log_inference(
            symbol_universe=['AAPL', 'GOOG'],
            inputs_snapshot={'risk': 'low'},
            predicted_mu={'AAPL': 0.1},
            predicted_sigma={'AAPL': 0.02},
            optimizer_profile='balanced'
        )

        # Verify it returned a UUID
        self.assertIsInstance(trace_id, uuid.UUID)
        # Verify insert was called
        mock_client.table.assert_called_with("inference_log")
        mock_insert.assert_called_once()

    @patch('packages.quantum.nested_logging._get_supabase_client')
    def test_log_inference_failure_graceful(self, mock_get_client):
        # Mock client to raise exception
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.table.side_effect = Exception("DB Connection Failed")

        # Should not raise exception
        trace_id = log_inference(
            symbol_universe=['AAPL'],
            inputs_snapshot={},
            predicted_mu={},
            predicted_sigma={},
            optimizer_profile='balanced'
        )

        self.assertIsInstance(trace_id, uuid.UUID)

    @patch('packages.quantum.nested_logging._get_supabase_client')
    def test_log_inference_no_client(self, mock_get_client):
        # Mock client returning None (e.g. env vars missing)
        mock_get_client.return_value = None

        trace_id = log_inference(
            symbol_universe=['AAPL'],
            inputs_snapshot={},
            predicted_mu={},
            predicted_sigma={},
            optimizer_profile='balanced'
        )

        self.assertIsInstance(trace_id, uuid.UUID)

if __name__ == '__main__':
    unittest.main()
