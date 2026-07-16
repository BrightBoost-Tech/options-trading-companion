"""Shadow-to-expiry thesis tracker (I5, 2026-07-11) — scoring + job contract.

Drives the pure scorer per structure AND the production handler end-to-end
(fake client + mocked price feed): the F-A4-1 partial contract, idempotent
skip of terminal verdicts, in_progress on a future expiry, unknown on a missing
price.
"""
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta, time
from zoneinfo import ZoneInfo

from packages.quantum.analytics.thesis_scoring import score_thesis, classify_structure
from packages.quantum.jobs.handlers import thesis_tracker as tt


def _ic(sp=650, lp=645, sc=765, lc=770, expiry="2026-06-18"):
    return [
        {"type": "put",  "action": "sell", "strike": sp, "expiry": expiry},
        {"type": "put",  "action": "buy",  "strike": lp, "expiry": expiry},
        {"type": "call", "action": "sell", "strike": sc, "expiry": expiry},
        {"type": "call", "action": "buy",  "strike": lc, "expiry": expiry},
    ]


def _bull_put(sold=500, bought=495):
    return [{"type": "put", "action": "sell", "strike": sold},
            {"type": "put", "action": "buy",  "strike": bought}]


def _bull_call(bought=500, sold=505):
    return [{"type": "call", "action": "buy",  "strike": bought},
            {"type": "call", "action": "sell", "strike": sold}]


# ── scoring (pure) ──────────────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_iron_condor(self):
        self.assertEqual(classify_structure(_ic()), "iron_condor")

    def test_credit_vertical(self):
        self.assertEqual(classify_structure(_bull_put()), "credit_vertical")

    def test_debit_vertical(self):
        self.assertEqual(classify_structure(_bull_call()), "debit_vertical")

    def test_directional(self):
        self.assertEqual(classify_structure([{"type": "call", "action": "buy", "strike": 500}]),
                         "directional")


class TestIronCondor(unittest.TestCase):
    def test_inside_is_hit(self):
        self.assertEqual(score_thesis(_ic(), 700.0)[0], "hit")

    def test_above_short_call_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 800.0)[0], "miss")

    def test_below_short_put_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 600.0)[0], "miss")

    def test_at_short_call_boundary_is_miss(self):
        # strict: AT the short strike = reached = MISS
        self.assertEqual(score_thesis(_ic(), 765.0)[0], "miss")

    def test_at_short_put_boundary_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 650.0)[0], "miss")


class TestVerticals(unittest.TestCase):
    def test_credit_put_kept_is_hit(self):
        self.assertEqual(score_thesis(_bull_put(), 510.0)[0], "hit")   # above short → OTM

    def test_credit_put_breached_is_miss(self):
        self.assertEqual(score_thesis(_bull_put(), 490.0)[0], "miss")  # below short → breached

    def test_debit_call_itm_is_hit(self):
        self.assertEqual(score_thesis(_bull_call(), 510.0)[0], "hit")  # above long → ITM

    def test_debit_call_otm_is_miss(self):
        self.assertEqual(score_thesis(_bull_call(), 495.0)[0], "miss")


class TestDirectionalAndUnknown(unittest.TestCase):
    def test_long_call_itm_hit(self):
        self.assertEqual(score_thesis([{"type": "call", "action": "buy", "strike": 500}], 510.0)[0], "hit")

    def test_long_call_otm_miss(self):
        self.assertEqual(score_thesis([{"type": "call", "action": "buy", "strike": 500}], 490.0)[0], "miss")

    def test_unknown_on_missing_price(self):
        self.assertEqual(score_thesis(_ic(), None)[0], "unknown")


# ── handler (production route, fake client + mocked feed) ────────────────────

class _Q:
    """Fake supabase query for the handler. Dispatches by table; records upserts."""
    def __init__(self, table, store):
        self.table_name = table
        self.store = store
        self._filters = {}
        self._select_args = ()

    def select(self, *a, **k):
        self._select_args = a
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[(col, "in")] = set(vals)
        return self

    def execute(self):
        if self.table_name == "paper_positions":
            return MagicMock(data=list(self.store["positions"]))
        if self.table_name == "paper_portfolios":
            return MagicMock(data=list(self.store["portfolios"]))
        if self.table_name == "paper_orders":
            return MagicMock(data=list(self.store["orders"]))
        if self.table_name == "position_thesis_outcomes":
            # Inject a FAILURE at only the population-summary select (the one that
            # projects execution_mode) — the terminal-check select and upserts
            # still succeed, proving upserts are preserved on a summary failure.
            cols = " ".join(self._select_args)
            if self.store.get("pop_fail") and "execution_mode" in cols:
                raise RuntimeError("injected population summary fetch failure")
            return MagicMock(data=list(self.store["terminal"]))
        return MagicMock(data=[])

    def upsert(self, row, on_conflict=None):
        self.store["upserts"].append(row)
        return self


