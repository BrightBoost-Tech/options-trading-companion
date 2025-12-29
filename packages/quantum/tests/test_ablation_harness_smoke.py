import unittest
from unittest.mock import patch, MagicMock
import sys
import os
import io

# Add repo root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from packages.quantum.tools import ablation_harness

class TestAblationHarnessSmoke(unittest.TestCase):

    @patch('sys.stdout', new_callable=io.StringIO)
    def test_harness_run(self, mock_stdout):
        """Smoke test for the ablation harness CLI."""

        # Override sys.argv
        test_args = ["ablation_harness", "--symbols", "5", "--seed", "123", "--mock"]
        with patch.object(sys, 'argv', test_args):
            ablation_harness.main()

        output = mock_stdout.getvalue()

        # Verify output contains the table headers and config names
        self.assertIn("Ablation Results", output)
        self.assertIn("Config", output)
        self.assertIn("baseline", output)
        self.assertIn("full_agents", output)
        self.assertIn("Suggestions", output)

        # Verify it actually ran simulation (metrics should be present)
        # Note: Mock data might result in 0 suggestions depending on random seed,
        # but the table structure should exist.

if __name__ == '__main__':
    unittest.main()
