"""
Backtest Identity Fingerprinting for v4 Backtesting.

Provides deterministic hashing for backtest runs to enable:
- Deduplication of identical runs
- Reproducibility verification
- Cache invalidation when config/data changes

Usage:
    from services.backtest_identity import BacktestIdentity

    data_hash = BacktestIdentity.compute_data_hash(request)
    config_hash = BacktestIdentity.compute_config_hash(config, cost_model, seed)
    code_sha = BacktestIdentity.get_code_sha()
"""

import hashlib
import json
import os
from typing import Any, Dict, Optional

from packages.quantum.services.replay.canonical import compute_content_hash

# v4 dual-import shim
try:
    from packages.quantum.strategy_profiles import (
        BacktestRequestV3,
        StrategyConfig,
        CostModelConfig,
    )
except ImportError:
    from strategy_profiles import (
        BacktestRequestV3,
        StrategyConfig,
        CostModelConfig,
    )


class BacktestIdentity:
    """
    Static helper for computing deterministic identity hashes.

    Hash Strategy:
    - data_hash: Identifies the data window (ticker, dates, data_version)
    - config_hash: Identifies the strategy configuration
    - code_sha: Identifies the code version (from env)

    All hashes use SHA256 with deterministic JSON serialization.
    """

    # Data version for cache invalidation when data processing changes
    # v2: switched to canonical_json_bytes (compute_content_hash) for determinism
    DATA_VERSION = "v2"

    @staticmethod
    def hash_dict(obj: Any) -> str:
        """
        Compute SHA256 hash of an object with deterministic JSON serialization.

        Args:
            obj: Any JSON-serializable object (dict, list, Pydantic model, etc.)

        Returns:
            64-character lowercase hex SHA256 hash
        """
        # Handle Pydantic models
        if hasattr(obj, "model_dump"):
            obj = obj.model_dump()
        elif hasattr(obj, "dict"):
            obj = obj.dict()

        # Deterministic serialization using canonical utility
        return compute_content_hash(obj)

    @staticmethod
    def compute_data_hash(
        request: BacktestRequestV3,
        data_version: Optional[str] = None
    ) -> str:
        """
        Compute hash identifying the data window for a backtest.

        Includes:
        - ticker
        - start_date, end_date
        - data_version (for cache invalidation)

        Does NOT include config/seed (those go in config_hash).

        Args:
            request: BacktestRequestV3 with ticker and date range
            data_version: Override data version (default: DATA_VERSION)

        Returns:
            64-character hex hash
        """
        version = data_version or BacktestIdentity.DATA_VERSION

        payload = {
            "ticker": request.ticker,
            "start_date": request.start_date,
            "end_date": request.end_date,
            "data_version": version,
        }

        return BacktestIdentity.hash_dict(payload)

    @staticmethod
    def compute_config_hash(
        config: StrategyConfig,
        cost_model: CostModelConfig,
        seed: int,
        walk_forward: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Compute hash identifying the strategy configuration.

        Includes:
        - All StrategyConfig fields
        - All CostModelConfig fields
        - Random seed
        - Walk-forward settings (if present)

        Args:
            config: Strategy configuration
            cost_model: Cost model configuration
            seed: Random seed for reproducibility
            walk_forward: Optional walk-forward config dict

        Returns:
            64-character hex hash
        """
        # Extract config as dict
        config_dict = config.model_dump() if hasattr(config, "model_dump") else dict(config)
        cost_dict = cost_model.model_dump() if hasattr(cost_model, "model_dump") else dict(cost_model)

        payload = {
            "strategy_config": config_dict,
            "cost_model": cost_dict,
            "seed": seed,
        }

        if walk_forward:
            payload["walk_forward"] = walk_forward

        return BacktestIdentity.hash_dict(payload)

    @staticmethod
    def get_code_sha() -> str:
        """
        Get the current code version SHA from environment.

        Checks (in order):
        1. GIT_SHA (explicit)
        2. RAILWAY_GIT_COMMIT_SHA (Railway deployment)
        3. VERCEL_GIT_COMMIT_SHA (Vercel deployment)
        4. "unknown" (fallback)

        Returns:
            Git commit SHA or "unknown"
        """
        return (
            os.getenv("GIT_SHA")
            or os.getenv("RAILWAY_GIT_COMMIT_SHA")
            or os.getenv("VERCEL_GIT_COMMIT_SHA")
            or "unknown"
        )

    @staticmethod
    def compute_full_identity(
        request: BacktestRequestV3,
        config: StrategyConfig,
        cost_model: CostModelConfig,
        seed: int
    ) -> Dict[str, str]:
        """
        Compute all identity hashes for a backtest run.

        Returns:
            Dict with data_hash, config_hash, code_sha
        """
        wf_dict = None
        if request.walk_forward:
            wf_dict = request.walk_forward.model_dump() if hasattr(request.walk_forward, "model_dump") else dict(request.walk_forward)

        return {
            "data_hash": BacktestIdentity.compute_data_hash(request),
            "config_hash": BacktestIdentity.compute_config_hash(config, cost_model, seed, wf_dict),
            "code_sha": BacktestIdentity.get_code_sha(),
        }
