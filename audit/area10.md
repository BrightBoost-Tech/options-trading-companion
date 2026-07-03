# AREA 10 — CALENDAR & CLOCK INTEGRITY (the rotating self-extension slot)

**Adopted:** 2026-07-03 (v5.3 FULL run 1; slot OPEN — A9 graduated to standing by owner
decision 2026-07-03, carrying no incumbency here). **Replaces:** none (first occupant of
the A10 slot).

**Rationale for adoption:** five time-boundary failures or near-misses in 72 hours, and
no area owns the class: (1) #1123 — a hardcoded test-fixture expiry crossed its
dte_threshold window at midnight UTC and turned ALL CI red for every diff (shipped fix:
relative dates); (2) the watch→merge automation fired into a presumed-RTH morning that
was actually the July-4th-observed holiday (false alarm, retracted against the broker
clock; P2 guard filed); (3) holiday-blind `is_us_market_hours` produces 4–7 false HIGH
`ops_data_stale` rows per market holiday while its own docstring claims "at most one";
(4) the winter-close asymmetry — the session-OPEN side was DST-hardened (14:30Z warm-up
anchor) but the CLOSE side is hardcoded 20:00Z, leaving the final EST-season session
hour (20:00–21:00Z) with staleness alerts suppressed AND intraday-job watchdog verdicts
unconditionally "ok" — a dead monitor in that hour is undetected from November to March;
(5) the alert cooldown (30m) vs check cadence (30m) suppression that holds by a
~2-second scheduling offset. A1–A9 audit components; nothing audits the calendar seams
BETWEEN them. Time boundaries are where correct components compose into wrong systems.

**Goal:** every date/time boundary the system computes with — DST transitions, market
holidays, weekends, session open/close edges, day-rollover (UTC vs CT vs broker), test
fixtures with absolute dates, cooldown-vs-cadence phase alignment — behaves correctly
ON the boundary, and every doc/docstring describing time behavior matches the measured
rate.

## Look-at list (each run)

1. **Upcoming-boundary preview:** what calendar events fall before the next audit
   (DST change, holiday, quarter/year rollover, any fixture date within 30 days)? For
   each: which code paths cross it, and is each verified or flagged?
2. **Hardcoded-date sweep:** tests and code containing absolute future dates (the #1123
   class) — anything entering a decision window within 45 days is a finding.
3. **Weekday-math vs broker-calendar:** sites using `weekday()`/mon-fri where the broker
   calendar is the truth (`get_clock`/`get_calendar`) — new sites since last run.
4. **Session-edge parity:** open-side vs close-side hardening symmetry
   (`is_us_market_hours`, `_rth_job_status`, warm-up anchors) in both DST regimes.
5. **Phase-alignment inventory:** cooldowns, TTLs, and cadences that are EQUAL or
   near-equal (suppression by coincidence) — margin measured in seconds is a finding.
6. **Docstring-vs-measured-rate:** any comment claiming a time-conditional frequency
   ("at most one per X") checked against actual rows.

**Constraints:** READ-ONLY; broker clock/calendar outranks all local weekday math;
findings need a quantified consequence (a boundary that changes a decision, an alert
rate, or a detection window). **Disqualifiers:** ledger re-finds (#1123 shipped; the
holiday-merge P2 is filed); timezone pedantry with no decision consequence; proposals
that add calendar dependencies to safety paths without a fail-safe.

## Run log

- **2026-07-03 (adoption run):** instances (1)–(5) enumerated above. NEW finding this
  run: the winter-close blind hour (item 4 above; fix recommended alongside the next
  ops_health PR before November). Shared finding with A9: the "at most one per holiday"
  docstring (A9-F5). Verified-correct on sweep: scheduler mon–fri holiday-blindness is
  safe-by-design (holiday jobs no-op; the staleness gate correctly blocked today's
  holiday executor run); `_weekend_excluded_age` UTC-skew documented and bounded;
  `_RTH_WARMUP_OPEN_UTC` winter anchor correct; remaining hardcoded test expiries are
  concentration-grouping-only (swept under #1123). Next-boundary preview: no DST change
  until 2026-11-01 (the winter-close blind hour activates then); next holiday Labor Day
  2026-09-07; no fixture date inside 45 days.
