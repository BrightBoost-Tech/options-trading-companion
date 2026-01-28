## 2024-10-18 - JSON Serialization Determinism
**Issue:** `param_hash` in `strategy_endpoints.py` relied on `json.dumps(sort_keys=True)` which is insufficient for determinism due to whitespace (separators) and float formatting ambiguity.
**Learning:** Even with `sort_keys=True`, standard JSON serialization can drift across environments or library versions. A canonical serializer (stripping whitespace, normalizing floats) is required for robust deduplication and identity hashing.
**Prevention:** Always use `canonical_json_bytes` or `compute_content_hash` from `packages.quantum.services.replay.canonical` for generating content hashes or canonical storage formats, rather than raw `json.dumps`.

## 2025-02-18 - Centralized Canonicalization
**Issue:** Canonicalization logic was duplicated in `LineageSigner` and `telemetry`, causing potential drift and violating the single source of truth principle. `LineageSigner` was using raw `json.dumps`, which is vulnerable to float formatting differences.
**Learning:** Low-level observability components (like lineage signing) require robust canonicalization but cannot import from higher-level `services` without circular dependencies.
**Prevention:** Moved `canonical.py` to `packages/quantum/observability/canonical.py` and re-exported it from `services/replay/canonical.py`. This makes robust canonicalization available to the lowest layers of the application while preserving backward compatibility.

## 2025-02-24 - Unstable Job Hashing
**Issue:** `stable_hash` in `idempotency.py` used `json.dumps(default=str)` which caused nondeterministic hashes for sets (random iteration order) and unnormalized floats.
**Learning:** Even functions explicitly named "stable" can be flawed if they rely on standard library defaults like `default=str`. `compute_content_hash` provides stronger guarantees.
**Prevention:** Replaced implementation with `compute_content_hash`. Future code should strictly avoid `json.dumps` for hashing purposes.

## 2025-02-25 - Nondeterministic Alert Fingerprinting
**Issue:** `get_alert_fingerprint` in `ops_health_service.py` used `json.dumps(default=str)`, causing nondeterministic fingerprints for float values (precision noise) and sets (random iteration order), risking duplicate alerts.
**Learning:** `json.dumps` with `default=str` is fundamentally unsafe for hashing identity if inputs can contain floats or sets.
**Prevention:** Replaced implementation with `compute_content_hash`. Migrated `ops_health_service.py` to use `packages.quantum.observability.canonical` for all identity hashing.

## 2025-02-26 - Unstable List Order in Hashing
**Issue:** Alert fingerprints in `ops_health_service.py` were non-deterministic because they hashed the `stale_symbols` list, which was constructed from iterating over a dictionary (`snapshots.items()`). The dictionary population order depended on concurrent thread completion order in `MarketDataTruthLayer`.
**Learning:** `compute_content_hash` preserves list order (unlike sets/dicts which it sorts). Any list fed into a hash function must be explicitly sorted if its source is not order-guaranteed (e.g., parallel results, dict keys).
**Prevention:** Always apply `sorted()` to lists derived from unordered sources before using them in identity hashing or signatures.
