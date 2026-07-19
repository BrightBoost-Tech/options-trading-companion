"""Mirror parity — fleet_policy_design canonicalization/hash ↔ the seed SQL
digest (edge cases).

The seed (policy_registrations_seed_50.sql) stores ``config_canonical`` (the
Python-produced text) VERBATIM and derives the hash IN SQL:
``encode(extensions.digest(config_canonical,'sha256'),'hex')``. Postgres never
re-serializes the config for the digest — it hashes the exact bytes Python
emitted — so the parity contract is precisely:

    config_hash(canonical) == sha256(canonical.encode('utf-8')).hexdigest()

and ``canonical_config`` must be byte-deterministic across the numeric-type and
key-order artifacts the DB introduces (int-vs-float JSON, 0.30 vs 0.3, key
order). This extends test_fleet_policy_design with the malformed / unicode /
number-formatting edges the #1286-adjacent hash review named.
"""

import hashlib
import json

import pytest

from packages.quantum.policy_lab import fleet_policy_design as design

BASE = dict(design.NEUTRAL_ANCHOR)


def _full(**over):
    """A complete, valid config (all 11 fields) with overrides."""
    cfg = dict(BASE)
    cfg.update(over)
    return cfg


def _sql_digest(canonical: str) -> str:
    """What the seed computes in-SQL: sha256 hex over the stored canonical
    TEXT bytes (utf-8). This is the digest semantics config_hash mirrors."""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Number-formatting artifacts are neutralized by the type coercion ────────
class TestNumberFormatting:
    def test_int_vs_float_input_types_produce_identical_hash(self):
        # The DB stores risk_multiplier as `1` or `1.2`, min_score as `30`.
        # A float field fed an int and an int field fed a float must canonicalize
        # identically (the whole point of _coerce).
        a = _full(min_score_threshold=50.0, max_positions_open=3,
                  risk_multiplier=1.0, max_suggestions_per_day=3)
        b = _full(min_score_threshold=50, max_positions_open=3.0,
                  risk_multiplier=1, max_suggestions_per_day=3.0)
        ca, cb = design.canonical_config(a), design.canonical_config(b)
        assert ca == cb, (ca, cb)
        assert design.config_hash(ca) == design.config_hash(cb)

    def test_float_fields_render_canonically_not_padded(self):
        # 0.30 and 0.3 are the same float; the canonical must render the compact
        # form the SQL side stores + digests (never a padded "0.30").
        c = design.canonical_config(_full(budget_cap_pct=0.30,
                                          stop_loss_pct=0.20))
        assert '"budget_cap_pct":0.3' in c
        assert '"budget_cap_pct":0.30' not in c
        parsed = json.loads(c)
        assert parsed["budget_cap_pct"] == 0.3

    def test_int_field_never_renders_as_float(self):
        # An INT_FIELD fed a float coerces to int → renders `3`, never `3.0`.
        c = design.canonical_config(_full(max_positions_open=3.0))
        assert '"max_positions_open":3' in c
        assert '"max_positions_open":3.0' not in c

    def test_typed_round_trip_matches_declared_field_types(self):
        parsed = json.loads(design.canonical_config(_full()))
        for f in design.FLOAT_FIELDS:
            assert isinstance(parsed[f], float), f
        for f in design.INT_FIELDS:
            assert isinstance(parsed[f], int) and not isinstance(parsed[f], bool), f
        assert isinstance(parsed[design.STR_FIELDS[0]], str)


# ── Key order is irrelevant to the canonical bytes ──────────────────────────
class TestKeyOrder:
    def test_shuffled_key_order_is_byte_identical(self):
        cfg = _full()
        reversed_cfg = dict(reversed(list(cfg.items())))
        assert design.canonical_config(cfg) == design.canonical_config(reversed_cfg)

    def test_canonical_keys_are_sorted_and_compact(self):
        c = design.canonical_config(_full())
        parsed = json.loads(c)
        assert list(parsed) == sorted(parsed)         # sort_keys=True
        assert ", " not in c and ": " not in c        # compact separators

    def test_canonical_is_idempotent(self):
        c1 = design.canonical_config(_full())
        # Re-canonicalizing the parsed form yields the same bytes.
        c2 = design.canonical_config(json.loads(c1))
        assert c1 == c2


# ── config_hash IS the SQL digest semantics ─────────────────────────────────
class TestHashDigestSemantics:
    def test_hash_equals_sql_sha256_of_canonical(self):
        for cfg in (_full(), design.AGGRESSIVE_ANCHOR, design.CONSERVATIVE_ANCHOR):
            c = design.canonical_config(dict(cfg))
            assert design.config_hash(c) == _sql_digest(c)

    def test_every_generated_row_hash_matches_sql_digest(self):
        # The whole seed set: each committed config_hash equals the in-SQL
        # digest of its canonical string.
        for r in design.build_registrations():
            assert r["config_hash"] == _sql_digest(r["config_canonical"])

    def test_seed_derives_hash_in_sql_never_embeds_it(self):
        seed = design.render_seed_sql()
        assert "encode(extensions.digest(v.config_canonical, 'sha256'), 'hex')" in seed
        # config_hash is derived in-SQL — never present as a literal in the seed.
        for r in design.build_registrations():
            assert r["config_hash"] not in seed


# ── Unicode: ensure_ascii makes the canonical byte-stable for the digest ────
class TestUnicodeDeterminism:
    def test_non_ascii_value_is_escaped_and_pure_ascii(self):
        # sizing_method is only ever 'budget_proportional' in production, but the
        # digest parity must not depend on that: a non-ASCII value canonicalizes
        # to \uXXXX-escaped, pure-ASCII bytes (json.dumps ensure_ascii=True), so
        # the string the SQL stores == the string Python digests, byte for byte.
        c = design.canonical_config(_full(sizing_method="café_proportional"))
        assert "\\u00e9" in c                         # escaped, not raw é
        assert all(ord(ch) < 128 for ch in c)         # pure ASCII text
        c.encode("ascii")                             # never raises
        assert design.config_hash(c) == _sql_digest(c)

    def test_unicode_canonical_is_deterministic(self):
        cfg = _full(sizing_method="ünicode_中文")
        assert design.canonical_config(cfg) == design.canonical_config(dict(cfg))


# ── Malformed input fails LOUD (never a silent partial hash) ────────────────
class TestMalformedInput:
    def test_missing_field_raises(self):
        cfg = _full()
        cfg.pop("stop_loss_pct")
        with pytest.raises(ValueError, match="missing.*stop_loss_pct"):
            design.canonical_config(cfg)

    def test_extra_field_raises(self):
        cfg = _full(bogus_axis=1.0)
        with pytest.raises(ValueError, match="extra.*bogus_axis"):
            design.canonical_config(cfg)

    def test_empty_config_raises(self):
        with pytest.raises(ValueError, match="field mismatch"):
            design.canonical_config({})


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
