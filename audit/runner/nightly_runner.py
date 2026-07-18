#!/usr/bin/env python3
"""Nightly audit runner — reliability wrapper around ``claude -p``.

Replaces the bare ``claude -p >> cron.log`` invocation in run-nightly.cmd. It
exists because the nightly audit loop silently DIED on 2026-07-16 and
2026-07-17 (start markers in cron.log with no end markers, no report), and the
same class hit weekends on 06-14 / 07-05 / 07-11. Root cause: the audit host
is a laptop that SLEEPS mid-run. The scheduled task already sets WakeToRun=true
(verified in the exported XML) — so the machine wakes to *start* the task — but
nothing holds it awake DURING the ~11-18 minute run, so the OS idle timer
re-engages and suspends/kills the whole process tree partway through. In
``-p`` headless mode Claude emits output only at run end, so a kill at any
point leaves ZERO transcript — exactly the empty cron.log signature observed.

WHAT THIS WRAPPER ADDS (defense in depth):
  1. WAKE LOCK — SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED
     [|ES_AWAYMODE_REQUIRED]) held for the whole run so the machine cannot
     sleep under it. This is `powercfg /requests`-visible (EXECUTION). This is
     the PRIMARY fix for the observed death mode. (Chosen over
     `powercfg /requestsoverride` because that needs an elevated one-time
     config and is per-app-name, not per-run; the P/Invoke is scoped to the
     process and self-clears on exit.)
  2. FRESH-CODE WORKSPACE — `git fetch --prune origin main` + a DEDICATED audit
     worktree forced to origin/main, so the audit reads the RUNNING code, not
     whatever stale SHA the operator checkout happens to sit at. The operator
     checkout is never touched.
  3. HEADLESS BROKER SNAPSHOT — a read-only GET-only broker capture dropped
     into the worktree so the (MCP-absent) audit has a secondary broker-truth
     source. See broker_snapshot.py.
  4. HEARTBEAT + PER-RUN TRANSCRIPT — timestamped liveness lines to cron.log
     every ~60s and the child's stdout/stderr streamed to a per-run file, so a
     killed run leaves evidence of how far it got.
  5. HARD TIMEOUT — graceful terminate then forced tree-kill, so a hung child
     cannot occupy the machine indefinitely.
  6. UNCONDITIONAL END MARKER (try/finally) with the exact child exit code.
  7. COMPLETION CONTRACT — success ONLY when the manifest exists, the report
     exists and passes structural checks (nonzero, expected header, references
     the run SHA), the end marker is written, the child exited 0, and the ping
     is sent or explicitly unavailable. Otherwise a failure artifact
     (audit/ALERT-<date>-runner.md) is written and the success ping is
     WITHHELD — so the receiving dead-man DOWN-pages.

IMPORT SAFETY: this module imports cleanly on Linux/CI. Every Windows-only
call (ctypes wake lock, taskkill) is deferred behind a `sys.platform` guard at
call time, so pytest can import and drive the logic on any platform.
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

RUNNER_VERSION = "1"
DEFAULT_TIMEOUT_SEC = 90 * 60  # 90 minutes — recent runs took 11-18 min; wide margin.
DEFAULT_HEARTBEAT_SEC = 60
DEFAULT_GRACE_SEC = 20  # graceful-terminate window before forced kill
REPORT_HEADER_PREFIX = "# AUDIT"
MARK_START = "nightly-audit start"
MARK_END = "nightly-audit end"
MARK_HEARTBEAT = "nightly-audit heartbeat"


# ---------------------------------------------------------------------------
# time / logging helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_ts(now: Optional[datetime.datetime] = None) -> str:
    return (now or utcnow()).strftime("%Y-%m-%d %H:%M:%SZ")


def local_date_str(now: Optional[datetime.datetime] = None) -> str:
    return (now or datetime.datetime.now()).strftime("%Y-%m-%d")


def append_line(path: Path, line: str) -> None:
    """Append a single line to a log file, best-effort (never raises)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line.rstrip("\n") + "\n")
    except OSError:
        pass


def write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)


