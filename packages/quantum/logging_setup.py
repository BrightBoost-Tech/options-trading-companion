"""Process-wide logging configuration (PR-0, F-LOG-INFO-DROP, 2026-07-13).

Until this module existed the repo had NO logging configuration anywhere:
the workers start as a bare ``rq worker`` CLI (no entrypoint of ours), so the
root logger fell back to Python's lastResort handler (stderr, WARNING) and
EVERY ``logger.info`` in the application was dropped in-process — including
the #1187 shadow heartbeats that were built precisely to detect silent
observe windows. The d5edd50 arm-evidence window collected nothing because
of this.

Polarity (ledgered): fail-OPEN on visibility. Root at INFO with one stream
handler; third-party chatty libs pinned to WARNING by an explicit denylist.
The opposite shape — a targeted allowlist of app loggers raised to INFO —
is the drift class that caused this finding: every new observe window would
have to remember to register itself, and the one that forgets is silent
again. Noisy is tunable; silent is undiagnosable.

Call sites (one per service entrypoint):
- ``packages.quantum.jobs.runner`` (module import) — both RQ workers; the
  canary line appears at the FIRST JOB after a recycle, not container start,
  because the bare ``rq worker`` start command imports nothing of ours.
- ``packages.quantum.api`` (module import) — the BE/uvicorn process.
"""
import logging
import os
import sys

# Attribute stamped on the root logger after configuration — survives
# re-imports within the process, keys the idempotence check.
_CONFIGURED_FLAG = "_otc_logging_configured"

# Third-party loggers pinned to WARNING (operator-enumerated + the known
# request-per-line offenders that ride under supabase-py). Pinning here can
# never hide app evidence: packages.quantum.* loggers stay at the root level.
# NOTE ``rq`` is pinned per the PR-0 charter — job lifecycle truth lives in
# ``job_runs`` rows, not the worker's stdout.
NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "requests",
    "postgrest",
    "supabase",
    "gotrue",
    "storage3",
    "realtime",
    "apscheduler",
    "asyncio",
    "rq",
)


def setup_logging() -> bool:
    """Configure root logging once per process.

    Returns True on the call that actually configured, False on repeat calls
    (idempotent — repeat calls never stack handlers). Level override via
    ``OTC_LOG_LEVEL`` (default INFO); an unknown value falls back to INFO
    rather than raising (a typo in an env var must not kill a worker).
    """
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_FLAG, False):
        return False

    level_name = (os.environ.get("OTC_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level_name, level = "INFO", logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(level)

    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    setattr(root, _CONFIGURED_FLAG, True)

    # The canary: the PRESENCE of this line in Railway deploy logs proves the
    # configuration deployed and INFO reaches stdout. Do not reword — the H8
    # read-back greps for "logging configured".
    logging.getLogger(__name__).info(
        "logging configured root=%s handler=stream noisy_pinned=%d",
        level_name, len(NOISY_LOGGERS),
    )
    return True
