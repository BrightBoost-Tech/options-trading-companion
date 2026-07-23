"""Startup effective-behavioral-flag echo (P2 §3, 2026-07-16).

CLAUDE.md §3 ends "Startup flag-echo is backlogged (P2)"; deploy doctrine (§2)
requires flags be *read-back-confirmed on the RUNNING process*, which today
means manual Railway inspection. This module closes that gap: at process
startup each behavioral/safety flag's EFFECTIVE PARSED value (the boolean the
code will actually use — not the raw env string), its polarity class, and
whether it was set-explicitly vs defaulted are logged in ONE structured,
greppable INFO block (prefix ``[FLAG_ECHO]``).

TRUTH-DOCTRINE COMPLIANCE — no reimplementation. Every registry entry points
at the flag's REAL parser (imported and CALLED), so the echo cannot drift from
the decision path: if a parser changes, the echo changes with it. The one
exception is a handful of flags whose value is a module-level constant frozen
at import (SCHEDULER_ENABLED, CALIBRATION_ENABLED, RISK_ENVELOPE_ENFORCE,
INTRADAY_TARGET_PROFIT_ENABLED); for those the echo reads the SAME constant the
code reads, and flags them ``read=import_constant`` so an operator knows a flip
needs a recycle to take effect.

SECRETS SCRUBBED. The echo is ALLOWLIST-ONLY: it reads exactly the env-var
names in ``_REGISTRY`` (via their parsers) and never iterates ``os.environ``.
No raw env value is ever emitted — only the parsed boolean/mode value. A
defensive name guard (``_is_secret_name``) additionally scrubs any value whose
env-var name looks secret-shaped, and a registry-hygiene test asserts no
allowlisted name is secret-shaped in the first place.

Fail-soft. The whole echo is wrapped so a bug here can NEVER block a process
from starting — one WARNING, empty/partial dict, and the process continues.

Call sites (mirrors the PR-0 logging_setup precedent — two module-import hooks
covering all three runtime processes):
- ``packages.quantum.api`` (module import) — BE / uvicorn.
- ``packages.quantum.jobs.runner`` (module import) — BOTH RQ workers (otc +
  background); the block lands on the first job after a recycle because the
  bare ``rq worker`` start command imports nothing of ours.
"""
from __future__ import annotations

import importlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Polarity classes (CLAUDE.md §3) ─────────────────────────────────────────
SAFETY_DEFAULT_ON = "safety_default_on"      # unset/empty -> ON; explicit falsy disables
BEHAVIORAL_OPT_IN = "behavioral_opt_in"      # unset/empty -> OFF; explicit truthy enables
GLOBAL_SWITCH = "global_switch"              # process-wide master switch
EXECUTION_MODE = "execution_mode"            # string-valued effective routing mode

# ── Parse-style tags (the heterogeneity §3 warns about — surfaced per flag) ──
FALSY_DISABLES = "falsy_disables(0/false/no/off)"   # default-ON safety parse
TRUTHY_FULL = "truthy(1/true/yes/on)"               # lenient behavioral parse
TRUTHY_1_TRUE_YES = "truthy(1/true/yes)"            # partial lenient (no 'on')
TRUTHY_TRUE_1 = "truthy(true/1)"                    # LIVE_ENABLED's narrower set
STRICT_EQ_1 = "strict(==1)"                         # strict — 'true' does NOT enable
ENUM_MODE = "enum(mode-string)"
# is_agent_enabled's tri-state: {1/true/yes}->on, {0/false/no}->off, else->default
# (note: 'on'/'off' are NOT recognized — they fall through to the default).
AGENT_TRISTATE = "tristate(1/true/yes|0/false/no|else default)"

# Secret-shaped env-var names must never be echoed. Belt-and-suspenders on top
# of the allowlist: even if a future registry entry names a secret-shaped var,
# its VALUE is scrubbed. A registry-hygiene test asserts this set is empty.
# NOTE: deliberately does NOT include "AUTH" — it would misfire on
# FLEET_ACTIVATION_AUTHORIZED, a boolean arming flag, not a credential.
_SECRET_NAME_RE = re.compile(
    r"(KEY|SECRET|TOKEN|PASSWORD|PASSWD|CRED|PRIVATE|SIGNING|WEBHOOK|"
    r"URL|URI|DSN|BEARER|CONNECTION)",
    re.IGNORECASE,
)


def _is_secret_name(name: str) -> bool:
    return bool(_SECRET_NAME_RE.search(name or ""))


