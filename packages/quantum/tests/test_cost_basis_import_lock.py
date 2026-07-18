"""Import-lock guardrail: cost_basis is a ONE-WAY dependency.

The typed multi-basis cost model (analytics/cost_basis.py) is observe-only:
it may import production formulas to freeze them as baselines, but NO
production DECISION module may import cost_basis. If a future change wires
cost_basis into a decision path, this test breaks the build — that wiring
must be its own deliberate, flagged, doctrine-reviewed PR, never a side
effect.

The single exception is the OBSERVE-ONLY consumer allowlist below. A module
earns a slot only if it: (a) writes/decides nothing that feeds a rank or a
gate, and (b) is reviewed as such in the PR that adds it. Adding to the
allowlist IS the "deliberate, flagged, doctrine-reviewed" act the paragraph
above requires — never a silent side effect. Every DECISION module (scanner,
scoring, ranker, paper_endpoints, exit evaluator, risk, allocator, executor)
stays locked regardless.

  - services/cost_reconciliation_artifact.py — Lane 2C phase-2 consumer #1:
    builds the observe-only cost-reconciliation artifact attached to the
    candidate_terminal_dispositions.detail jsonb by the (observe-only)
    disposition recorder. Nothing in the decision path reads that table.

Three locks:
1. Static sweep — no non-test, non-allowlisted module under packages/quantum
   imports cost_basis.
2. Allowlist integrity — every allowlisted module exists AND actually imports
   cost_basis (a slot cannot rot into permitting a module that never needed
   it), and the named decision modules are NEVER allowlisted.
3. Inertness — cost_basis itself has NO module-level packages.quantum
   imports (all production imports are lazy, inside extractor bodies), so
   importing it can never drag production modules in at import time.
"""

import ast
import re
import unittest
from pathlib import Path

REPO_QUANTUM = Path(__file__).resolve().parents[1]  # packages/quantum
COST_BASIS_FILE = REPO_QUANTUM / "analytics" / "cost_basis.py"

# Observe-only modules permitted to import cost_basis. POSIX-relative to
# packages/quantum. Keep this MINIMAL and reviewed — see the module docstring.
OBSERVE_ONLY_CONSUMERS = frozenset({
    "services/cost_reconciliation_artifact.py",
})

# Decision modules that must NEVER appear in the allowlist (belt-and-suspenders
# proof: the reconciliation artifact is provably out of the decision path).
_LOCKED_DECISION_MODULES = (
    "options_scanner.py",
    "analytics/scoring.py",
    "analytics/canonical_ranker.py",
    "paper_endpoints.py",
    "services/paper_exit_evaluator.py",
)

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
            rel_posix = rel.as_posix()
            if rel_posix in OBSERVE_ONLY_CONSUMERS:
                continue  # reviewed observe-only consumer (see docstring)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:  # pragma: no cover - unreadable file
                self.fail(f"could not read {rel}: {exc}")
            if _IMPORT_PATTERN.search(text):
                offenders.append(rel_posix)
        self.assertEqual(
            offenders, [],
            "non-allowlisted modules must NEVER import cost_basis (one-way "
            f"dependency); offenders: {offenders}",
        )

    def test_allowlist_integrity(self):
        # Every allowlisted slot must point at a real module that ACTUALLY
        # imports cost_basis — an allowlist entry cannot rot into permitting a
        # module that never needed the exception.
        for rel_posix in sorted(OBSERVE_ONLY_CONSUMERS):
            path = REPO_QUANTUM / rel_posix
            self.assertTrue(
                path.exists(),
                f"allowlisted observe-only consumer missing: {rel_posix}",
            )
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertIsNotNone(
                _IMPORT_PATTERN.search(text),
                f"allowlisted {rel_posix} does not import cost_basis — remove "
                "the stale slot",
            )
        # And no decision module may hide in the allowlist.
        for decision in _LOCKED_DECISION_MODULES:
            self.assertNotIn(
                decision, OBSERVE_ONLY_CONSUMERS,
                f"decision module {decision} must NEVER be allowlisted",
            )

    def test_decision_modules_do_not_import_cost_basis(self):
        # Direct proof that the reconciliation artifact stays out of the
        # decision path: the named gate/ranker/scanner/scoring/exit modules
        # never import cost_basis (transitively or otherwise, statically).
        for decision in _LOCKED_DECISION_MODULES:
            path = REPO_QUANTUM / decision
            if not path.exists():  # pragma: no cover - path drift guard
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(
                _IMPORT_PATTERN.search(text),
                f"decision module {decision} must NEVER import cost_basis",
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
