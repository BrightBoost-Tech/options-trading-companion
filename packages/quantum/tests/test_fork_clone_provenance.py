"""F-CLONE-PROVENANCE — cohort-clone rows must carry ranking_costs + code_sha.

Defect (2026-07-16 16:00:35Z Row B): `_clone_suggestion_for_cohort` built
live-executable `status="pending"` rows without `ranking_costs`/`code_sha`,
while the primary writer stamped both — two same-cycle IRON_CONDOR rows with
divergent provenance. The executor fetch (`status='pending'` per cohort) does
not distinguish clones, so the under-stamped row rode the live route.

Route tests here drive the REAL `fork_suggestions_for_cohorts` against the
hardened DB-contract fake from test_prerejection_fork_e19 — never a copied
row builder. Inheritance is honest: a source row that predates the stamps
clones to NULL ranking_costs (never fabricated).
"""
import copy
import os
import unittest

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.tests.test_prerejection_fork_e19 import (
    UID,
    FakeSupabase,
    _clones,
    _pending_qqq,
    _run_fork,
    _seed,
)

_TEST_SHA40 = "1234567890abcdef1234567890abcdef12345678"


class _GitShaEnv(unittest.TestCase):
    """Pin GIT_SHA so get_code_sha() is deterministic in-process."""

    def setUp(self):
        self._saved = os.environ.get("GIT_SHA")
        os.environ["GIT_SHA"] = _TEST_SHA40
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("GIT_SHA", None)
        else:
            os.environ["GIT_SHA"] = self._saved
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)


def _stamped_source():
    """Champion-shaped source row carrying the primary writer's stamps."""
    row = _pending_qqq()
    row["ranking_costs"] = {
        "fees": 5.2,
        "slippage": 1.86,
        "basis": "leg_aware_v1",
    }
    row["code_sha"] = _TEST_SHA40[:12]
    return row


class TestClonePersistsProvenance(_GitShaEnv):
    def test_neutral_clone_carries_ranking_costs_and_code_sha(self):
        client = FakeSupabase()
        source = _stamped_source()
        _seed(client, source)

        result = _run_fork(client)
        self.assertIn(result.get("status"), ("ok", "partial"))

        clones = _clones(client)
        self.assertEqual(len(clones), 1, f"expected one neutral clone, got {clones}")
        clone = clones[0]

        # Live-executable row: same fetch surface as a champion row.
        self.assertEqual(clone.get("status"), "pending")
        # Inherited cost basis behind the inherited risk_adjusted_ev.
        self.assertEqual(clone.get("ranking_costs"), source["ranking_costs"])
        # Fresh producing-version stamp (12-char contract of get_code_sha).
        self.assertEqual(clone.get("code_sha"), _TEST_SHA40[:12])

    def test_champion_row_keeps_primary_writer_stamps(self):
        client = FakeSupabase()
        source = _stamped_source()
        _seed(client, source)

        _run_fork(client)

        champions = [
            r
            for r in client.tables["trade_suggestions"]
            if r.get("cohort_name") == "aggressive"
        ]
        self.assertEqual(len(champions), 1)
        # Tag-in-place must not strip the primary stamps (UPDATE, not re-insert).
        self.assertEqual(champions[0].get("ranking_costs"), source["ranking_costs"])
        self.assertEqual(champions[0].get("code_sha"), _TEST_SHA40[:12])
        self.assertEqual(
            champions[0].get("legs_fingerprint"), source["legs_fingerprint"],
            "champion fingerprint must remain unsuffixed (writer discriminator)",
        )


class TestNoFabrication(_GitShaEnv):
    def test_unstamped_legacy_source_clones_null_ranking_costs(self):
        """A source predating the stamps inherits NULL — never a fabricated basis."""
        client = FakeSupabase()
        source = _pending_qqq()  # no ranking_costs / code_sha on the source
        source.pop("ranking_costs", None)
        source.pop("code_sha", None)
        _seed(client, source)

        _run_fork(client)

        clones = _clones(client)
        self.assertEqual(len(clones), 1)
        self.assertIsNone(clones[0].get("ranking_costs"))
        # code_sha is a fresh producing-version stamp, independent of source.
        self.assertEqual(clones[0].get("code_sha"), _TEST_SHA40[:12])

    def test_builder_emits_both_keys(self):
        """The clone dict itself must contain both keys (droppable-list guard:
        neither field is in DROPPABLE_SUGGESTION_COLUMNS, so their presence is
        a hard schema dependency — this pins that the builder emits them)."""
        source = _stamped_source()
        clone = fork_mod._clone_suggestion_for_cohort(
            copy.deepcopy(source), "neutral", PolicyConfig(), 2000.0,
        )
        self.assertIsNotNone(clone)
        self.assertIn("ranking_costs", clone)
        self.assertIn("code_sha", clone)


if __name__ == "__main__":
    unittest.main()