@dataclass(frozen=True)
class FlagSpec:
    """One live behavioral/safety control.

    ``reader`` is imported lazily and CALLED at echo time so the reported value
    is the parser's own output — the anti-drift contract. ``read`` is 'call'
    for call-time parsers, 'import_constant' for module constants frozen at
    import (a flip of those needs a recycle).
    """
    name: str                 # env-var name (also the display name)
    module: str               # dotted module path of the real parser
    attr: str                 # function or constant name in that module
    polarity: str
    parse_style: str
    doc: str                  # CLAUDE.md pointer
    call: bool = True         # call attr() if True, else read it as a constant
    transform: Optional[Callable[[Any], Any]] = None  # e.g. enum -> .value
    read: str = "call"        # "call" | "import_constant"
    args: tuple = ()          # positional args passed to attr() — used ONLY to
                              # reproduce a production call site verbatim (e.g.
                              # is_agent_enabled("QUANT_AGENTS_ENABLED", False)),
                              # never to synthesize a new parse.


# ── The allowlist / registry. Every ``name`` is verified to be read by prod ──
# ── code by ``test_flag_echo``'s registry-vs-code drift test.               ──
_REGISTRY: List[FlagSpec] = [
    # ---- Safety / default-ON (empty/unset -> ON; only explicit falsy off) ----
    FlagSpec("ENTRY_QUOTE_VALIDATION_ENABLED", "packages.quantum.paper_endpoints",
             "_entry_quote_validation_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1038"),
    FlagSpec("ENTRY_QUOTE_SOURCE_ALIGNED", "packages.quantum.paper_endpoints",
             "_entry_quote_source_aligned", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1052"),
    FlagSpec("ENTRY_ROUNDTRIP_COST_GATE_ENABLED", "packages.quantum.paper_endpoints",
             "_entry_roundtrip_cost_gate_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1101"),
    FlagSpec("REENTRY_COOLDOWN_ENABLED", "packages.quantum.services.reentry_cooldown",
             "is_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1040"),
    FlagSpec("CLOSE_REARM_ENABLED", "packages.quantum.services.paper_exit_evaluator",
             "_close_rearm_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1046"),
    FlagSpec("CLOSE_QUOTE_VALIDATION_ENABLED", "packages.quantum.services.paper_exit_evaluator",
             "_close_quote_validation_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1072"),
    FlagSpec("INTRADAY_COHORT_STOP_ENABLED", "packages.quantum.jobs.handlers.intraday_risk_monitor",
             "_intraday_cohort_stop_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1048"),
    FlagSpec("CALIBRATION_STALENESS_TTL_ENABLED", "packages.quantum.analytics.calibration_service",
             "_staleness_ttl_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1045"),
    FlagSpec("CALIBRATION_TRAIN_LIVE_ONLY", "packages.quantum.analytics.calibration_service",
             "_train_live_only_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1076"),
    FlagSpec("FUNNEL_STATUS_TRUTHFUL_ENABLED", "packages.quantum.services.suggestion_status",
             "funnel_status_truthful_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1073"),
    FlagSpec("QUOTE_PROVENANCE_ENABLED", "packages.quantum.services.quote_provenance",
             "is_provenance_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§8 A9"),
    FlagSpec("STREAK_BREAKER_ENABLED", "packages.quantum.risk.streak_breaker",
             "_is_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1119"),
    FlagSpec("STREAK_BREAKER_EDGE_TRIGGER_ENABLED", "packages.quantum.risk.streak_breaker",
             "_edge_trigger_enabled", SAFETY_DEFAULT_ON, FALSY_DISABLES, "§4 #1119"),

    # ---- Behavioral / opt-in (empty/unset -> OFF; explicit truthy on) --------
    FlagSpec("EXIT_MARK_SANITY_OBSERVE_ENABLED", "packages.quantum.analytics.exit_mark_corroboration",
             "is_observe_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "§4 #1034"),
    FlagSpec("EXIT_MARK_SANITY_ENFORCE_ENABLED", "packages.quantum.analytics.exit_mark_corroboration",
             "is_enforce_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "§4 #1034"),
    FlagSpec("GTC_PROFIT_EXIT_ENABLED", "packages.quantum.services.gtc_profit_exit",
             "is_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "§4 #1021/#1064"),
    FlagSpec("GATE_QTY_FIX_LIVE_ENABLED", "packages.quantum.paper_endpoints",
             "_gate_qty_fix_live_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "§8 E2"),
    FlagSpec("IV_RANK_NONE_ROUTING_ENABLED", "packages.quantum.observability.feature_flags",
             "is_iv_rank_none_routing_enabled", BEHAVIORAL_OPT_IN, TRUTHY_1_TRUE_YES, "docs/backlog #115"),

    # ---- Dark / observe / experimental env controls (2026-07-23 census, Lane D) --
    # These observe/enforce/enable toggles gate dark subsystems that are OFF today.
    # None was in the echo, so an accidental arm would NOT surface at startup — the
    # one place §3 says to read effective state. All default OFF; each entry CALLS
    # the control's OWN production parser (anti-drift), never a reimplementation.
    #   QUANT_AGENTS_ENABLED is the ONLY dark control that AFFECTS LIVE ENTRIES if
    #   flipped (census #2). Its master-toggle parser is is_agent_enabled — the gate
    #   build_agent_pipeline actually reads (runner.py:29). ⚠ SEAM: a SECOND, divergent
    #   inline parser exists at workflow_orchestrator.py:3363
    #   (os.getenv(...,"false").lower()=="true"); that one treats '1'/'yes' as OFF.
    #   The echo reports the master-toggle value (the pipeline-build decision).
    FlagSpec("QUANT_AGENTS_ENABLED", "packages.quantum.agents.runner",
             "is_agent_enabled", BEHAVIORAL_OPT_IN, AGENT_TRISTATE, "census#2 (affects live entries)",
             args=("QUANT_AGENTS_ENABLED", False)),
    FlagSpec("OI_ENRICHMENT_ENABLED", "packages.quantum.services.oi_enrichment",
             "is_oi_enrichment_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "census#7 OI enrichment"),
    FlagSpec("VOL_SIGNAL_OBSERVE_ENABLED", "packages.quantum.analytics.vol_signal",
             "is_observe_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "census#6 vol-signal observe"),
    FlagSpec("REGIME_FILTER_OBSERVE_ENABLED", "packages.quantum.analytics.regime_filter",
             "is_observe_enabled", BEHAVIORAL_OPT_IN, TRUTHY_FULL, "census#5 cross-asset regime"),

    # ---- Behavioral / opt-in but STRICT ==1 (the §3 footgun class) -----------
    FlagSpec("RISK_UTILIZATION_GATE_ENABLED", "packages.quantum.risk.utilization_gate",
             "is_enabled", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "§4 #1044"),
    FlagSpec("PAPER_AUTOPILOT_ENABLED", "packages.quantum.services.paper_autopilot_service",
             "_get_config", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "§4 autopilot",
             transform=lambda cfg: bool(cfg.get("enabled"))),
    FlagSpec("FLEET_ACTIVATION_AUTHORIZED", "packages.quantum.services.shadow_fleet_activation",
             "activation_authorized", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "§4 shadow-fleet"),
    # ---- Dark / observe / enforce controls, STRICT ==1 (2026-07-23 census, Lane D) ----
    FlagSpec("RISK_BASIS_MAX_LOSS_ENABLED", "packages.quantum.services.risk_basis_shadow",
             "is_max_loss_basis_enabled", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "census#11 risk-basis"),
    FlagSpec("BUCKET_CONTROL_ENFORCE", "packages.quantum.risk.bucket_control",
             "is_bucket_enforce_enabled", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "census#12 bucket enforce"),
    FlagSpec("FLEET_RECEIPT_PRODUCER_ENABLED", "packages.quantum.jobs.handlers.alpaca_order_sync",
             "_fleet_receipt_producer_enabled", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "census#16 fleet receipts"),
    FlagSpec("RISK_ENVELOPE_ENFORCE", "packages.quantum.jobs.handlers.intraday_risk_monitor",
             "_ENFORCE_FORCE_CLOSE", GLOBAL_SWITCH, STRICT_EQ_1, "§5", call=False,
             read="import_constant"),
    FlagSpec("INTRADAY_TARGET_PROFIT_ENABLED", "packages.quantum.jobs.handlers.intraday_risk_monitor",
             "_INTRADAY_TARGET_PROFIT_ENABLED", BEHAVIORAL_OPT_IN, STRICT_EQ_1, "§3 (strict-parse liar)",
             call=False, read="import_constant"),

    # ---- Global switches -----------------------------------------------------
    FlagSpec("SCHEDULER_ENABLED", "packages.quantum.scheduler",
             "SCHEDULER_ENABLED", GLOBAL_SWITCH, STRICT_EQ_1, "§4 global trio", call=False,
             read="import_constant"),
    FlagSpec("CALIBRATION_ENABLED", "packages.quantum.analytics.calibration_service",
             "CALIBRATION_ENABLED", GLOBAL_SWITCH, STRICT_EQ_1, "§4 global trio", call=False,
             read="import_constant"),

    # ---- Execution mode (effective — folds in the LIVE_ENABLED safety gate) --
    FlagSpec("EXECUTION_MODE", "packages.quantum.brokers.execution_router",
             "get_execution_mode", EXECUTION_MODE, ENUM_MODE, "§6 (effective)",
             transform=lambda m: getattr(m, "value", str(m))),
    FlagSpec("LIVE_ENABLED", "packages.quantum.brokers.execution_router",
             "live_enabled", GLOBAL_SWITCH, TRUTHY_TRUE_1, "§6 live-arm gate"),
]


def registry_env_names() -> List[str]:
    """The allowlist: the exact env-var names this module will ever read."""
    return [spec.name for spec in _REGISTRY]


def _read_effective(spec: FlagSpec) -> Any:
    """Call/read the flag's REAL parser. Returns the effective value, or an
    ``"<error:...>"`` sentinel on any failure (per-flag isolation — one broken
    parser never sinks the block)."""
    mod = importlib.import_module(spec.module)
    obj = getattr(mod, spec.attr)
    value = obj(*spec.args) if spec.call else obj
    if spec.transform is not None:
        value = spec.transform(value)
    return value


def _source(name: str, env: Dict[str, str]) -> str:
    """Explicit vs defaulted, matching the parsers' own 'empty -> default'
    semantics: a present-but-blank value is treated as defaulted."""
    raw = env.get(name)
    return "explicit" if (raw is not None and raw.strip() != "") else "default"


def collect_effective_flags(env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Build the structured flag dict WITHOUT logging. Pure/for tests + programmatic
    callers. Never raises — a per-flag failure records an ``errors`` entry and a
    ``<error:...>`` value; the flag's value is scrubbed if its name is secret-shaped."""
    env = env if env is not None else os.environ
    flags: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for spec in _REGISTRY:
        scrub = _is_secret_name(spec.name)
        try:
            value = _read_effective(spec)
        except Exception as e:  # noqa: BLE001 — per-flag isolation is the point
            value = f"<error:{type(e).__name__}>"
            errors.append(f"{spec.name}: {type(e).__name__}: {e}")
        flags[spec.name] = {
            "value": "<scrubbed>" if scrub else value,
            "polarity": spec.polarity,
            "parse_style": spec.parse_style,
            "source": _source(spec.name, env),
            "read": spec.read,
            "doc": spec.doc,
            "env_var": spec.name,
        }
    return {"flag_count": len(_REGISTRY), "flags": flags, "errors": errors}


def _format_block(process: str, data: Dict[str, Any]) -> str:
    """Render the one greppable multi-line block. Emits ONLY parsed values +
    metadata — never a raw env string."""
    lines: List[str] = [
        f"[FLAG_ECHO] effective behavioral/safety flags @ startup "
        f"(process={process}, allowlist-scrubbed, {data['flag_count']} flags)"
    ]
    order = [SAFETY_DEFAULT_ON, BEHAVIORAL_OPT_IN, GLOBAL_SWITCH, EXECUTION_MODE]
    flags = data["flags"]
    for polarity in order:
        group = [(n, m) for n, m in flags.items() if m["polarity"] == polarity]
        if not group:
            continue
        lines.append(f"[FLAG_ECHO]   {polarity}:")
        for name, meta in group:
            recycle = " [recycle-to-change]" if meta["read"] == "import_constant" else ""
            lines.append(
                f"[FLAG_ECHO]     {name:<38} = {str(meta['value']):<16} "
                f"({meta['source']:<8} {meta['parse_style']}) {meta['doc']}{recycle}"
            )
    if data["errors"]:
        lines.append(f"[FLAG_ECHO]   parse_errors={len(data['errors'])}: {data['errors']}")
    return "\n".join(lines)


# Idempotence: echo once per (process) per Python process, mirroring
# setup_logging's once-per-process contract. Re-imports never double-log.
_echoed_processes: set = set()


def echo_effective_flags(
    process: str = "unknown",
    *,
    force: bool = False,
    env: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Log the one-block flag echo and return the structured dict.

    Fail-soft: any internal error is swallowed to a single WARNING and an
    empty dict — a bug in the echo must never keep a process from starting.
    ``force=True`` bypasses the once-per-process idempotence guard (tests).
    """
    try:
        if not force and process in _echoed_processes:
            return {"flag_count": 0, "flags": {}, "errors": [], "skipped": "already_echoed"}
        data = collect_effective_flags(env=env)
        logger.info(_format_block(process, data))
        _echoed_processes.add(process)
        return data
    except Exception:  # noqa: BLE001 — startup must never be blocked by the echo
        logger.warning("[FLAG_ECHO] flag echo failed (non-fatal)", exc_info=True)
        return {"flag_count": 0, "flags": {}, "errors": ["echo_failed"]}
