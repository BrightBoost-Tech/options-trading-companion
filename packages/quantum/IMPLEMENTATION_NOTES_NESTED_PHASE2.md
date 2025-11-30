# Implementation Notes: Nested Learning Phase 2 (The Advisor)

## Overview
Phase 2 introduces **Level-1 Symbol Adapters**, a mechanism to gently bias the optimizer's inputs (Expected Returns `mu` and Risk `sigma`) based on historical performance. This creates a feedback loop where the system learns from its own "surprise" (divergence between prediction and reality).

## Architecture

### 1. Adapter Module (`packages/quantum/nested/adapters.py`)
- **SymbolAdapterState**: A dataclass holding the state for each ticker (`alpha_adjustment`, `sigma_scaler`).
- **load_symbol_adapters**: Fetches adapter states from the Supabase `model_states` table.
- **apply_biases**: Applies the adjustments to `mu` and `sigma` with strict safety clamps.
  - `alpha_adjustment`: Clamped to ±25% of the raw expected return.
  - `sigma_scaler`: Clamped between 0.8x and 1.5x.

### 2. Integration (`packages/quantum/optimizer.py`)
- The adapter logic is injected into the `/optimize/portfolio` endpoint.
- It runs **after** raw market data calculation (`calculate_portfolio_inputs`) and **before** the solver (`SurrogateOptimizer` or `QciDiracAdapter`) is called.
- **Feature Flag**: Controlled by the `NESTED_L1_ENABLED` environment variable. Defaults to `False`.

### 3. Training Script (`packages/quantum/scripts/train_symbol_adapters.py`)
- **Purpose**: Runs nightly (or periodically) to update adapter states.
- **Input**: Joins `inference_log` (predictions) and `outcomes_log` (realized P&L/Vol).
- **Logic**:
  - High Surprise + High Volatility -> Increase `sigma_scaler` (assume riskier than thought).
  - Negative P&L -> Decrease `alpha_adjustment` (reduce bullish bias).
- **Output**: Updates `model_states` in Supabase.

## Usage

### Enabling L1 Adapters
Set the environment variable in `.env` or deployment config:
```bash
NESTED_L1_ENABLED=true
```

### Running the Training Script
```bash
# Run from repo root or packages/quantum
python3 packages/quantum/scripts/train_symbol_adapters.py --days 30 --min-samples 10
```

### Dry Run
To see potential updates without writing to the database:
```bash
python3 packages/quantum/scripts/train_symbol_adapters.py --dry-run
```

## Safety & Constraints
- **Non-Destructive**: If adapters fail to load or apply, the system falls back to raw `mu`/`sigma`.
- **Clamping**: Biases cannot fundamentally alter the nature of an asset (e.g., cannot make a volatile asset look like cash).
- **No Trade Size Changes**: The adapter only influences *selection weights*, not the sizing logic (Kelly/Half-Kelly).

## Database Schema
Expects `model_states` table with:
- `scope_id` (ticker)
- `scope_type` ('ticker')
- `state_data` (JSONB containing `alpha_adjustment`, `sigma_scaler`)