class _FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(name, self.store)


def _run_handler(store, bars_by_symbol):
    from packages.quantum.jobs.handlers import thesis_tracker as tt

    class _Truth:
        def daily_bars(self, symbol, start, end):
            return bars_by_symbol.get(symbol, [])

    with patch.object(tt, "get_admin_client", return_value=_FakeClient(store)), \
         patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
               return_value=_Truth()):
        return tt.run({})


class TestHandlerContract(unittest.TestCase):
    def _store(self, positions, orders=None, terminal=None):
        return {
            "positions": positions,
            "portfolios": [{"id": "port-agg", "routing_mode": "live_eligible"}],
            "orders": orders or [],
            "terminal": terminal or [],
            "upserts": [],
        }

    def _pos(self, pid, expiry, legs, symbol="QQQ"):
        return {"id": pid, "user_id": "u1", "symbol": symbol, "nearest_expiry": expiry,
                "created_at": "2026-06-01T00:00:00+00:00", "closed_at": "2026-06-10T00:00:00+00:00",
                "close_reason": "stop_loss_hit", "realized_pl": -50, "legs": legs,
                "portfolio_id": "port-agg"}

    def test_scores_hit_from_bars(self):
        store = self._store([self._pos("p1", "2026-06-18", _ic())])
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})
        self.assertEqual(out["counts"]["errors"], 0)
        row = store["upserts"][0]
        self.assertEqual(row["thesis_outcome"], "hit")
        self.assertEqual(row["underlying_at_expiry"], 700.0)

    def test_partial_when_price_missing(self):
        # expiry passed but the feed returns no bars → unknown → counts.errors>0
        store = self._store([self._pos("p2", "2026-06-18", _ic())])
        out = _run_handler(store, {})  # no bars
        self.assertGreaterEqual(out["counts"]["errors"], 1)
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "unknown")

    def test_in_progress_on_future_expiry(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        store = self._store([self._pos("p3", future, _ic())])
        out = _run_handler(store, {"QQQ": [{"date": future, "close": 700.0}]})
        self.assertEqual(out["counts"]["errors"], 0)  # in_progress is NOT an error
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "in_progress")

    def test_scores_on_expiry_day_post_close_run(self):
        # The production job is scheduled post-close. Same-day expiry is
        # terminal-eligible so a Friday contract does not remain in_progress
        # until the next scheduled run after the weekend.
        market_day = datetime.now(ZoneInfo("America/New_York")).date()
        expiry = market_day.isoformat()
        as_of = datetime.combine(
            market_day, time(16, 16), tzinfo=ZoneInfo("America/New_York")
        ).astimezone(timezone.utc)
        store = self._store([self._pos("p3-today", expiry, _ic(expiry=expiry))])
        with patch.object(tt, "_utc_now", return_value=as_of):
            out = _run_handler(
                store, {"QQQ": [{"date": expiry, "close": 700.0}]}
            )
        self.assertEqual(out["counts"]["errors"], 0)
        row = store["upserts"][0]
        self.assertEqual(row["thesis_outcome"], "hit")
        self.assertEqual(row["price_basis"], "expiry_close")

    def test_same_day_manual_preclose_run_stays_in_progress(self):
        market_day = datetime.now(ZoneInfo("America/New_York")).date()
        expiry = market_day.isoformat()
        as_of = datetime.combine(
            market_day, time(15, 59), tzinfo=ZoneInfo("America/New_York")
        ).astimezone(timezone.utc)
        store = self._store([self._pos("p3-preclose", expiry, _ic(expiry=expiry))])
        with patch.object(tt, "_utc_now", return_value=as_of):
            out = _run_handler(
                store, {"QQQ": [{"date": expiry, "close": 700.0}]}
            )
        self.assertEqual(out["counts"]["errors"], 0)
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "in_progress")

    def test_idempotent_skips_terminal(self):
        store = self._store(
            [self._pos("p4", "2026-06-18", _ic())],
            terminal=[{"position_id": "p4", "thesis_outcome": "hit"}],
        )
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})
        self.assertEqual(len(store["upserts"]), 0)  # terminal verdict never re-scored


