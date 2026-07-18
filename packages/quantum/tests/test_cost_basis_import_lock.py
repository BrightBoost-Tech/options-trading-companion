"""Import-lock guardrail: cost_basis is a ONE-WAY dependency.

The typed multi-basis cost model (analytics/cost_basis.py) is observe-only:
it may import production formulas to freeze them as baselines, but NO
production decision module may import cost_basis. If a future change wires
cost_basis into a decision path, this test breaks the build — that wiring
must be its own deliberate, flagged, doctrine-reviewed PR, never a side
effect.

Two locks:
1. Static sweep — no non-test module under packages/quantum imports
   cost_basis.
2. Inertness — cost_basis itself has NO module-level packages.quantum
   imports (all production imports are lazy, inside extractor bodies), so
   importing it can never drag production modules in at import time.
"""

import ast
import re
import unittest
from pathlib import Path

REPO_QUANTUM = Path(__file__).resolve().parents[1]  # packages/quantum
COST_BASIS_FILE = REPO_QUANTUM / "analytics" / "cost_basis.py"

# Matches real import statements of the cost_basis module (never the
# unrelated `cost_basis = denom` local in scoring.py, never
# transaction_cost_model).
_IMPORT_PATTERN = re.compile(
    r"^\s*(?:"
    r"from\s+[\w\.]*\bcost_basis\b\s+import"      # from ...cost_basis import x
    r"|import\s+[\w\.]*\bcost_basis\b"            # import ...cost_basis
    r"|from\s+[\w\.]+\s+import\s+[^\n]*\bcost_basis\b"  # from pkg import cost_basis
    r")",
    re.MULTILINE,
)


class TestNoProductionModuleImportsCostBasis(unittest.TestCase):
    def test_static_sweep(self):
        self.assertTrue(
            COST_BASIS_FILE.exists(),
            f"cost_basis module missing at {COST_BASIS_FILE}",
        )
        offenders = []
        for path in sorted(REPO_QUANTUM.rglob("*.py")):
            rel = path.relative_to(REPO_QUANTUM)
            if "tests" in rel.parts:
                continue  # tests may import it freely
            if path == COST_BASIS_FILE:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:  # pragma: no cover - unreadable file
                self.fail(f"could not read {rel}: {exc}")
            if _IMPORT_PATTERN.search(text):
                offenders.append(str(rel))
        self.assertEqual(
            offenders, [],
            "production modules must NEVER import cost_basis (one-way "
            f"dependency); offenders: {offenders}",
        )

    def test_pattern_catches_the_import_shapes(self):
        # The lock must actually bite — pin the regex against the ways a
        # production module would realistically wire it in.
        for line in (
            "from packages.quantum.analytics.cost_basis import reconcile_cost_bases",
            "from packages.quantum.analytics import cost_basis",
            "import packages.quantum.analytics.cost_basis",
            "from .cost_basis import CostBreakdown",
            "    from packages.quantum.analytics.cost_basis import CostDelta",
        ):
            self.assertIsNotNone(
                _IMPORT_PATTERN.search(line), f"pattern missed: {line!r}"
            )
        # ...and must NOT false-positive on the known near-misses.
        for line in (
            "cost_basis = denom",  # scoring.py:77 local variable
            "from packages.quantum.services.transaction_cost_model import TransactionCostModel",
            "# cost_basis is documented here",
        ):
            self.assertIsNone(
                _IMPORT_PATTERN.search(line), f"false positive: {line!r}"
            )


class TestCostBasisModuleLevelInertness(unittest.TestCase):
    def test_no_module_level_production_imports(self):
        tree = ast.parse(COST_BASIS_FILE.read_text(encoding="utf-8"))
        offenders = []
        for node in tree.body:  # TOP-LEVEL statements only — lazy is fine
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("packages."):
                        offenders.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").startswith("packages."):
                    offenders.append(node.module)
        self.assertEqual(
            offenders, [],
            "cost_basis must keep ALL production imports lazy (inside "
            f"function bodies); module-level offenders: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()
