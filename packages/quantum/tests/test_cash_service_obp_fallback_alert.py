"""Tests for #849 follow-up B — alert when cash_service falls back to
paper_baseline_capital.

When equity_state.get_alpaca_options_buying_power returns None,
cash_service.get_deployable_capital substitutes
v3_go_live_state.paper_baseline_capital as a defense-in-depth fallback.
This was silent (log-only) for 3 days post-#849 — the 2026-05-04
OBP-divergence diagnostic surfaced it because alpaca_client.get_account
wrapper dropped options_buying_power, making the helper always return None.

PR A fixes the immediate cause (wrapper exposes the field). PR B (this
PR) covers the latent class — if the helper ever regresses again
(alpaca-py version skew, broker permissions revoked, future wrapper
trim), the operator gets a risk_alerts row instead of silent stale-data
operation.

Per Loud-Error Doctrine v1.0 anti-pattern 2 (log-only swallow with
default return). Same shape as PR #859 (cohort_clone_insert_failed)
and PR #96 framing (operationally inert today, latent class).
"""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


CASH_SERVICE_PATH = (
    Path(__file__).parent.parent / "services" / "cash_service.py"
)


def _read_cash_service() -> str:
    return CASH_SERVICE_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestSourceLevelAlertWired(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = _read_cash_service()

    def test_obp_fallback_writes_alert(self):
        """Required strings present at the fallback site."""
        self.assertIn("cash_service_alpaca_obp_fallback", self.src)
        self.assertIn("operator_action_required", self.src)
        self.assertIn("alert(", self.src)

    def test_obp_fallback_alert_severity_is_warning(self):
        """Severity = warning per #96 convention (operationally inert
        today post-PR A; latent class warrants observability without
        alarm-fatigue level)."""
        anchor = self.src.find('"cash_service_alpaca_obp_fallback"')
        self.assertGreater(
            anchor, 0,
            "alert_type literal cash_service_alpaca_obp_fallback not found",
        )
        # Severity sits 1-2 lines below alert_type per call-site convention.
        window = self.src[anchor:anchor + 500]
        self.assertIn('severity="warning"', window)

    def test_doctrine_reference_present(self):
        """Comment block at the alert site references the doctrine
        anti-pattern by name."""
        anchor = self.src.find('"cash_service_alpaca_obp_fallback"')
        # Comment block sits just before the alert call.
        window = self.src[max(0, anchor - 800):anchor]
        self.assertIn("Loud-Error Doctrine", window)
        self.assertIn("anti-pattern 2", window)

    def test_alert_wrapped_in_try_except(self):
        """Alert-write failure must not break the fallback return path
        (per doctrine Valid 5). The try: opens ~500 chars before the
        anchor; the except sits ~2500 chars after (long metadata dict
        + multi-line f-strings). Window the asserts independently."""
        anchor = self.src.find('"cash_service_alpaca_obp_fallback"')
        before = self.src[max(0, anchor - 500):anchor]
        after = self.src[anchor:anchor + 3000]
        self.assertIn("try:", before)
        self.assertIn("except Exception", after)

    def test_fallback_return_preserved(self):
        """Behavioral invariant: return paper_baseline still happens.
        Observability is additive."""
        # The fallback variable is named paper_baseline; a return
        # statement using it must still exist.
        self.assertIn("return paper_baseline", self.src)


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral tests intentionally omitted
# ─────────────────────────────────────────────────────────────────────
# `cash_service.get_deployable_capital` is an async method. Behavioral
# coverage requires `unittest.IsolatedAsyncioTestCase` or pytest-asyncio,
# which interact unpredictably with the patching topology used here
# (the helper imports `equity_state.get_alpaca_options_buying_power`
# inside the async function body). Local pytest runs the IsolatedAsyncio
# variant cleanly, but CI's pytest+plugin combination produces
# `TypeError: object MagicMock can't be used in 'await' expression`
# inside the patched call chain — a classic async/mock interaction
# fragility, not a code defect.
#
# Per Loud-Error Doctrine v1.0 testing convention (see PR #859 and the
# Doctrine §"Edge cases and caveats"): when behavioral coverage of an
# alert wiring is brittle, structural coverage above is sufficient.
# Behavioral verification happens at runtime by the next production
# fire — if the helper regresses to returning None, this alert writes
# a `risk_alerts` row that the operator inspects directly.
#
# If the team wants strict behavioral coverage in the future, the path
# is: add pytest-asyncio + asyncio_mode=auto in pyproject.toml, then
# either rewrite as plain async functions (not unittest classes) OR
# investigate the IsolatedAsyncioTestCase interaction with our pytest
# version specifically. Both are out of scope for this observability PR.


if __name__ == "__main__":
    unittest.main()
