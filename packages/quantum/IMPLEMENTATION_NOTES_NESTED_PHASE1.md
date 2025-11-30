# Implementation Notes - Nested Learning Phase 1

## Overview
This phase lays the foundation for the Nested Learning system, which allows the optimizer to learn from its past predictions and outcomes.

## Components Implemented

### 1. Database Schema
New tables were added via migration `supabase/migrations/20240524000000_add_nested_learning_tables.sql`:
- `nested_regimes`: For tracking global market states.
- `model_states`: For tracking model weights and performance.
- `inference_log`: For logging optimizer inputs and predictions (Trace ID).
- `outcomes_log`: For logging realized performance against predictions.

### 2. Logging Module
File: `packages/quantum/nested_logging.py`
- `log_inference`: Captures the optimization context (inputs, predictions) and returns a unique `trace_id`. Designed to be non-blocking and fail gracefully.
- `log_outcome`: Captures the realized P&L and volatility for a given `trace_id`.

### 3. Surprise Metric
File: `packages/quantum/analytics/surprise.py`
- `compute_surprise`: Calculates a scalar score representing how much the market "surprised" the model.
- Formula: `Surprise = w1 * abs(sigma_pred - sigma_realized) + w2 * ReLU(-PnL)`
- Penalizes unexpected volatility and realized losses.

### 4. Integration
- **Optimizer Wiring**: `packages/quantum/optimizer.py` was updated to call `log_inference` at the end of `optimize_portfolio`. It captures the symbol universe, input snapshot, predicted returns (mu), and risk matrix (sigma).
- **Outcome Script**: `packages/quantum/scripts/update_outcomes.py` was created to find pending inference logs from "yesterday", fetch realized market data via Polygon, calculate the Surprise score, and populate `outcomes_log`.

## Testing
- Unit tests for Surprise and Logging: `packages/quantum/tests/test_surprise.py`, `packages/quantum/tests/test_logging.py`
- Integration tests: `packages/quantum/tests/test_integration.py`
- Run tests via: `python3 -m unittest discover packages/quantum/tests`

## Running the Outcome Updater
To run the outcome updater manually:
```bash
python3 -m packages.quantum.scripts.update_outcomes
```

## Data Flow
1. **Optimize Request**: User calls `/optimize/portfolio`.
2. **Inference Log**: Optimizer calculates weights and logs inputs/predictions to `inference_log` (returning `trace_id`).
3. **Wait**: Time passes (e.g., 24 hours).
4. **Update Script**: Cron job runs `update_outcomes.py`.
5. **Realized Data**: Script fetches actual market moves for the logged symbols.
6. **Surprise Calc**: Script compares Predicted Vol vs Realized Vol + Realized PnL.
7. **Outcome Log**: Result stored in `outcomes_log`.
