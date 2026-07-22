"""Runtime injection bridge for the single-leg shadow experiment.

This module lives outside ``packages/quantum`` intentionally: the challenger
probability package is observe-only and protected by a full-tree import lock on
production modules.  The approved shadow experiment consumes the adapter only
through dependency injection.
"""

from packages.quantum.analytics.terminal_distribution.single_leg import (
    evaluate_single_leg_from_inputs,
)


def evaluate_request(inputs):
    """Evaluate the generator's duck-typed ``SingleLegEVInputs`` request."""

    return evaluate_single_leg_from_inputs(
        option_type=inputs.option_type,
        strike=inputs.strike,
        debit_per_share=inputs.debit_per_share,
        iv=inputs.iv,
        spot=inputs.spot,
        dte_days=inputs.dte_days,
        known_at=inputs.known_at,
        contracts=inputs.contracts,
    )
