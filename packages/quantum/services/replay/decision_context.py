"""
Decision Context for collecting inputs and features during a decision cycle.

Provides:
- Context manager pattern for decision boundaries
- contextvars for async-safe context access
- Deferred bulk commit to avoid hot-path DB writes
- Atomic-ish error handling
"""

import logging
import os
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.services.replay.blob_store import BlobStore, get_blob_store
from packages.quantum.services.replay.canonical import (
    compute_aggregate_hash,
    compute_content_hash,
)

logger = logging.getLogger(__name__)

# Environment configuration
REPLAY_ENABLE = os.getenv("REPLAY_ENABLE", "0") == "1"

# ContextVar for async-safe access to current decision context
_current_decision_context: ContextVar[Optional["DecisionContext"]] = ContextVar(
    "current_decision_context", default=None
)


def is_replay_enabled() -> bool:
    """Check if replay feature store is enabled."""
    return REPLAY_ENABLE


def get_current_decision_context() -> Optional["DecisionContext"]:
    """
    Get the current DecisionContext if one is active.

    Uses contextvars for async safety (works with asyncio, threads, etc.)

    Returns:
        Active DecisionContext or None
    """
    return _current_decision_context.get()


@dataclass
class InputRecord:
    """Record of a single input blob with metadata."""
    key: str
    snapshot_type: str
    blob_hash: str
    metadata: Dict[str, Any]


@dataclass
class FeatureRecord:
    """Record of computed features for a symbol/namespace."""
    symbol: str
    namespace: str
    features: Dict[str, Any]
    features_hash: str


