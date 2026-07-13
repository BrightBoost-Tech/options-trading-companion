"""
Content-addressable blob storage for replay data.

Provides:
- Deduplication via SHA256 hashing
- Gzip compression for storage efficiency
- LRU cache to avoid repeated DB lookups
- Bulk insert support for commit phase
"""

import gzip
import json
import logging
import os
from collections import OrderedDict
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.services.replay.canonical import (
    canonical_json_bytes,
    sha256_hex,
)

logger = logging.getLogger(__name__)

# Environment configuration
REPLAY_MAX_BLOB_BYTES = int(os.getenv("REPLAY_MAX_BLOB_BYTES", str(2 * 1024 * 1024)))  # 2MB default
REPLAY_LRU_CACHE_SIZE = int(os.getenv("REPLAY_LRU_CACHE_SIZE", "50000"))  # 50k hashes


class LRUCache:
    """
    Thread-safe LRU cache for tracking seen blob hashes.

    Used to avoid repeated DB lookups for already-stored blobs.
    """

    def __init__(self, max_size: int = REPLAY_LRU_CACHE_SIZE):
        self.max_size = max_size
        self._cache: OrderedDict[str, bool] = OrderedDict()
        self._lock = Lock()

    def contains(self, key: str) -> bool:
        """Check if key is in cache, updating LRU order."""
        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                return True
            return False

    def add(self, key: str) -> None:
        """Add key to cache, evicting oldest if at capacity."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return

            self._cache[key] = True

            # Evict oldest if over capacity
            while len(self._cache) > self.max_size:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        """Clear the cache."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


def _decode_bytea(payload) -> Optional[bytes]:
    """Decode a data_blobs.payload value to raw bytes.

    PostgREST returns BYTEA as a hex STRING (``\\x`` + hex) — the read half of
    the PR-② fix (encode-only would have moved the breakage to replay time,
    ``get()`` previously assumed bytes/memoryview). Direct-driver paths that
    hand back bytes/memoryview keep working. Unknown shape → None (loud at the
    caller, never a fabricated payload — H9).
    """
    if isinstance(payload, memoryview):
        return bytes(payload)
    if isinstance(payload, (bytes, bytearray)):
        return bytes(payload)
    if isinstance(payload, str):
        s = payload[2:] if payload.startswith("\\x") else payload
        try:
            return bytes.fromhex(s)
        except ValueError:
            return None
    return None


