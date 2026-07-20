# Emergency Market-Calendar Hotfix — space-separated datetime bounds — 2026-07-20

Mid-session hotfix, operator-authorized while the market was OPEN (broker reported flat).
Orchestrator: Fable (claude-fable-5). Opus build + adversarial-review agents. **Zero migration /
production-DB write / broker write / fleet action / env / live-control change; no manual
suggestions_open rerun, no executor trigger.**

## Incident
Monday 2026-07-20, ~09:00–09:18 CT (14:00–14:18 UTC), the operator issued two forced
`suggestions_open --skip-time-gate --force` requests. Both were accepted as distinct fresh forced
jobs (`df3c56e9`, `25a96ae6`), claimed immediately, completed in ~370 ms, and terminated
`status='partial'` with `counts.errors=1` — **zero decision_runs, zero suggestions** — firing two
HIGH `job_succeeded_with_errors` alerts (`82d407f5`, `6e0a7d67`; the #1100 A4 detector). The
`--skip-time-gate`/`--force` flags worked correctly at the endpoint; there was **no
forced-idempotency defect**. The failure was a later boundary.

## Root cause (two-layer, both introduced by Lane C #1304 `54fd978a`)
The alpaca-py SDK `Calendar.open`/`.close` are **naive `datetime` objects** (built by the SDK via
`strptime("%Y-%m-%d %H:%M")` from the API's ET session strings), whose `str()` is the
space-separated `'2026-07-20 09:30:00'`.
1. `brokers/alpaca_client.py::get_calendar` blindly `str()`'d those objects, emitting the
   space-separated form — contradicting its docstring's promise of normalized bare ET times
   (DOC≠BUILT).
2. `services/market_session.py::_parse_session_time` only accepted `HH:MM`, `HH:MM:SS`, or a
   `'T'`-containing ISO datetime. A space-separated datetime matched neither → returned `None` →
   `get_market_session` raised `MarketCalendarUnavailable` → `suggestions_open` fail-closed before
   scanning. **Fail-closed but fail-WRONG:** entries were blocked on every valid trading day on the
   deployed SHA.

## The fix (PR #1320, merge `2070056f`)
One canonical parsing authority. `_parse_session_time` now branches on SHAPE (not the literal
`'T'`): `datetime` objects (tz-aware → convert to America/New_York then take the time; naive → its
clock fields are ET session wall-time, never reinterpreted as UTC), `time` objects, `'T'`-OR-space
ISO strings (`datetime.fromisoformat`, which handles both separators + offsets in Python 3.11),
bare `HH:MM`/`HH:MM:SS`(+fractional). A date-only string or bare `date` object → `None`; malformed
→ `None`. New `normalize_session_bound` renders a coerced time to a bare `'HH:MM'` string and
delegates to the same helper (no second parser). `AlpacaClient.get_calendar` now normalizes SDK
bounds through `normalize_session_bound` (lazy import, cycle-safe), fulfilling its documented
bare-time contract. **H9 preserved:** a genuinely malformed row still yields `None` bounds →
`MarketCalendarUnavailable` → fail-closed. Files: `packages/quantum/services/market_session.py`,
`packages/quantum/brokers/alpaca_client.py`, new
`packages/quantum/tests/test_market_session_datetime_bounds.py` (41 route-driven tests).

**No control changed:** holiday source, fail-closed behavior, open/close boundaries, time gates,
scan schedule, and all liquidity/H7/cost/calibration/edge/risk/suggestions/executor/routing
behavior are byte-untouched. The change only makes valid calendar rows readable.

## Verification
- **Adversarial review: PASS** (8/8 questions) — independently confirmed the alpaca-py Calendar
  model yields naive ET-wall datetimes (naive→ET rule provably correct; the fix also corrects a
  latent aware-datetime bug), fail-closed preserved, no closed-day-as-open vector, one parser
  authority, scope exactly 3 files.
- **CI:** green at head `4f73e343`.
- **Deployment:** all four services SUCCESS at merge `2070056f` (~15:28 UTC), no mixed backend.
- **Post-deploy read-only smoke** (deployed resolver, no trading job): the exact incident shape
  `'2026-07-20 09:30:00'` → `is_trading_day=True`, `open_at=09:30 ET`, `close_at=16:00 ET`,
  `is_early_close=False`, `MarketCalendarUnavailable=False`; raw SDK naive datetime → same;
  malformed → `MarketCalendarUnavailable` (fail-closed preserved); empty calendar → non-trading
  (not raised). Live Alpaca calendar for 2026-07-20 = trading day, open 09:30 / close 16:00.
- **The two forced partial rows remain historical and untouched** (no rerun, no mutation).

## Natural falsifier — PASSED (live production proof)
The scheduled 11:00 CT / 16:00 UTC `suggestions_open` scan (`c526991f`, `apscheduler_in_process`
— natural, NOT forced) ran on the fixed worker (`2070056f`):
- **status = succeeded**, `counts.errors=0`, duration **41.6 s** — a full decision cycle, vs the
  incident's 370 ms fast-path blocks.
- **Passed the calendar gate** (`blocked`/`fast_path`/`reason` all null) and reached a decision
  cycle (**1 new `decision_runs` row** — the blocked forced runs produced zero).
- Scanned the universe and **honestly rejected all 163 candidates** through the ordinary gates
  (163 `suggestion_rejections`), persisting **0 `trade_suggestions`** and placing **0
  `paper_orders`**.
- **No new `job_succeeded_with_errors` alert** (errors=0) — the fix cleared the alert class too.

This is a REAL honest zero (universe scanned, all candidates rejected by the normal controls in
learning-mode) — the decisive contrast with the incident's FAKE zero (blocked before any scan).
Broker remained flat (0/0); `entries_paused` untouched; no order placed; no control loosened.

## Mid-session authorization
Explicit operator override `MID_SESSION_HOTFIX_MERGE_AUTHORIZED=true`, `WAIT_UNTIL_MARKET_CLOSE=false`
(broker flat). It authorized ONLY the narrow code hotfix + merge + deploy — not a manual scan,
executor run, order, threshold change, or control bypass. All safety gates (broker flat 0/0, single
current-main SHA, no unexplained crit/high beyond the two known calendar alerts, no file-ownership
collision) were confirmed before and after.

## Separate non-blocking follow-ups (NOT part of this hotfix)
- **Async CLI result-follow UX:** the signed CLI returns after the HTTP 202 enqueue and does not
  surface the eventual `suggestions_open` job result, so the operator saw "nothing came back"
  without the terminal reason. Consider a `--wait`/status-follow option. (UX, not a scanner bug.)
- **`url.txt` secret-at-rest:** an untracked repo-root file holds a Postgres connection string with
  an embedded password — a security-hygiene item to remove/gitignore, adjudicated separately (not
  broadened into this hotfix; no secret reproduced).
