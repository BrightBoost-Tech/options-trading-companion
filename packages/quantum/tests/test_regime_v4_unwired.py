"""Pins for the regime V4 honesty facts (2026-06-07), updated 2026-07-23 for the
Audit-B observe-only wiring.

Facts pinned:
1. RegimeEngineV4 has NO callers in the LIVE DECISION PATH — the scanner,
   orchestrator, selector, allocator, and executor carry ZERO V4-engine
   references. The ONLY production module that references the V4 engine is the
   census-allowlisted observe SCORER (regime_v4_shadow_compare.py), which runs
   on the `background` queue as an OBSERVE-ONLY parallel comparison and never
   touches a live decision. (Pre-Audit-B this was "zero callers ANYWHERE"; the
   deliberate observe wiring — authorized by this pin's own contract — converts
   it to "zero in the live path + one allowlisted observe scorer".)
2. REGIME_V4_ENABLED is read by exactly one function (the unwired module's own
   is_regime_v4_enabled) — setting that env var changes nothing today. The
   observe arc uses a SEPARATE flag (REGIME_V4_OBSERVE_ENABLED), so this
   single-reader fact is UNCHANGED.
3. The v3 engine reports engine_version "v3" (it claimed "v4" — a label
   collision with the separate continuous-vector V4 engine that misled audits).
"""

import os
import re
import unittest

_QUANTUM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {"tests", ".venv", "venv", "__pycache__", "node_modules"}

# The V4 engine itself + the census-allowlisted OBSERVE-ONLY scorer. These are
# the ONLY production files permitted to reference RegimeEngineV4. The scorer
# runs on the background queue after the live cycle returns, on copies of
# captured inputs — it cannot influence a live decision. Adding a THIRD file
# here is a deliberate act that requires updating CLAUDE.md's flag table + this
# pin together (per the contract in this docstring).
_V4_ENGINE_ALLOWLIST = {"regime_engine_v4.py", "regime_v4_shadow_compare.py"}

# The live DECISION-PATH modules — these must ALWAYS carry zero V4-engine
# references (the observe arc reaches them only through the V4-free capture seam
# regime_v4_shadow_capture.py, never the engine).
_LIVE_DECISION_PATH = (
    ("options_scanner.py",),
    ("services", "workflow_orchestrator.py"),
    ("analytics", "strategy_selector.py"),
    ("analytics", "canonical_ranker.py"),
    ("services", "paper_autopilot_service.py"),
    ("services", "analytics", "small_account_compounder.py"),
)


def _production_py_files():
    for root, dirs, files in os.walk(_QUANTUM_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(root, f)


class TestRegimeV4Unwired(unittest.TestCase):
    # Executable references only — an import or an instantiation. Comment
    # MENTIONS (e.g. the v3 file's disambiguation note) are allowed; a
    # comment can't wire anything.
    _WIRING_NEEDLES = (
        "import regime_engine_v4",
        "from packages.quantum.analytics.regime_engine_v4",
        "RegimeEngineV4(",
        "is_regime_v4_enabled(",
    )

    def test_only_allowlisted_modules_reference_regime_engine_v4(self):
        """Census: only the V4 engine itself + the allowlisted OBSERVE-ONLY scorer
        may import or instantiate the V4 engine / call its flag helper. A new
        executable reference in ANY other module = V4 got wired into a new path =
        update CLAUDE.md + _V4_ENGINE_ALLOWLIST here together."""
        offenders = []
        for path in _production_py_files():
            if os.path.basename(path) in _V4_ENGINE_ALLOWLIST:
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for needle in self._WIRING_NEEDLES:
                if needle in content:
                    offenders.append(f"{os.path.relpath(path, _QUANTUM_ROOT)}: {needle}")
        self.assertEqual(
            offenders, [],
            "RegimeEngineV4 may only be referenced by the allowlisted observe "
            f"scorer; new production references found: {offenders}",
        )

    def test_live_decision_path_has_zero_v4_engine_references(self):
        """The stronger invariant the observe wiring must preserve: the LIVE
        decision path (scanner / orchestrator / selector / ranker / allocator /
        executor) contains ZERO V4-engine references. The observe arc reaches
        these modules only through the V4-FREE capture seam
        (regime_v4_shadow_capture.py), never RegimeEngineV4 — so a real wiring of
        V4 into a live decision would trip THIS assertion even if someone added a
        new allowlist entry."""
        offenders = []
        for parts in _LIVE_DECISION_PATH:
            path = os.path.join(_QUANTUM_ROOT, *parts)
            if not os.path.isfile(path):
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for needle in self._WIRING_NEEDLES:
                if needle in content:
                    offenders.append(f"{os.path.join(*parts)}: {needle}")
        self.assertEqual(
            offenders, [],
            f"live decision path must carry zero V4-engine references: {offenders}",
        )

    def test_regime_v4_flag_read_only_by_its_own_module(self):
        """REGIME_V4_ENABLED must have exactly one production READER — the unwired
        module's own helper. An EXECUTABLE read (os.environ.get / os.getenv on the
        exact var) is what counts; a doc/comment MENTION does not wire anything
        (e.g. the observe capture seam names the flag only to say it does NOT
        repurpose it). The distinct observe flag REGIME_V4_OBSERVE_ENABLED is a
        different var and does not match ``REGIME_V4_ENABLED`` as a whole token."""
        # Match an executable env read of EXACTLY REGIME_V4_ENABLED (word boundary
        # after the name → REGIME_V4_OBSERVE_ENABLED never matches).
        reader_re = re.compile(
            r"os\.(?:environ\.get|getenv)\(\s*[\"']REGIME_V4_ENABLED[\"']"
        )
        readers = []
        for path in _production_py_files():
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if reader_re.search(fh.read()):
                    readers.append(os.path.basename(path))
        self.assertEqual(sorted(readers), ["regime_engine_v4.py"])


class TestV3ReportsV3(unittest.TestCase):
    def test_v3_engine_version_is_v3(self):
        """The naming-collision fix: the file named v3 reports v3. (Source
        pin, matching test_regime_engine_v3_schema.py's no-heavy-import
        convention.)"""
        path = os.path.join(_QUANTUM_ROOT, "analytics", "regime_engine_v3.py")
        with open(path, encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn('ENGINE_VERSION = "v3"', content)
        self.assertNotIn('ENGINE_VERSION = "v4"', content)

    def test_v4_engine_keeps_its_own_version_label(self):
        path = os.path.join(_QUANTUM_ROOT, "analytics", "regime_engine_v4.py")
        with open(path, encoding="utf-8") as fh:
            self.assertIn('engine_version: str = "v4_continuous"', fh.read())


if __name__ == "__main__":
    unittest.main()
