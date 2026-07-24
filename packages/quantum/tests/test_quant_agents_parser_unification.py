"""E4 (2026-07-23): QUANT_AGENTS_ENABLED single-parser unification.

DEFECT (audit-D §E4, VERIFIED-CODE): the master toggle ``QUANT_AGENTS_ENABLED``
was read by TWO divergent production parsers —

  * Site A (canonical): ``packages/quantum/agents/runner.py``
        ``is_agent_enabled("QUANT_AGENTS_ENABLED", default=False)``  # tri-state
        {1,true,yes}->ON · {0,false,no}->OFF · unknown->default · strip()+lower()
  * Site B (divergent): ``packages/quantum/services/workflow_orchestrator.py``
        ``os.getenv("QUANT_AGENTS_ENABLED", "false").lower() == "true"``  # strict

Setting ``=1`` / ``yes`` / ``" true "`` built the agent pipeline (scanner+design
phases ON via Site A) while the orchestrator sizing branch (Site B) read OFF — a
split-brain, half-on state on the live entry-suggestion path
(``run_midday_cycle`` -> per-candidate sizing).

FIX: route Site B through the SAME canonical ``is_agent_enabled`` parser. The
import at the Site-B seam is deliberately FUNCTION-LOCAL so that
``workflow_orchestrator``'s module-level import block stays byte-identical to
``origin/main`` (a module-level add there shifted pytest's collection/import
order and tipped a pre-existing, order-sensitive test-isolation seam in the
executor suites). Because Site B does ``from packages.quantum.agents.runner
import is_agent_enabled``, its parser is the SAME function object this test
imports from ``runner`` — so the truth-table assertions below exercise the exact
callable the orchestrator seam calls.

Proof layers (CLAUDE.md §10 — labelled per group):
  * Canonical parser truth table  — VERIFIED-CODE (executes the real parser
    object that BOTH sites now call).
  * Runner seam (build_agent_pipeline) — VERIFIED-CODE, end-to-end route
    (current unset value -> agents OFF; previously-divergent inputs -> ON).
  * Orchestrator seam (Site B) — AST guard on ``run_midday_cycle``: it imports
    ``is_agent_enabled`` from the canonical runner module and calls it with the
    verbatim production args, and the divergent inline ``== "true"`` parser is
    gone. (The full ``run_midday_cycle`` end-to-end harness,
    ``test_workflow_orchestrator_agent_persistence.py``, is skip-quarantined
    under #769 and is deliberately NOT unskipped here.)
"""
import ast
import inspect
import os

import pytest

from packages.quantum.agents.runner import build_agent_pipeline, is_agent_enabled
# imported ONLY to read source for the Site-B AST guard — never for a
# `wo_mod.is_agent_enabled` reference (the seam import is function-local by design)
from packages.quantum.services import workflow_orchestrator as wo_mod


_ENV = "QUANT_AGENTS_ENABLED"
_CANONICAL_MODULE = "packages.quantum.agents.runner"
_UNSET = object()  # sentinel distinct from any string value


class _env:
    """Context manager: set (or, for the _UNSET sentinel, remove)
    QUANT_AGENTS_ENABLED, restoring the prior value on exit."""

    def __init__(self, value):
        self._value = value
        self._had = False
        self._prev = None

    def __enter__(self):
        self._had = _ENV in os.environ
        self._prev = os.environ.get(_ENV)
        if self._value is _UNSET:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = self._value
        return self

    def __exit__(self, *exc):
        if self._had:
            os.environ[_ENV] = self._prev
        else:
            os.environ.pop(_ENV, None)
        return False


# ── The audit-D §E4 truth table: raw env value -> canonical parser result ────
# ON  == is_agent_enabled(default=False) is True
# The three inputs marked DIVERGENT were previously OFF at Site B; after the fix
# both sites read them as ON (toward the canonical interpretation).
_ON_INPUTS = ["true", "True", "TRUE", "1", "yes", "Yes", " true "]
_OFF_INPUTS = ["", "0", "false", "False", "FALSE", "no", "on", "garbage"]
_DIVERGENT_INPUTS = ["1", "yes", " true "]  # OFF under the old Site B, ON now


# ─────────────────────────────────────────────────────────────────────────────
# 1. Canonical parser truth table (VERIFIED-CODE — executes the real parser
#    object that BOTH sites now call).
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", _ON_INPUTS)
def test_canonical_parser_on(value):
    with _env(value):
        assert is_agent_enabled(_ENV, default=False) is True


