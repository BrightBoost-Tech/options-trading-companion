@echo off
rem nightly-audit runner — invoked by Windows Task Scheduler at 00:00 local daily.
rem READ-ONLY audit; permission scope pinned by audit\nightly-settings.json
rem (file writes only under audit\, no shell, no deploy/migration/order tools).
cd /d C:\options-trading-companion
echo ==================================================================== >> audit\cron.log
echo ==== %DATE% %TIME% nightly-audit start ==== >> audit\cron.log
claude -p "Execute audit/v5-prompt.md in NIGHTLY mode (FULL on Sundays)." --settings audit\nightly-settings.json --max-turns 200 >> audit\cron.log 2>&1
echo ==== %DATE% %TIME% nightly-audit end (exit %ERRORLEVEL%) ==== >> audit\cron.log
