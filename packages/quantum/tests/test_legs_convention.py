"""Unit tests for the full-count legs.quantity fill-seam coercion (#3).

This is the CAUSE-side prevention: per-spread legs are coerced to full-count at
persist time and flagged, while legitimate full-count fills are a NO-OP.
"""

import unittest

from packages.quantum.risk.legs_convention import coerce_legs_to_full_count


def _legs(q):
    return [
        {"action": "buy", "symbol": "O:F260626C00015500", "quantity": q},
        {"action": "sell", "symbol": "O:F260626C00017500", "quantity": q},
    ]


class TestCoerceLegsToFullCount(unittest.TestCase):
    def test_full_count_is_noop(self):
        # Legitimate F fill: legs already full-count (5) for a 5-contract pos.
        legs = _legs(5)
        coerced, violations = coerce_legs_to_full_count(legs, 5)
        self.assertEqual(violations, [])
        self.assertEqual([l["quantity"] for l in coerced], [5, 5])

    def test_per_spread_is_coerced_and_flagged(self):
        # CSX BUG-A shape: legs per-spread (1) on a 4-contract position.
        coerced, violations = coerce_legs_to_full_count(_legs(1), 4)
        self.assertEqual([l["quantity"] for l in coerced], [4, 4])
        self.assertEqual(len(violations), 2)
        self.assertEqual(violations[0]["stored_quantity"], 1)
        self.assertEqual(violations[0]["expected"], 4)

    def test_negative_pos_quantity_uses_abs(self):
        # Credit/short position: pos.quantity negative, legs stored positive.
        coerced, violations = coerce_legs_to_full_count(_legs(2), -4)
        self.assertEqual([l["quantity"] for l in coerced], [4, 4])
        self.assertEqual(len(violations), 2)

    def test_zero_quantity_left_untouched(self):
        # Closed/in-flight (qty 0): nothing reliable to coerce toward → no-op.
        legs = _legs(1)
        coerced, violations = coerce_legs_to_full_count(legs, 0)
        self.assertEqual(violations, [])
        self.assertEqual([l["quantity"] for l in coerced], [1, 1])

    def test_non_dict_legs_preserved(self):
        legs = ["junk", {"action": "buy", "symbol": "X", "quantity": 1}]
        coerced, violations = coerce_legs_to_full_count(legs, 3)
        self.assertEqual(coerced[0], "junk")
        self.assertEqual(coerced[1]["quantity"], 3)
        self.assertEqual(len(violations), 1)

    def test_already_full_count_negative_noop(self):
        # Short position whose legs already match abs(qty) → no violation.
        coerced, violations = coerce_legs_to_full_count(_legs(4), -4)
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
