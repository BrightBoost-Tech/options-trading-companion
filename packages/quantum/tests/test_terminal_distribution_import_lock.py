"""Import-lock guardrail: the ⑤ terminal-distribution package is OBSERVE-ONLY.

Nothing in the live economics path (scanner / orchestrator / ranker / stage
seam / executor — nor ANY production module) may import or reference the
challenger/evaluator package. The only permitted coupling direction is
terminal_distribution -> packages.quantum.ev_calculator (frozen baselines
wrapping production read-only). Production -> ev_calculator wiring is
unchanged and separately asserted.

Grep-based on purpose: a source-level lock catches lazy/function-level imports
that an import-graph probe would miss. (This is a NEGATIVE lock — asserting
the ABSENCE of a reference — not a wiring test; the #1126 source-pin doctrine
targets POSITIVE wiring claims, which live in the behavioral suites.)
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
QUANTUM = REPO_ROOT / "packages" / "quantum"
PACKAGE_DIR = QUANTUM / "analytics" / "terminal_distribution"
TESTS_DIR = QUANTUM / "tests"

MARKER = "terminal_distribution"

# The named live-economics modules from the ⑤ charter.
LIVE_ECONOMICS_MODULES = [
    QUANTUM / "options_scanner.py",
    QUANTUM / "services" / "workflow_orchestrator.py",
    QUANTUM / "analytics" / "canonical_ranker.py",
    QUANTUM / "paper_endpoints.py",
    QUANTUM / "services" / "paper_autopilot_service.py",
]


def test_charter_modules_exist():
    """If one of these moves, the lock below silently weakens — fail loudly."""
    for path in LIVE_ECONOMICS_MODULES:
        assert path.is_file(), f"charter module missing: {path}"


def test_live_economics_modules_never_reference_the_package():
    offenders = []
    for path in LIVE_ECONOMICS_MODULES:
        text = path.read_text(encoding="utf-8", errors="replace")
        if MARKER in text:
            offenders.append(str(path))
    assert not offenders, (
        f"OBSERVE-ONLY VIOLATION: live-economics module(s) reference "
        f"'{MARKER}': {offenders}"
    )


def test_no_production_module_references_the_package():
    """Full-tree sweep: no .py under packages/quantum outside the package
    itself and the test suite may mention the package at all."""
    offenders = []
    for path in QUANTUM.rglob("*.py"):
        if PACKAGE_DIR in path.parents:
            continue
        if TESTS_DIR in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if MARKER in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"OBSERVE-ONLY VIOLATION: production module(s) reference '{MARKER}': "
        f"{offenders}"
    )


def test_wrap_direction_is_package_to_ev_calculator_only():
    """baselines.py wraps production read-only; ev_calculator must not know
    the package exists (no reverse coupling)."""
    baselines = (PACKAGE_DIR / "baselines.py").read_text(encoding="utf-8")
    assert "from packages.quantum import ev_calculator" in baselines
    ev_calc = (QUANTUM / "ev_calculator.py").read_text(encoding="utf-8")
    assert MARKER not in ev_calc


def test_production_ev_calculator_wiring_unchanged():
    """The scanner still consumes production condor EV directly — the frozen
    baselines did not reroute or shadow the production call path."""
    scanner = (QUANTUM / "options_scanner.py").read_text(encoding="utf-8")
    assert "calculate_condor_ev" in scanner
    assert "CONDOR_EV_MODEL" in scanner


def test_package_never_imports_live_economics_or_jobs():
    """Reverse direction of the lock: the observe-only package must not reach
    into the scanner/executor/jobs/DB (only ev_calculator + its own modules).
    Scans IMPORT LINES (docstrings may cite production files by name as
    pointers — pointers are doctrine; imports are coupling)."""
    forbidden = (
        "options_scanner",
        "paper_autopilot_service",
        "canonical_ranker",
        "paper_endpoints",
        "workflow_orchestrator",
        "opportunity_scorer",
        ".jobs",
        "supabase",
    )
    offenders = []
    for path in PACKAGE_DIR.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not (stripped.startswith("import ") or stripped.startswith("from ")):
                continue
            for token in forbidden:
                if token in stripped:
                    offenders.append(f"{path.name}:{lineno}: {stripped}")
    assert not offenders, f"package reached into production/jobs/DB: {offenders}"
