@echo off
rem nightly-audit runner — invoked by Windows Task Scheduler at 00:00 local daily.
rem READ-ONLY audit; permission scope pinned by audit\nightly-settings.json
rem (file writes only under audit\, no shell, no deploy/migration/order tools).
cd /d C:\options-trading-companion
echo ==================================================================== >> audit\cron.log
echo ==== %DATE% %TIME% nightly-audit start ==== >> audit\cron.log
claude -p "Execute audit/v5-prompt.md in NIGHTLY mode (FULL on Sundays)." --settings audit\nightly-settings.json --max-turns 200 >> audit\cron.log 2>&1
echo ==== %DATE% %TIME% nightly-audit end (exit %ERRORLEVEL%) ==== >> audit\cron.log

rem ── Dead-man ping (2026-07-08, meta-audit gap #8): ping healthchecks ONLY
rem after the dated report file exists. A run that launches but writes no
rem report sends NO ping, so the DOWN email fires — the 06-13/06-14/06-20
rem silent-empty class becomes visible. NOTE: %DATE% on this machine is
rem locale-formatted ("Wed 07/08/2026") and would NEVER match the YYYY-MM-DD
rem report filenames — the date MUST come from PowerShell. Unset ping URL =
rem logged no-op (this block can never fail the run).
for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set RDATE=%%i
if not exist "audit\reports\%RDATE%.md" (
  echo ==== %DATE% %TIME% REPORT MISSING for %RDATE% — ping WITHHELD ==== >> audit\cron.log
  goto :eof
)
if "%NIGHTLY_AUDIT_PING_URL%"=="" (
  echo ==== %DATE% %TIME% report %RDATE%.md exists; NIGHTLY_AUDIT_PING_URL unset — ping skipped ==== >> audit\cron.log
  goto :eof
)
curl -fsS -m 10 "%NIGHTLY_AUDIT_PING_URL%" >nul 2>&1
echo ==== %DATE% %TIME% report %RDATE%.md exists; ping sent (curl exit %ERRORLEVEL%) ==== >> audit\cron.log
