import unittest

from packages.quantum.services.workflow_orchestrator import _resolve_model_version


class TestModelVersionProvenance(unittest.TestCase):
    def test_candidate_model_version_wins(self):
        version, basis = _resolve_model_version(
            {"model_version": "calibration-v3", "strategy_version": 86},
            "LONG_CALL_DEBIT_SPREAD",
            "midday_entry",
        )
        self.assertEqual(version, "model_version:calibration-v3")
        self.assertEqual(basis, "model_version")

    def test_strategy_version_changes_without_app_version(self):
        old, old_basis = _resolve_model_version(
            {"strategy_version": 86},
            "LONG_CALL_DEBIT_SPREAD",
            "midday_entry",
        )
        new, new_basis = _resolve_model_version(
            {"strategy_version": 87},
            "LONG_CALL_DEBIT_SPREAD",
            "midday_entry",
        )
        self.assertEqual(old_basis, "strategy_version")
        self.assertEqual(new_basis, "strategy_version")
        self.assertEqual(old, "strategy_version:86")
        self.assertEqual(new, "strategy_version:87")
        self.assertNotEqual(old, new)

    def test_scanner_version_is_supported(self):
        version, basis = _resolve_model_version(
            {"scanner_version": "v12"},
            "IRON_CONDOR",
            "midday_entry",
        )
        self.assertEqual(version, "scanner_version:v12")
        self.assertEqual(basis, "scanner_version")

    def test_missing_provenance_is_honestly_unversioned(self):
        version, basis = _resolve_model_version(
            {},
            "LONG_PUT_DEBIT_SPREAD",
            "midday_entry",
        )
        self.assertEqual(
            version,
            "midday_entry:LONG_PUT_DEBIT_SPREAD:unversioned",
        )
        self.assertEqual(basis, "unversioned")
        self.assertNotIn("v2-dev", version)

    def test_exit_rule_identity_is_not_deploy_identity(self):
        version, basis = _resolve_model_version(
            None,
            "take_profit_limit",
            "morning_limit",
        )
        self.assertEqual(
            version,
            "morning_limit:take_profit_limit:unversioned",
        )
        self.assertEqual(basis, "unversioned")


if __name__ == "__main__":
    unittest.main()