def copy_atomic(src: Path, dst: Path) -> None:
    """Copy src->dst via a temp file + os.replace so dst is never partial."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    data = src.read_bytes()
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dst)


# ---------------------------------------------------------------------------
# single-instance lock
# ---------------------------------------------------------------------------
def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
        )
        return str(pid) in out.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class SingleInstanceLock:
    """Atomic exclusive-create lockfile carrying the owner PID.

    A stale lock (owner PID no longer alive) is reclaimed. This prevents two
    overlapping nightly runs (e.g. a hung run plus the next night's trigger)
    from racing on the worktree and the report.
    """

    def __init__(self, path: Path, pid: Optional[int] = None) -> None:
        self.path = Path(path)
        self.pid = pid if pid is not None else os.getpid()
        self._held = False

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):  # one reclaim retry
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w") as fh:
                    fh.write(str(self.pid))
                self._held = True
                return True
            except FileExistsError:
                if self._reclaim_if_stale():
                    continue
                return False
        return False

    def _reclaim_if_stale(self) -> bool:
        try:
            owner = int(self.path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            owner = 0
        if owner == self.pid:
            # our own lock (re-entrant) — treat as held
            self._held = True
            return False
        if owner and _pid_alive(owner):
            return False
        # stale — remove and let the caller retry the exclusive create
        try:
            self.path.unlink()
        except OSError:
            return False
        return True

    def release(self) -> None:
        if not self._held:
            return
        try:
            owner = int(self.path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            owner = self.pid
        if owner == self.pid:
            try:
                self.path.unlink()
            except OSError:
                pass
        self._held = False

    def __enter__(self) -> "SingleInstanceLock":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.release()


# ---------------------------------------------------------------------------
# wake lock (Windows execution-state)
# ---------------------------------------------------------------------------
class WakeLock:
    """Hold the machine awake for the duration of the run.

    On Windows: SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    [| ES_AWAYMODE_REQUIRED]). ES_CONTINUOUS makes the request persist until
    cleared; ES_SYSTEM_REQUIRED forbids system sleep; ES_AWAYMODE_REQUIRED (best
    effort) keeps it running through connected-standby where supported. On any
    other platform this is a logged no-op (CI/tests).
    """

    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    ES_AWAYMODE_REQUIRED = 0x00000040

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log or (lambda _m: None)
        self._active = False

    def __enter__(self) -> "WakeLock":
        if sys.platform != "win32":
            self._log("wake lock: non-Windows platform — no-op (host cannot sleep in tests/CI)")
            return self
        try:
            import ctypes  # noqa: PLC0415 — Windows-only, deferred to call time

            kernel32 = ctypes.windll.kernel32
            flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED | self.ES_AWAYMODE_REQUIRED
            res = kernel32.SetThreadExecutionState(flags)
            if res == 0:
                # AWAYMODE unsupported on this SKU — retry without it.
                flags = self.ES_CONTINUOUS | self.ES_SYSTEM_REQUIRED
                res = kernel32.SetThreadExecutionState(flags)
            self._active = res != 0
            if self._active:
                self._log("wake lock ACQUIRED (SetThreadExecutionState; powercfg /requests-visible)")
            else:
                self._log("wake lock FAILED to acquire (SetThreadExecutionState returned 0)")
        except Exception as exc:  # noqa: BLE001
            self._log(f"wake lock error (continuing without it): {exc}")
        return self

    def __exit__(self, *exc: Any) -> None:
        if sys.platform != "win32" or not self._active:
            return
        try:
            import ctypes  # noqa: PLC0415

            ctypes.windll.kernel32.SetThreadExecutionState(self.ES_CONTINUOUS)
            self._log("wake lock released")
        except Exception as exc:  # noqa: BLE001
            self._log(f"wake lock release error: {exc}")


# ---------------------------------------------------------------------------
# git / fresh-code worktree
# ---------------------------------------------------------------------------
GitRun = Callable[[List[str]], str]


def _default_git_run(args: List[str]) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=True
    ).stdout


@dataclasses.dataclass
class WorkspaceInfo:
    path: str
    target_ref: str
    sha: Optional[str] = None
    short_sha: Optional[str] = None
    stale: bool = False
    error: Optional[str] = None
    prior_report_date: Optional[str] = None
    commit_subjects_since_prior_report: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def refresh_audit_worktree(
    operator_repo: Path,
    worktree: Path,
    remote: str,
    branch: str,
    git_run: GitRun,
    prior_report_date: Optional[str] = None,
    log: Optional[Callable[[str], None]] = None,
) -> WorkspaceInfo:
    """Fetch origin/<branch> and force a DEDICATED worktree to that tip.

    The operator checkout is READ-ONLY here: we only `git -C <operator_repo>
    fetch` (which never touches its working tree) and `git -C <operator_repo>
    worktree add <dedicated_path>`. All checkout/reset --force operations run
    ONLY against the dedicated worktree path. If the fetch or refresh fails, we
    mark the workspace `stale=True` LOUDLY so the audit knows it may be reading
    old code (the old silent-stale-checkout failure, now surfaced).
    """
    log = log or (lambda _m: None)
    target = f"{remote}/{branch}"
    info = WorkspaceInfo(path=str(worktree), target_ref=target, prior_report_date=prior_report_date)

    try:
        git_run(["-C", str(operator_repo), "fetch", "--prune", remote, branch])
        log(f"fetched {target}")
    except Exception as exc:  # noqa: BLE001
        info.stale = True
        info.error = f"fetch failed: {exc}"
        log(f"WARNING fetch failed — worktree may be stale: {exc}")

    try:
        is_worktree = (worktree / ".git").exists()
        if not is_worktree:
            git_run(
                ["-C", str(operator_repo), "worktree", "add", "--force",
                 "--detach", str(worktree), target]
            )
            log(f"created audit worktree at {worktree}")
        else:
            git_run(["-C", str(worktree), "checkout", "--force", "--detach", target])
            git_run(["-C", str(worktree), "reset", "--hard", target])
            log(f"refreshed audit worktree at {worktree} -> {target}")
    except Exception as exc:  # noqa: BLE001
        info.stale = True
        info.error = (info.error + "; " if info.error else "") + f"worktree refresh failed: {exc}"
        log(f"WARNING worktree refresh failed — may be stale: {exc}")

    try:
        info.sha = git_run(["-C", str(worktree), "rev-parse", "HEAD"]).strip() or None
        if info.sha:
            info.short_sha = info.sha[:8]
    except Exception as exc:  # noqa: BLE001
        info.error = (info.error + "; " if info.error else "") + f"rev-parse failed: {exc}"
        info.stale = True

    # Commit subjects since the prior report (best-effort — never fail the run).
    try:
        log_args = ["-C", str(worktree), "log", "--no-merges", "--pretty=format:%h %s"]
        if prior_report_date:
            log_args.append(f"--since={prior_report_date} 00:00")
        else:
            log_args.append("-30")
        log_args.append(target)
        out = git_run(log_args).strip()
        info.commit_subjects_since_prior_report = [
            ln for ln in out.splitlines() if ln.strip()
        ][:60]
    except Exception as exc:  # noqa: BLE001
        info.commit_subjects_since_prior_report = [f"(commit-subject read failed: {exc})"]

    return info


def find_prior_report_date(reports_dir: Path, today: str) -> Optional[str]:
    """Most recent audit/reports/YYYY-MM-DD.md strictly before `today`."""
    if not reports_dir.exists():
        return None
    dates: List[str] = []
    for p in reports_dir.glob("*.md"):
        stem = p.stem
        if len(stem) == 10 and stem[4] == "-" and stem[7] == "-" and stem < today:
            dates.append(stem)
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# child spawn + monitor (heartbeat, transcript, timeout -> terminate -> kill)
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class ChildResult:
    exit_code: int
    timed_out: bool
    duration_sec: float
    pid: Optional[int] = None


def _terminate_process_tree(proc: "subprocess.Popen[Any]") -> None:
    """Best-effort GRACEFUL stop of the child (and, on POSIX, its group).

    On Windows we use TerminateProcess (proc.terminate) rather than a
    CTRL_BREAK_EVENT: CTRL_BREAK is delivered to the whole console group and
    can propagate to the parent (killing an unattended runner or, in tests,
    the pytest process). The forced step below (taskkill /T) still reaps the
    child's subprocess tree.
    """
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass


def _kill_process_tree(proc: "subprocess.Popen[Any]") -> None:
    """FORCED kill of the whole child tree."""
    if proc.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
            capture_output=True,
        )
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass


def spawn_and_monitor(
    child_argv: Sequence[str],
    cwd: Optional[Path],
    transcript_path: Path,
    cron_log: Path,
    timeout_sec: int,
    heartbeat_sec: int,
    grace_sec: int,
    log: Optional[Callable[[str], None]] = None,
    env: Optional[Dict[str, str]] = None,
) -> ChildResult:
    """Spawn the child as an explicit process, stream stdout+stderr to the
    transcript, emit heartbeats to cron.log, and enforce the hard timeout."""
    log = log or (lambda _m: None)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)

    popen_kwargs: Dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "env": env,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    start = time.monotonic()
    stop_heartbeat = threading.Event()

    with open(transcript_path, "w", encoding="utf-8", errors="replace") as tfh:
        tfh.write(f"# transcript for child: {' '.join(str(a) for a in child_argv)}\n")
        tfh.flush()
        proc = subprocess.Popen(  # noqa: S603 — argv is caller-controlled, not shell
            list(child_argv), stdout=tfh, stderr=subprocess.STDOUT, **popen_kwargs
        )
        log(f"spawned child PID={proc.pid} (timeout {timeout_sec}s)")

        def _heartbeat() -> None:
            while not stop_heartbeat.wait(heartbeat_sec):
                elapsed = int(time.monotonic() - start)
                append_line(
                    cron_log,
                    f"---- {_utc_ts()} {MARK_HEARTBEAT} (elapsed {elapsed}s, "
                    f"child PID {proc.pid} alive) ----",
                )

        hb = threading.Thread(target=_heartbeat, name="nightly-heartbeat", daemon=True)
        hb.start()

        timed_out = False
        try:
            proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            log(f"child exceeded {timeout_sec}s — graceful terminate")
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=grace_sec)
            except subprocess.TimeoutExpired:
                log("child did not exit on terminate — forced tree kill")
                _kill_process_tree(proc)
                try:
                    proc.wait(timeout=grace_sec)
                except subprocess.TimeoutExpired:
                    log("child STILL alive after kill — abandoning wait")
        finally:
            stop_heartbeat.set()
            hb.join(timeout=2)

    exit_code = proc.returncode if proc.returncode is not None else -1
    duration = time.monotonic() - start
    log(f"child PID={proc.pid} exited code={exit_code} timed_out={timed_out} in {duration:.1f}s")
    return ChildResult(exit_code=exit_code, timed_out=timed_out, duration_sec=duration, pid=proc.pid)


# ---------------------------------------------------------------------------
# completion contract
# ---------------------------------------------------------------------------
def structural_report_check(
    report_path: Path, run_sha: Optional[str]
) -> Tuple[bool, List[str]]:
    """Return (ok, reasons). A report is structurally valid if it exists, is
    nonzero, starts with the expected audit header, and references the run SHA
    (short form) — evidence the audit grounded on the fresh code, not a stale
    tree."""
    reasons: List[str] = []
    if not report_path.exists():
        return False, ["report file does not exist"]
    text = report_path.read_text(encoding="utf-8", errors="replace")
    if len(text.strip()) == 0:
        reasons.append("report is empty")
    if not text.lstrip().startswith(REPORT_HEADER_PREFIX):
        reasons.append(f"report does not start with '{REPORT_HEADER_PREFIX}'")
    if run_sha:
        short = run_sha[:8]
        if short[:7] not in text and short not in text:
            reasons.append(f"report does not reference run SHA {short[:7]}")
    return (len(reasons) == 0), reasons


@dataclasses.dataclass
class ContractResult:
    met: bool
    manifest_exists: bool
    report_ok: bool
    report_reasons: List[str]
    end_marker_written: bool
    child_exit_zero: bool
    child_exit_code: int
    timed_out: bool

    def summary(self) -> str:
        return (
            f"met={self.met} manifest={self.manifest_exists} report_ok={self.report_ok} "
            f"end_marker={self.end_marker_written} exit0={self.child_exit_zero} "
            f"(code={self.child_exit_code}, timed_out={self.timed_out})"
        )


def evaluate_completion_contract(
    manifest_path: Path,
    report_path: Path,
    run_sha: Optional[str],
    child: ChildResult,
    end_marker_written: bool,
) -> ContractResult:
    manifest_exists = manifest_path.exists()
    report_ok, reasons = structural_report_check(report_path, run_sha)
    child_exit_zero = child.exit_code == 0 and not child.timed_out
    met = manifest_exists and report_ok and end_marker_written and child_exit_zero
    return ContractResult(
        met=met,
        manifest_exists=manifest_exists,
        report_ok=report_ok,
        report_reasons=reasons,
        end_marker_written=end_marker_written,
        child_exit_zero=child_exit_zero,
        child_exit_code=child.exit_code,
        timed_out=child.timed_out,
    )


def write_failure_artifact(
    path: Path,
    run_date: str,
    contract: ContractResult,
    workspace: WorkspaceInfo,
    transcript_path: Path,
    now: Optional[datetime.datetime] = None,
) -> None:
    lines = [
        f"# RUNNER ALERT — nightly-audit incomplete — {run_date}",
        "",
        f"Written by audit/runner/nightly_runner.py at {_utc_ts(now)} because the",
        "completion contract was NOT met. The success ping was WITHHELD, so the",
        "receiving dead-man should DOWN-page. Investigate before trusting tonight's",
        "audit — it may be missing or partial.",
        "",
        "## Contract",
        f"- {contract.summary()}",
        f"- manifest_exists: {contract.manifest_exists}",
        f"- report_ok: {contract.report_ok}  reasons: {contract.report_reasons}",
        f"- end_marker_written: {contract.end_marker_written}",
        f"- child_exit_zero: {contract.child_exit_zero} (code={contract.child_exit_code}, timed_out={contract.timed_out})",
        "",
        "## Workspace",
        f"- audit worktree: {workspace.path}",
        f"- target ref: {workspace.target_ref}",
        f"- SHA: {workspace.sha} (stale={workspace.stale})",
        f"- workspace error: {workspace.error}",
        "",
        "## Evidence",
        f"- per-run transcript: {transcript_path}",
        "- cron.log: search for tonight's start/heartbeat markers",
        "",
        "## Likely causes (in order)",
        "1. Host slept mid-run despite the wake lock (check `powercfg /requests`",
        "   history / Event Viewer sleep events) — the primary historical cause.",
        "2. Child (claude) crashed or was killed (non-zero/negative exit).",
        "3. Audit produced no report or a malformed one (see report_reasons).",
        "4. Timeout tripped (timed_out=true) — audit hung.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------
PingRun = Callable[[str], int]


def _default_ping(url: str) -> int:
    return subprocess.run(
        ["curl", "-fsS", "-m", "10", url], capture_output=True
    ).returncode


# ---------------------------------------------------------------------------
# runner config + orchestrator
# ---------------------------------------------------------------------------
@dataclasses.dataclass
class RunnerConfig:
    operator_repo: Path
    audit_worktree: Path
    report_date: str
    child_argv: Sequence[str]
    child_cwd: Path
    cron_log: Path
    transcript_dir: Path
    manifest_dir: Path
    snapshot_dir: Path
    lock_path: Path
    reports_subpath: str = "audit/reports"
    settings_subpath: str = "audit/nightly-settings.json"
    remote: str = "origin"
    branch: str = "main"
    timeout_sec: int = DEFAULT_TIMEOUT_SEC
    heartbeat_sec: int = DEFAULT_HEARTBEAT_SEC
    grace_sec: int = DEFAULT_GRACE_SEC
    ping_url: Optional[str] = None
    selftest: bool = False
    # injectable seams (tests / self-test)
    git_run: GitRun = _default_git_run
    ping_run: PingRun = _default_ping
    snapshot_writer: Optional[Callable[[Path], Dict[str, Any]]] = None
    wake_lock_factory: Optional[Callable[[Callable[[str], None]], Any]] = None
    child_env: Optional[Dict[str, str]] = None


class NightlyRunner:
    def __init__(self, config: RunnerConfig) -> None:
        self.cfg = config
        self.pid = os.getpid()
        self._end_marker_written = False

    # -- small helpers ----------------------------------------------------
    def _log(self, msg: str) -> None:
        append_line(self.cfg.cron_log, f"==== {_utc_ts()} runner: {msg} ====")

    def _worktree_audit_dir(self) -> Path:
        return self.cfg.audit_worktree / "audit"

    def _worktree_report(self) -> Path:
        return self.cfg.audit_worktree / self.cfg.reports_subpath / f"{self.cfg.report_date}.md"

    def _operator_report(self) -> Path:
        return self.cfg.operator_repo / self.cfg.reports_subpath / f"{self.cfg.report_date}.md"

    def _manifest_worktree(self) -> Path:
        return self._worktree_audit_dir() / "preflight-manifest.json"

    def _snapshot_worktree(self) -> Path:
        return self._worktree_audit_dir() / "broker-snapshot.json"

    def _default_snapshot_writer(self, path: Path) -> Dict[str, Any]:
        # Lazy sibling import so this module loads even where broker_snapshot's
        # optional deps are absent; failure becomes an error-state snapshot.
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            import broker_snapshot  # noqa: PLC0415

            return broker_snapshot.write_snapshot(str(path))
        except Exception as exc:  # noqa: BLE001
            snap = {
                "generated_at": _utc_ts(),
                "available": False,
                "error": f"snapshot generation failed: {type(exc).__name__}: {exc}",
                "trust": "SECONDARY to the Alpaca MCP.",
            }
            write_json_atomic(path, snap)
            return snap

    def _write_end_marker(self, exit_code: int) -> None:
        append_line(
            self.cfg.cron_log,
            f"==== {_utc_ts()} {MARK_END} (exit {exit_code}) ====",
        )
        self._end_marker_written = True

    # -- phases -----------------------------------------------------------
    def _preflight(self) -> Tuple[WorkspaceInfo, Dict[str, Any]]:
        # 1. Fresh-code worktree
        prior = find_prior_report_date(
            self.cfg.operator_repo / self.cfg.reports_subpath, self.cfg.report_date
        )
        workspace = refresh_audit_worktree(
            self.cfg.operator_repo,
            self.cfg.audit_worktree,
            self.cfg.remote,
            self.cfg.branch,
            self.cfg.git_run,
            prior_report_date=prior,
            log=self._log,
        )

        # 2. Broker snapshot (headless MCP-absent fallback) into the worktree.
        writer = self.cfg.snapshot_writer or self._default_snapshot_writer
        try:
            snap = writer(self._snapshot_worktree())
        except Exception as exc:  # noqa: BLE001
            snap = {"available": False, "error": f"{type(exc).__name__}: {exc}"}
        # durable copy
        try:
            if self._snapshot_worktree().exists():
                copy_atomic(
                    self._snapshot_worktree(),
                    self.cfg.snapshot_dir / f"{self.cfg.report_date}.json",
                )
        except Exception as exc:  # noqa: BLE001
            self._log(f"snapshot durable-copy failed: {exc}")
        self._log(
            f"broker snapshot: available={snap.get('available')} error={snap.get('error')}"
        )

        # 3. Capability / preflight manifest into the worktree (+ durable copy).
        now = utcnow()
        manifest = {
            "generated_at": _utc_ts(now),
            "runner_version": RUNNER_VERSION,
            "run_date": self.cfg.report_date,
            "selftest": self.cfg.selftest,
            "workspace": workspace.to_dict(),
            "broker_snapshot": {
                "present": self._snapshot_worktree().exists(),
                "path": self.cfg.settings_subpath.rsplit("/", 1)[0] + "/broker-snapshot.json",
                "available": bool(snap.get("available")),
                "error": snap.get("error"),
                "source": snap.get("source"),
            },
            "mcp": {
                "expected_headless_broker": "absent",
                "note": (
                    "The Alpaca MCP historically does NOT surface in the headless "
                    "claude -p session. Broker truth for this run is the read-only "
                    "REST snapshot at audit/broker-snapshot.json (SECONDARY to MCP)."
                ),
            },
            "clock_grounding": {
                "runner_utc": _utc_ts(now),
                "runner_local": local_date_str(datetime.datetime.now()),
                "broker_clock": snap.get("clock"),
                "note": (
                    "Ground DB now() as PRIMARY per STEP 0. The runner UTC above and "
                    "the broker clock (if present) are corroborating references only."
                ),
            },
            "child": {
                # argv is redacted to the program + flags; it carries no secrets,
                # but we never echo env either way.
                "argv": [str(a) for a in self.cfg.child_argv],
                "cwd": str(self.cfg.child_cwd),
                "timeout_sec": self.cfg.timeout_sec,
            },
            "contract": {
                "required": [
                    "preflight manifest exists",
                    "report exists + nonzero + '# AUDIT' header + references run SHA",
                    "unconditional end marker written",
                    "child exit code 0 (not timed out)",
                    "success ping sent or explicitly unavailable",
                ]
            },
        }
        write_json_atomic(self._manifest_worktree(), manifest)
        try:
            copy_atomic(
                self._manifest_worktree(),
                self.cfg.manifest_dir / f"{self.cfg.report_date}.json",
            )
        except Exception as exc:  # noqa: BLE001
            self._log(f"manifest durable-copy failed: {exc}")
        self._log(
            f"preflight manifest written; workspace SHA={workspace.short_sha} stale={workspace.stale}"
        )
        return workspace, manifest

    def _copy_report_back(self) -> None:
        src = self._worktree_report()
        if src.exists():
            try:
                copy_atomic(src, self._operator_report())
                self._log(f"report copied back to operator checkout: {self._operator_report()}")
            except Exception as exc:  # noqa: BLE001
                self._log(f"report copy-back failed: {exc}")
        # copy any ALERT-<date>.md the audit produced
        alert = self.cfg.audit_worktree / "audit" / f"ALERT-{self.cfg.report_date}.md"
        if alert.exists():
            try:
                copy_atomic(alert, self.cfg.operator_repo / "audit" / f"ALERT-{self.cfg.report_date}.md")
                self._log("audit ALERT file copied back to operator checkout")
            except Exception as exc:  # noqa: BLE001
                self._log(f"ALERT copy-back failed: {exc}")

    def _do_ping(self, contract_met: bool) -> None:
        if not contract_met:
            self._log("completion contract NOT met — success ping WITHHELD")
            return
        if not self.cfg.ping_url:
            self._log("contract met; NIGHTLY_AUDIT_PING_URL unset — ping explicitly unavailable (no-op)")
            return
        try:
            rc = self.cfg.ping_run(self.cfg.ping_url)
            self._log(f"contract met; success ping sent (curl exit {rc})")
        except Exception as exc:  # noqa: BLE001
            self._log(f"contract met; ping attempt errored: {exc}")

    # -- orchestrator -----------------------------------------------------
    def run(self) -> int:
        lock = SingleInstanceLock(self.cfg.lock_path, pid=self.pid)
        if not lock.acquire():
            append_line(
                self.cfg.cron_log,
                f"==== {_utc_ts()} {MARK_START} ABORTED — another nightly run holds "
                f"the lock ({self.cfg.lock_path}) ====",
            )
            return 3  # duplicate run

        exit_code = 1
        workspace = WorkspaceInfo(path=str(self.cfg.audit_worktree), target_ref="?")
        child = ChildResult(exit_code=-1, timed_out=False, duration_sec=0.0)
        try:
            append_line(self.cfg.cron_log, "=" * 68)
            append_line(self.cfg.cron_log, f"==== {_utc_ts()} {MARK_START} (runner v{RUNNER_VERSION}, PID {self.pid}) ====")

            wake_factory = self.cfg.wake_lock_factory or (lambda log: WakeLock(log))
            with wake_factory(self._log):
                workspace, _manifest = self._preflight()

                child_env = self.cfg.child_env if self.cfg.child_env is not None else os.environ.copy()
                child = spawn_and_monitor(
                    self.cfg.child_argv,
                    self.cfg.child_cwd,
                    self.cfg.transcript_dir / f"{self.cfg.report_date}-{self.pid}.log",
                    self.cfg.cron_log,
                    self.cfg.timeout_sec,
                    self.cfg.heartbeat_sec,
                    self.cfg.grace_sec,
                    log=self._log,
                    env=child_env,
                )
                self._copy_report_back()
            exit_code = child.exit_code
        except Exception as exc:  # noqa: BLE001
            self._log(f"UNEXPECTED runner error: {type(exc).__name__}: {exc}")
            exit_code = 1
        finally:
            # UNCONDITIONAL end marker with the exact child exit code.
            self._write_end_marker(child.exit_code)

            # Completion contract (evaluated after the end marker exists).
            contract = evaluate_completion_contract(
                self._manifest_worktree(),
                self._operator_report(),
                workspace.sha,
                child,
                self._end_marker_written,
            )
            self._log(f"completion contract: {contract.summary()}")
            if not contract.met:
                try:
                    write_failure_artifact(
                        self.cfg.operator_repo / "audit" / f"ALERT-{self.cfg.report_date}-runner.md",
                        self.cfg.report_date,
                        contract,
                        workspace,
                        self.cfg.transcript_dir / f"{self.cfg.report_date}-{self.pid}.log",
                    )
                    self._log("failure artifact written: audit/ALERT-<date>-runner.md")
                except Exception as exc:  # noqa: BLE001
                    self._log(f"failure-artifact write failed: {exc}")
            self._do_ping(contract.met)
            lock.release()

        return exit_code


# ---------------------------------------------------------------------------
# CLI / production wiring
# ---------------------------------------------------------------------------
def _local_appdata_worktree() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "otc-audit-worktree"
    return Path(os.path.expanduser("~/.cache/otc-audit-worktree"))


def build_production_config(
    operator_repo: Path, selftest: bool = False
) -> RunnerConfig:
    audit_dir = operator_repo / "audit"
    worktree = Path(os.environ.get("AUDIT_WORKTREE_DIR", "")) or _local_appdata_worktree()
    report_date = local_date_str()

    if selftest:
        # Echo-style child through the REAL spawn path — no real claude, no audit.
        report_date = f"selftest-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"
        wt_report = worktree / "audit" / "reports" / f"{report_date}.md"
        # A tiny python child that emulates claude: prints to the transcript and
        # writes a structurally-valid mini report referencing the run SHA. Shell
        # -free (python -c), exercising spawn/heartbeat/transcript/timeout/kill,
        # end marker, report copy-back, and the completion contract end-to-end.
        child_argv = [
            sys.executable,
            "-c",
            _SELFTEST_CHILD_SRC,
            str(wt_report),
        ]
        child_cwd = worktree
        ping_url = None  # never ping on a self-test
    else:
        prompt = "Execute audit/v5-prompt.md in NIGHTLY mode (FULL on Sundays)."
        settings = worktree / "audit" / "nightly-settings.json"
        child_argv = [
            "claude", "-p", prompt,
            "--settings", str(settings),
            "--max-turns", "200",
        ]
        child_cwd = worktree
        ping_url = os.environ.get("NIGHTLY_AUDIT_PING_URL") or None

    return RunnerConfig(
        operator_repo=operator_repo,
        audit_worktree=worktree,
        report_date=report_date,
        child_argv=child_argv,
        child_cwd=child_cwd,
        cron_log=audit_dir / "cron.log",
        transcript_dir=audit_dir / "transcripts",
        manifest_dir=audit_dir / "manifests",
        snapshot_dir=audit_dir / "snapshots",
        lock_path=audit_dir / ".nightly-runner.lock",
        ping_url=ping_url,
        selftest=selftest,
    )


# Source for the self-test echo child. Writes a minimal, structurally-valid
# report (header + the run SHA) so the completion contract passes end-to-end
# WITHOUT running a real audit or a real claude session.
_SELFTEST_CHILD_SRC = r"""
import os, sys, subprocess, datetime
report = sys.argv[1]
wt = os.path.dirname(os.path.dirname(os.path.dirname(report)))  # <worktree>
try:
    sha = subprocess.run(['git','-C',wt,'rev-parse','HEAD'],
                         capture_output=True, text=True).stdout.strip()[:8]
except Exception:
    sha = 'unknownsha'
os.makedirs(os.path.dirname(report), exist_ok=True)
ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
with open(report, 'w', encoding='utf-8') as f:
    f.write('# AUDIT runner SELFTEST\n\n')
    f.write('This is a self-test report written by the echo child through the\n')
    f.write('real spawn path. It is NOT a real audit.\n\n')
    f.write('- run SHA: ' + sha + '\n')
    f.write('- generated: ' + ts + '\n')
print('[selftest] echo child wrote ' + report + ' (sha ' + sha + ')')
"""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Nightly audit reliability runner")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run the real spawn path with an echo child (no real audit / claude). "
        "For post-merge verification by the operator.",
    )
    parser.add_argument(
        "--repo",
        default=None,
        help="Operator repo root (default: inferred from this file's location).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.repo:
        operator_repo = Path(args.repo).resolve()
    else:
        operator_repo = Path(__file__).resolve().parents[2]

    config = build_production_config(operator_repo, selftest=args.selftest)
    return NightlyRunner(config).run()


if __name__ == "__main__":
    raise SystemExit(main())