# ── population headline: EXECUTION-MODE split, never routing (F-A3-4 D2/D3) ──

def _pop_rows(routing, execution, *, scored, in_progress=0, unknown=0, hits=None):
    """Build (scored + in_progress + unknown) position_thesis_outcomes rows for
    one (routing_mode, execution_mode) group. `hits` of the scored rows are
    'hit', the remainder 'miss'."""
    hits = scored if hits is None else hits
    rows = []
    for i in range(scored):
        rows.append({"thesis_outcome": "hit" if i < hits else "miss",
                     "execution_mode": execution, "routing_mode": routing})
    for _ in range(in_progress):
        rows.append({"thesis_outcome": "in_progress",
                     "execution_mode": execution, "routing_mode": routing})
    for _ in range(unknown):
        rows.append({"thesis_outcome": "unknown",
                     "execution_mode": execution, "routing_mode": routing})
    return rows


def _bucket_total(t):
    return t["hit"] + t["miss"] + t["in_progress"] + t["unknown"]


class TestPopulationSummary(unittest.TestCase):
    """The reconciled production-shaped population, split by EXECUTION_MODE.
    routing_mode='live_eligible' must NOT relabel alpaca_paper / internal_paper
    rows as broker-live."""

    def _pinned_population(self):
        # THE authoritative 2026-07-13 broker-live reconciliation census
        # (ledger cohort-reconciliation entry):
        #   alpaca_live               5 hit / 2 miss = 7 scored, +5 in_progress = 12
        #   alpaca_paper              6 hit / 15 miss = 21 scored               = 21
        #   live_eligible/internal    19 hit / 22 miss = 41 scored              = 41
        #   shadow_only/internal      7 hit / 1 miss = 8 scored, +1 in_progress = 9
        #   pooled                    37 hit / 40 miss = 77 scored, +6 ip       = 83
        return (
            _pop_rows("live_eligible", "alpaca_live", scored=7, hits=5,
                      in_progress=5)                       # 12 rows
            + _pop_rows("live_eligible", "alpaca_paper", scored=21, hits=6)  # 21 rows
            + _pop_rows("live_eligible", "internal_paper", scored=41,
                        hits=19)                           # 41 rows
            + _pop_rows("shadow_only", "internal_paper", scored=8, hits=7,
                        in_progress=1)                     # 9 rows
        )

    def test_pinned_population_matches_authoritative_07_13_census(self):
        """The fixture MUST encode the authoritative 2026-07-13 broker-live
        reconciliation census (the ledger's cohort-reconciliation entry), not a
        synthetic stand-in. execution_mode is the broker-truth discriminator;
        routing_mode='live_eligible' pools alpaca_live + alpaca_paper +
        internal_paper eras and must NOT relabel them broker-live."""
        summ = tt._summarize_population(self._pinned_population())
        be = summ["population_by_execution_mode"]
        cross = summ["population_by_routing_x_execution"]
        pooled = summ["pooled_all_modes"]

        # alpaca_live: 5 hit / 2 miss = 7 scored, +5 in_progress = 12 rows
        self.assertEqual(be["alpaca_live"]["hit"], 5)
        self.assertEqual(be["alpaca_live"]["miss"], 2)
        self.assertEqual(be["alpaca_live"]["scored"], 7)
        self.assertEqual(be["alpaca_live"]["in_progress"], 5)
        self.assertEqual(_bucket_total(be["alpaca_live"]), 12)
        self.assertEqual(be["alpaca_live"]["hit_rate"], round(5 / 7, 4))
        # alpaca_paper: 6/21
        self.assertEqual(be["alpaca_paper"]["hit"], 6)
        self.assertEqual(be["alpaca_paper"]["scored"], 21)
        self.assertEqual(_bucket_total(be["alpaca_paper"]), 21)
        self.assertEqual(be["alpaca_paper"]["hit_rate"], round(6 / 21, 4))
        # internal_paper pooled across BOTH routing modes: 19+7=26 / 41+8=49,
        # +1 in_progress → 50 rows
        self.assertEqual(be["internal_paper"]["hit"], 26)
        self.assertEqual(be["internal_paper"]["scored"], 49)
        self.assertEqual(be["internal_paper"]["in_progress"], 1)
        self.assertEqual(_bucket_total(be["internal_paper"]), 50)
        self.assertEqual(be["internal_paper"]["hit_rate"], round(26 / 49, 4))
        # routing×execution cross-tabs: the two internal cohorts stay SEPARATE
        self.assertEqual(cross["live_eligible/internal_paper"]["hit"], 19)
        self.assertEqual(cross["live_eligible/internal_paper"]["scored"], 41)
        self.assertEqual(_bucket_total(cross["live_eligible/internal_paper"]), 41)
        self.assertEqual(cross["shadow_only/internal_paper"]["hit"], 7)
        self.assertEqual(cross["shadow_only/internal_paper"]["scored"], 8)
        self.assertEqual(cross["shadow_only/internal_paper"]["in_progress"], 1)
        self.assertEqual(_bucket_total(cross["shadow_only/internal_paper"]), 9)
        # routing totals: live_eligible 74 rows / 69 scored; shadow 9 / 8.
        live_elig = {k: v for k, v in cross.items()
                     if k.startswith("live_eligible/")}
        self.assertEqual(sum(_bucket_total(v) for v in live_elig.values()), 74)
        self.assertEqual(sum(v["scored"] for v in live_elig.values()), 69)
        # broker-live scored is 7, NEVER the 69 live_eligible-routed scored:
        # naive routing-based "live" would overcount by 62.
        self.assertEqual(be["alpaca_live"]["scored"], 7)
        self.assertEqual(69 - be["alpaca_live"]["scored"], 62)
        # pooled_all_modes: 37 hit / 40 miss = 77 scored, +6 in_progress = 83
        self.assertEqual(pooled["hit"], 37)
        self.assertEqual(pooled["miss"], 40)
        self.assertEqual(pooled["scored"], 77)
        self.assertEqual(pooled["in_progress"], 6)
        self.assertEqual(pooled["unknown"], 0)
        self.assertEqual(pooled["hit_rate"], round(37 / 77, 4))
        # CONSERVATION: total rows == sum of all buckets == 83
        total_rows = len(self._pinned_population())
        self.assertEqual(total_rows, 83)
        self.assertEqual(
            pooled["hit"] + pooled["miss"] + pooled["in_progress"]
            + pooled["unknown"], 83)
        self.assertEqual(total_rows,
                         pooled["hit"] + pooled["miss"]
                         + pooled["in_progress"] + pooled["unknown"])

    def test_pinned_population_by_execution_mode(self):
        summ = tt._summarize_population(self._pinned_population())
        be = summ["population_by_execution_mode"]

        self.assertEqual(be["alpaca_live"]["scored"], 7)
        self.assertEqual(_bucket_total(be["alpaca_live"]), 12)
        self.assertEqual(be["alpaca_paper"]["scored"], 21)
        self.assertEqual(_bucket_total(be["alpaca_paper"]), 21)
        # internal_paper pools BOTH internal cohorts: 19 + 7 = 26 scored,
        # 41 + 8 = 49 scored... (live_eligible/internal 41 scored + shadow 8
        # scored = 49 scored; 41 + 9 = 50 rows incl. the shadow in_progress).
        self.assertEqual(be["internal_paper"]["scored"], 49)
        self.assertEqual(be["internal_paper"]["hit"], 26)
        self.assertEqual(_bucket_total(be["internal_paper"]), 50)
        # nothing stray → the unknown bucket is empty and carries NO hit_rate.
        self.assertEqual(be["unknown_execution_mode"]["scored"], 0)
        self.assertNotIn("hit_rate", be["unknown_execution_mode"])

    def test_hit_rate_only_when_scored(self):
        be = tt._summarize_population(self._pinned_population())["population_by_execution_mode"]
        # alpaca_live: 5 hit / 7 scored → 0.7143.
        self.assertEqual(be["alpaca_live"]["hit"], 5)
        self.assertEqual(be["alpaca_live"]["miss"], 2)
        self.assertEqual(be["alpaca_live"]["hit_rate"], round(5 / 7, 4))

    def test_routing_x_execution_cross_tabs(self):
        cross = tt._summarize_population(
            self._pinned_population())["population_by_routing_x_execution"]

        self.assertEqual(cross["live_eligible/internal_paper"]["scored"], 41)
        self.assertEqual(_bucket_total(cross["live_eligible/internal_paper"]), 41)
        self.assertEqual(cross["shadow_only/internal_paper"]["scored"], 8)
        self.assertEqual(cross["shadow_only/internal_paper"]["in_progress"], 1)
        self.assertEqual(_bucket_total(cross["shadow_only/internal_paper"]), 9)
        # the two internal cohorts stay SEPARATE — routing distinguishes them.
        self.assertNotEqual(cross["live_eligible/internal_paper"],
                            cross["shadow_only/internal_paper"])

    def test_live_eligible_routing_does_not_make_paper_or_internal_live(self):
        summ = tt._summarize_population(self._pinned_population())
        be = summ["population_by_execution_mode"]
        # broker-live scored is ONLY the 7 true alpaca_live rows — NOT the
        # 7 + 21 + 41 = 69 that also carry routing_mode='live_eligible'.
        self.assertEqual(be["alpaca_live"]["scored"], 7)
        self.assertNotEqual(be["alpaca_live"]["scored"], 69)
        # pooled totals live ONLY under the literal pooled label, never "live".
        pooled = summ["pooled_all_modes"]
        self.assertEqual(pooled["scored"], 7 + 21 + 41 + 8)   # 77
        self.assertEqual(_bucket_total(pooled), 83)
        self.assertIn("hit_rate", pooled)                    # scored > 0
        self.assertNotIn("live", summ["population_by_execution_mode"])

    def test_missing_execution_mode_isolated_never_live(self):
        rows = [
            {"thesis_outcome": "hit", "execution_mode": None, "routing_mode": "live_eligible"},
            {"thesis_outcome": "miss", "execution_mode": "", "routing_mode": "live_eligible"},
            {"thesis_outcome": "hit", "execution_mode": "weird_mode", "routing_mode": "shadow_only"},
        ]
        summ = tt._summarize_population(rows)
        be = summ["population_by_execution_mode"]
        # None / "" / unrecognized ALL land under unknown_execution_mode…
        self.assertEqual(be["unknown_execution_mode"]["hit"], 2)
        self.assertEqual(be["unknown_execution_mode"]["miss"], 1)
        self.assertEqual(be["unknown_execution_mode"]["scored"], 3)
        # …and NEVER under alpaca_live.
        self.assertEqual(be["alpaca_live"]["scored"], 0)
        self.assertEqual(be["alpaca_live"]["hit"], 0)
        cross = summ["population_by_routing_x_execution"]
        self.assertIn("live_eligible/unknown_execution_mode", cross)
        self.assertIn("shadow_only/unknown_execution_mode", cross)


