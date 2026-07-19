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

# File the runner writes into a worktree IT created, to prove the worktree is a
# disposable runner-owned tree and never the operator checkout. Destructive git
# (checkout --force / reset --hard / worktree remove) is only ever allowed
# against a path that carries this marker (on reuse) or that the runner is about
# to create fresh (F-RUNNER-WORKTREE-DEADFALLBACK item 3/5).
AUDIT_WORKTREE_MARKER = ".otc-audit-worktree-marker"

# Typed append-result statuses — cron/marker writes NEVER swallow their failure
# anymore (the old `except OSError: pass` let a lost marker read as "written",
# after which the dead-man UP-ping fired over an empty evidence sink).
APPEND_OK = "ok"
APPEND_SHARING_VIOLATION = "sharing_violation"  # WinError 32 — the shim holds cron.log via >>
APPEND_LOCKED = "locked"                        # WinError 33 / read-only / other permission
APPEND_MISSING_DIR = "missing_dir"
APPEND_SHORT_WRITE = "short_write"
APPEND_ERROR = "error"

# Completion-contract artifact classes (named so a partial/failed run says which
# durable artifact was missing, and the /fail ping can carry the class list).
ARTIFACT_START_MARKER = "start_marker"
ARTIFACT_TRANSCRIPT = "transcript"
ARTIFACT_REPORT = "report"
ARTIFACT_MANIFEST = "manifest"
ARTIFACT_END_MARKER = "end_marker"
ARTIFACT_CHILD_EXIT = "child_exit"


class WorktreeSafetyError(RuntimeError):
    """The audit worktree cannot be used safely — it equals, sits inside, or was
    resolved to the operator checkout / process cwd, or an existing worktree
    lacks the runner-owned ownership marker. Raised BEFORE any git command runs;
    it makes the run fail (typed, loud) rather than mutate the operator checkout.
    """


# ---------------------------------------------------------------------------
# time / logging helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _utc_ts(now: Optional[datetime.datetime] = None) -> str:
    return (now or utcnow()).strftime("%Y-%m-%d %H:%M:%SZ")


def local_date_str(now: Optional[datetime.datetime] = None) -> str:
    return (now or datetime.datetime.now()).strftime("%Y-%m-%d")


@dataclasses.dataclass
class AppendResult:
    """Typed outcome of a single-line append. ``ok`` is the only success."""

    status: str
    path: str
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == APPEND_OK


def classify_append_error(exc: OSError) -> str:
    """Map an OSError from a marker/cron append to a typed status.

    Windows surfaces a cmd ``>>``-held file as ERROR_SHARING_VIOLATION (32) or
    ERROR_LOCK_VIOLATION (33) when it populates ``winerror``; some CPython
    builds instead map the sharing violation to ``EACCES`` with ``winerror``
    unset — that still classifies as a locked/denied sink (never ``ok``,
    never swallowed).
    """
    win = getattr(exc, "winerror", None)
    if win == 32:
        return APPEND_SHARING_VIOLATION
    if win == 33:
        return APPEND_LOCKED
    if isinstance(exc, (FileNotFoundError, NotADirectoryError, IsADirectoryError)):
        return APPEND_MISSING_DIR
    if isinstance(exc, PermissionError):
        return APPEND_LOCKED
    return APPEND_ERROR


def append_line(path: Path, line: str) -> AppendResult:
    """Append a single line to a log file, returning a TYPED result.

    NEVER swallows silently. A Windows sharing violation (WinError 32 — the shim
    holds cron.log open via its own ``>>`` redirect), a lock violation (33), a
    missing parent directory, a short write, or any other OSError is classified
    and returned so the caller records it and does NOT treat a lost marker as
    written. This is the F-RUNNER-WORKTREE-DEADFALLBACK item-3 fix: the old
    ``except OSError: pass`` dropped every marker, after which
    ``_end_marker_written`` was set unconditionally and the dead-man UP-ping
    fired over an empty evidence sink.
    """
    encoded = (line.rstrip("\n") + "\n").encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # noqa: BLE001
        return AppendResult(APPEND_MISSING_DIR, str(path), f"{type(exc).__name__}: {exc}")
    try:
        with open(path, "ab") as fh:
            written = fh.write(encoded)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass  # durability best-effort; the write itself succeeded
        if written != len(encoded):
            return AppendResult(
                APPEND_SHORT_WRITE, str(path), f"wrote {written}/{len(encoded)} bytes"
            )
        return AppendResult(APPEND_OK, str(path))
    except OSError as exc:
        return AppendResult(classify_append_error(exc), str(path), f"{type(exc).__name__}: {exc}")


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


