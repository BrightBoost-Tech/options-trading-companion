"""Tests for the startup effective-flag echo (P2 §3).

Coverage, per the build charter:
  1. registry-vs-code DRIFT — every allowlisted name is read by prod code, and
     every CLAUDE.md §3 canonical flag is in the registry (no phantom, no gap).
  2. parser-HONESTY — the echo's reported value equals the flag's REAL parser
     output for the tricky inputs the doctrine cares about ('', '0', 'false',
     'yes', '1 ', 'on', 'true'). Compared against INDEPENDENTLY-imported parser
     refs, so a registry entry pointing at the wrong function is caught.
  3. SCRUB — no non-allowlisted env name/value can reach the output (the echo
     never iterates os.environ); a secret-shaped registry name has its VALUE
     scrubbed.
  4. FAIL-SOFT — a per-flag parser exception is isolated; a total failure never
     raises and never blocks startup.
  5. WIRING — the real worker import route (jobs.runner) fires the echo; the
     echo emits exactly ONE block and is idempotent per process.

§9 discipline: the wiring test DRIVES the production import route (not a source
string / getsource assertion) and asserts on the OUTPUT (the call fired / the
block was logged).
"""
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from packages.quantum.observability import flag_echo
from packages.quantum.observability.flag_echo import (
    FlagSpec,
    SAFETY_DEFAULT_ON,
    collect_effective_flags,
    echo_effective_flags,
    registry_env_names,
    _is_secret_name,
)


# Independently-imported REAL parser refs (hardcoded here on purpose — if the
# registry points at a different function, the honesty test values diverge).
from packages.quantum.paper_endpoints import _entry_quote_validation_enabled
from packages.quantum.services.gtc_profit_exit import is_enabled as _gtc_is_enabled
from packages.quantum.risk.utilization_gate import is_enabled as _util_is_enabled
from packages.quantum.observability.feature_flags import is_iv_rank_none_routing_enabled


def _set_env(name, value):
    """Set or unset an env var; returns a patch.dict-style undo via os.environ."""
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


