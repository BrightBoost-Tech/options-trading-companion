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

## 2025-02-27 - Analytics Event Hashing
**Issue:** `AnalyticsService` used a local `canonical_json` with `json.dumps(default=str)`, causing potential nondeterminism for sets and floats in analytics event keys.
**Learning:** `default=str` is pervasive and should be aggressively hunted down. Even code labeled "canonical" might be flawed if it relies on standard `json` defaults.
**Prevention:** Refactored `AnalyticsService` to use `packages.quantum.observability.canonical`.

## 2025-03-01 - Mixed Key Types in Canonicalization
**Issue:** `compute_content_hash` crashed when processing dictionaries with mixed key types (e.g., `str` and `int`) or non-standard keys (e.g., `datetime`), because Python's `sorted()` raises `TypeError` on mixed/complex types, and `json.dumps(sort_keys=True)` strictly requires basic key types.
**Learning:** To create a truly robust canonical serializer for arbitrary internal state, we must handle key sorting and stringification explicitly before handing off to `json.dumps`. Stringifying keys provides a stable sort order for mixed types and allows complex objects to be used as keys (via their string representation).
**Prevention:** Updated `_normalize_value` in `canonical.py` to stringify keys and sort by string representation. This ensures robustness against mixed keys and supports broader key types without breaking JSON compatibility.
