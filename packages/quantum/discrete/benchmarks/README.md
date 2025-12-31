# Discrete Selection Benchmark Harness

This harness benchmarks the performance of classical greedy selection vs QCI Dirac-3 for discrete trade selection problems.

## Scenarios

1.  **Cash Tight Knapsack**:
    -   Selection of high EV candidates under a strict cash budget.
    -   Tests the ability to solve the Knapsack problem (combinatorial optimization).

2.  **Greek Tight**:
    -   Selection constrained by a risk metric (e.g., Vega).
    -   Modeled using the `tail_risk` parameter in the polynomial builder as a proxy for the binding constraint.

3.  **Tail Coupled**:
    -   Scenario with high tail risk contributions.
    -   The quadratic penalty `(Sum T_i)^2` forces diversification.
    -   Tests the solver's ability to handle quadratic interactions (risk coupling).

## Usage

### Classical Baseline (Default)

Runs only the classical greedy solver. Does not require QCI credentials.

```bash
python3 packages/quantum/discrete/benchmarks/run_benchmarks.py --mode classical
```

### Dirac Smoke Test

Runs a minimal set of small scenarios (2 scenarios, <25 candidates). Designed for verifying the pipeline without consuming significant QCI quota.

```bash
export QCI_API_TOKEN="your_token_here"
python3 packages/quantum/discrete/benchmarks/run_benchmarks.py --mode dirac-smoke
```

If `QCI_API_TOKEN` is missing or `qci_client` is not installed, it will gracefully skip Dirac execution and report classical results only.

### Full Benchmark

Runs larger scenarios with more candidates.

```bash
export QCI_API_TOKEN="your_token_here"
python3 packages/quantum/discrete/benchmarks/run_benchmarks.py --mode full
```

## Output

The script outputs a JSON report to stdout containing:
-   Solver used
-   Objective values (lower is better, energy minimization)
-   Feasibility status
-   Runtime metrics
-   Selected trade counts

## Requirements

-   `qci-client` python package (optional, required for Dirac mode)
-   `QCI_API_TOKEN` environment variable (for Dirac mode)
