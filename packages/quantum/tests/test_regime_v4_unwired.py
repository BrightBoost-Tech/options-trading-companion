"""Pins for the 2026-06-07 regime V4 honesty fixes.

Three facts, each previously misdocumented:
1. RegimeEngineV4 is BUILT BUT UNWIRED — zero production callers. If this
   pin breaks because someone wired V4, that's a deliberate decision:
   update CLAUDE.md's flag table and this test together.
2. REGIME_V4_ENABLED is read by exactly one function (the unwired
   module's own is_regime_v4_enabled) — setting the env var changes
   nothing in production today.
3. The v3 engine reports engine_version "v3" (it claimed "v4" — a label
   collision with the separate continuous-vector V4 engine that misled
   audits, e.g. the 2026-06-06 feasibility read had to disprove it).
"""

import os
import unittest

_QUANTUM_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SKIP_DIRS = {"tests", ".venv", "venv", "__pycache__", "node_modules"}


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

    def test_no_production_module_references_regime_engine_v4(self):
        """Zero-caller census: only regime_engine_v4.py itself may import or
        instantiate the V4 engine / call its flag helper. A new executable
        reference = V4 got wired = update CLAUDE.md + this pin together."""
        offenders = []
        for path in _production_py_files():
            if os.path.basename(path) == "regime_engine_v4.py":
                continue
            with open(path, encoding="utf-8", errors="ignore") as fh:
                content = fh.read()
            for needle in self._WIRING_NEEDLES:
                if needle in content:
                    offenders.append(f"{os.path.relpath(path, _QUANTUM_ROOT)}: {needle}")
        self.assertEqual(
            offenders, [],
            "RegimeEngineV4 is documented as UNWIRED; production references "
            f"found (wire deliberately + update docs): {offenders}",
        )

    def test_regime_v4_flag_read_only_by_its_own_module(self):
        """REGIME_V4_ENABLED must have exactly one production reader — the
        unwired module's own helper. The env var is otherwise a no-op."""
        readers = []
        for path in _production_py_files():
            with open(path, encoding="utf-8", errors="ignore") as fh:
                if "REGIME_V4_ENABLED" in fh.read():
                    readers.append(os.path.basename(path))
        self.assertEqual(readers, ["regime_engine_v4.py"])


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