@dataclass
class DecisionContext:
    """
    Context manager for collecting inputs and features during a decision cycle.

    Collects data in memory during the cycle, then performs bulk DB writes
    on successful exit. On error, writes a failed decision_run record.

    Usage:
        with DecisionContext(
            strategy_name="suggestions_close",
            as_of_ts=datetime.now(timezone.utc)
        ) as ctx:
            # Market data calls automatically record inputs via hooks
            snapshots = truth_layer.snapshot_many_v4(symbols)

            # Explicitly record computed features
            ctx.record_feature("SPY", "regime_features", regime_data)

        # On exit, bulk commit happens automatically
    """

    strategy_name: str
    as_of_ts: datetime
    user_id: Optional[str] = None
    git_sha: Optional[str] = None

    # Auto-generated
    decision_id: uuid.UUID = field(default_factory=uuid.uuid4)

    # Collected data (populated during cycle)
    inputs: Dict[Tuple[str, str], InputRecord] = field(default_factory=dict)
    features: List[FeatureRecord] = field(default_factory=list)

    # Internal state
    _blob_store: Optional[BlobStore] = field(default=None, repr=False)
    _start_time: Optional[float] = field(default=None, repr=False)
    _token: Any = field(default=None, repr=False)
    _committed: bool = field(default=False, repr=False)

    def __post_init__(self):
        # Ensure as_of_ts is timezone-aware
        if self.as_of_ts.tzinfo is None:
            self.as_of_ts = self.as_of_ts.replace(tzinfo=timezone.utc)

        # Get or create blob store
        if self._blob_store is None:
            self._blob_store = get_blob_store()

    def __enter__(self) -> "DecisionContext":
        """Enter the decision context."""
        if not is_replay_enabled():
            return self

        self._start_time = time.time()

        # Set as current context (contextvars)
        self._token = _current_decision_context.set(self)

        logger.debug(
            f"DecisionContext entered: {self.strategy_name} "
            f"decision_id={self.decision_id}"
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Exit the decision context and commit data."""
        if not is_replay_enabled():
            return False

        # Reset context
        if self._token is not None:
            _current_decision_context.reset(self._token)
            self._token = None

        # Don't suppress exceptions
        return False

    def record_input(
        self,
        key: str,
        snapshot_type: str,
        payload: Any,
        metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Record an input payload for this decision.

        Computes blob hash and stores in memory. No DB write happens here.

        Args:
            key: Input key (e.g., "SPY:polygon:snapshot_v4")
            snapshot_type: Type of snapshot (quote|chain|surface|rates_divs|bars|regime)
            payload: Raw payload object
            metadata: Optional quality/timestamp metadata

        Returns:
            Blob hash of the payload
        """
        if not is_replay_enabled():
            return ""

        # Compute blob hash (stores in pending)
        blob_hash, _, _ = self._blob_store.put(payload)

        # Store input record
        input_key = (key, snapshot_type)
        self.inputs[input_key] = InputRecord(
            key=key,
            snapshot_type=snapshot_type,
            blob_hash=blob_hash,
            metadata=metadata or {},
        )

        logger.debug(
            f"DecisionContext recorded input: {key} ({snapshot_type}) "
            f"hash={blob_hash[:16]}..."
        )
        return blob_hash

    def record_feature(
        self,
        symbol: str,
        namespace: str,
        features: Dict[str, Any]
    ) -> str:
        """
        Record computed features for a symbol.

        Args:
            symbol: Symbol or "__global__" for market-wide features
            namespace: Feature category (e.g., "regime_features", "symbol_features")
            features: Feature dictionary

        Returns:
            Features hash
        """
        if not is_replay_enabled():
            return ""

        # Compute features hash
        features_hash = compute_content_hash(features)

        # Check for duplicate (same symbol+namespace)
        for i, existing in enumerate(self.features):
            if existing.symbol == symbol and existing.namespace == namespace:
                # Replace with new features
                self.features[i] = FeatureRecord(
                    symbol=symbol,
                    namespace=namespace,
                    features=features,
                    features_hash=features_hash,
                )
                logger.debug(
                    f"DecisionContext updated feature: {symbol}/{namespace} "
                    f"hash={features_hash[:16]}..."
                )
                return features_hash

        # Add new feature record
        self.features.append(FeatureRecord(
            symbol=symbol,
            namespace=namespace,
            features=features,
            features_hash=features_hash,
        ))

        logger.debug(
            f"DecisionContext recorded feature: {symbol}/{namespace} "
            f"hash={features_hash[:16]}..."
        )
        return features_hash

    def commit(
        self,
        supabase,
        status: str = "ok",
        error_summary: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Commit all collected data to database.

        Performs bulk writes in order:
        1. data_blobs (upsert for dedup)
        2. decision_runs (header)
        3. decision_inputs (link rows)
        4. decision_features (computed features)

        Args:
            supabase: Supabase client
            status: "ok" or "failed"
            error_summary: Error message if failed

        Returns:
            Dict with commit statistics
        """
        if not is_replay_enabled():
            return {"status": "disabled"}

        if self._committed:
            logger.warning("DecisionContext already committed")
            return {"status": "already_committed"}

        self._committed = True
        duration_ms = None
        if self._start_time:
            duration_ms = int((time.time() - self._start_time) * 1000)

        stats = {
            "decision_id": str(self.decision_id),
            "strategy_name": self.strategy_name,
            "status": status,
            "blobs_committed": 0,
            "inputs_count": 0,
            "features_count": 0,
            "duration_ms": duration_ms,
        }

        try:
            # 1. Commit blobs
            stats["blobs_committed"] = self._blob_store.commit(supabase)

            # 2. Compute aggregate hashes
            input_hashes = sorted([inp.blob_hash for inp in self.inputs.values()])
            input_hash = compute_aggregate_hash(input_hashes) if input_hashes else None

            feature_hashes = sorted([f.features_hash for f in self.features])
            features_hash = compute_aggregate_hash(feature_hashes) if feature_hashes else None

            # 3. Insert decision_runs header
            decision_run = {
                "decision_id": str(self.decision_id),
                "strategy_name": self.strategy_name,
                "as_of_ts": self.as_of_ts.isoformat(),
                "user_id": self.user_id,
                "git_sha": self.git_sha,
                "status": status,
                "error_summary": error_summary[:500] if error_summary else None,
                "input_hash": input_hash,
                "features_hash": features_hash,
                "inputs_count": len(self.inputs),
                "features_count": len(self.features),
                "duration_ms": duration_ms,
            }

            supabase.table("decision_runs").insert(decision_run).execute()

            # 4. Insert decision_inputs
            if self.inputs:
                input_rows = [
                    {
                        "decision_id": str(self.decision_id),
                        "blob_hash": inp.blob_hash,
                        "key": inp.key,
                        "snapshot_type": inp.snapshot_type,
                        "metadata": inp.metadata,
                    }
                    for inp in self.inputs.values()
                ]
                supabase.table("decision_inputs").insert(input_rows).execute()
                stats["inputs_count"] = len(input_rows)

            # 5. Insert decision_features
            if self.features:
                feature_rows = [
                    {
                        "decision_id": str(self.decision_id),
                        "symbol": f.symbol,
                        "namespace": f.namespace,
                        "features": f.features,
                        "features_hash": f.features_hash,
                    }
                    for f in self.features
                ]
                supabase.table("decision_features").insert(feature_rows).execute()
                stats["features_count"] = len(feature_rows)

            logger.info(
                f"DecisionContext committed: {self.strategy_name} "
                f"decision_id={self.decision_id} "
                f"inputs={stats['inputs_count']} features={stats['features_count']}"
            )

        except Exception as e:
            logger.error(f"DecisionContext commit failed: {e}")
            stats["error"] = str(e)

            # Try to write failed decision_run for traceability
            try:
                supabase.table("decision_runs").insert({
                    "decision_id": str(self.decision_id),
                    "strategy_name": self.strategy_name,
                    "as_of_ts": self.as_of_ts.isoformat(),
                    "user_id": self.user_id,
                    "status": "failed",
                    "error_summary": f"Commit failed: {str(e)[:450]}",
                    "inputs_count": 0,
                    "features_count": 0,
                }).execute()
            except Exception:
                pass  # Best effort

        return stats

    def get_input_hash(self) -> Optional[str]:
        """Compute current input hash (for testing/debugging)."""
        if not self.inputs:
            return None
        input_hashes = sorted([inp.blob_hash for inp in self.inputs.values()])
        return compute_aggregate_hash(input_hashes)

    def get_features_hash(self) -> Optional[str]:
        """Compute current features hash (for testing/debugging)."""
        if not self.features:
            return None
        feature_hashes = sorted([f.features_hash for f in self.features])
        return compute_aggregate_hash(feature_hashes)


def load_decision_context(
    supabase,
    decision_id: str
) -> Optional[Dict[str, Any]]:
    """
    Load a decision context from database for replay.

    Args:
        supabase: Supabase client
        decision_id: UUID of the decision to load

    Returns:
        Dict with decision_run, inputs, and features data
    """
    try:
        # Load decision_run header
        run_result = supabase.table("decision_runs").select("*").eq(
            "decision_id", decision_id
        ).single().execute()

        if not run_result.data:
            logger.warning(f"Decision not found: {decision_id}")
            return None

        decision_run = run_result.data

        # Load decision_inputs
        inputs_result = supabase.table("decision_inputs").select("*").eq(
            "decision_id", decision_id
        ).execute()
        inputs = inputs_result.data or []

        # Load decision_features
        features_result = supabase.table("decision_features").select("*").eq(
            "decision_id", decision_id
        ).execute()
        features = features_result.data or []

        return {
            "decision_run": decision_run,
            "inputs": inputs,
            "features": features,
        }

    except Exception as e:
        logger.error(f"Failed to load decision context {decision_id}: {e}")
        return None