class BlobStore:
    """
    Content-addressable blob storage with deduplication.

    Stores canonical JSON payloads compressed with gzip.
    Uses SHA256 hash as the unique key.

    v1.1 Write Safety:
    - Maintains separate persisted_hashes (confirmed in DB) and pending (staged)
    - Only marks as persisted after commit succeeds
    - Commit failure does NOT lose pending blobs (can retry)

    Usage:
        store = BlobStore()

        # Store a payload (returns hash)
        blob_hash = store.put({"symbol": "SPY", "price": 500.0})

        # Retrieve later (needs supabase client)
        payload = store.get(supabase, blob_hash)
    """

    # Batch size for upserts (performance optimization)
    COMMIT_BATCH_SIZE = 200

    def __init__(self):
        # LRU cache for persisted hashes (confirmed in DB)
        self._persisted_cache = LRUCache(max_size=REPLAY_LRU_CACHE_SIZE)

        # Pending blobs for bulk insert (hash -> compressed_blob_info)
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_lock = Lock()

        # Hashes dropped for exceeding REPLAY_MAX_BLOB_BYTES — the typed
        # oversize degrade (PR-②, 2026-07-13): an oversize payload is NEVER
        # staged (so it can never be half-referenced); the commit-side gate in
        # DecisionContext sees the hash as unpersisted and downgrades the run
        # to capture_partial instead of letting decision_inputs FK-orphan.
        self._dropped_oversize: set = set()

    def put(
        self,
        obj: Any,
        compression: str = "gzip"
    ) -> Tuple[str, bytes, int]:
        """
        Compute blob hash and prepare for storage.

        Does NOT write to DB - use commit() for bulk writes.

        v1.1: Only checks persisted_cache for dedup. Pending blobs are always
        re-staged if not yet persisted (prevents data loss on commit failure).

        Args:
            obj: Python object to store
            compression: Compression algorithm (only 'gzip' supported currently)

        Returns:
            Tuple of (blob_hash, compressed_bytes, uncompressed_size)

        Raises:
            ValueError: If payload exceeds REPLAY_MAX_BLOB_BYTES (warning only)
        """
        # Serialize to canonical bytes
        canonical_bytes = canonical_json_bytes(obj)
        uncompressed_size = len(canonical_bytes)

        # Compute hash
        blob_hash = sha256_hex(canonical_bytes)

        # Size limit — typed degrade (PR-②): an oversize blob is NOT staged.
        # The hash is still returned (content addressing is real), but the
        # commit-side gate will see it unpersisted and downgrade the run to
        # capture_partial — never an FK-orphaned decision_inputs row.
        if uncompressed_size > REPLAY_MAX_BLOB_BYTES:
            logger.warning(
                f"Blob exceeds size limit — DROPPED (typed capture_partial): "
                f"{uncompressed_size} bytes > {REPLAY_MAX_BLOB_BYTES} bytes "
                f"(hash: {blob_hash[:16]}...)"
            )
            self._dropped_oversize.add(blob_hash)
            return blob_hash, b"", uncompressed_size

        # Compress
        if compression == "gzip":
            compressed_bytes = gzip.compress(canonical_bytes, compresslevel=6)
        else:
            raise ValueError(f"Unsupported compression: {compression}")

        # Add to pending if not already persisted (v1.1: only check persisted, not pending)
        # This ensures commit failures don't prevent re-staging the same blob
        if not self._persisted_cache.contains(blob_hash):
            with self._pending_lock:
                if blob_hash not in self._pending:
                    self._pending[blob_hash] = {
                        "hash": blob_hash,
                        "compression": compression,
                        "payload": compressed_bytes,
                        "size_bytes": uncompressed_size,
                    }

        return blob_hash, compressed_bytes, uncompressed_size

    def get(self, supabase, blob_hash: str) -> Optional[Any]:
        """
        Retrieve and decompress a blob from storage.

        Args:
            supabase: Supabase client
            blob_hash: SHA256 hash of the blob

        Returns:
            Deserialized Python object, or None if not found
        """
        try:
            result = supabase.table("data_blobs").select(
                "payload, compression"
            ).eq("hash", blob_hash).single().execute()

            if not result.data:
                logger.warning(f"Blob not found: {blob_hash[:16]}...")
                return None

            payload_bytes = _decode_bytea(result.data["payload"])
            compression = result.data.get("compression", "gzip")
            if payload_bytes is None:
                logger.error(
                    f"Blob payload undecodable (unexpected type/format) for "
                    f"{blob_hash[:16]}..."
                )
                return None

            # Decompress
            if compression == "gzip":
                decompressed = gzip.decompress(payload_bytes)
            else:
                logger.error(f"Unsupported compression: {compression}")
                return None

            # Parse JSON
            return json.loads(decompressed.decode("utf-8"))

        except Exception as e:
            logger.error(f"Failed to retrieve blob {blob_hash[:16]}...: {e}")
            return None

    def get_many(
        self,
        supabase,
        blob_hashes: List[str]
    ) -> Dict[str, Any]:
        """
        Retrieve multiple blobs in a single query.

        Args:
            supabase: Supabase client
            blob_hashes: List of blob hashes

        Returns:
            Dict mapping hash -> deserialized object
        """
        if not blob_hashes:
            return {}

        results = {}
        try:
            # Query all at once
            response = supabase.table("data_blobs").select(
                "hash, payload, compression"
            ).in_("hash", blob_hashes).execute()

            for row in (response.data or []):
                blob_hash = row["hash"]
                payload_bytes = _decode_bytea(row["payload"])
                compression = row.get("compression", "gzip")
                if payload_bytes is None:
                    logger.warning(
                        f"Blob payload undecodable for {blob_hash[:16]}..."
                    )
                    continue

                try:
                    if compression == "gzip":
                        decompressed = gzip.decompress(payload_bytes)
                    else:
                        continue

                    results[blob_hash] = json.loads(decompressed.decode("utf-8"))
                except Exception as e:
                    logger.warning(f"Failed to decompress blob {blob_hash[:16]}...: {e}")

        except Exception as e:
            logger.error(f"Failed to retrieve blobs: {e}")

        return results

    def commit(self, supabase) -> int:
        """
        Bulk insert all pending blobs to database.

        v1.1 Write Safety:
        - Batches upserts for performance (COMMIT_BATCH_SIZE rows per call)
        - Only marks blobs as persisted after successful commit
        - On failure, keeps blobs in pending for retry (no data loss)

        Args:
            supabase: Supabase client

        Returns:
            Number of blobs successfully committed
        """
        with self._pending_lock:
            if not self._pending:
                return 0

            # Take snapshot of pending (don't clear yet - wait for success)
            pending_list = list(self._pending.values())
            pending_hashes = set(self._pending.keys())

        if not pending_list:
            return 0

        committed_hashes = set()
        failed_hashes = set()

        try:
            # Batch insert with upsert in chunks for performance
            for i in range(0, len(pending_list), self.COMMIT_BATCH_SIZE):
                batch = pending_list[i:i + self.COMMIT_BATCH_SIZE]

                try:
                    # PR-② (F-REPLAY-FK root cause): the payload is raw gzip
                    # BYTES, which supabase-py's JSON layer cannot serialize —
                    # every batch threw `Object of type bytes is not JSON
                    # serializable` and data_blobs stayed empty forever.
                    # PostgREST bytea input format is a hex string: \x + hex.
                    encoded_batch = [
                        {**info, "payload": "\\x" + info["payload"].hex()}
                        for info in batch
                    ]
                    # Single upsert call for the batch
                    result = supabase.table("data_blobs").upsert(
                        encoded_batch,
                        on_conflict="hash"
                    ).execute()

                    # Mark all blobs in this batch as committed
                    for blob_info in batch:
                        committed_hashes.add(blob_info["hash"])

                except Exception as e:
                    # Batch failed - mark all in batch as failed
                    for blob_info in batch:
                        failed_hashes.add(blob_info["hash"])

                    if "duplicate key" not in str(e).lower():
                        logger.warning(f"BlobStore batch commit failed: {e}")

            # Only remove committed blobs from pending, mark as persisted
            with self._pending_lock:
                for h in committed_hashes:
                    self._pending.pop(h, None)
                    self._persisted_cache.add(h)

            logger.debug(
                f"BlobStore committed {len(committed_hashes)}/{len(pending_list)} blobs "
                f"(failed: {len(failed_hashes)})"
            )

        except Exception as e:
            logger.error(f"BlobStore commit failed: {e}")
            # Don't clear pending on failure - blobs can be retried

        return len(committed_hashes)

    def get_pending_hashes(self) -> List[str]:
        """Get list of pending blob hashes (for debugging/testing)."""
        with self._pending_lock:
            return list(self._pending.keys())

    def is_persisted(self, blob_hash: str) -> bool:
        """Check if a blob hash is confirmed persisted (for testing)."""
        return self._persisted_cache.contains(blob_hash)

    def was_dropped_oversize(self, blob_hash: str) -> bool:
        """True if this hash was refused staging for exceeding the size cap
        (typed capture_partial input for the commit-side gate)."""
        return blob_hash in self._dropped_oversize

    def unpersisted_of(self, blob_hashes) -> list:
        """The subset of ``blob_hashes`` NOT confirmed persisted — the
        commit-side atomicity gate (PR-②): decision_inputs must never
        reference a hash in this list."""
        return sorted(h for h in blob_hashes if not self._persisted_cache.contains(h))

    def clear_pending(self) -> None:
        """Clear pending blobs without committing."""
        with self._pending_lock:
            self._pending.clear()

    def clear_persisted_cache(self) -> None:
        """Clear persisted cache (for testing)."""
        self._persisted_cache.clear()


# Singleton instance for shared state within a process
_blob_store: Optional[BlobStore] = None
_blob_store_lock = Lock()


def get_blob_store() -> BlobStore:
    """Get the singleton BlobStore instance."""
    global _blob_store
    if _blob_store is None:
        with _blob_store_lock:
            if _blob_store is None:
                _blob_store = BlobStore()
    return _blob_store
