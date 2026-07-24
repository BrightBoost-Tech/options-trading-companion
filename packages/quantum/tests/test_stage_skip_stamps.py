"""Stage-skip blocked_reason stamps (ledger N2 item, 06-12).

The #1051 rider stamped only cooldown/utilization/quote rejections; the
symbol-dedup and min-edge/min-score filters skipped with `continue` at
logger.INFO and left suggestions pending/NULL to be swept (the 06-10 NFLX
forks). All four skip sites now stamp:
- symbol_already_held (user-level dedup AND per-cohort dedup — cohort forks
  are separate rows, so stamping one fork never masks another cohort's copy)
- edge_below_minimum_at_stage
- below_min_score
"""

import sys
import types
import unittest
from pathlib import Path

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

SRC = (
    Path(__file__).parent.parent / "services" / "paper_autopilot_service.py"
).read_text(encoding="utf-8")


class TestSkipSitesStamp(unittest.TestCase):
    def test_user_level_symbol_dedup_stamps(self):
        idx = SRC.find("[DEDUP] Rejected")
        self.assertGreater(idx, 0)
        block = SRC[idx:idx + 400]
        self.assertIn('"symbol_already_held"', block)
        self.assertIn("_stamp_blocked_reason(", block)

    def test_min_edge_filter_stamps(self):
        idx = SRC.find("[FILTER] Rejected")
        self.assertGreater(idx, 0)
        block = SRC[idx:idx + 450]
        self.assertIn('"edge_below_minimum_at_stage"', block)

    def test_below_min_score_stamps(self):
        idx = SRC.find("below_min_score_count += 1")
        self.assertGreater(idx, 0)
        block = SRC[idx:idx + 300]
        self.assertIn('"below_min_score"', block)

    def test_cohort_dedup_stamps(self):
        idx = SRC.find("already have open position\", flush=True)")
        self.assertGreater(idx, 0)
        block = SRC[idx:idx + 600]
        self.assertIn('"symbol_already_held"', block)

    def test_all_three_reason_strings_present(self):
        for reason in ("symbol_already_held", "edge_below_minimum_at_stage",
                       "below_min_score"):
            self.assertIn(f'"{reason}"', SRC, reason)


if __name__ == "__main__":
    unittest.main()
