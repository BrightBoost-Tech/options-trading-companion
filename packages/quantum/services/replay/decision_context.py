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
from packages.quantum.observability.lineage import resolve_git_sha

logger = logging.getLogger(__name__)

# ContextVar for async-safe access to current decision context
_current_decision_context: ContextVar[Optional["DecisionContext"]] = ContextVar(
    "current_decision_context", default=None
)


def is_replay_enabled() -> bool:
    """
    Check if replay feature store is enabled.

    Phase 2.1: Reads REPLAY_ENABLE at runtime (not import time).
    This allows environment variables to be set after module import
    without requiring a process restart.

    Returns:
        True if REPLAY_ENABLE=1, False otherwise
    """
    return os.getenv("REPLAY_ENABLE", "0") == "1"


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
        # Resolve the full deployment SHA at the writer boundary.  This repairs
        # handlers that pass the Docker placeholder "unknown" while preserving
        # an explicit real SHA supplied by replay/tests.
        self.git_sha = resolve_git_sha(self.git_sha)

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

        v1.1 Atomic Commit:
        1. data_blobs (upsert for dedup) - via BlobStore.commit()
        2. decision_runs + decision_inputs + decision_features via RPC
           (single transaction for atomicity)

        Falls back to sequential inserts if RPC unavailable.

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
            # 1. Commit blobs first (must succeed before decision commit)
            stats["blobs_committed"] = self._blob_store.commit(supabase)

            # 1b. ATOMICITY GATE (PR-②, F-REPLAY-FK): decision_inputs must
            # NEVER reference a blob hash that is not confirmed persisted —
            # that FK-orphan class broke all five of 2026-07-13's tapes. A
            # shortfall (failed batch, oversize drop) downgrades the run to a
            # TYPED capture_partial: the run row + features + the persisted
            # subset of inputs still commit (maximal evidence), the missing
            # hashes are named in error_summary, and the caller folds
            # stats["blobs_missing"] into its job counts (F-A4-1 contract).
            expected_hashes = {inp.blob_hash for inp in self.inputs.values()}
            missing = self._blob_store.unpersisted_of(expected_hashes)
            missing_set = set(missing)
            oversize = [h for h in missing
                        if self._blob_store.was_dropped_oversize(h)]
            tape_integrity = "complete"
            if missing:
                tape_integrity = "capture_partial"
                if status == "ok":
                    status = "capture_partial"
                miss_note = (
                    f"capture_partial: {len(missing)}/{len(expected_hashes)} "
                    f"input blob(s) unpersisted (oversize={len(oversize)}): "
                    + ",".join(h[:16] for h in missing[:4])
                )
                error_summary = (
                    f"{error_summary} | {miss_note}" if error_summary
                    else miss_note
                )
                stats["blobs_missing"] = len(missing)
                stats["blobs_oversize_dropped"] = len(oversize)
                logger.warning(f"DecisionContext {miss_note} "
                               f"decision_id={self.decision_id}")
            stats["tape_integrity"] = tape_integrity
            self._tape_integrity = tape_integrity
            stats["status"] = status

            # 2. Compute aggregate hashes (over ATTEMPTED inputs — the
            # decision's true input set; the persisted subset is what the
            # decision_inputs rows carry)
            input_hashes = sorted([inp.blob_hash for inp in self.inputs.values()])
            input_hash = compute_aggregate_hash(input_hashes) if input_hashes else None

            feature_hashes = sorted([f.features_hash for f in self.features])
            features_hash = compute_aggregate_hash(feature_hashes) if feature_hashes else None

            # 3. Build inputs/features JSONB arrays for RPC — persisted-blob
            # rows ONLY (the gate's guarantee)
            inputs_jsonb = [
                {
                    "blob_hash": inp.blob_hash,
                    "key": inp.key,
                    "snapshot_type": inp.snapshot_type,
                    "metadata": inp.metadata,
                }
                for inp in self.inputs.values()
                if inp.blob_hash not in missing_set
            ]

            features_jsonb = [
                {
                    "symbol": f.symbol,
                    "namespace": f.namespace,
                    "features": f.features,
                    "features_hash": f.features_hash,
                }
                for f in self.features
            ]

            # 4. Try atomic RPC commit
            rpc_result = self._commit_via_rpc(
                supabase,
                input_hash=input_hash,
                features_hash=features_hash,
                duration_ms=duration_ms,
                status=status,
                error_summary=error_summary,
                inputs_jsonb=inputs_jsonb,
                features_jsonb=features_jsonb,
            )

            if rpc_result:
                stats["inputs_count"] = len(inputs_jsonb)
                stats["features_count"] = len(features_jsonb)
                stats["commit_method"] = "rpc"
                was_update = (
                    rpc_result.get("was_update") is True
                    or rpc_result.get("commit_status") == "updated"
                )
                stats["rpc_was_update"] = was_update
                self._stamp_rpc_header(
                    supabase,
                    tape_integrity=tape_integrity,
                    require_affected=was_update,
                )
            else:
                # Fallback to sequential inserts if RPC fails. Pass the
                # FILTERED inputs (gate guarantee) — rebuilding from
                # self.inputs here would resurrect the FK-orphan class.
                self._commit_sequential(
                    supabase,
                    input_hash=input_hash,
                    features_hash=features_hash,
                    duration_ms=duration_ms,
                    status=status,
                    error_summary=error_summary,
                    inputs_jsonb=inputs_jsonb,
                    features_jsonb=features_jsonb,
                    tape_integrity=tape_integrity,
                )
                stats["inputs_count"] = len(inputs_jsonb)
                stats["features_count"] = len(features_jsonb)
                stats["commit_method"] = "sequential"

            logger.info(
                f"DecisionContext committed: {self.strategy_name} "
                f"decision_id={self.decision_id} "
                f"inputs={stats['inputs_count']} features={stats['features_count']} "
                f"method={stats.get('commit_method', 'unknown')}"
            )

        except Exception as e:
            logger.error(f"DecisionContext commit failed: {e}")
            stats["error"] = str(e)
            stats["error_type"] = (
                "decision_run_stamp_failed"
                if str(e).startswith("decision_run_stamp_failed:")
                else "decision_commit_failed"
            )
            stats["status"] = "failed"
            stats["tape_integrity"] = "commit_failed"

            # Try to write failed decision_run for traceability (don't duplicate)
            self._try_mark_failed(supabase, str(e))

        return stats

    def _commit_via_rpc(
        self,
        supabase,
        input_hash: Optional[str],
        features_hash: Optional[str],
        duration_ms: Optional[int],
        status: str,
        error_summary: Optional[str],
        inputs_jsonb: List[Dict],
        features_jsonb: List[Dict],
    ) -> Optional[Dict[str, Any]]:
        """
        Commit decision atomically via RPC function.

        Returns the production RPC result row when successful, otherwise None
        so the caller can use the sequential fallback. The row's was_update
        field is load-bearing: an existing decision needs an authoritative
        follow-up SHA/tape stamp rather than a best-effort annotation.
        """
        try:
            result = supabase.rpc("rpc_commit_decision_v4", {
                "p_decision_id": str(self.decision_id),
                "p_strategy_name": self.strategy_name,
                "p_as_of_ts": self.as_of_ts.isoformat(),
                "p_user_id": self.user_id,
                "p_git_sha": self.git_sha,
                "p_status": status,
                "p_error_summary": error_summary[:500] if error_summary else None,
                "p_input_hash": input_hash,
                "p_features_hash": features_hash,
                "p_duration_ms": duration_ms,
                "p_inputs": inputs_jsonb,
                "p_features": features_jsonb,
            }).execute()

            if result.data:
                logger.debug(f"RPC commit succeeded: {result.data}")
                row = (
                    result.data[0]
                    if isinstance(result.data, list)
                    else result.data
                )
                if isinstance(row, dict):
                    return row
                return {"commit_status": "unknown", "was_update": False}

            return None

        except Exception as e:
            # RPC might not exist yet - fall back to sequential
            logger.debug(f"RPC commit failed, falling back: {e}")
            return None

    def _stamp_rpc_header(
        self,
        supabase,
        *,
        tape_integrity: str,
        require_affected: bool,
    ) -> None:
        """Stamp fields omitted by the RPC's existing-row update path.

        A newly inserted RPC row already receives p_git_sha; its
        tape-integrity annotation retains the pre-existing best-effort
        behavior. For was_update=True, however, this is the only writer of
        the current deployment SHA. An exception or zero-row result is
        therefore a typed commit failure, never a green stale-provenance tape.
        """
        try:
            result = supabase.table("decision_runs").update({
                "tape_integrity": tape_integrity,
                "git_sha": self.git_sha,
            }).eq("decision_id", str(self.decision_id)).execute()
        except Exception as exc:
            if require_affected:
                raise RuntimeError(
                    f"decision_run_stamp_failed: update_error: {exc}"
                ) from exc
            logger.warning(f"tape_integrity stamp failed (non-fatal): {exc}")
            return

        if require_affected:
            rows = getattr(result, "data", None)
            if not isinstance(rows, list) or len(rows) != 1:
                count = len(rows) if isinstance(rows, list) else 0
                raise RuntimeError(
                    "decision_run_stamp_failed: "
                    f"expected_one_row_got_{count}"
                )

    def _commit_sequential(
        self,
        supabase,
        input_hash: Optional[str],
        features_hash: Optional[str],
        duration_ms: Optional[int],
        status: str,
        error_summary: Optional[str],
        inputs_jsonb: Optional[List[Dict]] = None,
        features_jsonb: Optional[List[Dict]] = None,
        tape_integrity: str = "complete",
    ) -> None:
        """Fallback sequential commit (non-atomic).

        PR-②: consumes the caller's FILTERED ``inputs_jsonb`` (persisted-blob
        rows only). Rebuilding from ``self.inputs`` here would reintroduce the
        FK-orphan class the atomicity gate exists to kill.
        """
        # Insert decision_runs header
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
            "tape_integrity": tape_integrity,
        }

        supabase.table("decision_runs").insert(decision_run).execute()

        # Insert decision_inputs (persisted-blob rows only — gate guarantee)
        input_rows = [
            {
                "decision_id": str(self.decision_id),
                "blob_hash": row["blob_hash"],
                "key": row["key"],
                "snapshot_type": row["snapshot_type"],
                "metadata": row["metadata"],
            }
            for row in (inputs_jsonb or [])
        ]
        if input_rows:
            supabase.table("decision_inputs").insert(input_rows).execute()

        # Insert decision_features
        feature_rows = [
            {
                "decision_id": str(self.decision_id),
                "symbol": row["symbol"],
                "namespace": row["namespace"],
                "features": row["features"],
                "features_hash": row["features_hash"],
            }
            for row in (features_jsonb or [])
        ]
        if feature_rows:
            supabase.table("decision_features").insert(feature_rows).execute()

    def _try_mark_failed(self, supabase, error_msg: str) -> None:
        """Best-effort failed-row write without mistaking zero updates for one."""
        try:
            update_result = supabase.table("decision_runs").update({
                "status": "failed",
                "error_summary": f"Commit failed: {error_msg[:450]}",
                "tape_integrity": "commit_failed",
                "git_sha": self.git_sha,
            }).eq("decision_id", str(self.decision_id)).execute()
            if getattr(update_result, "data", None):
                return
        except Exception:
            pass

        # An update that succeeds with zero affected rows means no header
        # exists. Insert the trace row just as we do for an update exception.
        try:
            supabase.table("decision_runs").insert({
                "decision_id": str(self.decision_id),
                "strategy_name": self.strategy_name,
                "as_of_ts": self.as_of_ts.isoformat(),
                "user_id": self.user_id,
                "git_sha": self.git_sha,
                "status": "failed",
                "error_summary": f"Commit failed: {error_msg[:450]}",
                "inputs_count": 0,
                "features_count": 0,
                "tape_integrity": "commit_failed",
            }).execute()
        except Exception:
            pass  # Best effort

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
