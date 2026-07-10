"""ITEM 1 (Lane 1, 2026-07-10): the PoP clamp at the calibration APPLY site
(calibration_service.py:629) must clamp pop*pop_mult into [0,1] AND log a
POP_CLAMP_ENGAGED boundary line when it engages — the free-look overshoot must
never be silently erased. Attribution: the overshoot is the MULTIPLIER, not the
delta-cushion composition path.
"""

import unittest

from packages.quantum.analytics.calibration_service import apply_calibration

_LOGGER = "packages.quantum.analytics.calibration_service"


def _adj(pop_mult, ev_mult=1.0):
    # old-format blob: regime_adj carries ev_multiplier at top level
    return {"IRON_CONDOR": {"normal": {"ev_multiplier": ev_mult,
                                       "pop_multiplier": pop_mult}}}


class TestPopClampLog(unittest.TestCase):
    def test_overshoot_1_0704_clamps_and_logs(self):
        # the exact free-look case: raw pop 0.7136 x 1.5 = 1.0704
        with self.assertLogs(_LOGGER, "WARNING") as cm:
            _ev, pop = apply_calibration(40.0, 0.7136, "IRON_CONDOR", "normal",
                                         _adj(1.5))
        self.assertEqual(pop, 1.0)  # clamped to the boundary
        self.assertTrue(any("POP_CLAMP_ENGAGED" in m for m in cm.output))

    def test_deep_itm_boundary_exactly_one_no_clamp_log(self):
        # deep-ITM long delta ~= 1.0, multiplier 1.0 -> product exactly 1.0:
        # 1.0 is NOT > 1.0, so the clamp does not engage and must not log.
        with self.assertNoLogs(_LOGGER, "WARNING"):
            _ev, pop = apply_calibration(40.0, 1.0, "IRON_CONDOR", "normal",
                                         _adj(1.0))
        self.assertEqual(pop, 1.0)

    def test_in_range_untouched_no_log(self):
        # 0.6 x 1.2 = 0.72, well inside [0,1]: clamp must not touch it, no WARNING.
        with self.assertNoLogs(_LOGGER, "WARNING"):
            _ev, pop = apply_calibration(40.0, 0.6, "IRON_CONDOR", "normal",
                                         _adj(1.2))
        self.assertAlmostEqual(pop, 0.72)

    def test_floor_clamps_and_logs(self):
        # completeness of the [0, .] floor: a negative product clamps to 0 + logs.
        with self.assertLogs(_LOGGER, "WARNING") as cm:
            _ev, pop = apply_calibration(40.0, -0.1, "IRON_CONDOR", "normal",
                                         _adj(1.5))
        self.assertEqual(pop, 0.0)
        self.assertTrue(any("POP_CLAMP_ENGAGED" in m for m in cm.output))


if __name__ == "__main__":
    unittest.main()
