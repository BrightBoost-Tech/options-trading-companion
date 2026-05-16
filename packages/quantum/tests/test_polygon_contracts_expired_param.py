"""Verify Polygon /v3/reference/options/contracts call includes
expired=true so the contract listing is time-stable.

Finding B (2026-05-17): without expired=true, contracts that have
expired are dropped from Polygon's default response, causing the same
(symbol, as_of_date) to produce different iv_30d values over time as
bracketing expiry contracts pass. expired=true makes the contract
listing time-stable.

DO NOT also add ``as_of`` to this call — Sunday 2026-05-17 Test C
empirically confirmed that combining expired=true with as_of returns
0 results. The service-layer as_of_date arg is used for cache-key
construction only.

Source-level structural assertions, mirroring the convention from
``test_background_queue_routing.py`` and
``test_internal_tasks_tier1_body_acceptance.py``. Survives refactors
of the underlying HTTP call without coupling to fixture mock shape.
"""

import re
import unittest
from pathlib import Path


MARKET_DATA_PATH = (
    Path(__file__).parent.parent / "market_data.py"
)


def _contracts_params_block(src: str) -> str:
    """Extract the params dict that the contracts-listing API call
    uses. The block is identified by its distinctive
    ``expiration_date.gte`` key (no other Polygon call site uses this
    exact field name with the same dict shape)."""
    # Match a params = { ... } block containing 'expiration_date.gte'.
    # Multiline-friendly; stops at the matching closing brace.
    m = re.search(
        r"params\s*=\s*\{[^{}]*'expiration_date\.gte'[^{}]*\}",
        src,
        re.DOTALL,
    )
    assert m is not None, (
        "Could not locate the contracts-listing params dict in "
        f"{MARKET_DATA_PATH}. If file structure changed, update this "
        "test to match the new location."
    )
    return m.group(0)


class TestPolygonContractsExpiredParam(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.src = MARKET_DATA_PATH.read_text(encoding="utf-8")

    def test_contracts_call_includes_expired_true(self):
        """The contracts-listing params dict MUST include
        ``'expired': 'true'``. Without it, Polygon's default response
        excludes expired contracts; bracketing-anchor contracts that
        pass their expiry are silently dropped, making the handler
        non-deterministic over time (Finding B 2026-05-17)."""
        block = _contracts_params_block(self.src)

        # Accept either single- or double-quoted form.
        present = (
            "'expired'" in block and "'true'" in block
        ) or (
            '"expired"' in block and '"true"' in block
        )

        self.assertTrue(
            present,
            "expired=true is missing from the contracts-listing call. "
            "See Finding B 2026-05-17: bracketing expiry contracts "
            "disappear from Polygon's default response after they "
            "expire, causing iv_30d drift over time. Add: "
            "'expired': 'true' to the params dict.",
        )

    def test_contracts_call_does_NOT_include_as_of(self):
        """Regression guard against a well-intentioned future PR that
        adds ``as_of`` thinking it improves historical-date filtering.

        Sunday 2026-05-17 Test C empirically confirmed:
        combining ``expired=true`` with ``as_of=<date>`` returns 0
        contracts on the /v3/reference/options/contracts endpoint at
        Polygon's current Options Developer tier. The current code's
        omission of as_of is accidentally correct — keep it that way.
        """
        block = _contracts_params_block(self.src)

        # Match as_of ONLY when it appears as an actual dict key
        # (followed by ':'), not when it appears inside a comment
        # warning AGAINST adding it. Polygon's parameter is literally
        # "as_of" — match the dict-entry form exactly.
        has_as_of_key = bool(
            re.search(r"['\"]as_of['\"]\s*:", block)
        )

        self.assertFalse(
            has_as_of_key,
            "as_of parameter found in contracts-listing call. "
            "DO NOT combine with expired=true — Sunday 2026-05-17 "
            "Test C empirically confirmed this returns 0 results. "
            "The service-layer as_of_date arg is used for cache-key "
            "construction only; it should not be forwarded to the "
            "Polygon API.",
        )

    def test_explanatory_comment_present(self):
        """The code MUST include a comment near the expired=true line
        warning future readers against adding as_of. The comment is
        the most valuable part of this fix — the param itself is
        mechanical; the comment captures the empirical 'why not'
        that prevents the obvious-looking 'improvement' regression.

        Looks for any of several markers: Finding B reference, the
        2026-05-17 investigation date, Test C reference, or explicit
        'DO NOT' guidance near as_of mention."""
        # Search the whole file (not just the block) because the
        # comment is intentionally adjacent to the param.
        has_finding_b = "Finding B" in self.src
        has_date_ref = "2026-05-17" in self.src
        has_test_c = "Test C" in self.src
        has_do_not_as_of = (
            "DO NOT" in self.src and "as_of" in self.src
        )

        markers_present = sum([
            has_finding_b, has_date_ref, has_test_c, has_do_not_as_of,
        ])

        self.assertGreaterEqual(
            markers_present, 2,
            "Code should include explanatory comment near expired=true "
            "with at least 2 of: 'Finding B' / '2026-05-17' / 'Test C' "
            "/ 'DO NOT'+'as_of' warning. Future-reader context is the "
            "most load-bearing part of this fix — the param is "
            "trivial but the 'don't combine with as_of' lesson is "
            "non-obvious without empirical evidence.",
        )


if __name__ == "__main__":
    unittest.main()
