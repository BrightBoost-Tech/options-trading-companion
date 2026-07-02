"""P1-A (2026-07-02) — ops_health_check q30min-real idempotency bucket.

Owner decision: cadence intent is q30min REAL. The prior hour-granular key
deduped the :37 scheduled fire against the :07 run every hour, silently
halving the health-check and A3 alert-relay cadence. Pin: the :07 and :37
fires land in DIFFERENT buckets (both execute); same-half-hour retries still
dedup; the synthetic-delivery-test suffix path is unaffected.
"""

import sys
import types
import unittest
from datetime import datetime

# Windows-local shim: rq's import raises ValueError (no 'fork' context) so
# public_tasks — which imports rq_enqueue at module level — is uncollectable
# locally (the known 9-file fork class). CI (Linux) imports the real rq;
# the shim only engages where rq itself cannot load.
try:  # pragma: no cover - environment-dependent
    import rq  # noqa: F401
except Exception:
    _rq_stub = types.ModuleType("rq")
    _rq_stub.Queue = type("Queue", (), {"__init__": lambda self, *a, **k: None})
    sys.modules["rq"] = _rq_stub

from packages.quantum.public_tasks import _ops_health_idempotency_key


def _at(minute, hour=14):
    return datetime(2026, 7, 2, hour, minute, 0)


class TestQ30Bucket(unittest.TestCase):
    def test_scheduled_07_and_37_fires_both_execute(self):
        self.assertNotEqual(
            _ops_health_idempotency_key(_at(7)),
            _ops_health_idempotency_key(_at(37)),
            "the :37 fire must not dedup against the :07 run — q30min real",
        )

    def test_same_half_hour_retries_still_dedup(self):
        self.assertEqual(
            _ops_health_idempotency_key(_at(7)),
            _ops_health_idempotency_key(_at(29)),
        )
        self.assertEqual(
            _ops_health_idempotency_key(_at(37)),
            _ops_health_idempotency_key(_at(59)),
        )
        self.assertEqual(
            _ops_health_idempotency_key(_at(0)),
            _ops_health_idempotency_key(_at(7)),
        )
        self.assertEqual(
            _ops_health_idempotency_key(_at(30)),
            _ops_health_idempotency_key(_at(37)),
        )

    def test_buckets_differ_across_hours(self):
        self.assertNotEqual(
            _ops_health_idempotency_key(_at(7, hour=14)),
            _ops_health_idempotency_key(_at(7, hour=15)),
        )

    def test_key_shape_is_prefix_stable(self):
        # The synthetic_delivery_test path appends "-synthetic" to this key;
        # pin the base shape so that suffix keeps composing.
        key = _ops_health_idempotency_key(_at(37))
        self.assertEqual(key, "2026-07-02-14-30")
        key = _ops_health_idempotency_key(_at(7))
        self.assertEqual(key, "2026-07-02-14-00")


if __name__ == "__main__":
    unittest.main()
