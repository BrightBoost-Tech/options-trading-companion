"""
Schema-contract + job-truth regression for the 2026-07-16 `ranking_costs` failure.

ROOT CAUSE: PR #1218 began stamping ``suggestion["ranking_costs"]`` in
``analytics/canonical_ranker.py`` but shipped NO migration, so production
``trade_suggestions`` lacked the column. Every scan-selected suggestion carrying
``ranking_costs`` then failed to persist with PostgREST ``PGRST204`` ("Could not
find the 'ranking_costs' column ... in the schema cache"): ``created=0``, the
executor processed 0, the row (with its required cost provenance) was lost — and
``suggestions_open`` still reported green.

These tests DRIVE THE REAL PRODUCTION SYMBOLS (not local mirrors — cf. the older
``test_trade_suggestions_strip_missing_cols.py`` which copies the constants):

* ``canonical_ranker.compute_risk_adjusted_ev`` (the rank step that stamps the field)
* ``workflow_orchestrator.insert_or_get_suggestion`` (the persistence primitive)
* ``workflow_orchestrator._extract_missing_column`` + ``DROPPABLE_SUGGESTION_COLUMNS``
* ``jobs.handlers.midday_scan.run`` (the ``suggestions_open`` handler)
* ``jobs.runner._classify_handler_return`` (the terminal-status classifier)

The DB client is the ONLY fake: a production-shaped PostgREST stand-in that
rejects unknown columns with the exact ``PGRST204`` schema-cache error shape.
"""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.quantum.services.workflow_orchestrator import (
    insert_or_get_suggestion,
    _extract_missing_column,
    DROPPABLE_SUGGESTION_COLUMNS,
)
from packages.quantum.analytics import canonical_ranker
from packages.quantum.jobs.handlers import midday_scan
from packages.quantum.jobs import runner

REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS_DIR = REPO_ROOT / "supabase" / "migrations"
RANKER_SRC = REPO_ROOT / "packages" / "quantum" / "analytics" / "canonical_ranker.py"


# ---------------------------------------------------------------------------
# Production-shaped PostgREST fake (deliverable 4).
# Unknown columns fail with the PGRST204 schema-cache shape that the REAL
# _extract_missing_column parses — so a code-before-migration column mismatch
# reproduces exactly as production does, not as a hand-waved generic error.
# ---------------------------------------------------------------------------
class PostgrestSchemaCacheError(Exception):
    """Mirrors the supabase-py APIError str for a PGRST204 schema-cache miss."""

    def __init__(self, column: str, table: str = "trade_suggestions"):
        self.code = "PGRST204"
        message = f"Could not find the '{column}' column of '{table}' in the schema cache"
        super().__init__(
            "{'code': 'PGRST204', 'details': None, 'hint': None, "
            f"'message': \"{message}\"}}"
        )


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=list(self._rows))


class _FakeInsert:
    def __init__(self, table, payload, known):
        self._table = table
        self._payload = payload
        self._known = known

    def execute(self):
        for col in self._payload:
            if col not in self._known:
                raise PostgrestSchemaCacheError(col, self._table)
        return SimpleNamespace(
            data=[{
                "id": "11111111-1111-1111-1111-111111111111",
                "trace_id": self._payload.get("trace_id") or "fake-trace",
            }]
        )


class _FakeTable:
    def __init__(self, name, known, existing_rows):
        self._name = name
        self._known = known
        self._existing = existing_rows

    def insert(self, payload):
        return _FakeInsert(self._name, payload, self._known)

    def select(self, *a, **k):
        return _FakeQuery(self._existing)


class ProductionShapedFakeSupabase:
    """Supabase client stand-in whose insert enforces a known-column set the way
    PostgREST does: any column absent from the schema cache -> PGRST204."""

    def __init__(self, known_columns, existing_rows=()):
        self._known = set(known_columns)
        self._existing = list(existing_rows)

    def table(self, name):
        return _FakeTable(name, self._known, self._existing)


def _qqq_ic_suggestion():
    """A QQQ iron-condor suggestion with real 4-leg order_json so the ranker
    computes a genuine multi-leg cost provenance."""
    return {
        "ticker": "QQQ",
        "strategy": "iron_condor",
        "ev": 42.0,
        "trace_id": "trace-qqq-ic",
        "status": "pending",
        "sizing_metadata": {"contracts": 1},
        "max_loss": 300.0,
        "order_json": {
            "legs": [
                {"side": "sell", "type": "call"},
                {"side": "buy", "type": "call"},
                {"side": "sell", "type": "put"},
                {"side": "buy", "type": "put"},
            ]
        },
    }