def _is_relative_to(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` or lives under it (Py3.8-safe)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _dir_nonempty(path: Path) -> bool:
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def verify_worktree_geometry(operator_repo: Path, worktree: Path) -> Path:
    """Resolve and geometry-check the audit worktree; raise WorktreeSafetyError.

    Refuses (typed, loud) when the worktree — after ``Path.resolve()`` — equals
    the operator checkout, lives inside it, or equals the process cwd (the
    ``Path(".")`` accident that mutated the operator checkout on 07-19). Returns
    the RESOLVED worktree path so every downstream git command uses a
    canonical, non-operator path. Never mutates anything.
    """
    op = Path(operator_repo).resolve()
    wt = Path(worktree).resolve()
    cwd = Path.cwd().resolve()
    if wt == op:
        raise WorktreeSafetyError(
            f"audit worktree resolves to the operator checkout ({wt}) — refusing"
        )
    if _is_relative_to(wt, op):
        raise WorktreeSafetyError(
            f"audit worktree ({wt}) is inside the operator checkout ({op}) — refusing"
        )
    if wt == cwd:
        raise WorktreeSafetyError(
            f"audit worktree resolves to the process cwd ({wt}) — refusing "
            "(the Path('.') dead-fallback accident)"
        )
    return wt


def run_destructive_git(
    git_run: GitRun,
    worktree_target: Path,
    operator_repo: Path,
    args: List[str],
) -> str:
    """The ONLY route for checkout --force / reset --hard / worktree remove.

    Re-verifies (geometry) that ``worktree_target`` is NOT the operator checkout,
    not inside it, and not the cwd IMMEDIATELY before executing — a structural
    guarantee (item 12) that no destructive git can ever land on the operator
    checkout regardless of caller mistakes.
    """
    verify_worktree_geometry(operator_repo, worktree_target)
    return git_run(args)


def _ensure_worktree_marker(worktree: Path) -> None:
    """Stamp the runner-owned ownership marker into a worktree the runner owns."""
    try:
        worktree.mkdir(parents=True, exist_ok=True)
        (worktree / AUDIT_WORKTREE_MARKER).write_text(
            "This worktree is owned and recycled by audit/runner/nightly_runner.py.\n"
            "Its presence authorizes the runner's destructive git refresh. Do not\n"
            "put anything you care about here — it is reset --hard to origin/main.\n",
            encoding="utf-8",
        )
    except OSError:
        pass


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
    """Fetch origin/<branch>, resolve it to an IMMUTABLE SHA, and force a
    DEDICATED, DISPOSABLE worktree to that SHA — never the operator checkout.

    Ordering and invariants (F-RUNNER-WORKTREE-DEADFALLBACK):
      * Both paths are ``Path.resolve()``-canonicalized (item 2) and the
        worktree is geometry-verified (item 3) BEFORE any git command runs. A
        worktree that equals / is inside the operator checkout, or resolves to
        the cwd, RAISES WorktreeSafetyError — the run fails, it never mutates
        the operator checkout.
      * The operator checkout is READ-ONLY: only ``git -C <op> fetch`` and
        ``rev-parse`` (which never touch its working tree) and ``worktree add``
        (which writes only into the dedicated path) run against it (item 6).
      * The worktree is pinned to the resolved SHA (item 4), detached.
      * checkout --force / reset --hard run ONLY via ``run_destructive_git``
        against the verified disposable path (items 5, 12), and ONLY when the
        worktree already carries the runner-owned ownership marker (item 3).
      * A fresh worktree gets the ownership marker stamped after creation.
    If the fetch or refresh fails we mark ``stale=True`` LOUDLY; a safety
    violation is NOT stale — it propagates so the run fails.
    """
    log = log or (lambda _m: None)
    target = f"{remote}/{branch}"

    # (item 2 + 3) resolve + geometry check BEFORE any git command. Raises
    # WorktreeSafetyError — the caller lets it propagate to a failed run.
    op_resolved = Path(operator_repo).resolve()
    wt = verify_worktree_geometry(op_resolved, worktree)
    info = WorkspaceInfo(path=str(wt), target_ref=target, prior_report_date=prior_report_date)

    try:
        git_run(["-C", str(op_resolved), "fetch", "--prune", remote, branch])
        log(f"fetched {target}")
    except Exception as exc:  # noqa: BLE001
        info.stale = True
        info.error = f"fetch failed: {exc}"
        log(f"WARNING fetch failed — worktree may be stale: {exc}")

    # (item 4) pin to an immutable SHA, not the moving ref.
    target_sha: Optional[str] = None
    try:
        target_sha = git_run(["-C", str(op_resolved), "rev-parse", target]).strip() or None
    except Exception as exc:  # noqa: BLE001
        info.stale = True
        info.error = (info.error + "; " if info.error else "") + f"resolve {target} failed: {exc}"
        log(f"WARNING could not resolve {target} to a SHA: {exc}")

    if target_sha:
        try:
            is_worktree = (wt / ".git").exists()
            has_marker = (wt / AUDIT_WORKTREE_MARKER).exists()
            if is_worktree:
                # REUSE — must be a runner-owned disposable worktree (item 3).
                if not has_marker:
                    raise WorktreeSafetyError(
                        f"existing worktree {wt} lacks the runner ownership marker "
                        f"{AUDIT_WORKTREE_MARKER} — refusing to reset --hard it"
                    )
                run_destructive_git(
                    git_run, wt, op_resolved,
                    ["-C", str(wt), "checkout", "--force", "--detach", target_sha],
                )
                run_destructive_git(
                    git_run, wt, op_resolved,
                    ["-C", str(wt), "reset", "--hard", target_sha],
                )
                log(f"refreshed audit worktree at {wt} -> {target} ({target_sha[:8]})")
            else:
                # CREATE — refuse to clobber a non-empty, unowned directory.
                if _dir_nonempty(wt) and not has_marker:
                    raise WorktreeSafetyError(
                        f"refusing to create audit worktree over non-empty unowned "
                        f"directory {wt} (no {AUDIT_WORKTREE_MARKER})"
                    )
                run_destructive_git(
                    git_run, wt, op_resolved,
                    ["-C", str(op_resolved), "worktree", "add", "--force",
                     "--detach", str(wt), target_sha],
                )
                _ensure_worktree_marker(wt)
                log(f"created audit worktree at {wt} -> {target} ({target_sha[:8]})")
        except WorktreeSafetyError:
            raise  # loud, typed — makes the run fail; never downgraded to stale
        except Exception as exc:  # noqa: BLE001
            info.stale = True
            info.error = (info.error + "; " if info.error else "") + f"worktree refresh failed: {exc}"
            log(f"WARNING worktree refresh failed — may be stale: {exc}")

    try:
        info.sha = git_run(["-C", str(wt), "rev-parse", "HEAD"]).strip() or None
        if info.sha:
            info.short_sha = info.sha[:8]
    except Exception as exc:  # noqa: BLE001
        info.error = (info.error + "; " if info.error else "") + f"rev-parse failed: {exc}"
        info.stale = True

    # Commit subjects since the prior report (best-effort — never fail the run).
    try:
        log_args = ["-C", str(wt), "log", "--no-merges", "--pretty=format:%h %s"]
        if prior_report_date:
            log_args.append(f"--since={prior_report_date} 00:00")
        else:
            log_args.append("-30")
        log_args.append(target_sha or target)
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
    timeout_sec: int,
    heartbeat_sec: int,
    grace_sec: int,
    log: Optional[Callable[[str], None]] = None,
    env: Optional[Dict[str, str]] = None,
) -> ChildResult:
    """Spawn the child as an explicit process, stream stdout+stderr to the
    transcript, emit heartbeats through ``log`` (the runner-owned marker sink,
    NOT a second open on cron.log — that double-open was the sharing-violation
    source), and enforce the hard timeout."""
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
                log(
                    f"{MARK_HEARTBEAT} (elapsed {elapsed}s, child PID {proc.pid} alive)"
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
    else:
        # A missing run SHA means the workspace rev-parse failed — a broken
        # workspace must NOT weaken report_ok (it must fail closed), so the
        # absent SHA is itself a typed reason, never a silently skipped check.
        reasons.append("run SHA unavailable (workspace rev-parse failed) — report cannot be SHA-grounded")
    return (len(reasons) == 0), reasons


@dataclasses.dataclass
class ContractResult:
    met: bool
    status: str  # "met" | "partial" | "failed"
    manifest_exists: bool
    report_ok: bool
    report_reasons: List[str]
    start_marker_present: bool
    end_marker_present: bool
    transcript_present: bool
    child_exit_zero: bool
    child_exit_code: int
    timed_out: bool
    missing_artifacts: List[str]

    def summary(self) -> str:
        return (
            f"status={self.status} met={self.met} manifest={self.manifest_exists} "
            f"report_ok={self.report_ok} start_marker={self.start_marker_present} "
            f"end_marker={self.end_marker_present} transcript={self.transcript_present} "
            f"exit0={self.child_exit_zero} (code={self.child_exit_code}, "
            f"timed_out={self.timed_out}) missing={self.missing_artifacts}"
        )


def _read_text_safe(path: Path) -> str:
    try:
        if path.exists():
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def evaluate_completion_contract(
    manifest_path: Path,
    report_path: Path,
    marker_log: Path,
    transcript_path: Path,
    run_sha: Optional[str],
    child: ChildResult,
    run_tag: str,
) -> ContractResult:
    """Evaluate the contract from DURABLE evidence RE-READ FROM DISK — never an
    in-memory boolean (item 8). The old code trusted ``_end_marker_written``,
    which was set unconditionally even when the append was silently swallowed;
    here we re-read the marker sink and confirm the start AND end markers
    actually landed. Any missing artifact class → partial/failed, and the
    dead-man UP-ping is withheld upstream.

    CRITICAL: the marker sink is an APPEND-ONLY log shared across nights. The
    presence check is SCOPED to THIS run via ``run_tag`` (a unique per-run id
    stamped into the start/end marker lines) — a prior night's start/end
    markers must NEVER satisfy tonight's contract. A bare substring check over
    the accumulated file would report every subsequent night as complete even
    when tonight's appends all failed.
    """
    marker_lines = _read_text_safe(marker_log).splitlines()
    start_present = any(MARK_START in ln and run_tag in ln for ln in marker_lines)
    end_present = any(MARK_END in ln and run_tag in ln for ln in marker_lines)

    manifest_exists = manifest_path.exists()
    report_ok, reasons = structural_report_check(report_path, run_sha)
    try:
        transcript_present = transcript_path.exists() and transcript_path.stat().st_size > 0
    except OSError:
        transcript_present = False
    child_exit_zero = child.exit_code == 0 and not child.timed_out

    missing: List[str] = []
    if not start_present:
        missing.append(ARTIFACT_START_MARKER)
    if not transcript_present:
        missing.append(ARTIFACT_TRANSCRIPT)
    if not report_ok:
        missing.append(ARTIFACT_REPORT)
    if not manifest_exists:
        missing.append(ARTIFACT_MANIFEST)
    if not end_present:
        missing.append(ARTIFACT_END_MARKER)
    if not child_exit_zero:
        missing.append(ARTIFACT_CHILD_EXIT)

    met = not missing
    if met:
        status = "met"
    elif child_exit_zero and start_present:
        # child ran clean and we have a start marker, but some artifact did not
        # land — the audit ran but did not fully complete.
        status = "partial"
    else:
        status = "failed"

    return ContractResult(
        met=met,
        status=status,
        manifest_exists=manifest_exists,
        report_ok=report_ok,
        report_reasons=reasons,
        start_marker_present=start_present,
        end_marker_present=end_present,
        transcript_present=transcript_present,
        child_exit_zero=child_exit_zero,
        child_exit_code=child.exit_code,
        timed_out=child.timed_out,
        missing_artifacts=missing,
    )


def write_failure_artifact(
    path: Path,
    run_date: str,
    contract: ContractResult,
    workspace: WorkspaceInfo,
    transcript_path: Path,
    marker_log: Optional[Path] = None,
    marker_failures: Optional[List[Dict[str, Any]]] = None,
    fatal_error: Optional[str] = None,
    now: Optional[datetime.datetime] = None,
) -> None:
    lines = [
        f"# RUNNER ALERT — nightly-audit incomplete ({contract.status}) — {run_date}",
        "",
        f"Written by audit/runner/nightly_runner.py at {_utc_ts(now)} because the",
        "completion contract was NOT met. The success ping was WITHHELD, so the",
        "receiving dead-man should DOWN-page. Investigate before trusting tonight's",
        "audit — it may be missing or partial.",
        "",
        "## Contract",
        f"- {contract.summary()}",
        f"- MISSING ARTIFACT CLASSES: {contract.missing_artifacts}",
        f"- manifest_exists: {contract.manifest_exists}",
        f"- report_ok: {contract.report_ok}  reasons: {contract.report_reasons}",
        f"- start_marker_present: {contract.start_marker_present}",
        f"- end_marker_present: {contract.end_marker_present}",
        f"- transcript_present: {contract.transcript_present}",
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
        f"- marker sink (start/heartbeat/end): {marker_log}",
        "- cron.log: the shim's `>>` capture of the runner's stdout narration",
    ]
    if fatal_error:
        lines += ["", "## Fatal error (run aborted before completion)", f"- {fatal_error}"]
    if marker_failures:
        lines += ["", "## Marker-sink write failures (NOT swallowed)"]
        lines += [f"- {mf.get('status')}: {mf.get('error')} :: {mf.get('line')}" for mf in marker_failures]
    lines += [
        "",
        "## Likely causes (in order)",
        "1. Host slept mid-run despite the wake lock (check `powercfg /requests`",
        "   history / Event Viewer sleep events) — the primary historical cause.",
        "2. Child (claude) crashed or was killed (non-zero/negative exit).",
        "3. Audit produced no report or a malformed one (see report_reasons).",
        "4. Timeout tripped (timed_out=true) — audit hung.",
        "5. Worktree-safety refusal or marker-sink lock (see the sections above).",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------
# (url, message?) -> curl exit code. The UP ping GETs the base URL; a
# partial/failure DOWN ping GETs "<base>/fail" and POSTs a no-secret message
# naming the missing artifact classes (healthchecks.io logs the body).
PingRun = Callable[..., int]


def _default_ping(url: str, message: Optional[str] = None) -> int:
    args = ["curl", "-fsS", "-m", "10"]
    if message:
        args += ["--data-raw", message]
    args.append(url)
    return subprocess.run(args, capture_output=True).returncode


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
    # Runner-owned DURABLE marker sink (start / heartbeat / end). Distinct from
    # cron.log so the runner never opens the file the shim holds via `>>`
    # (that double-open was the sharing violation). The completion contract
    # re-reads THIS file from disk. cron.log still receives the runner's stdout
    # narration via the shim's `>>` capture — the runner never opens it directly.
    marker_log: Optional[Path] = None
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
        self._marker_failures: List[Dict[str, Any]] = []
        self._fatal_error: Optional[str] = None
        # Serializes marker-sink appends: the heartbeat thread and the main
        # thread both emit through _emit_raw; independent `ab` handles race and
        # interleave (Windows has no atomic-append guarantee across handles).
        self._emit_lock = threading.Lock()
        # Unique per-run id stamped into the start/end marker lines so the
        # completion contract scopes its start/end check to THIS run's markers
        # in the append-only, night-shared sink (never a prior night's markers).
        self.run_id = f"{self.cfg.report_date}-{self.pid}-{os.urandom(4).hex()}"

    def _run_tag(self) -> str:
        return f"[run={self.run_id}]"

    # -- marker sink ------------------------------------------------------
    def _marker_log(self) -> Path:
        # Default to a runner-owned sidecar in the operator audit dir if the
        # config didn't set one (the shim never opens this file).
        return self.cfg.marker_log or (self.cfg.operator_repo / "audit" / "runner-markers.log")

    def _emit_raw(self, line: str) -> AppendResult:
        """Write one EXACT line to the durable marker sink AND mirror it to the
        runner's stdout (the shim's `>>` capture puts that in cron.log for
        humans). Serialized so concurrent emits (heartbeat + main thread) never
        interleave. A non-ok append is RECORDED, never swallowed."""
        with self._emit_lock:
            res = append_line(self._marker_log(), line)
            if not res.ok:
                self._marker_failures.append(
                    {"line": line[-120:], "status": res.status, "error": res.error}
                )
            try:
                print(line, flush=True)
            except Exception:  # noqa: BLE001 — stdout closed/redirected; sink is authoritative
                pass
            return res

    def _log(self, msg: str) -> AppendResult:
        return self._emit_raw(f"==== {_utc_ts()} runner: {msg} ====")

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
        # Reflects the TYPED append result — NOT set unconditionally (item 3).
        # The contract re-reads the sink from disk regardless, so a swallowed
        # append can no longer read as "written". The run tag scopes it to THIS
        # run in the night-shared append-only sink.
        res = self._emit_raw(f"==== {_utc_ts()} {MARK_END} (exit {exit_code}) {self._run_tag()} ====")
        self._end_marker_written = res.ok

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
                "evidence": "ALL re-read from disk (not in-memory booleans)",
                "required": [
                    "start marker present in the runner-owned marker sink",
                    "per-run transcript exists and is nonzero",
                    "report exists + nonzero + '# AUDIT' header + references run SHA",
                    "preflight manifest exists",
                    "end marker present in the runner-owned marker sink",
                    "child exit code 0 (not timed out)",
                    "UP ping sent ONLY when every artifact above validated; else /fail",
                ],
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

    def _send_fail_ping(self, reason: str) -> None:
        """DOWN ping to "<base>/fail" with a no-secret reason (items 10/11). The
        UP ping is NEVER sent from here — this is the fail path only."""
        if not self.cfg.ping_url:
            return
        try:
            fail_url = self.cfg.ping_url.rstrip("/") + "/fail"
            rc = self.cfg.ping_run(fail_url, reason[:200])
            self._log(f"DOWN (/fail) ping sent (curl exit {rc})")
        except Exception as exc:  # noqa: BLE001
            self._log(f"DOWN ping attempt errored: {exc}")

    def _do_ping(self, contract: ContractResult) -> None:
        """UP-ping ONLY when the contract is met (every artifact re-read from
        disk). On partial/failure, WITHHOLD the UP ping and — if a ping URL is
        configured — send a DOWN ping to "<base>/fail" whose no-secret body
        names the missing artifact classes (items 10 + 11)."""
        if contract.met:
            if not self.cfg.ping_url:
                self._log("contract met; NIGHTLY_AUDIT_PING_URL unset — ping explicitly unavailable (no-op)")
                return
            try:
                rc = self.cfg.ping_run(self.cfg.ping_url, None)
                self._log(f"contract met; success (UP) ping sent (curl exit {rc})")
            except Exception as exc:  # noqa: BLE001
                self._log(f"contract met; UP ping attempt errored: {exc}")
            return

        self._log(
            f"completion contract NOT met ({contract.status}) — UP ping WITHHELD; "
            f"missing artifact classes: {contract.missing_artifacts}"
        )
        self._send_fail_ping(
            "nightly-audit " + contract.status + "; missing artifact classes: "
            + ",".join(contract.missing_artifacts)
        )

    # -- orchestrator -----------------------------------------------------
    def run(self) -> int:
        lock = SingleInstanceLock(self.cfg.lock_path, pid=self.pid)
        if not lock.acquire():
            self._emit_raw(
                f"==== {_utc_ts()} {MARK_START} ABORTED — another nightly run holds "
                f"the lock ({self.cfg.lock_path}) {self._run_tag()} ===="
            )
            return 3  # duplicate run

        transcript_path = self.cfg.transcript_dir / f"{self.cfg.report_date}-{self.pid}.log"
        exit_code = 1
        workspace = WorkspaceInfo(path=str(self.cfg.audit_worktree), target_ref="?")
        child = ChildResult(exit_code=-1, timed_out=False, duration_sec=0.0)
        try:
            self._emit_raw("=" * 68)
            self._emit_raw(
                f"==== {_utc_ts()} {MARK_START} (runner v{RUNNER_VERSION}, PID {self.pid}) {self._run_tag()} ===="
            )

            wake_factory = self.cfg.wake_lock_factory or (lambda log: WakeLock(log))
            with wake_factory(self._log):
                workspace, _manifest = self._preflight()

                child_env = self.cfg.child_env if self.cfg.child_env is not None else os.environ.copy()
                child = spawn_and_monitor(
                    self.cfg.child_argv,
                    self.cfg.child_cwd,
                    transcript_path,
                    self.cfg.timeout_sec,
                    self.cfg.heartbeat_sec,
                    self.cfg.grace_sec,
                    log=self._log,
                    env=child_env,
                )
                self._copy_report_back()
            exit_code = child.exit_code
        except WorktreeSafetyError as exc:
            # Typed, loud worktree-safety refusal — the run FAILS before it can
            # touch the operator checkout (items 3, 9). Never downgraded.
            self._fatal_error = f"WorktreeSafetyError: {exc}"
            self._log(f"WORKTREE SAFETY REFUSAL — run FAILED: {exc}")
            exit_code = 1
        except Exception as exc:  # noqa: BLE001
            self._fatal_error = f"{type(exc).__name__}: {exc}"
            self._log(f"UNEXPECTED runner error: {type(exc).__name__}: {exc}")
            exit_code = 1
        finally:
            # The whole completion evaluation is guarded: a TOCTOU exception
            # (e.g. the report/marker file races away between exists() and read)
            # must NEVER skip the ping or leak the lock, and must NEVER leave the
            # run looking green. On any such error we send an explicit DOWN ping
            # and always release the lock (item 3 hardening).
            try:
                # UNCONDITIONAL end marker with the exact child exit code.
                self._write_end_marker(child.exit_code)

                # Completion contract — every artifact RE-READ FROM DISK (item 8),
                # scoped to THIS run's markers, evaluated after the end marker.
                contract = evaluate_completion_contract(
                    self._manifest_worktree(),
                    self._operator_report(),
                    self._marker_log(),
                    transcript_path,
                    workspace.sha,
                    child,
                    self._run_tag(),
                )
                self._log(f"completion contract: {contract.summary()}")
                if not contract.met:
                    try:
                        write_failure_artifact(
                            self.cfg.operator_repo / "audit" / f"ALERT-{self.cfg.report_date}-runner.md",
                            self.cfg.report_date,
                            contract,
                            workspace,
                            transcript_path,
                            marker_log=self._marker_log(),
                            marker_failures=self._marker_failures,
                            fatal_error=self._fatal_error,
                        )
                        self._log("failure artifact written: audit/ALERT-<date>-runner.md")
                    except Exception as exc:  # noqa: BLE001
                        self._log(f"failure-artifact write failed: {exc}")
                self._do_ping(contract)
            except Exception as exc:  # noqa: BLE001
                self._log(f"completion evaluation errored — forcing DOWN ping (never UP): {exc}")
                self._send_fail_ping(f"nightly-audit completion-evaluation error: {type(exc).__name__}")
            finally:
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
    operator_repo = Path(operator_repo).resolve()
    audit_dir = operator_repo / "audit"
    # ITEM 1 — a blank OR whitespace AUDIT_WORKTREE_DIR counts as UNSET. The old
    # `Path(os.environ.get(..., "")) or _local_appdata_worktree()` was DEAD:
    # Path("") is WindowsPath('.') which is TRUTHY, so the %LOCALAPPDATA%
    # fallback never ran and the worktree resolved to "." (the operator
    # checkout). Geometry resolution/verification happens later, in
    # refresh_audit_worktree (item 2), before any git command.
    _wt_env = os.environ.get("AUDIT_WORKTREE_DIR", "")
    worktree = Path(_wt_env.strip()) if _wt_env.strip() else _local_appdata_worktree()
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
        marker_log=audit_dir / "runner-markers.log",
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