class TestRegistryDrift(unittest.TestCase):
    def test_registry_names_unique(self):
        names = registry_env_names()
        self.assertEqual(len(names), len(set(names)), "duplicate flag in registry")

    def test_every_registry_name_read_by_production_code(self):
        """No phantom flags: each allowlisted env-var name must actually be read
        somewhere in production code (the #1126 orphan-with-green-test class)."""
        pkg_root = Path(flag_echo.__file__).resolve().parents[1]  # packages/quantum
        prod_text = []
        for p in pkg_root.rglob("*.py"):
            parts = p.parts
            if "tests" in parts or p.name == "flag_echo.py":
                continue
            try:
                prod_text.append(p.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass
        blob = "\n".join(prod_text)
        missing = [n for n in registry_env_names() if n not in blob]
        self.assertEqual(missing, [], f"registry names not read by prod code: {missing}")

    def test_claude_md_canonical_flags_present(self):
        """CLAUDE.md §3 canonical lists must all be represented in the registry."""
        canonical_default_on = {
            "ENTRY_QUOTE_VALIDATION_ENABLED", "REENTRY_COOLDOWN_ENABLED",
            "CLOSE_REARM_ENABLED", "INTRADAY_COHORT_STOP_ENABLED",
            "CALIBRATION_STALENESS_TTL_ENABLED", "ENTRY_QUOTE_SOURCE_ALIGNED",
        }
        canonical_behavioral = {
            "RISK_UTILIZATION_GATE_ENABLED", "EXIT_MARK_SANITY_ENFORCE_ENABLED",
            "GTC_PROFIT_EXIT_ENABLED",
        }
        names = set(registry_env_names())
        self.assertTrue(canonical_default_on <= names,
                        f"missing §3 default-ON: {canonical_default_on - names}")
        self.assertTrue(canonical_behavioral <= names,
                        f"missing §3 behavioral: {canonical_behavioral - names}")


class TestParserHonesty(unittest.TestCase):
    """echo value == real parser output, for tricky inputs. Both go through the
    same function by design (anti-drift); the independent import catches a
    mis-wired registry entry."""

    TRICKY = ["", "0", "false", "no", "off", "1", "true", "yes", "on", "1 ", "TRUE"]

    def _assert_matches(self, flag_name, parser_ref):
        saved = os.environ.get(flag_name)
        try:
            for raw in self.TRICKY:
                _set_env(flag_name, raw)
                expected = parser_ref()
                got = collect_effective_flags()["flags"][flag_name]["value"]
                self.assertEqual(
                    got, expected,
                    f"{flag_name} raw={raw!r}: echo={got!r} != parser={expected!r}",
                )
        finally:
            _set_env(flag_name, saved)

    def test_default_on_safety_parse(self):
        self._assert_matches("ENTRY_QUOTE_VALIDATION_ENABLED", _entry_quote_validation_enabled)

    def test_lenient_truthy_full_parse(self):
        self._assert_matches("GTC_PROFIT_EXIT_ENABLED", _gtc_is_enabled)

    def test_strict_eq_1_parse(self):
        self._assert_matches("RISK_UTILIZATION_GATE_ENABLED", _util_is_enabled)

    def test_partial_lenient_parse(self):
        self._assert_matches("IV_RANK_NONE_ROUTING_ENABLED", is_iv_rank_none_routing_enabled)

    def test_hand_computed_doctrine_expectations(self):
        """Independent of the parser refs: the doctrine's own truth-table for a
        few well-understood cases, to catch echo+parser drifting together."""
        cases = [
            # default-ON: empty -> ON; explicit falsy -> OFF; unknown -> ON
            ("ENTRY_QUOTE_VALIDATION_ENABLED", "", True),
            ("ENTRY_QUOTE_VALIDATION_ENABLED", "0", False),
            ("ENTRY_QUOTE_VALIDATION_ENABLED", "false", False),
            ("ENTRY_QUOTE_VALIDATION_ENABLED", "yes", True),
            ("ENTRY_QUOTE_VALIDATION_ENABLED", "1 ", True),
            # strict ==1: 'true'/'yes' do NOT enable — the §3 footgun
            ("RISK_UTILIZATION_GATE_ENABLED", "1", True),
            ("RISK_UTILIZATION_GATE_ENABLED", "true", False),
            ("RISK_UTILIZATION_GATE_ENABLED", "yes", False),
            ("RISK_UTILIZATION_GATE_ENABLED", "", False),
            # lenient full truthy
            ("GTC_PROFIT_EXIT_ENABLED", "on", True),
            ("GTC_PROFIT_EXIT_ENABLED", "0", False),
        ]
        for name, raw, expected in cases:
            saved = os.environ.get(name)
            try:
                _set_env(name, raw)
                got = collect_effective_flags()["flags"][name]["value"]
                self.assertEqual(got, expected, f"{name} raw={raw!r} -> {got!r}, want {expected!r}")
            finally:
                _set_env(name, saved)

    def test_source_explicit_vs_default(self):
        saved = os.environ.get("GTC_PROFIT_EXIT_ENABLED")
        try:
            _set_env("GTC_PROFIT_EXIT_ENABLED", None)
            self.assertEqual(collect_effective_flags()["flags"]["GTC_PROFIT_EXIT_ENABLED"]["source"], "default")
            _set_env("GTC_PROFIT_EXIT_ENABLED", "")  # blank still 'default' per parser semantics
            self.assertEqual(collect_effective_flags()["flags"]["GTC_PROFIT_EXIT_ENABLED"]["source"], "default")
            _set_env("GTC_PROFIT_EXIT_ENABLED", "1")
            self.assertEqual(collect_effective_flags()["flags"]["GTC_PROFIT_EXIT_ENABLED"]["source"], "explicit")
        finally:
            _set_env("GTC_PROFIT_EXIT_ENABLED", saved)


class TestDarkControlEntries(unittest.TestCase):
    """The 7 dark/observe/experimental env controls added 2026-07-23 (Lane D).
    Each echo entry must reproduce its OWN production parser's polarity, both
    ways, and the startup collect path must remain DB-free."""

    # (flag_name, module, attr, production-call args) — the EXACT parser + call
    # site the echo entry reproduces (never a second/reimplemented parse).
    NEW = [
        ("QUANT_AGENTS_ENABLED", "packages.quantum.agents.runner",
         "is_agent_enabled", ("QUANT_AGENTS_ENABLED", False)),
        ("OI_ENRICHMENT_ENABLED", "packages.quantum.services.oi_enrichment",
         "is_oi_enrichment_enabled", ()),
        ("VOL_SIGNAL_OBSERVE_ENABLED", "packages.quantum.analytics.vol_signal",
         "is_observe_enabled", ()),
        ("REGIME_FILTER_OBSERVE_ENABLED", "packages.quantum.analytics.regime_filter",
         "is_observe_enabled", ()),
        ("RISK_BASIS_MAX_LOSS_ENABLED", "packages.quantum.services.risk_basis_shadow",
         "is_max_loss_basis_enabled", ()),
        ("BUCKET_CONTROL_ENFORCE", "packages.quantum.risk.bucket_control",
         "is_bucket_enforce_enabled", ()),
        ("FLEET_RECEIPT_PRODUCER_ENABLED", "packages.quantum.jobs.handlers.alpaca_order_sync",
         "_fleet_receipt_producer_enabled", ()),
    ]

    TRICKY = ["", "0", "false", "no", "off", "1", "true", "yes", "on", "1 ", "TRUE"]

    def test_all_seven_registered(self):
        names = set(registry_env_names())
        for flag_name, *_ in self.NEW:
            self.assertIn(flag_name, names, f"{flag_name} not registered")

    def test_each_entry_matches_its_real_parser_both_ways(self):
        """echo value == the flag's REAL production parser output across the
        tricky truth-table — catches a mis-wired module/attr or a second parse."""
        import importlib
        for flag_name, module, attr, args in self.NEW:
            parser = getattr(importlib.import_module(module), attr)
            saved = os.environ.get(flag_name)
            try:
                for raw in self.TRICKY:
                    _set_env(flag_name, raw)
                    expected = parser(*args)
                    got = collect_effective_flags()["flags"][flag_name]["value"]
                    self.assertEqual(
                        got, expected,
                        f"{flag_name} raw={raw!r}: echo={got!r} != parser={expected!r}",
                    )
            finally:
                _set_env(flag_name, saved)

    def test_polarity_hand_computed_both_ways(self):
        """Independent of the parser refs: the polarity truth-table, ON and OFF."""
        strict = ["RISK_BASIS_MAX_LOSS_ENABLED", "BUCKET_CONTROL_ENFORCE",
                  "FLEET_RECEIPT_PRODUCER_ENABLED"]
        lenient = ["OI_ENRICHMENT_ENABLED", "VOL_SIGNAL_OBSERVE_ENABLED",
                   "REGIME_FILTER_OBSERVE_ENABLED"]
        cases = []
        for f in strict:  # strict ==1: only '1' enables
            cases += [(f, "1", True), (f, "true", False), (f, "yes", False),
                      (f, "", False), (f, "0", False)]
        for f in lenient:  # lenient full truthy: 1/true/yes/on
            cases += [(f, "1", True), (f, "true", True), (f, "yes", True),
                      (f, "on", True), (f, "", False), (f, "0", False)]
        # agent tri-state: {1/true/yes}->on, {0/false/no}->off, 'on'/else->default(OFF)
        cases += [("QUANT_AGENTS_ENABLED", "1", True),
                  ("QUANT_AGENTS_ENABLED", "yes", True),
                  ("QUANT_AGENTS_ENABLED", "true", True),
                  ("QUANT_AGENTS_ENABLED", "no", False),
                  ("QUANT_AGENTS_ENABLED", "on", False),  # NOT recognized -> default OFF
                  ("QUANT_AGENTS_ENABLED", "", False)]
        for name, raw, expected in cases:
            saved = os.environ.get(name)
            try:
                _set_env(name, raw)
                got = collect_effective_flags()["flags"][name]["value"]
                self.assertEqual(got, expected,
                                 f"{name} raw={raw!r} -> {got!r}, want {expected!r}")
            finally:
                _set_env(name, saved)

    def test_new_entries_emit_bool_never_secret(self):
        data = collect_effective_flags()
        block = flag_echo._format_block("test", data)
        for flag_name, *_ in self.NEW:
            self.assertIn(flag_name, block, f"{flag_name} missing from block")
            # every value is a parsed bool — never a raw env string that could
            # carry a secret.
            self.assertIn(data["flags"][flag_name]["value"], (True, False))

    def test_startup_collect_makes_no_db_call(self):
        """The startup echo path (collect_effective_flags) must never build a DB
        client. Poison the supabase client constructor; collect must still return
        every flag as a real bool with ZERO errors — proving the new DB-adjacent
        controls are read via their ENV parser, not a startup DB read."""
        import importlib
        try:
            supabase = importlib.import_module("supabase")
        except Exception:  # pragma: no cover - supabase always present in CI
            supabase = None
        if supabase is not None and hasattr(supabase, "create_client"):
            ctx = mock.patch.object(
                supabase, "create_client",
                side_effect=AssertionError("DB touched in startup echo"))
        else:  # pragma: no cover
            ctx = mock.patch.object(flag_echo, "logger", flag_echo.logger)
        with ctx:
            data = collect_effective_flags()
        self.assertEqual(data["errors"], [], f"startup echo errored: {data['errors']}")
        for flag_name, *_ in self.NEW:
            self.assertIn(data["flags"][flag_name]["value"], (True, False))


class TestScrub(unittest.TestCase):
    def test_no_registry_name_is_secret_shaped(self):
        bad = [n for n in registry_env_names() if _is_secret_name(n)]
        self.assertEqual(bad, [], f"secret-shaped allowlisted names: {bad}")

    def test_nonallowlisted_secret_never_appears(self):
        """Proves the echo reads ONLY allowlisted names — an unrelated secret
        env var leaks neither its NAME nor its VALUE."""
        fake_name = "ZZZ_FAKE_SECRET_TOKEN"
        fake_val = "UNIQUE-ENV-LEAK-999"
        with mock.patch.dict(os.environ, {fake_name: fake_val}):
            data = collect_effective_flags()
            block = flag_echo._format_block("test", data)
        self.assertNotIn(fake_name, block)
        self.assertNotIn(fake_val, block)
        self.assertNotIn(fake_val, str(data))
        self.assertNotIn(fake_name, data["flags"])

    def test_secret_shaped_registry_value_scrubbed(self):
        """Defense in depth: even if a future registry entry names a secret-
        shaped var, its VALUE is scrubbed to '<scrubbed>'."""
        leaky = FlagSpec(
            name="MY_FAKE_API_KEY", module="packages.quantum.observability.flag_echo",
            attr="SAFETY_DEFAULT_ON", polarity=SAFETY_DEFAULT_ON, parse_style="x",
            doc="test", call=False, transform=lambda _: "UNIQUE-LEAK-TOKEN-XYZ",
        )
        with mock.patch.object(flag_echo, "_REGISTRY", [leaky]):
            data = collect_effective_flags()
            block = flag_echo._format_block("test", data)
        self.assertEqual(data["flags"]["MY_FAKE_API_KEY"]["value"], "<scrubbed>")
        self.assertNotIn("UNIQUE-LEAK-TOKEN-XYZ", block)


class TestFailSoft(unittest.TestCase):
    def test_per_flag_error_isolated(self):
        """One broken parser records an error sentinel; other flags still read."""
        good = FlagSpec(
            name="ENTRY_QUOTE_VALIDATION_ENABLED", module="packages.quantum.paper_endpoints",
            attr="_entry_quote_validation_enabled", polarity=SAFETY_DEFAULT_ON,
            parse_style="x", doc="ok",
        )
        bad = FlagSpec(
            name="SCHEDULER_ENABLED", module="packages.quantum.does_not_exist_xyz",
            attr="nope", polarity="global_switch", parse_style="x", doc="bad",
        )
        with mock.patch.object(flag_echo, "_REGISTRY", [good, bad]):
            data = collect_effective_flags()
        self.assertEqual(data["flags"]["ENTRY_QUOTE_VALIDATION_ENABLED"]["value"], True)
        self.assertTrue(str(data["flags"]["SCHEDULER_ENABLED"]["value"]).startswith("<error:"))
        self.assertEqual(len(data["errors"]), 1)

    def test_total_failure_never_raises(self):
        """A total failure inside echo returns an empty dict + WARNING, never
        raising — startup must not be blocked by the echo."""
        with mock.patch.object(flag_echo, "collect_effective_flags", side_effect=RuntimeError("boom")):
            with self.assertLogs("packages.quantum.observability.flag_echo", level="WARNING") as cm:
                out = echo_effective_flags(process="failtest", force=True)
        self.assertEqual(out["flag_count"], 0)
        self.assertIn("echo_failed", out["errors"])
        self.assertTrue(any("flag echo failed" in m for m in cm.output))


class TestEchoLoggingAndIdempotence(unittest.TestCase):
    def setUp(self):
        flag_echo._echoed_processes.discard("p1")
        flag_echo._echoed_processes.discard("blocktest")

    def test_logs_exactly_one_block_with_all_flags(self):
        with self.assertLogs("packages.quantum.observability.flag_echo", level="INFO") as cm:
            echo_effective_flags(process="blocktest", force=True)
        headers = [r for r in cm.output if "effective behavioral/safety flags" in r]
        self.assertEqual(len(headers), 1, "expected exactly one echo block")
        block = "\n".join(cm.output)
        for name in registry_env_names():
            self.assertIn(name, block, f"{name} missing from block")

    def test_idempotent_once_per_process(self):
        with self.assertLogs("packages.quantum.observability.flag_echo", level="INFO") as cm:
            first = echo_effective_flags(process="p1")
            second = echo_effective_flags(process="p1")  # no force -> skipped
        headers = [r for r in cm.output if "effective behavioral/safety flags" in r]
        self.assertEqual(len(headers), 1)
        self.assertGreater(first["flag_count"], 0)
        self.assertEqual(second.get("skipped"), "already_echoed")


import subprocess  # noqa: E402


_REPO_ROOT = Path(flag_echo.__file__).resolve().parents[3]  # -> repo root


def _import_route_stdout(module: str, extra_env=None):
    """Drive the REAL production import route in a FRESH subprocess and return
    its combined stdout+stderr.

    Why a subprocess and not an in-process import/reload: the wiring fires at
    MODULE IMPORT. Popping + re-importing api/runner in-process mutates the
    shared sys.modules a whole test session depends on — that pollution broke
    the rebalance contract tests when this file ran before them. A fresh
    process drives the exact production route (`import <module>`) with ZERO
    in-process side effects, and asserts on the real logged OUTPUT (§9: drive
    the route, assert the output — never a source-string / getsource pin).

    PYTHONUTF8=1 so api.py's emoji startup prints don't UnicodeError on a
    Windows cp1252 stdout (Linux CI stdout is already UTF-8). The echo line at
    api.py module scope fires BEFORE the later router imports, so its block is
    captured even if a downstream import (e.g. the Windows 'fork' class) then
    crashes — proving the wiring regardless of full-import success.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.setdefault("PYTHONPATH", str(_REPO_ROOT))
    # Placeholders so api's startup config validation reaches the echo line.
    for k, v in {
        "SUPABASE_JWT_SECRET": "test-secret",
        "NEXT_PUBLIC_SUPABASE_URL": "http://localhost:54321",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "SUPABASE_SERVICE_ROLE_KEY": "test-service-key",
        "ENCRYPTION_KEY": "ke2AXS883XK_QFY9uLNGUiQlce1MifOaZNmmn06eoC8=",
        "TASK_SIGNING_SECRET": "test-task-secret",
        "POLYGON_API_KEY": "test-polygon-key",
    }.items():
        env.setdefault(k, v)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(_REPO_ROOT), env=env, timeout=180,
    )
    return (proc.stdout or "") + (proc.stderr or "")


class TestWorkerWiringRoute(unittest.TestCase):
    """DRIVE the real both-workers import route (jobs.runner module-level call)
    in a fresh process; assert the echo block was emitted with process=worker."""

    def test_runner_import_fires_echo(self):
        out = _import_route_stdout("packages.quantum.jobs.runner")
        self.assertIn("[FLAG_ECHO]", out, f"no echo block on worker route:\n{out[-2000:]}")
        self.assertIn("process=worker", out)


class TestBackendWiringRoute(unittest.TestCase):
    """DRIVE the real BE import route (api module-level call) in a fresh
    process; assert the echo block was emitted with process=backend. The echo
    fires before router imports, so a later Windows-only 'fork' crash does not
    hide it."""

    def test_api_import_fires_echo(self):
        out = _import_route_stdout("packages.quantum.api")
        self.assertIn("[FLAG_ECHO]", out, f"no echo block on BE route:\n{out[-2000:]}")
        self.assertIn("process=backend", out)


if __name__ == "__main__":
    unittest.main()
