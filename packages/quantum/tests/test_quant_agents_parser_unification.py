"""E4 (2026-07-23): QUANT_AGENTS_ENABLED single-parser unification.

DEFECT (audit-D §E4, VERIFIED-CODE at 61fd50ee): the master toggle
``QUANT_AGENTS_ENABLED`` was read by TWO divergent production parsers —

  * Site A (canonical): ``packages/quantum/agents/runner.py:29``
        ``is_agent_enabled("QUANT_AGENTS_ENABLED", default=False)``  # tri-state
        {1,true,yes}->ON · {0,false,no}->OFF · unknown->default · strip()+lower()
  * Site B (divergent): ``packages/quantum/services/workflow_orchestrator.py:3370``
        ``os.getenv("QUANT_AGENTS_ENABLED", "false").lower() == "true"``  # strict

Setting ``=1`` / ``yes`` / ``" true "`` built the agent pipeline (scanner+design
phases ON via Site A) while the orchestrator sizing branch (Site B) read OFF — a
split-brain, half-on state on the live entry-suggestion path
(``run_midday_cycle`` -> per-candidate sizing).

FIX: route Site B through the SAME canonical ``is_agent_enabled`` parser. A single
parser now governs both sites and matches the startup FLAG_ECHO
(``observability/flag_echo.py``), which already ratified ``is_agent_enabled`` as
the master-toggle parser.

Proof layers (CLAUDE.md §10 — labelled per assertion group):
  * Canonical parser truth table  — VERIFIED-CODE (executes the real parser).
  * Runner seam (build_agent_pipeline) — VERIFIED-CODE, end-to-end route.
  * Orchestrator seam (Site B) — object-IDENTITY to the canonical parser (the
    bare ``is_agent_enabled`` name at :3370 resolves to the module global that
    IS ``runner.is_agent_enabled``) + execution of that bound object with the
    verbatim production args + source-absence of the divergent inline pattern.
    The full ``run_midday_cycle`` end-to-end harness
    (``test_workflow_orchestrator_agent_persistence.py``) is skip-quarantined
    under #769 ("Cluster C mock wiring drift") and is deliberately NOT unskipped
    here.
  * FLAG_ECHO tie — the registry spec resolves to the SAME parser object.
"""
import importlib
import inspect
import os
import re
from contextlib import contextmanager

import pytest

from packages.quantum.agents import runner as runner_mod
from packages.quantum.agents.runner import build_agent_pipeline, is_agent_enabled
from packages.quantum.services import workflow_orchestrator as wo_mod


_ENV = "QUANT_AGENTS_ENABLED"
_UNSET = object()  # sentinel distinct from any string value


@contextmanager
def _env(value):
    """Set (or, for the _UNSET sentinel, remove) QUANT_AGENTS_ENABLED.

    ``patch.dict`` snapshots os.environ on enter and fully restores it on exit,
    so mutating the key inside is always reverted.
    """
    from unittest.mock import patch

    with patch.dict(os.environ, clear=False):
        if value is _UNSET:
            os.environ.pop(_ENV, None)
        else:
            os.environ[_ENV] = value
        yield


# ── The audit-D §E4 truth table: raw env value -> canonical parser result ────
# ON  == is_agent_enabled(default=False) is True
# The three inputs marked DIVERGENT were previously OFF at Site B; after the fix
# both sites read them as ON (toward the canonical interpretation).
_ON_INPUTS = ["true", "True", "TRUE", "1", "yes", "Yes", " true "]
_OFF_INPUTS = ["", "0", "false", "False", "FALSE", "no", "on", "garbage"]
_DIVERGENT_INPUTS = ["1", "yes", " true "]  # OFF under the old Site B, ON now
_UNSET_EXPECT_OFF = _UNSET


# ─────────────────────────────────────────────────────────────────────────────
# 1. Canonical parser truth table (VERIFIED-CODE — executes the real parser)
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
    with _env(_UNSET_EXPECT_OFF):
        assert _ENV not in os.environ
        assert is_agent_enabled(_ENV, default=False) is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Both sites now share ONE parser object (kills the split-brain by identity)
# ─────────────────────────────────────────────────────────────────────────────
def test_orchestrator_binds_the_canonical_parser_object():
    """The name ``is_agent_enabled`` used at workflow_orchestrator.py:3370
    resolves to the module global, which must BE runner.is_agent_enabled — not a
    local reimplementation. Identity, not a source string."""
    assert wo_mod.is_agent_enabled is runner_mod.is_agent_enabled


def test_no_divergent_inline_parser_remains_in_orchestrator():
    """Regression guard: the old strict ``== "true"`` inline read of this env var
    must be gone from the orchestrator, and the canonical call must be present."""
    src = inspect.getsource(wo_mod)
    divergent = re.compile(
        r"""getenv\(\s*["']QUANT_AGENTS_ENABLED["'][^)]*\)\s*\.lower\(\)\s*==\s*["']true["']"""
    )
    assert divergent.search(src) is None, "divergent inline == 'true' parser reintroduced"
    assert 'is_agent_enabled("QUANT_AGENTS_ENABLED", default=False)' in src


def test_flag_echo_registry_resolves_to_the_same_parser():
    """The startup FLAG_ECHO master-toggle spec must call the SAME parser object,
    so the echo can never drift from the two decision sites."""
    from packages.quantum.observability import flag_echo

    specs = [s for s in flag_echo._REGISTRY if s.name == _ENV]
    assert len(specs) == 1, "expected exactly one QUANT_AGENTS_ENABLED FlagSpec"
    spec = specs[0]
    parser = getattr(importlib.import_module(spec.module), spec.attr)
    assert parser is runner_mod.is_agent_enabled


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
# 4. Orchestrator seam — the production statement's parser + args, executed.
#    Because test #2 proves wo_mod.is_agent_enabled IS runner.is_agent_enabled,
#    this calls the exact callable that workflow_orchestrator.py:3370 calls, with
#    the verbatim production arguments ("QUANT_AGENTS_ENABLED", default=False).
# ─────────────────────────────────────────────────────────────────────────────
def test_orchestrator_gate_unset_is_off():
    with _env(_UNSET):
        assert _ENV not in os.environ
        assert wo_mod.is_agent_enabled(_ENV, default=False) is False


@pytest.mark.parametrize("value", _DIVERGENT_INPUTS)
def test_orchestrator_gate_matches_runner_on_divergent_inputs(value):
    """The three previously-divergent inputs now read ON at BOTH seams (the fix).
    Under the OLD Site B parser these were OFF while the runner built agents."""
    with _env(value):
        orch = wo_mod.is_agent_enabled(_ENV, default=False)
        run = is_agent_enabled(_ENV, default=False)
        assert orch is True
        assert orch == run
        assert len(build_agent_pipeline("all")) > 0  # runner agrees: ON


@pytest.mark.parametrize("value", _ON_INPUTS + _OFF_INPUTS)
def test_both_seams_agree_on_every_input(value):
    """Full agreement: the orchestrator gate and the runner pipeline decision
    move together for every input in the truth table."""
    with _env(value):
        orch_on = wo_mod.is_agent_enabled(_ENV, default=False)
        runner_on = len(build_agent_pipeline("all")) > 0
        assert orch_on == runner_on