@pytest.mark.parametrize("value", _OFF_INPUTS)
def test_canonical_parser_off(value):
    with _env(value):
        assert is_agent_enabled(_ENV, default=False) is False


def test_canonical_parser_unset_is_off():
    with _env(_UNSET):
        assert _ENV not in os.environ
        assert is_agent_enabled(_ENV, default=False) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Orchestrator seam (Site B) routes through the canonical parser — AST guard.
#    Proves run_midday_cycle imports is_agent_enabled from the runner module and
#    calls it with the production args, and the divergent inline parser is gone.
# ─────────────────────────────────────────────────────────────────────────────
def _run_midday_cycle_node():
    src = inspect.getsource(wo_mod)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run_midday_cycle":
            return node, src
    raise AssertionError("run_midday_cycle not found in workflow_orchestrator")


def test_orchestrator_seam_imports_canonical_parser():
    node, _ = _run_midday_cycle_node()
    imports_canonical = any(
        isinstance(n, ast.ImportFrom)
        and n.module == _CANONICAL_MODULE
        and any(a.name == "is_agent_enabled" for a in n.names)
        for n in ast.walk(node)
    )
    assert imports_canonical, (
        "run_midday_cycle must import is_agent_enabled from "
        f"{_CANONICAL_MODULE} (the canonical tri-state parser)"
    )


def test_orchestrator_seam_calls_canonical_parser_with_production_args():
    node, src = _run_midday_cycle_node()
    seg = ast.get_source_segment(src, node) or ""
    assert 'is_agent_enabled("QUANT_AGENTS_ENABLED", default=False)' in seg


def test_no_divergent_inline_parser_remains_in_orchestrator():
    """Regression guard: the old strict ``== "true"`` inline read of this env var
    must be gone from the orchestrator module entirely."""
    src = inspect.getsource(wo_mod)
    assert 'os.getenv("QUANT_AGENTS_ENABLED"' not in src
    assert '"QUANT_AGENTS_ENABLED", "false"' not in src


def test_flag_echo_registry_resolves_to_the_same_parser():
    """The startup FLAG_ECHO master-toggle spec must call the SAME parser object,
    so the echo can never drift from the two decision sites."""
    import importlib

    from packages.quantum.observability import flag_echo

    specs = [s for s in flag_echo._REGISTRY if s.name == _ENV]
    assert len(specs) == 1, "expected exactly one QUANT_AGENTS_ENABLED FlagSpec"
    spec = specs[0]
    parser = getattr(importlib.import_module(spec.module), spec.attr)
    assert parser is is_agent_enabled


# ─────────────────────────────────────────────────────────────────────────────
# 3. Runner seam — end-to-end route (VERIFIED-CODE): the gate build_agent_pipeline
#    actually reads. Current unset value -> agents OFF; divergent inputs -> ON.
# ─────────────────────────────────────────────────────────────────────────────
def test_runner_route_unset_yields_agents_off():
    with _env(_UNSET):
        assert _ENV not in os.environ
        assert build_agent_pipeline("all") == []
        assert build_agent_pipeline("scanner") == []


@pytest.mark.parametrize("value", _OFF_INPUTS)
def test_runner_route_off_inputs_yield_empty_pipeline(value):
    with _env(value):
        assert build_agent_pipeline("all") == []


@pytest.mark.parametrize("value", _ON_INPUTS)
def test_runner_route_on_inputs_build_pipeline(value):
    with _env(value):
        assert len(build_agent_pipeline("all")) > 0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Both seams agree on every input. The orchestrator seam calls exactly this
#    `is_agent_enabled` object (its function-local import binds the same name
#    from the same runner module), so comparing it against the runner pipeline
#    decision pins that the two sites move together — including on the three
#    previously-divergent inputs the old Site-B parser read as OFF.
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("value", _DIVERGENT_INPUTS)
def test_divergent_inputs_now_on_at_both_seams(value):
    with _env(value):
        assert is_agent_enabled(_ENV, default=False) is True  # orchestrator gate
        assert len(build_agent_pipeline("all")) > 0            # runner pipeline


@pytest.mark.parametrize("value", _ON_INPUTS + _OFF_INPUTS)
def test_both_seams_agree_on_every_input(value):
    with _env(value):
        gate_on = is_agent_enabled(_ENV, default=False)       # orchestrator gate
        pipeline_on = len(build_agent_pipeline("all")) > 0     # runner pipeline
        assert gate_on == pipeline_on
