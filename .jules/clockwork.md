## 2024-10-18 - JSON Serialization Determinism
**Issue:** `param_hash` in `strategy_endpoints.py` relied on `json.dumps(sort_keys=True)` which is insufficient for determinism due to whitespace (separators) and float formatting ambiguity.
**Learning:** Even with `sort_keys=True`, standard JSON serialization can drift across environments or library versions. A canonical serializer (stripping whitespace, normalizing floats) is required for robust deduplication and identity hashing.
**Prevention:** Always use `canonical_json_bytes` or `compute_content_hash` from `packages.quantum.services.replay.canonical` for generating content hashes or canonical storage formats, rather than raw `json.dumps`.
