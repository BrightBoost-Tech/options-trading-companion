import math
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.jobs.handlers.policy_lab_eval import _evaluate_user
from packages.quantum.policy_lab.capital import (
    PolicyCapitalUnavailable,
    normalize_capital,
)
from packages.quantum.policy_lab.evaluator import (
    _compute_cohort_metrics,
    evaluate_cohorts,
)


class _Query:
    def __init__(self, db, table):
        self.db = db
        self.table_name = table
        self.count = None
        self._insert = None

    def select(self, *args, **kwargs):
        if kwargs.get("count") == "exact":
            self.count = 0
        return self

    def eq(self, *args, **kwargs):
        return self

    def gte(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def neq(self, *args, **kwargs):
        return self

    def single(self):
        return self

    def upsert(self, *args, **kwargs):
        return self

    def insert(self, row):
        self._insert = row
        return self

    def execute(self):
        if self.table_name == "policy_lab_cohorts":
            return SimpleNamespace(data=[{
                "id": "c1", "cohort_name": "neutral",
                "portfolio_id": "p1", "policy_config": {},
            }])
        if self.table_name == "paper_portfolios":
            return SimpleNamespace(data=self.db.portfolio)
        if self.table_name == "paper_positions":
            return SimpleNamespace(data=[], count=self.count or 0)
        if self.table_name == "risk_alerts":
            self.db.alerts.append(self._insert)
            return SimpleNamespace(data=[self._insert])
        if self.table_name == "policy_daily_scores":
            return SimpleNamespace(data=[])
        raise AssertionError(f"unexpected table {self.table_name}")


class _DB:
    def __init__(self, portfolio):
        self.portfolio = portfolio
        self.alerts = []

    def table(self, name):
        return _Query(self, name)


class TestCapitalContract(unittest.TestCase):
    def test_net_liq_is_authoritative_and_never_falls_through(self):
        for bad in (0, -1, float("nan"), float("inf"), "not-a-number"):
            value, reason = normalize_capital(
                {"net_liq": bad, "cash_balance": 100000}
            )
            self.assertIsNone(value)
            self.assertIsNotNone(reason)

    def test_cash_is_used_only_when_net_liq_absent_or_null(self):
        self.assertEqual(
            normalize_capital({"cash_balance": "2067.86"}), (2067.86, None)
        )
        self.assertEqual(
            normalize_capital({"net_liq": None, "cash_balance": 2067.86}),
            (2067.86, None),
        )

    def test_missing_portfolio_never_becomes_100000(self):
        value, reason = normalize_capital(None)
        self.assertIsNone(value)
        self.assertEqual(reason, "portfolio_row_missing")

    def test_evaluator_uses_actual_capital(self):
        metrics = _compute_cohort_metrics(
            _DB({"net_liq": 2067.86, "cash_balance": 1800}),
            "p1",
            "2026-07-15",
        )
        self.assertEqual(metrics["capital_deployed"], 267.86)
        self.assertAlmostEqual(metrics["risk_budget_used"], 267.86 / 2067.86, 4)

    def test_evaluator_invalid_capital_raises_typed(self):
        with self.assertRaises(PolicyCapitalUnavailable):
            _compute_cohort_metrics(
                _DB({"net_liq": 0, "cash_balance": 100000}),
                "p1",
                "2026-07-15",
            )

    def test_evaluate_cohorts_surfaces_partial_and_alert(self):
        db = _DB({"net_liq": float("nan"), "cash_balance": 100000})
        result = evaluate_cohorts("u1", date(2026, 7, 15), db)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(len(db.alerts), 1)
        self.assertIn("PolicyCapitalUnavailable", db.alerts[0]["message"])

    def test_handler_propagates_evaluation_error_count(self):
        eval_result = {
            "status": "partial",
            "counts": {"errors": 1},
            "results": [{"cohort_name": "neutral", "error": "capital"}],
        }
        with patch(
            "packages.quantum.policy_lab.evaluator.evaluate_cohorts",
            return_value=eval_result,
        ), patch(
            "packages.quantum.policy_lab.evaluator.check_promotion",
            return_value={"status": "no_scores_data"},
        ), patch(
            "packages.quantum.policy_lab.evaluator.compute_decision_accuracy",
            return_value={},
        ):
            result = _evaluate_user("u1", object())
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["counts"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
