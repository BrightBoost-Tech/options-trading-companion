import unittest
from datetime import datetime, timezone, timedelta
from packages.quantum.inbox.ranker import rank_suggestions

class TestInboxRanker(unittest.TestCase):
    def test_ranking(self):
        now = datetime.now(timezone.utc)

        s1 = {
            "id": "1",
            "ev": 10.0,
            "sizing_metadata": {"max_loss_total": 100.0}, # yield 0.1
            "created_at": now.isoformat()
        }
        s2 = {
            "id": "2",
            "ev": 50.0,
            "sizing_metadata": {"max_loss_total": 100.0}, # yield 0.5
            "created_at": (now - timedelta(minutes=1)).isoformat()
        }
        s3 = {
            "id": "3",
            "ev": 10.0,
            "sizing_metadata": {}, # yield 10.0 / 1.0 = 10.0
            "created_at": (now - timedelta(minutes=2)).isoformat()
        }

        results = rank_suggestions([s1, s2, s3])

        # Expected order: s3 (10.0), s2 (0.5), s1 (0.1)
        self.assertEqual(results[0]["id"], "3")
        self.assertEqual(results[1]["id"], "2")
        self.assertEqual(results[2]["id"], "1")

        self.assertEqual(results[0]["yield_on_risk"], 10.0)
        self.assertEqual(results[1]["yield_on_risk"], 0.5)
        self.assertEqual(results[2]["yield_on_risk"], 0.1)

    def test_stale(self):
        now = datetime.now(timezone.utc)
        s1 = {
            "id": "1",
            "ev": 10.0,
            "created_at": (now - timedelta(minutes=10)).isoformat() # 600s old
        }
        results = rank_suggestions([s1], stale_after_seconds=300)
        self.assertTrue(results[0]["is_stale"])

if __name__ == "__main__":
    unittest.main()
