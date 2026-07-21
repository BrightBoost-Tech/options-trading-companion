"""Doc drift pin — the canonical H7 disposition taxonomy doc
(``docs/h7_disposition_taxonomy.md``) MUST stay set-equal to the writer's
``H7_SUBREASONS`` frozenset, and MUST keep ``sizing_outcome`` documented as a
SEPARATE detail key (never an h7 subreason).

Anti-drift discipline (the same the CHECK ↔ frozenset contract test enforces):
the ratified taxonomy is recorded in prose ONLY where a test guarantees the
prose can never silently diverge from the code. If a subreason is added/removed
in ``candidate_disposition.H7_SUBREASONS`` without the doc moving with it —
or if ``sizing_outcome`` or the ``unspecified`` sentinel is folded into the
canonical block — this test fails.

Docs-only PR: no product behavior is asserted here, only doc↔code consistency.
"""

import re
import unittest
from pathlib import Path

from packages.quantum.services.candidate_disposition import (
    H7_SUBREASON_UNSPECIFIED,
    H7_SUBREASONS,
)

DOC = (
    Path(__file__).resolve().parents[3]
    / "docs" / "h7_disposition_taxonomy.md"
)

# The owner approval token that ratifies the RETAIN decision.
RATIFY_TOKEN = "H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON"


def _doc() -> str:
    return DOC.read_text(encoding="utf-8")


def _canonical_block() -> set:
    """The lowercase identifiers inside the delimited canonical block.

    The block is fenced by explicit HTML-comment markers so surrounding prose
    (which mentions the sentinel, sizing_outcome, etc.) can never leak into the
    parsed canonical set."""
    text = _doc()
    m = re.search(
        r"H7_SUBREASONS_CANONICAL:START(.*?)H7_SUBREASONS_CANONICAL:END",
        text, re.S,
    )
    assert m is not None, "canonical subreason block markers missing from doc"
    return set(re.findall(r"[a-z_]+", m.group(1)))


class TestH7TaxonomyDocContract(unittest.TestCase):
    def test_doc_exists(self):
        self.assertTrue(DOC.is_file(), DOC)

    def test_canonical_block_set_equals_frozenset(self):
        # THE drift pin: the doc's canonical list == the writer's frozenset,
        # exactly. Neither may add nor drop a value without the other moving.
        self.assertEqual(_canonical_block(), set(H7_SUBREASONS))

    def test_canonical_block_excludes_sentinel(self):
        # 'unspecified' is the soft-fail sentinel, NOT a canonical subreason;
        # it must not appear inside the canonical block.
        self.assertNotIn(H7_SUBREASON_UNSPECIFIED, _canonical_block())

    def test_canonical_block_excludes_sizing_outcome(self):
        # 'sizing_outcome' is a SEPARATE detail key, never a subreason.
        self.assertNotIn("sizing_outcome", _canonical_block())

    def test_sizing_outcome_is_not_a_subreason_in_code(self):
        # Belt-and-braces: the ratified separation must also hold in code.
        self.assertNotIn("sizing_outcome", set(H7_SUBREASONS))

    def test_doc_documents_parent_sentinel_and_separation(self):
        text = _doc()
        # Parent retained, backward-compatible.
        self.assertIn("h7_dropped", text)
        # Sentinel documented (as non-canonical).
        self.assertIn(H7_SUBREASON_UNSPECIFIED, text)
        # sizing_outcome documented as separate.
        self.assertIn("sizing_outcome", text)

    def test_doc_records_the_ratification_token(self):
        self.assertIn(RATIFY_TOKEN, _doc())


if __name__ == "__main__":
    unittest.main()
