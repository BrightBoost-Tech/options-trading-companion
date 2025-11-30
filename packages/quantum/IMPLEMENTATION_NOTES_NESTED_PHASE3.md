# Nested Learning - Phase 3 (Full Nested) Implementation

## Overview

Phase 3 introduces the "Full Nested" architecture, adding global market regime awareness (L2) and session-level confidence adaptation (L0) to the existing symbol-level adapters (L1).

The goal is to proactively reduce risk during market shocks or periods of poor session performance (losses/surprises), while preserving upside in calm markets.

## Components

### 1. L2 Global Backbone (`nested/backbone.py`)

*   **Responsibility**: Detects the global market regime (Bull, Bear, Crab, Shock) and volatility state.
*   **Input**: Macro features (SPY trend, VIX level) fetched via Polygon.
*   **Output**: `GlobalContext` containing:
    *   `global_regime`: String (e.g., "shock")
    *   `global_risk_scaler`: Float (0.01 - 1.0). Lower values indicate higher risk perception.
*   **Logic**:
    *   High VIX (>30) -> "shock" regime, low scaler (e.g., 0.6).
    *   Declining SPY + Medium VIX -> "bear" regime.
    *   Rising SPY + Low VIX -> "bull" regime.
*   **Integration**: The `optimizer.py` uses `global_risk_scaler` to inflate the covariance matrix `sigma` (making the optimizer "see" more risk) by a factor of `(1/scaler)^2`.
*   **Logging**: Inserts a row into the `nested_regimes` table.

### 2. L0 Session Adapter (`nested/session.py`)

*   **Responsibility**: Tracks intraday confidence based on recent performance (surprises, P&L).
*   **Input**: `account_id`, recent surprise scores, recent P&L (currently mocked/lightweight in implementation).
*   **Output**: `SessionState` containing `confidence` (0.0 - 1.0).
*   **Logic**:
    *   Confidence decays on high surprise (>2.0) or frequent losses.
    *   Confidence recovers slowly in calm periods.
*   **Integration**: Maps `confidence` to a `sigma_scaler` (e.g., Conf 0.2 -> Sigma * 1.5^2).

### 3. Optimizer Integration (`optimizer.py`)

The pipeline execution order is now:

1.  **Raw Calculation**: Compute initial `mu` and `sigma` from market data.
2.  **L2 Global Adjustment**:
    *   If `NESTED_L2_ENABLED=true`:
        *   Fetch macro features.
        *   Scale `sigma` UP if regime is risky.
        *   Trigger "Crisis Mode" if regime is "shock".
3.  **L1 Symbol Adjustment**:
    *   If `NESTED_L1_ENABLED=true` (Existing Phase 2):
        *   Apply per-symbol alpha/sigma biases from `model_states`.
4.  **L0 Session Adjustment**:
    *   If `NESTED_L0_ENABLED=true`:
        *   Scale `sigma` UP further if session confidence is low.
        *   Trigger "Crisis Mode" if confidence < 0.4.
5.  **Crisis Mode**:
    *   If triggered (by L2 or L0), force `req.profile = "conservative"` and ensure strict constraints.

## Diagnostics

The `/optimize/portfolio` response now includes a `diagnostics.nested` object:

```json
"diagnostics": {
  "nested": {
    "l2": {
      "global_regime": "shock",
      "market_volatility_state": "high",
      "global_risk_scaler": 0.6
    },
    "l0": {
      "confidence": 0.3,
      "sigma_scaler": 1.35
    },
    "crisis_mode_triggered_by": "l2_shock"
  }
}
```

## Testing

*   **Unit Tests**: `tests/test_nested_phase3.py` verifies L2 inference logic and L0 state transitions.
*   **Manual verification**: Enable flags `NESTED_L2_ENABLED=true` and `NESTED_L0_ENABLED=true` in `.env` and run the optimizer against known market conditions.

## Safety & Constraints

*   **Additive Risk Only**: Both L2 and L0 only *increase* perceived risk (inflate sigma) or reduce constraints. They never artificially deflate risk to encourage gambling.
*   **Crisis Mode**: Acts as a hard circuit breaker to enforce conservative profiling.

## Gating & Rollout

Phase 3 introduces strict gating to ensure safety during the rollout.

### 1. Request Flags
*   `nested_enabled` (bool): Master toggle. Must be `True` for any nested logic (L2/L1/L0) to affect **live** trades. Defaults to `False`.
*   `nested_shadow` (bool): Debug flag. If `True`, the optimizer forces the main execution path to **Baseline** (safe), but runs a parallel **Nested** path for diagnostics.

### 2. Environment Flags
Even if `nested_enabled=True`, logic is gated by server-side environment variables:
*   `NESTED_GLOBAL_ENABLED`: Master kill-switch.
*   `NESTED_L2_ENABLED`: Enables Global Backbone.
*   `NESTED_L1_ENABLED`: Enables Symbol Adapters.
*   `NESTED_L0_ENABLED`: Enables Session Adapters.

### 3. Shadow Mode (QA)
To validate Nested Learning changes without affecting live trades:

*   **Request**: `POST /optimize/portfolio` with `{"nested_shadow": true, "nested_enabled": false}` (or true, ignored for main path).
*   **Behavior**:
    *   **Main Path**: Forced Baseline. Returns standard MVO trades.
    *   **Shadow Path**: Forced Nested. Computes what *would* happen if nested were live.
    *   **Response**: Returns Main Path trades. Includes `diagnostics.nested_shadow` with comparison metrics.
    *   **Logs**: Both paths are logged to `inference_log`.

### 4. Micro-Live Rollout
To gradually introduce Nested Learning influence on live sizing:

*   **Prerequisites**: `nested_enabled=True` in request AND `NESTED_GLOBAL_ENABLED=True` in env.
*   **Env Var**: `NESTED_LIVE_RISK_MULTIPLIER` (float, e.g., `0.25`).
*   **Logic**:
    *   `mu_final = mu_baseline * (1 - multiplier) + mu_nested * multiplier`
    *   `sigma_final = sigma_baseline * (1 - multiplier) + sigma_nested * multiplier`
*   **Effect**:
    *   If `0.0` (default): Nested logic runs and logs to diagnostics, but **does not affect trades** (Safe Mode).
    *   If `0.0 < m < 1.0`: Blends the nested view with the baseline view.
    *   If `1.0`: Full Nested Learning.
