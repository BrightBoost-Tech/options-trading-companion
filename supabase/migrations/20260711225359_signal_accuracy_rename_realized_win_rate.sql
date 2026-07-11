-- F-A9-1 (2026-07-11): the signal_accuracy_rolling.hit_rate column counts
-- pnl_realized>0 — a REALIZED WIN RATE, not signal/thesis accuracy. It was read
-- as "signal accuracy" (the 12.5%-vs-~78% confusion). Rename it to what it is;
-- true thesis accuracy is now its own measure in position_thesis_outcomes.
ALTER VIEW signal_accuracy_rolling RENAME COLUMN hit_rate TO realized_trade_win_rate;