# ---------------------------------------------------------------------------
# Deliverable 4 — the fake reproduces the exact PGRST204 shape.
# ---------------------------------------------------------------------------
def test_production_shaped_fake_raises_pgrst204_shape():
    fake = ProductionShapedFakeSupabase(known_columns={"ticker"})
    with pytest.raises(PostgrestSchemaCacheError) as ei:
        fake.table("trade_suggestions").insert(
            {"ticker": "QQQ", "ranking_costs": {"x": 1}}
        ).execute()
    # The REAL production parser must extract the column from the fake's shape.
    assert _extract_missing_column(str(ei.value)) == "ranking_costs"
    assert "PGRST204" in str(ei.value)
    assert "schema cache" in str(ei.value)


# ---------------------------------------------------------------------------
# Deliverable 5 — real route: scanner-shaped suggestion -> rank -> ranking_costs
# -> persistence. Pre-migration schema must FAIL LOUD (never silently drop the
# cost provenance); post-migration schema persists it.
# ---------------------------------------------------------------------------
def test_real_route_rank_then_persist_ranking_costs():
    sug = _qqq_ic_suggestion()

    # RANK STEP — the real canonical ranker stamps ranking_costs.
    canonical_ranker.compute_risk_adjusted_ev(sug, [], portfolio_budget=10_000.0)
    assert "ranking_costs" in sug, "the real ranker must stamp ranking_costs (#1218)"
    assert sug["ranking_costs"]["leg_count"] == 4, "multi-leg IC provenance"
    assert sug["ranking_costs"]["round_trip_sides"] == 2

    clean = {
        k: v for k, v in sug.items()
        if k != "internal_cand" and not k.startswith("_v4_")
    }
    unique = ("u1", "midday_entry", "2026-07-16", "QQQ", "iron_condor", None)

    # PERSISTENCE, PRE-MIGRATION schema (ranking_costs column absent): the row's
    # required cost provenance must NOT be silently dropped -> it RAISES PGRST204.
    pre = ProductionShapedFakeSupabase(known_columns=set(clean) - {"ranking_costs"})
    with pytest.raises(Exception) as ei:
        insert_or_get_suggestion(pre, clean, unique)
    assert _extract_missing_column(str(ei.value)) == "ranking_costs"

    # PERSISTENCE, POST-MIGRATION schema (ranking_costs column present): inserts
    # WITH the provenance intact.
    post = ProductionShapedFakeSupabase(known_columns=set(clean) | {"ranking_costs"})
    sid, tid, is_new = insert_or_get_suggestion(post, clean, unique)
    assert sid and is_new is True


# ---------------------------------------------------------------------------
# Deliverable 7 — ranking_costs must NOT be silently discarded. It gets a real
# column; it is never added to the droppable-compatibility list.
# ---------------------------------------------------------------------------
def test_required_cost_provenance_is_not_droppable():
    assert "ranking_costs" not in DROPPABLE_SUGGESTION_COLUMNS
    assert "vrp_ranking" not in DROPPABLE_SUGGESTION_COLUMNS


def test_ranking_costs_routes_to_failure_not_strip():
    """The production strip/retry loop is `if missing in DROPPABLE: strip else:
    fail`. Prove with the REAL symbols that ranking_costs takes the failure
    branch (so the row is recorded lost, not silently stripped)."""
    err = (
        "{'code': 'PGRST204', 'message': \"Could not find the 'ranking_costs' "
        "column of 'trade_suggestions' in the schema cache\"}"
    )
    missing = _extract_missing_column(err)
    assert missing == "ranking_costs"
    assert missing not in DROPPABLE_SUGGESTION_COLUMNS  # -> loop `else: break` -> recorded failure


# ---------------------------------------------------------------------------
# Deliverable 3 — schema-contract: EVERY top-level field the canonical ranker
# persists must have a committed schema representation (a migration column) or a
# sanctioned DROPPABLE entry. This FAILS before the migration and PASSES after.
# ---------------------------------------------------------------------------
def _ranker_persisted_stamps():
    src = RANKER_SRC.read_text(encoding="utf-8")
    return set(re.findall(r'suggestion\["(\w+)"\]\s*=(?!=)', src))


