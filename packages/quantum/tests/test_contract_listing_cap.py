"""Regression test: contract-listing pagination cap is raised to 20000.

Added 2026-05-17 (F2a) after Phase 3 sparse-coverage investigation
identified the prior 1000 cap as consuming pagination budget with
daily-expiry strikes for deep-chain symbols.

Empirical evidence from that investigation:
  - QQQ window query returned 1000 contracts covering ONLY 8 distinct
    expiry dates (Feb 23 - Mar 4 2026)
  - Strict correlation: deeper daily-options chain → earlier
    "missing-from" date in 60-day backfill window
  - 19 of 70 symbols affected at the prior cap; worst case QQQ at
    7 of 61 dates covered

Test uses ``inspect.signature`` directly rather than going through
the PolygonService class (which needs HTTP session, env, etc.), so
it's a pure source-level signature check.
"""

import inspect
import unittest

from packages.quantum.market_data import PolygonService


F2A_CAP = 20000  # Sized 2026-05-17; raise via PR if a symbol exceeds.
PRE_F2A_CAP = 1000  # The broken value; defend against accidental revert.


class TestContractListingCap(unittest.TestCase):
    """Source-level assertions on the
    ``PolygonService.get_option_contract_candidates`` signature's
    ``limit`` default."""

    @classmethod
    def setUpClass(cls):
        sig = inspect.signature(
            PolygonService.get_option_contract_candidates
        )
        cls.limit_default = sig.parameters["limit"].default

    def test_default_limit_is_above_pre_f2a_value(self):
        """Defend against accidental revert. 1000 was empirically
        insufficient for QQQ-class deep-chain symbols (Phase 3
        sparse-coverage investigation 2026-05-17). Any change back
        toward 1000 reproduces that bug."""
        self.assertGreater(
            self.limit_default, PRE_F2A_CAP,
            f"get_option_contract_candidates default limit "
            f"{self.limit_default} reverted toward pre-F2a value "
            f"{PRE_F2A_CAP}. This reintroduces the Phase 3 sparse-"
            f"coverage bug: QQQ-class symbols' daily-options chains "
            f"exhaust the 1000 cap with only ~8 expiry dates' worth "
            f"of strikes, leaving no anchors for middle/late dates "
            f"in 60-day backfill windows. See investigation "
            f"2026-05-17 + F2a PR.",
        )

    def test_default_limit_matches_f2a_value(self):
        """F2a sized at 20000. If you intentionally change this value
        (e.g., 50000 for symbols with even deeper chains), update both
        the function's inline comment AND this test in the same PR."""
        self.assertEqual(
            self.limit_default, F2A_CAP,
            f"Default limit {self.limit_default} differs from F2a-"
            f"sized {F2A_CAP}. If intentional: update F2A_CAP here, "
            f"the function's inline comment, and the PR rationale "
            f"in the same change.",
        )


if __name__ == "__main__":
    unittest.main()
