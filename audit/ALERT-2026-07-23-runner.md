# RUNNER ALERT — nightly-audit incomplete (failed) — 2026-07-23

Written by audit/runner/nightly_runner.py at 2026-07-23 05:00:49Z because the
completion contract was NOT met. The success ping was WITHHELD, so the
receiving dead-man should DOWN-page. Investigate before trusting tonight's
audit — it may be missing or partial.

## Contract
- status=failed met=False manifest=True report_ok=False start_marker=True end_marker=True transcript=True exit0=False (code=1, timed_out=False) missing=['report', 'child_exit']
- MISSING ARTIFACT CLASSES: ['report', 'child_exit']
- manifest_exists: True
- report_ok: False  reasons: ['report file does not exist']
- start_marker_present: True
- end_marker_present: True
- transcript_present: True
- child_exit_zero: False (code=1, timed_out=False)

## Workspace
- audit worktree: C:\Users\17734\AppData\Local\otc-audit-worktree
- target ref: origin/main
- SHA: 14f29190f4755584bf7862404d76d824117f0e6d (stale=False)
- workspace error: None

## Evidence
- per-run transcript: C:\options-trading-companion\audit\transcripts\2026-07-23-12068.log
- marker sink (start/heartbeat/end): C:\options-trading-companion\audit\runner-markers.log
- cron.log: the shim's `>>` capture of the runner's stdout narration

## Likely causes (in order)
1. Host slept mid-run despite the wake lock (check `powercfg /requests`
   history / Event Viewer sleep events) — the primary historical cause.
2. Child (claude) crashed or was killed (non-zero/negative exit).
3. Audit produced no report or a malformed one (see report_reasons).
4. Timeout tripped (timed_out=true) — audit hung.
5. Worktree-safety refusal or marker-sink lock (see the sections above).
