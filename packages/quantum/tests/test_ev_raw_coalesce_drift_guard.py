"""PR-B drift guard (2026-07-11): learning_trade_outcomes_v3.ev_predicted MUST
COALESCE ts.ev_raw (the RAW pre-calibration EV), never bare ts.ev — else the
prequential validator + the live calibrator train on their own calibrated
output (circular / self-referential).

This invariant has now flipped THREE times: added 2026-04-11 (20260411000000),
SILENTLY REVERTED 2026-06-23 (20260623010000, back to bare ts.ev), restored
2026-07-11. A DB view has no Python production route to drive in a DB-less CI,
so the guard reads the committed migrations and asserts the LATEST definition of
the view coalesces ev_raw — a fourth silent revert (a new migration with bare
ts.ev) becomes the latest and fails this test loudly.
"""
import re
from pathlib import Path

_MIGRATIONS = Path(__file__).resolve().parents[3] / "supabase" / "migrations"
_VIEW = "learning_trade_outcomes_v3"


def _latest_view_definition():
    """(filename, sql) of the highest-versioned migration that (re)defines the
    view. Version prefixes sort chronologically, so the last wins — exactly the
    definition live in the DB."""
    hits = []
    for f in sorted(_MIGRATIONS.glob("*.sql")):
        txt = f.read_text(encoding="utf-8")
        if re.search(rf"CREATE\s+OR\s+REPLACE\s+VIEW\s+{_VIEW}", txt, re.I):
            hits.append((f.name, txt))
    return hits[-1] if hits else (None, None)


def test_latest_v3_view_coalesces_ev_raw():
    name, txt = _latest_view_definition()
    assert txt is not None, f"no migration defines {_VIEW}"
    assert re.search(r"COALESCE\(\s*ts\.ev_raw\s*,\s*ts\.ev\s*\)\s+AS\s+ev_predicted",
                     txt, re.I), (
        f"{name}: ev_predicted must be COALESCE(ts.ev_raw, ts.ev) — the raw EV. "
        f"Bare ts.ev is the 2026-06-23 circular-training revert.")
    assert re.search(r"COALESCE\(\s*ts\.pop_raw", txt, re.I), (
        f"{name}: pop_predicted must COALESCE ts.pop_raw (raw PoP).")


def test_no_bare_ev_predicted_in_latest():
    name, txt = _latest_view_definition()
    # 'ts.ev)' inside COALESCE is fine; 'ts.ev AS ev_predicted' (bare) is the revert.
    assert not re.search(r"\bts\.ev\s+AS\s+ev_predicted", txt, re.I), (
        f"{name}: bare 'ts.ev AS ev_predicted' reintroduces the self-referential "
        f"training bug (2026-06-23).")