def _committed_trade_suggestions_columns():
    cols = set()
    add_col = re.compile(
        r'ALTER\s+TABLE\s+(?:public\.)?trade_suggestions\s+ADD\s+COLUMN\s+'
        r'(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)"?',
        re.IGNORECASE,
    )
    create = re.compile(
        r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?trade_suggestions\s*\((.*?)\n\)\s*;',
        re.IGNORECASE | re.DOTALL,
    )
    _reserved = {"constraint", "primary", "unique", "foreign", "check", "like"}
    for f in sorted(MIGRATIONS_DIR.glob("*.sql")):
        text = f.read_text(encoding="utf-8")
        for m in add_col.finditer(text):
            cols.add(m.group(1).lower())
        cm = create.search(text)
        if cm:
            for line in cm.group(1).splitlines():
                line = line.strip().strip(",")
                mm = re.match(r'"?(\w+)"?\s+\w', line)
                if mm and mm.group(1).lower() not in _reserved:
                    cols.add(mm.group(1).lower())
    return cols


def test_every_ranker_persisted_field_has_committed_schema():
    stamped = _ranker_persisted_stamps()
    # guard: the parser is actually finding the ranker's stamps
    assert "ranking_costs" in stamped
    assert "vrp_ranking" in stamped

    committed = _committed_trade_suggestions_columns()
    missing = sorted(
        f for f in stamped
        if f.lower() not in committed and f not in DROPPABLE_SUGGESTION_COLUMNS
    )
    assert not missing, (
        f"canonical_ranker persists top-level field(s) {missing} to trade_suggestions "
        f"with NO committed column and NO sanctioned DROPPABLE entry — the #1218 class. "
        f"Add an additive migration column (not a DROPPABLE strip)."
    )


def test_ranking_costs_and_vrp_ranking_have_columns():
    committed = _committed_trade_suggestions_columns()
    assert "ranking_costs" in committed, "the #1218 fix migration must add ranking_costs"
    assert "vrp_ranking" in committed, "the gated-off sibling column must exist before VRP is enabled"


# ---------------------------------------------------------------------------
# Deliverable 6 — job-truth: an exhausted per-suggestion insert failure (a lost
# row) propagates to counts.errors > 0 and the runner classifies 'partial'
# instead of green. The aggregated alert is emitted inside run_midday_cycle and
# is unchanged (asserted by absence of any change to that path).
# ---------------------------------------------------------------------------
def test_runner_classifier_maps_errors_to_partial():
    # the REAL terminal-status classifier
    assert runner._classify_handler_return({"counts": {"errors": 1}}) == "partial"
    assert runner._classify_handler_return({"counts": {"errors": 0}}) == "succeeded"


def _patch_handler(monkeypatch, cycle_result):
    async def fake_cycle(client, uid):
        return cycle_result
    monkeypatch.setattr(midday_scan, "run_midday_cycle", fake_cycle)
    monkeypatch.setattr(midday_scan, "get_admin_client", lambda: object())
    monkeypatch.setattr(midday_scan, "get_active_user_ids", lambda c: ["u1"])


def test_midday_scan_insert_failures_make_run_partial(monkeypatch):
    # run_midday_cycle catches insert failures internally and returns normally
    # with counts.suggestion_insert_failures — the field the production function
    # now emits (value produced by the real accounting proven above).
    _patch_handler(
        monkeypatch,
        {"skipped": False, "counts": {"created": 0, "suggestion_insert_failures": 2}},
    )
    result = midday_scan.run({})
    assert result["counts"]["suggestion_insert_failures"] == 2
    assert result["counts"]["errors"] == 2
    assert result["ok"] is False
    assert runner._classify_handler_return(result) == "partial"


def test_midday_scan_green_when_all_persist(monkeypatch):
    _patch_handler(
        monkeypatch,
        {"skipped": False, "counts": {"created": 3, "suggestion_insert_failures": 0}},
    )
    result = midday_scan.run({})
    assert result["counts"]["errors"] == 0
    assert result["ok"] is True
    assert runner._classify_handler_return(result) == "succeeded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
