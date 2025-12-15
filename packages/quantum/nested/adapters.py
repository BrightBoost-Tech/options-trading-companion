from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
import os
import json
from datetime import datetime
import numpy as np
from supabase import create_client, Client

# Use the same client helper as logging if possible, or duplicate
def _get_supabase_client() -> Optional[Client]:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None

@dataclass
class SymbolAdapterState:
    symbol: str
    alpha_adjustment: float  # Bias to expected return (additive)
    sigma_scaler: float      # Bias to risk (multiplicative)
    model_version: Optional[str] = None
    cumulative_error: Optional[float] = None

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "alpha_adjustment": self.alpha_adjustment,
            "sigma_scaler": self.sigma_scaler,
            "model_version": self.model_version,
            "cumulative_error": self.cumulative_error
        }

def load_symbol_adapters(symbols: List[str]) -> Dict[str, SymbolAdapterState]:
    """
    Fetch symbol-specific adapter rows from model_states (scope = symbol).
    If an adapter doesn't exist for a symbol, returns identity (alpha=0, scaler=1).
    """
    adapters: Dict[str, SymbolAdapterState] = {}

    # Default initialization
    for sym in symbols:
        adapters[sym] = SymbolAdapterState(
            symbol=sym,
            alpha_adjustment=0.0,
            sigma_scaler=1.0
        )

    supabase = _get_supabase_client()
    if not supabase:
        print("Nested L1: Supabase not connected. Using identity adapters.")
        return adapters

    try:
        # New Schema: scope, model_version, weights, cumulative_error
        response = supabase.table("model_states")\
            .select("scope, model_version, weights, cumulative_error")\
            .in_("scope", symbols)\
            .execute()

        for record in response.data:
            sym = record.get("scope")
            weights = record.get("weights") or {}

            # Ensure weights is a dict
            if not isinstance(weights, dict):
                weights = {}

            if sym in adapters:
                adapters[sym].alpha_adjustment = float(weights.get("alpha_adjustment", 0.0))
                adapters[sym].sigma_scaler = float(weights.get("sigma_scaler", 1.0))
                adapters[sym].model_version = record.get("model_version")
                adapters[sym].cumulative_error = record.get("cumulative_error")

    except Exception as e:
        print(f"Nested L1: Error loading adapters: {e}")

    return adapters

def save_symbol_adapters(states: Dict[str, SymbolAdapterState]) -> None:
    """
    Persist updated adapter states back into model_states.
    Uses 'scope' (symbol) as the key.
    """
    supabase = _get_supabase_client()
    if not supabase:
        print("Nested L1: Supabase not connected. Cannot save adapters.")
        return

    # 1. Get existing IDs for these symbols to ensure safe updates
    # (Since 'scope' might not be unique-constrained in DB migration yet)
    existing_map = {}  # symbol -> id
    try:
        res = supabase.table("model_states")\
            .select("id, scope")\
            .in_("scope", list(states.keys()))\
            .execute()
        for r in res.data:
            existing_map[r["scope"]] = r["id"]
    except Exception as e:
        print(f"Nested L1: Error fetching existing IDs: {e}")
        return

    updates = []
    inserts = []
    now_str = datetime.utcnow().isoformat()

    for sym, state in states.items():
        payload = {
            "scope": sym,
            "model_version": state.model_version or "v3-l1",
            "weights": {
                "alpha_adjustment": state.alpha_adjustment,
                "sigma_scaler": state.sigma_scaler
            },
            "cumulative_error": state.cumulative_error,
            "last_updated": now_str
        }

        if sym in existing_map:
            # Update existing row by ID
            payload["id"] = existing_map[sym]
            updates.append(payload)
        else:
            # Insert new row
            inserts.append(payload)

    try:
        if inserts:
            supabase.table("model_states").insert(inserts).execute()

        if updates:
            supabase.table("model_states").upsert(updates).execute()

        print(f"Nested L1: Saved {len(inserts)} new, {len(updates)} updated adapters.")
    except Exception as e:
        print(f"Nested L1: Error saving adapters: {e}")

def apply_biases(
    mu: np.ndarray,
    sigma: np.ndarray,
    tickers: List[str],
    adapters: Dict[str, SymbolAdapterState],
    max_mu_deviation: float = 0.25,
    min_sigma_scaler: float = 0.8,
    max_sigma_scaler: float = 1.5,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Return (adj_mu, adj_sigma) with:
      - mu adjusted by alpha_adjustment, clamped to +/- max_mu_deviation relative to raw mu magnitude?
        Or absolute deviation? The prompt says "Do not push adj_mu more than +/-25% away from raw mu."
        This likely implies relative percentage if mu is large, or absolute if mu is small.
        Usually for expected returns (e.g. 0.05), a 25% deviation is 0.0125.
        Let's interpret as: |adj_mu - mu| <= 0.25 * |mu|

      - sigma scaled per symbol via sigma_scaler, clamped to [min_sigma_scaler, max_sigma_scaler].
        Since sigma is a covariance matrix, we scale the diagonal (volatility) and recompute?
        Or scale the whole row/col?
        Usually bias is on 'volatility' (std dev).
        Covariance C_ij = sigma_i * sigma_j * rho_ij.
        If we scale sigma_i by S_i, then C'_ij = (sigma_i * S_i) * (sigma_j * S_j) * rho_ij = S_i * S_j * C_ij.
    """

    adj_mu = mu.copy()
    adj_sigma = sigma.copy()

    n = len(tickers)
    scalers = np.ones(n)

    for i, ticker in enumerate(tickers):
        adapter = adapters.get(ticker)
        if not adapter:
            continue

        # 1. Apply Alpha Adjustment (Mu)
        # Prompt: "Do not push adj_mu more than +/-25% away from raw mu"
        raw_val = mu[i]

        # Calculate raw proposal
        proposed_val = raw_val + adapter.alpha_adjustment

        # Calculate bounds
        # If raw_val is 0, we can't do % bounds. Assume some absolute floor or skip?
        # Let's assume strict 25% of raw value.
        # If raw_val is negative, logic holds.
        upper = raw_val + abs(raw_val) * max_mu_deviation
        lower = raw_val - abs(raw_val) * max_mu_deviation

        # Clamp
        if proposed_val > upper:
            clamped_val = upper
        elif proposed_val < lower:
            clamped_val = lower
        else:
            clamped_val = proposed_val

        adj_mu[i] = clamped_val

        # 2. Prepare Sigma Scaler
        # Clamp scaler itself first
        s = adapter.sigma_scaler
        if s < min_sigma_scaler: s = min_sigma_scaler
        if s > max_sigma_scaler: s = max_sigma_scaler

        scalers[i] = s

    # Apply Sigma Scaling
    # C'_ij = S_i * S_j * C_ij
    # We can do this efficiently with broadcasting
    # S is (n,), sigma is (n,n)
    # result = S[:, None] * S[None, :] * sigma

    # Outer product of scalers
    scaler_matrix = np.outer(scalers, scalers)
    adj_sigma = sigma * scaler_matrix

    return adj_mu, adj_sigma
