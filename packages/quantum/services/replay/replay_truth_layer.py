"""
Replay-aware Truth Layer for deterministic replay.

Extends MarketDataTruthLayer to override raw fetch methods with
pre-stored blob data from a previous decision cycle.

Usage:
    # Load from a previous decision
    replay_layer = ReplayTruthLayer.from_decision_id(supabase, decision_id)

    # Use like normal MarketDataTruthLayer - fetches from stored blobs
    snapshots = replay_layer.snapshot_many_v4(symbols)

    # Compare features for determinism verification
    assert replay_layer.verify_determinism(original_features)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from packages.quantum.services.replay.blob_store import BlobStore, get_blob_store
from packages.quantum.services.replay.decision_context import load_decision_context
from packages.quantum.services.market_data_truth_layer import (
    MarketDataTruthLayer,
    TruthSnapshotV4,
    TruthQuoteV4,
    TruthTimestampsV4,
    TruthQualityV4,
    TruthSourceV4,
    compute_quote_quality,
)

logger = logging.getLogger(__name__)


class ReplayTruthLayer(MarketDataTruthLayer):
    """
    Replay-aware Truth Layer that serves data from stored blobs.

    Overrides raw fetch methods to return pre-stored data instead of
    making live API calls. This enables deterministic replay of
    previous decision cycles.

    Attributes:
        decision_id: UUID of the decision being replayed
        inputs_map: Dict mapping (key, snapshot_type) -> blob_hash + metadata
        blobs_cache: Dict mapping blob_hash -> deserialized payload
        features_map: Dict mapping (symbol, namespace) -> features dict
        original_input_hash: Input hash from original decision (for verification)
        original_features_hash: Features hash from original decision
    """

    def __init__(
        self,
        decision_id: str,
        decision_run: Dict[str, Any],
        inputs: List[Dict[str, Any]],
        features: List[Dict[str, Any]],
        supabase=None,
    ):
        """
        Initialize ReplayTruthLayer with pre-loaded decision data.

        Use from_decision_id() factory method for normal construction.

        Args:
            decision_id: UUID of the decision
            decision_run: decision_runs row
            inputs: List of decision_inputs rows
            features: List of decision_features rows
            supabase: Optional Supabase client for blob fetching
        """
        # Initialize parent with no API key (we won't make live calls)
        super().__init__(api_key=None)

        self.decision_id = decision_id
        self.decision_run = decision_run
        self._supabase = supabase
        self._blob_store = get_blob_store()

        # Build inputs map: (key, snapshot_type) -> {blob_hash, metadata}
        self.inputs_map: Dict[tuple, Dict[str, Any]] = {}
        for inp in inputs:
            key = (inp["key"], inp["snapshot_type"])
            self.inputs_map[key] = {
                "blob_hash": inp["blob_hash"],
                "metadata": inp.get("metadata", {}),
            }

        # Build features map: (symbol, namespace) -> {features, features_hash}
        self.features_map: Dict[tuple, Dict[str, Any]] = {}
        for feat in features:
            key = (feat["symbol"], feat["namespace"])
            self.features_map[key] = {
                "features": feat["features"],
                "features_hash": feat["features_hash"],
            }

        # Store original hashes for verification
        self.original_input_hash = decision_run.get("input_hash")
        self.original_features_hash = decision_run.get("features_hash")

        # Cache for loaded blobs (to avoid repeated DB queries)
        self.blobs_cache: Dict[str, Any] = {}

        logger.info(
            f"ReplayTruthLayer initialized: decision_id={decision_id} "
            f"inputs={len(inputs)} features={len(features)}"
        )

    @classmethod
    def from_decision_id(
        cls,
        supabase,
        decision_id: str
    ) -> Optional["ReplayTruthLayer"]:
        """
        Factory method to create ReplayTruthLayer from a decision_id.

        Loads decision_runs, decision_inputs, and decision_features from DB.

        Args:
            supabase: Supabase client
            decision_id: UUID of the decision to replay

        Returns:
            ReplayTruthLayer instance, or None if decision not found
        """
        context_data = load_decision_context(supabase, decision_id)
        if not context_data:
            return None

        return cls(
            decision_id=decision_id,
            decision_run=context_data["decision_run"],
            inputs=context_data["inputs"],
            features=context_data["features"],
            supabase=supabase,
        )

    def _get_blob(self, blob_hash: str) -> Optional[Any]:
        """Get blob from cache or fetch from DB."""
        if blob_hash in self.blobs_cache:
            return self.blobs_cache[blob_hash]

        if self._supabase is None:
            logger.warning("No supabase client for blob fetch")
            return None

        payload = self._blob_store.get(self._supabase, blob_hash)
        if payload is not None:
            self.blobs_cache[blob_hash] = payload
        return payload

    def _preload_blobs(self, blob_hashes: List[str]) -> None:
        """Preload multiple blobs in a single query."""
        missing = [h for h in blob_hashes if h not in self.blobs_cache]
        if not missing or self._supabase is None:
            return

        blobs = self._blob_store.get_many(self._supabase, missing)
        self.blobs_cache.update(blobs)

    def get_stored_input(
        self,
        key: str,
        snapshot_type: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get a stored input payload by key and type.

        Args:
            key: Input key (e.g., "SPY:polygon:snapshot_v4")
            snapshot_type: Snapshot type (e.g., "quote")

        Returns:
            Dict with {payload, metadata}, or None if not found
        """
        input_key = (key, snapshot_type)
        if input_key not in self.inputs_map:
            return None

        input_record = self.inputs_map[input_key]
        blob_hash = input_record["blob_hash"]

        payload = self._get_blob(blob_hash)
        if payload is None:
            return None

        return {
            "payload": payload,
            "metadata": input_record["metadata"],
        }

    def get_stored_feature(
        self,
        symbol: str,
        namespace: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get stored features by symbol and namespace.

        Args:
            symbol: Symbol or "__global__"
            namespace: Feature namespace

        Returns:
            Dict with {features, features_hash}, or None if not found
        """
        key = (symbol, namespace)
        return self.features_map.get(key)

    # =========================================================================
    # Override MarketDataTruthLayer methods to use stored data
    # =========================================================================

    def snapshot_many(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Override: Return stored raw snapshots instead of fetching from API.

        v1.1: Uses consistent key pattern "{ticker}:polygon:snapshot_v4" with
        snapshot_type="quote" (matches MarketDataTruthLayer recording).
        """
        results = {}

        for ticker in tickers:
            # Primary key pattern (used by MarketDataTruthLayer._record_snapshot_to_context)
            key = f"{ticker}:polygon:snapshot_v4"
            stored = self.get_stored_input(key, "quote")
            if stored:
                results[ticker] = stored["payload"]

        return results

    def snapshot_many_v4(
        self,
        tickers: List[str],
        raw_snapshots: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, TruthSnapshotV4]:
        """
        Override: Return stored V4 snapshots with quality scoring.

        v1.1: Uses consistent key pattern "{ticker}:polygon:snapshot_v4" with
        snapshot_type="quote" (matches MarketDataTruthLayer recording).
        """
        v4_results: Dict[str, TruthSnapshotV4] = {}

        # Preload blobs for efficiency
        blob_hashes = []
        for ticker in tickers:
            key = f"{ticker}:polygon:snapshot_v4"
            input_key = (key, "quote")
            if input_key in self.inputs_map:
                blob_hashes.append(self.inputs_map[input_key]["blob_hash"])
        self._preload_blobs(blob_hashes)

        for ticker in tickers:
            # Use canonical key pattern
            key = f"{ticker}:polygon:snapshot_v4"
            stored = self.get_stored_input(key, "quote")

            if stored:
                payload = stored["payload"]
                metadata = stored["metadata"]

                # Check if it's already a V4 format
                if "symbol_canonical" in payload and "quality" in payload:
                    # Stored as TruthSnapshotV4 dict
                    v4_results[ticker] = TruthSnapshotV4(
                        symbol_canonical=payload.get("symbol_canonical", ticker),
                        quote=TruthQuoteV4(**payload.get("quote", {})),
                        timestamps=TruthTimestampsV4(**payload.get("timestamps", {"received_ts": 0})),
                        quality=TruthQualityV4(**payload.get("quality", {"quality_score": 0, "issues": [], "is_stale": True})),
                        source=TruthSourceV4(**payload.get("source", {})),
                        iv=payload.get("iv"),
                        greeks=payload.get("greeks"),
                        day=payload.get("day"),
                        volume=payload.get("volume"),
                    )
                else:
                    # Raw format - apply quality scoring
                    v4_results[ticker] = self._build_v4_from_raw(
                        ticker, payload, metadata
                    )

        return v4_results

    def _build_v4_from_raw(
        self,
        ticker: str,
        raw: Dict[str, Any],
        metadata: Dict[str, Any]
    ) -> TruthSnapshotV4:
        """Build TruthSnapshotV4 from raw payload and metadata."""
        quote_data = raw.get("quote", {})

        # Build quote
        quote = TruthQuoteV4(
            bid=quote_data.get("bid"),
            ask=quote_data.get("ask"),
            mid=quote_data.get("mid"),
            last=quote_data.get("last"),
            bid_size=quote_data.get("bid_size"),
            ask_size=quote_data.get("ask_size"),
        )

        # Compute mid if missing
        if quote.mid is None and quote.bid is not None and quote.ask is not None:
            quote = quote.model_copy(update={"mid": (quote.bid + quote.ask) / 2.0})

        # Get timestamps from metadata
        quality_meta = metadata.get("quality", {})
        source_ts = metadata.get("source_ts")
        received_ts = metadata.get("received_ts", 0)

        timestamps = TruthTimestampsV4(
            source_ts=source_ts,
            received_ts=received_ts,
        )

        # Get freshness from metadata or compute
        freshness_ms = quality_meta.get("freshness_ms")
        if freshness_ms is None and source_ts and received_ts:
            freshness_ms = float(received_ts - source_ts)

        # Use stored quality if available, else compute
        if quality_meta:
            quality = TruthQualityV4(
                quality_score=quality_meta.get("score", 0),
                issues=quality_meta.get("issues", []),
                is_stale=quality_meta.get("is_stale", True),
                freshness_ms=freshness_ms,
            )
        else:
            quality = compute_quote_quality(quote, freshness_ms)

        source = TruthSourceV4(
            provider=metadata.get("provider", "polygon"),
            endpoint="/v3/snapshot",
        )

        return TruthSnapshotV4(
            symbol_canonical=ticker,
            quote=quote,
            timestamps=timestamps,
            quality=quality,
            source=source,
            iv=raw.get("iv"),
            greeks=raw.get("greeks"),
            day=raw.get("day"),
            volume=raw.get("day", {}).get("v") if raw.get("day") else None,
        )

    def option_chain(
        self,
        underlying: str,
        expiration_date=None,
        contract_type: str = None,
        limit: int = 250
    ) -> List[Dict]:
        """
        Override: Return stored option chain instead of fetching from API.

        Looks for chain with key pattern: "{underlying}:chain:{expiration}"
        """
        # Build key pattern
        if expiration_date:
            exp_str = expiration_date.strftime("%Y-%m-%d") if hasattr(expiration_date, "strftime") else str(expiration_date)
            key = f"{underlying}:chain:{exp_str}"
        else:
            key = f"{underlying}:chain:all"

        stored = self.get_stored_input(key, "chain")
        if stored:
            return stored["payload"]

        # Fallback: try without expiration
        stored = self.get_stored_input(f"{underlying}:chain", "chain")
        if stored:
            return stored["payload"]

        logger.warning(f"No stored chain found for {underlying}")
        return []

    def daily_bars(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime
    ) -> List[Dict]:
        """
        Override: Return stored daily bars instead of fetching from API.
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        key = f"{ticker}:bars:{start_str}:{end_str}"

        stored = self.get_stored_input(key, "bars")
        if stored:
            return stored["payload"]

        logger.warning(f"No stored bars found for {key}")
        return []

    def rates_divs(
        self,
        symbol: str,
        date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Override: Return stored rates/divs instead of env-based constants.

        Key pattern: "{symbol}:rates_divs:{date}" with snapshot_type="rates_divs"
        """
        if date is None:
            date = datetime.now()
        date_str = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)[:10]
        key = f"{symbol}:rates_divs:{date_str}"

        stored = self.get_stored_input(key, "rates_divs")
        if stored:
            return stored["payload"]

        # Fallback to symbol-only key
        stored = self.get_stored_input(f"{symbol}:rates_divs", "rates_divs")
        if stored:
            return stored["payload"]

        logger.warning(f"No stored rates_divs found for {symbol}")
        return {"risk_free_rate": None, "dividend_yield": None}

    def surface_snapshot(
        self,
        symbol: str
    ) -> Optional[Dict[str, Any]]:
        """
        Return stored surface snapshot for a symbol.

        Key pattern: "{symbol}:surface:v1" with snapshot_type="surface"
        """
        key = f"{symbol}:surface:v1"
        stored = self.get_stored_input(key, "surface")
        if stored:
            return stored["payload"]

        logger.warning(f"No stored surface snapshot found for {symbol}")
        return None

    # =========================================================================
    # Determinism verification
    # =========================================================================

    def verify_input_hash(self, computed_hash: str) -> bool:
        """
        Verify computed input hash matches original.

        Args:
            computed_hash: Hash computed from current replay

        Returns:
            True if hashes match
        """
        if self.original_input_hash is None:
            logger.warning("No original input_hash to verify against")
            return True

        matches = computed_hash == self.original_input_hash
        if not matches:
            logger.warning(
                f"Input hash mismatch: computed={computed_hash[:16]}... "
                f"original={self.original_input_hash[:16]}..."
            )
        return matches

    def verify_features_hash(self, computed_hash: str) -> bool:
        """
        Verify computed features hash matches original.

        Args:
            computed_hash: Hash computed from current replay

        Returns:
            True if hashes match
        """
        if self.original_features_hash is None:
            logger.warning("No original features_hash to verify against")
            return True

        matches = computed_hash == self.original_features_hash
        if not matches:
            logger.warning(
                f"Features hash mismatch: computed={computed_hash[:16]}... "
                f"original={self.original_features_hash[:16]}..."
            )
        return matches

    def get_replay_summary(self) -> Dict[str, Any]:
        """Get summary of replay state for debugging."""
        return {
            "decision_id": self.decision_id,
            "strategy_name": self.decision_run.get("strategy_name"),
            "as_of_ts": self.decision_run.get("as_of_ts"),
            "status": self.decision_run.get("status"),
            "inputs_count": len(self.inputs_map),
            "features_count": len(self.features_map),
            "blobs_cached": len(self.blobs_cache),
            "original_input_hash": self.original_input_hash,
            "original_features_hash": self.original_features_hash,
        }
