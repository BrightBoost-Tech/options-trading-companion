@echo off
rem ====================================================================
rem nightly-audit shim — invoked by Windows Task Scheduler at 00:00 local.
rem
rem This is now a THIN SHIM. All reliability logic lives in the Python
rem wrapper audit\runner\nightly_runner.py, which:
rem   - holds a wake lock so the laptop cannot sleep mid-run (the 07-16/07-17
rem     silent-death fix),
rem   - fetches origin/main into a dedicated audit worktree and runs the audit
rem     against the RUNNING code (never the operator checkout),
rem   - drops a read-only broker snapshot + capability manifest for the
rem     headless (MCP-absent) audit,
rem   - streams a per-run transcript + heartbeats to cron.log,
rem   - enforces a hard timeout, writes an UNCONDITIONAL end marker, and
rem   - only pings the dead-man when the completion contract is met.
rem
rem The shim's only jobs: locate a Python 3.11 interpreter and launch the
rem wrapper, capturing any python-level traceback into cron.log as a last
rem resort. The wrapper writes its own start/heartbeat/end markers directly.
rem ====================================================================
cd /d C:\options-trading-companion

set "PYCMD="
where py >nul 2>&1 && set "PYCMD=py -3.11"
if not defined PYCMD (
  where python >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
  echo ==== %DATE% %TIME% nightly-audit SHIM ERROR: no python interpreter found ==== >> audit\cron.log
  exit /b 9
)

echo ==== %DATE% %TIME% shim launching runner (%PYCMD%) ==== >> audit\cron.log
%PYCMD% "C:\options-trading-companion\audit\runner\nightly_runner.py" >> audit\cron.log 2>&1
set RC=%ERRORLEVEL%
if not "%RC%"=="0" echo ==== %DATE% %TIME% shim: runner exited %RC% ==== >> audit\cron.log
exit /b %RC%
