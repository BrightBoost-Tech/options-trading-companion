"""Terminal-distribution observe-only foundation (queue-⑤, Lane 3B).

ONE versioned terminal-distribution contract + FROZEN baseline adapters
(production math verbatim) + common payoff integrations + a deterministic
offline/prequential evaluator.

OBSERVE-ONLY BOUNDARY (charter, docs/backlog.md ⑤):
    NOTHING in the live economics path (scanner / ranker / gates / sizing /
    executor) imports this package. The only permitted coupling direction is
    terminal_distribution → packages.quantum.ev_calculator (read-only wrap
    inside baselines.py). The import-lock is pinned by
    packages/quantum/tests/test_terminal_distribution_import_lock.py.

FALSIFIER (charter, keep verbatim): locked prequential cohorts must beat the
delta/fair-odds baseline on Brier / EV-RMSE / net-P&L rank — else retain the
baseline and stop.
"""

from packages.quantum.analytics.terminal_distribution.contract import (
    CONTRACT_VERSION,
    DistributionInputs,
    EvalOutcome,
    LegSpec,
    Provenance,
    SingleLegGeometry,
    StrategyEvaluation,
    StructureSpec,
    TerminalDistribution,
    Unavailable,
    params_hash,
    validate_single_leg,
)
from packages.quantum.analytics.terminal_distribution.baselines import (
    CREDIT_IDENTITY_DEFECT,
    baseline_condor,
    baseline_credit_vertical,
    baseline_debit_vertical,
)
from packages.quantum.analytics.terminal_distribution.payoff import (
    integrate_structure,
)
from packages.quantum.analytics.terminal_distribution.challenger_lognormal import (
    LognormalTerminal,
    build_lognormal,
    challenger_lognormal_evaluate,
)
from packages.quantum.analytics.terminal_distribution.single_leg import (
    build_single_leg_structure,
    evaluate_single_leg,
    evaluate_single_leg_from_inputs,
)
from packages.quantum.analytics.terminal_distribution.evaluator import (
    EvalRecord,
    ModelReport,
    OutcomeRecord,
    SegmentKey,
    evaluate_model,
    head_to_head,
    records_from_rows,
    with_production_multipliers,
)

__all__ = [
    "CONTRACT_VERSION",
    "CREDIT_IDENTITY_DEFECT",
    "DistributionInputs",
    "EvalOutcome",
    "EvalRecord",
    "LegSpec",
    "LognormalTerminal",
    "ModelReport",
    "OutcomeRecord",
    "Provenance",
    "SegmentKey",
    "SingleLegGeometry",
    "StrategyEvaluation",
    "StructureSpec",
    "TerminalDistribution",
    "Unavailable",
    "baseline_condor",
    "baseline_credit_vertical",
    "baseline_debit_vertical",
    "build_lognormal",
    "build_single_leg_structure",
    "challenger_lognormal_evaluate",
    "evaluate_model",
    "evaluate_single_leg",
    "evaluate_single_leg_from_inputs",
    "head_to_head",
    "integrate_structure",
    "params_hash",
    "records_from_rows",
    "validate_single_leg",
    "with_production_multipliers",
]
