"""
Replay Feature Store v4

Content-addressable blob storage + decision context tracking for deterministic replay.

Modules:
- canonical: Hash utilities for deterministic serialization
- blob_store: Content-addressable blob storage with dedup
- decision_context: Context manager for collecting inputs/features
- replay_truth_layer: Replay-aware truth layer for deterministic replay

Usage:
    from packages.quantum.services.replay import (
        DecisionContext,
        get_current_decision_context,
        BlobStore,
        ReplayTruthLayer,
    )

    # Enable via REPLAY_ENABLE=1 environment variable
    with DecisionContext(strategy_name="suggestions_close", as_of_ts=now) as ctx:
        # Market data calls automatically record inputs
        snapshots = truth_layer.snapshot_many_v4(symbols)

        # Record computed features
        ctx.record_feature("SPY", "regime_features", regime_snapshot.features)

    # Replay later
    replay_layer = ReplayTruthLayer.from_decision_id(supabase, decision_id)
    replayed_snapshots = replay_layer.snapshot_many_v4(symbols)
"""

from packages.quantum.services.replay.canonical import (
    canonical_json_bytes,
    sha256_hex,
    normalize_float,
    normalize_timestamp,
)
from packages.quantum.services.replay.blob_store import BlobStore
from packages.quantum.services.replay.decision_context import (
    DecisionContext,
    get_current_decision_context,
    is_replay_enabled,
)

__all__ = [
    "canonical_json_bytes",
    "sha256_hex",
    "normalize_float",
    "normalize_timestamp",
    "BlobStore",
    "DecisionContext",
    "get_current_decision_context",
    "is_replay_enabled",
]

# ReplayTruthLayer imported separately to avoid circular imports
# from packages.quantum.services.replay.replay_truth_layer import ReplayTruthLayer