class TestHandlerPopulationHeadline(unittest.TestCase):
    def _store(self, positions, terminal=None, pop_fail=False):
        return {
            "positions": positions,
            "portfolios": [{"id": "port-agg", "routing_mode": "live_eligible"}],
            "orders": [],
            "terminal": terminal or [],
            "upserts": [],
            "pop_fail": pop_fail,
        }

    def _pos(self, pid, expiry, legs, symbol="QQQ"):
        return {"id": pid, "user_id": "u1", "symbol": symbol, "nearest_expiry": expiry,
                "created_at": "2026-06-01T00:00:00+00:00", "closed_at": "2026-06-10T00:00:00+00:00",
                "close_reason": "stop_loss_hit", "realized_pl": -50, "legs": legs,
                "portfolio_id": "port-agg"}

    def test_rerun_zero_upserts_but_stable_population_headline(self):
        # p4 already terminal → NO re-score; the population headline is computed
        # from the stored table and is present + distinct from the current run.
        terminal_pop = [
            {"position_id": "p4", "thesis_outcome": "hit",
             "execution_mode": "alpaca_live", "routing_mode": "live_eligible"},
            {"position_id": "p5", "thesis_outcome": "miss",
             "execution_mode": "internal_paper", "routing_mode": "shadow_only"},
        ]
        store = self._store([self._pos("p4", "2026-06-18", _ic())], terminal=terminal_pop)
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})

        self.assertEqual(len(store["upserts"]), 0)          # rerun mutates nothing
        self.assertEqual(out["counts"]["errors"], 0)
        self.assertEqual(out["current_run"]["upserts"], 0)  # (1) current-run counts
        pop = out["population"]                              # (2) full population
        self.assertIsNotNone(pop)
        self.assertEqual(pop["total_rows"], 2)
        be = pop["population_by_execution_mode"]
        self.assertEqual(be["alpaca_live"]["scored"], 1)
        self.assertEqual(be["internal_paper"]["scored"], 1)

    def test_population_fetch_failure_is_partial_but_upserts_preserved(self):
        store = self._store([self._pos("p6", "2026-06-18", _ic())], pop_fail=True)
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})

        # the thesis upsert still committed (preserved) …
        self.assertEqual(len(store["upserts"]), 1)
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "hit")
        # … while the population-summary failure → counts.errors (job PARTIAL).
        self.assertGreaterEqual(out["counts"]["errors"], 1)
        self.assertIsNone(out["population"])


if __name__ == "__main__":
    unittest.main()
