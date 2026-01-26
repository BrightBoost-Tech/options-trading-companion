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
