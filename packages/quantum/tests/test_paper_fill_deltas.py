
import unittest
from packages.quantum.paper_endpoints import _compute_fill_deltas

class TestPaperFillDeltas(unittest.TestCase):
    def test_initial_partial_fill(self):
        """
        Test case 1:
        order requested_qty=20, tcm.fees_usd=2.0, prev fees_usd=0.0;
        fill_res: filled_qty=10, avg_fill_price=1.50, last_fill_qty=10, last_fill_price=1.50
        Expect: fees_total=1.0, fees_delta=1.0, this_fill_qty=10, this_fill_price=1.50
        """
        order = {
            "requested_qty": 20,
            "tcm": {"fees_usd": 2.0},
            "fees_usd": 0.0
        }
        fill_res = {
            "filled_qty": 10,
            "avg_fill_price": 1.50,
            "last_fill_qty": 10,
            "last_fill_price": 1.50
        }

        deltas = _compute_fill_deltas(order, fill_res)

        self.assertEqual(deltas["this_fill_qty"], 10)
        self.assertEqual(deltas["this_fill_price"], 1.50)
        self.assertEqual(deltas["new_total_filled_qty"], 10)
        self.assertEqual(deltas["fees_total"], 1.0)
        self.assertEqual(deltas["fees_delta"], 1.0)

    def test_incremental_fill(self):
        """
        Test case 2:
        Same order but now order["fees_usd"]=1.0 and order["filled_qty"]=10;
        fill_res: filled_qty=20, avg_fill_price=1.60, last_fill_qty=10, last_fill_price=1.70
        Expect: fees_total=2.0, fees_delta=1.0, this_fill_qty=10, this_fill_price=1.70
        """
        order = {
            "requested_qty": 20,
            "filled_qty": 10,
            "tcm": {"fees_usd": 2.0},
            "fees_usd": 1.0
        }
        fill_res = {
            "filled_qty": 20,
            "avg_fill_price": 1.60,
            "last_fill_qty": 10,
            "last_fill_price": 1.70
        }

        deltas = _compute_fill_deltas(order, fill_res)

        self.assertEqual(deltas["this_fill_qty"], 10)
        self.assertEqual(deltas["this_fill_price"], 1.70)
        self.assertEqual(deltas["new_total_filled_qty"], 20)
        self.assertEqual(deltas["fees_total"], 2.0)
        self.assertEqual(deltas["fees_delta"], 1.0)

    def test_no_new_fill(self):
        """
        Test "no new fill" case:
        fill_res without last_fill_qty should yield this_fill_qty=0 and fees_delta=0.
        """
        order = {
            "requested_qty": 20,
            "filled_qty": 10,
            "tcm": {"fees_usd": 2.0},
            "fees_usd": 1.0
        }
        fill_res = {
            "filled_qty": 10,
            "avg_fill_price": 1.50,
            "last_fill_qty": 0,
            "last_fill_price": 0
        }

        deltas = _compute_fill_deltas(order, fill_res)

        self.assertEqual(deltas["this_fill_qty"], 0)
        self.assertEqual(deltas["fees_delta"], 0)
        self.assertEqual(deltas["new_total_filled_qty"], 10)
        self.assertEqual(deltas["fees_total"], 1.0)

if __name__ == '__main__':
    unittest.main()
