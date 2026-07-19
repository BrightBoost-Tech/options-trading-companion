"""Tests for the nightly-audit reliability runner (audit/runner/).

The runner lives outside packages/quantum, so we load it (and its broker
snapshot sibling) by file path — this keeps the tests independent of package
layout and pytest import mode, and works identically on Linux CI (the runner is
written to import cleanly there; every Windows-only call is deferred behind a
sys.platform guard).

Coverage:
  - duplicate-run lock
  - child killed mid-run  -> failure artifact + NO UP ping (DOWN /fail instead)
  - timeout -> terminate -> kill
  - stale-checkout detection (fetch failure marks workspace stale)
  - missing MCP -> broker snapshot fallback marker present
  - malformed / missing report -> failure artifact + NO UP ping
  - end marker ALWAYS written (happy path AND failure path)
  - broker snapshot: masking, error state, credential scrub
  - happy path -> contract met + UP ping sent

  F-RUNNER-WORKTREE-DEADFALLBACK (v1.6) additions — driven through the REAL
  filesystem / process boundary (mocks only for network), because a filesystem
  or path mock is exactly what would have hidden this defect:
  - AUDIT_WORKTREE_DIR absent/empty/whitespace -> %LOCALAPPDATA% fallback
    (the v1.6 named falsifier: cfg.audit_worktree == _local_appdata_worktree())
  - fallback directory absent -> created / typed failure
  - operator checkout dirty -> preserved BYTE-FOR-BYTE through a full run (real git)
  - audit worktree == operator / nested under operator / no ownership marker -> REFUSED
  - locked marker sink (held open on Windows) -> typed, NOT swallowed, NO false UP ping
  - short/unwritable append -> typed
  - command failure after start marker -> failed/partial, ping is NOT an UP ping
  - each missing durable artifact -> contract not met
  - successful disposable-worktree run end-to-end (real git repo fixture)
"""
import contextlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# module loading by file path
# ---------------------------------------------------------------------------
_RUNNER_DIR = Path(__file__).resolve().parents[3] / "audit" / "runner"


def _load(mod_name: str, filename: str):
    spec = importlib.util.spec_from_file_location(mod_name, _RUNNER_DIR / filename)
    assert spec and spec.loader, f"cannot load {filename} from {_RUNNER_DIR}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


nr = _load("otc_nightly_runner", "nightly_runner.py")
bs = _load("otc_broker_snapshot", "broker_snapshot.py")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
class FakeGit:
    """Records git calls; returns canned output; can be told to fail on a verb."""

    def __init__(self, sha="abcdef1234567890", fail_on=None):
        self.calls = []
        self.sha = sha
        self.fail_on = fail_on or set()

    def __call__(self, args):
        self.calls.append(list(args))
        # args look like ["-C", path, verb, ...]
        verb = args[2] if len(args) > 2 else (args[0] if args else "")
        if verb in self.fail_on:
            raise RuntimeError(f"simulated git {verb} failure")
        if verb == "rev-parse":
            return self.sha + "\n"
        if verb == "log":
            return "abc1234 fix: something\ndef5678 feat: another thing\n"
        return ""

    def verbs(self):
        return [c[2] if len(c) > 2 else (c[0] if c else "") for c in self.calls]


class PingRecorder:
    """Records (url, message) pairs. UP ping = (base, None); DOWN = (<base>/fail, msg)."""

    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, url, message=None):
        self.calls.append((url, message))
        return self.rc

    def up_calls(self, base):
        return [c for c in self.calls if c == (base, None)]

    def fail_calls(self):
        return [c for c in self.calls if c[0].endswith("/fail")]


def _fake_snapshot_writer(available=True, error=None):
    def _writer(path: Path):
        snap = {
            "generated_at": "2026-07-18T00:00:00Z",
            "available": available,
            "error": error,
            "source": "fake",
            "clock": {"is_open": False},
            "trust": "SECONDARY to the Alpaca MCP.",
        }
        nr.write_json_atomic(Path(path), snap)
        return snap

    return _writer


def _no_wake_lock(log):
    class _Ctx:
        def __enter__(self):
            log("wake lock: test stub")
            return self

        def __exit__(self, *a):
            return False

    return _Ctx()


_PING_URL = "http://ping.example/uuid"


def _make_config(
    tmp_path: Path,
    child_argv,
    *,
    report_date="2026-07-18",
    git=None,
    ping=None,
    ping_url=_PING_URL,
    snapshot_writer=None,
    timeout_sec=90 * 60,
    audit_worktree=None,
    marker_log=None,
):
    operator = tmp_path / "operator"
    worktree = audit_worktree or (tmp_path / "worktree")
    # Only the OPERATOR tree is pre-created — the runner is responsible for
    # creating (and stamping ownership of) the disposable worktree. Pre-creating
    # the worktree would mask the create-safety path.
    (operator / "audit" / "reports").mkdir(parents=True, exist_ok=True)
    audit_dir = operator / "audit"
    return nr.RunnerConfig(
        operator_repo=operator,
        audit_worktree=worktree,
        report_date=report_date,
        child_argv=child_argv,
        child_cwd=worktree,
        cron_log=audit_dir / "cron.log",
        marker_log=marker_log or (audit_dir / "runner-markers.log"),
        transcript_dir=audit_dir / "transcripts",
        manifest_dir=audit_dir / "manifests",
        snapshot_dir=audit_dir / "snapshots",
        lock_path=audit_dir / ".nightly-runner.lock",
        ping_url=ping_url,
        timeout_sec=timeout_sec,
        heartbeat_sec=1,
        grace_sec=2,
        git_run=git or FakeGit(),
        ping_run=ping or PingRecorder(),
        snapshot_writer=snapshot_writer or _fake_snapshot_writer(),
        wake_lock_factory=_no_wake_lock,
        child_env=dict(os.environ),
    )


def _child_writes_report(report_path: Path, sha_prefix="abcdef12", exit_code=0):
    """argv for a python child that writes a valid report then exits."""
    src = (
        "import sys\n"
        "p=sys.argv[1]; sha=sys.argv[2]; code=int(sys.argv[3])\n"
        "import os; os.makedirs(os.path.dirname(p), exist_ok=True)\n"
        "open(p,'w',encoding='utf-8').write('# AUDIT test report\\n\\nrun SHA: '+sha+'\\n')\n"
        "print('[child] wrote report')\n"
        "sys.exit(code)\n"
    )
    return [sys.executable, "-c", src, str(report_path), sha_prefix, str(exit_code)]


def _marker_text(cfg) -> str:
    ml = cfg.marker_log
    return ml.read_text(encoding="utf-8") if ml and ml.exists() else ""


def _good_child():
    return nr.ChildResult(exit_code=0, timed_out=False, duration_sec=1.0)


# ---- real git repo fixture (operator + origin remote) ---------------------
def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    ).stdout


def _make_git_operator(tmp_path: Path):
    """A real operator checkout with an origin remote, one commit on main, and a
    tracked file. Returns (operator_path, head_sha)."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    op = tmp_path / "operator"
    op.mkdir()
    _git(op, "init")
    _git(op, "config", "user.email", "test@example.com")
    _git(op, "config", "user.name", "test")
    _git(op, "config", "commit.gpgsign", "false")
    (op / "audit" / "reports").mkdir(parents=True)
    (op / "tracked.txt").write_text("committed content\n", encoding="utf-8")
    _git(op, "add", "-A")
    _git(op, "commit", "-m", "init")
    _git(op, "branch", "-M", "main")
    _git(op, "remote", "add", "origin", str(remote))
    _git(op, "push", "-u", "origin", "main")
    sha = _git(op, "rev-parse", "HEAD").strip()
    return op, sha


def _real_git_config(op: Path, tmp_path: Path, report_date="2026-07-19", ping=None):
    worktree = tmp_path / "audit-wt"
    wt_report = worktree / "audit" / "reports" / f"{report_date}.md"
    audit_dir = op / "audit"
    return nr.RunnerConfig(
        operator_repo=op,
        audit_worktree=worktree,
        report_date=report_date,
        child_argv=[sys.executable, "-c", nr._SELFTEST_CHILD_SRC, str(wt_report)],
        child_cwd=worktree,
        cron_log=audit_dir / "cron.log",
        marker_log=audit_dir / "runner-markers.log",
        transcript_dir=audit_dir / "transcripts",
        manifest_dir=audit_dir / "manifests",
        snapshot_dir=audit_dir / "snapshots",
        lock_path=audit_dir / ".nightly-runner.lock",
        ping_url=_PING_URL,
        heartbeat_sec=1,
        grace_sec=2,
        git_run=nr._default_git_run,
        ping_run=ping or PingRecorder(),
        snapshot_writer=_fake_snapshot_writer(),
        wake_lock_factory=_no_wake_lock,
        child_env=dict(os.environ),
    )


# ---- unwritable-sink helpers (real OS boundary, not a mock) ---------------
@contextlib.contextmanager
def _held_open_exclusive(path: Path):
    """Actually make ``path`` un-appendable while the block runs. On Windows we
    hold the file open with a no-sharing handle (the real cmd-`>>` sharing
    violation). Elsewhere we put a directory at the path so open(...,'ab')
    always fails. Either way the runner's append gets a TYPED non-ok result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        path.write_bytes(b"")
        CreateFileW = ctypes.windll.kernel32.CreateFileW
        CreateFileW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
        ]
        CreateFileW.restype = wintypes.HANDLE
        handle = CreateFileW(str(path), 0xC0000000, 0, None, 4, 0x80, None)  # GENERIC_RW, share=0, OPEN_ALWAYS
        assert handle not in (0, None, wintypes.HANDLE(-1).value), "failed to hold file exclusively"
        try:
            yield
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        path.mkdir()
        try:
            yield
        finally:
            path.rmdir()


# ---------------------------------------------------------------------------
# SingleInstanceLock
# ---------------------------------------------------------------------------
def test_lock_acquire_and_reclaim_stale(tmp_path):
    lp = tmp_path / ".lock"
    a = nr.SingleInstanceLock(lp, pid=1111)
    assert a.acquire() is True
    lp.write_text("999999999", encoding="utf-8")
    c = nr.SingleInstanceLock(lp, pid=2222)
    assert c.acquire() is True  # reclaimed the stale lock
    c.release()
    assert not lp.exists()


def test_duplicate_run_lock_blocks_second_runner(tmp_path):
    cfg = _make_config(tmp_path, _child_writes_report(tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"))
    held = nr.SingleInstanceLock(cfg.lock_path, pid=os.getpid())
    assert held.acquire()
    try:
        rc = nr.NightlyRunner(cfg).run()
        assert rc == 3  # duplicate-run exit code
        assert "ABORTED" in _marker_text(cfg)
    finally:
        held.release()


# ---------------------------------------------------------------------------
# happy path
# ---------------------------------------------------------------------------
def test_happy_path_contract_met_and_ping_sent(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    ping = PingRecorder(rc=0)
    cfg = _make_config(
        tmp_path,
        _child_writes_report(wt_report, sha_prefix="abcdef12", exit_code=0),
        git=FakeGit(sha="abcdef1234567890"),
        ping=ping,
    )
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 0
    assert (cfg.operator_repo / "audit" / "reports" / "2026-07-18.md").exists()
    assert (cfg.audit_worktree / "audit" / "preflight-manifest.json").exists()
    assert (cfg.audit_worktree / "audit" / "broker-snapshot.json").exists()
    # the runner created + stamped ownership on the disposable worktree
    assert (cfg.audit_worktree / nr.AUDIT_WORKTREE_MARKER).exists()
    txt = _marker_text(cfg)
    assert nr.MARK_START in txt
    assert "nightly-audit end (exit 0)" in txt
    assert "success (UP) ping sent" in txt
    assert ping.up_calls(_PING_URL) == [(_PING_URL, None)]
    assert ping.fail_calls() == []
    assert not (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


# ---------------------------------------------------------------------------
# child killed mid-run -> failure artifact, no UP ping
# ---------------------------------------------------------------------------
def test_child_nonzero_exit_writes_failure_artifact_and_withholds_ping(tmp_path):
    argv = [sys.executable, "-c", "import sys; print('dying'); sys.exit(137)"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 137
    txt = _marker_text(cfg)
    assert "nightly-audit end (exit 137)" in txt  # end marker ALWAYS written
    assert "UP ping WITHHELD" in txt
    assert ping.up_calls(_PING_URL) == []  # no UP ping
    assert ping.fail_calls()  # a DOWN /fail ping WAS sent naming the missing class
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


# ---------------------------------------------------------------------------
# command failure AFTER the start marker landed -> failed, not an UP ping
# ---------------------------------------------------------------------------
def test_command_failure_after_start_marker_no_up_ping(tmp_path):
    argv = [sys.executable, "-c", "import sys; sys.exit(4)"]  # runs, no report
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    nr.NightlyRunner(cfg).run()
    txt = _marker_text(cfg)
    assert nr.MARK_START in txt  # start marker DID land
    assert ping.up_calls(_PING_URL) == []
    assert ping.fail_calls()


# ---------------------------------------------------------------------------
# timeout -> terminate -> kill
# ---------------------------------------------------------------------------
def test_timeout_terminates_and_kills_child(tmp_path):
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping, timeout_sec=1)
    cfg.grace_sec = 2
    rc = nr.NightlyRunner(cfg).run()
    assert rc != 0
    txt = _marker_text(cfg)
    assert "exceeded" in txt
    assert "nightly-audit end" in txt
    assert ping.up_calls(_PING_URL) == []
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


def test_spawn_and_monitor_reports_timed_out(tmp_path):
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    res = nr.spawn_and_monitor(
        argv,
        cwd=tmp_path,
        transcript_path=tmp_path / "t.log",
        timeout_sec=1,
        heartbeat_sec=1,
        grace_sec=2,
    )
    assert res.timed_out is True
    assert res.exit_code != 0


# ---------------------------------------------------------------------------
# stale-checkout detection
# ---------------------------------------------------------------------------
def test_fetch_failure_marks_workspace_stale(tmp_path):
    git = FakeGit(fail_on={"fetch"})
    info = nr.refresh_audit_worktree(
        tmp_path / "operator",
        tmp_path / "worktree",
        "origin",
        "main",
        git,
    )
    assert info.stale is True
    assert "fetch failed" in (info.error or "")


def test_manifest_records_stale_when_fetch_fails(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    cfg = _make_config(
        tmp_path,
        _child_writes_report(wt_report),
        git=FakeGit(fail_on={"fetch"}),
    )
    nr.NightlyRunner(cfg).run()
    import json

    manifest = json.loads((cfg.audit_worktree / "audit" / "preflight-manifest.json").read_text())
    assert manifest["workspace"]["stale"] is True


# ---------------------------------------------------------------------------
# missing MCP -> broker snapshot fallback marker
# ---------------------------------------------------------------------------
def test_manifest_declares_headless_broker_absent_and_snapshot_present(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    cfg = _make_config(tmp_path, _child_writes_report(wt_report))
    nr.NightlyRunner(cfg).run()
    import json

    manifest = json.loads((cfg.audit_worktree / "audit" / "preflight-manifest.json").read_text())
    assert manifest["mcp"]["expected_headless_broker"] == "absent"
    assert manifest["broker_snapshot"]["present"] is True
    assert (cfg.audit_worktree / "audit" / "broker-snapshot.json").exists()


def test_snapshot_unavailable_still_records_error_marker(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    cfg = _make_config(
        tmp_path,
        _child_writes_report(wt_report),
        snapshot_writer=_fake_snapshot_writer(available=False, error="broker unreachable"),
    )
    nr.NightlyRunner(cfg).run()
    import json

    manifest = json.loads((cfg.audit_worktree / "audit" / "preflight-manifest.json").read_text())
    assert manifest["broker_snapshot"]["available"] is False
    assert manifest["broker_snapshot"]["error"] == "broker unreachable"


# ---------------------------------------------------------------------------
# malformed / missing report -> failure artifact + no UP ping
# ---------------------------------------------------------------------------
def test_malformed_report_fails_structural_check(tmp_path):
    bad = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    src = (
        "import sys,os; p=sys.argv[1]\n"
        "os.makedirs(os.path.dirname(p),exist_ok=True)\n"
        "open(p,'w').write('not an audit header at all')\n"
    )
    argv = [sys.executable, "-c", src, str(bad)]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    nr.NightlyRunner(cfg).run()
    txt = _marker_text(cfg)
    assert "nightly-audit end (exit 0)" in txt
    assert ping.up_calls(_PING_URL) == []
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


def test_report_missing_run_sha_fails_check(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("# AUDIT v5.5 — NIGHTLY\n\nno sha here\n", encoding="utf-8")
    ok, reasons = nr.structural_report_check(report, "abcdef1234")
    assert ok is False
    assert any("SHA" in r for r in reasons)


def test_report_valid_passes_check(tmp_path):
    report = tmp_path / "r.md"
    report.write_text("# AUDIT v5.5 — NIGHTLY — 2026-07-18\n\nSHA abcdef12\n", encoding="utf-8")
    ok, reasons = nr.structural_report_check(report, "abcdef1234567")
    assert ok is True, reasons


# ---------------------------------------------------------------------------
# end marker ALWAYS written
# ---------------------------------------------------------------------------
def test_end_marker_written_even_when_preflight_child_missing(tmp_path):
    argv = ["this-binary-does-not-exist-xyz", "--nope"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    nr.NightlyRunner(cfg).run()
    assert "nightly-audit end" in _marker_text(cfg)
    assert ping.up_calls(_PING_URL) == []
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


# ---------------------------------------------------------------------------
# TYPED append (F-RUNNER-WORKTREE-DEADFALLBACK item 7)
# ---------------------------------------------------------------------------
def test_append_line_ok(tmp_path):
    res = nr.append_line(tmp_path / "a.log", "hello")
    assert res.ok and res.status == nr.APPEND_OK
    assert (tmp_path / "a.log").read_text() == "hello\n"


def test_append_line_missing_dir_is_typed(tmp_path):
    # parent path is a FILE -> mkdir(parents) fails -> typed missing_dir
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    res = nr.append_line(blocker / "sub" / "x.log", "line")
    assert not res.ok
    assert res.status == nr.APPEND_MISSING_DIR


def test_append_line_unwritable_is_typed(tmp_path):
    target = tmp_path / "held.log"
    with _held_open_exclusive(target):
        res = nr.append_line(target, "cannot write this")
    assert not res.ok
    # Windows sharing violation may surface as winerror 32 (sharing_violation)
    # or EACCES (locked) depending on the CPython build; both are typed non-ok.
    assert res.status in (nr.APPEND_SHARING_VIOLATION, nr.APPEND_LOCKED, nr.APPEND_MISSING_DIR)


def test_classify_append_error_mapping():
    e32 = PermissionError(); e32.winerror = 32
    e33 = PermissionError(); e33.winerror = 33
    assert nr.classify_append_error(e32) == nr.APPEND_SHARING_VIOLATION
    assert nr.classify_append_error(e33) == nr.APPEND_LOCKED
    assert nr.classify_append_error(PermissionError()) == nr.APPEND_LOCKED
    assert nr.classify_append_error(FileNotFoundError()) == nr.APPEND_MISSING_DIR
    assert nr.classify_append_error(IsADirectoryError()) == nr.APPEND_MISSING_DIR


# ---------------------------------------------------------------------------
# LOCKED MARKER SINK -> no false UP ping (the exact defect scenario)
# ---------------------------------------------------------------------------
def test_locked_marker_sink_no_false_up_ping(tmp_path):
    """The defect: a swallowed marker append set _end_marker_written=True and the
    dead-man UP-ping fired over an EMPTY sink. Here the sink is genuinely
    un-appendable for the whole run; the contract re-reads disk, sees no
    start/end marker, and WITHHOLDS the UP ping."""
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    ping = PingRecorder()
    cfg = _make_config(tmp_path, _child_writes_report(wt_report), ping=ping)
    runner = nr.NightlyRunner(cfg)
    with _held_open_exclusive(cfg.marker_log):
        runner.run()
    # marker appends were RECORDED as failures, not swallowed
    assert runner._marker_failures
    assert all(mf["status"] != nr.APPEND_OK for mf in runner._marker_failures)
    # NO false UP ping; a DOWN /fail ping was sent instead
    assert ping.up_calls(_PING_URL) == []
    assert ping.fail_calls()
    # failure artifact names the missing marker classes
    art = (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").read_text()
    assert nr.ARTIFACT_START_MARKER in art
    assert nr.ARTIFACT_END_MARKER in art


def test_two_runs_shared_sink_second_run_appends_fail_not_met(tmp_path):
    """Reviewer finding 1 (BLOCKER) falsifier: the marker sink is append-only and
    shared across nights. Run 1 writes valid start/end markers. Run 2's appends
    ALL fail (the sink is read-only) while run 1's markers remain READABLE — run
    2's contract MUST be NOT met and its UP ping suppressed. A bare substring
    check over the accumulated file would (wrongly) see run 1's markers and fire
    a false UP ping for run 2."""
    import stat

    shared = tmp_path / "operator" / "audit" / "runner-markers.log"

    # RUN 1 — normal success into the shared sink
    wt1 = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    ping1 = PingRecorder()
    cfg1 = _make_config(
        tmp_path, _child_writes_report(wt1), report_date="2026-07-18", ping=ping1, marker_log=shared
    )
    assert nr.NightlyRunner(cfg1).run() == 0
    assert ping1.up_calls(_PING_URL) == [(_PING_URL, None)]  # run 1 legitimately UP-pinged
    run1_text = shared.read_text()
    assert nr.MARK_START in run1_text and nr.MARK_END in run1_text

    # RUN 2 — same shared sink, made READ-ONLY so run 2's appends FAIL (typed)
    # while run 1's markers stay READABLE in the file.
    os.chmod(shared, stat.S_IREAD)
    try:
        wt2 = tmp_path / "worktree2" / "audit" / "reports" / "2026-07-19.md"
        ping2 = PingRecorder()
        cfg2 = _make_config(
            tmp_path,
            _child_writes_report(wt2, sha_prefix="abcdef12"),
            report_date="2026-07-19",
            ping=ping2,
            marker_log=shared,
            audit_worktree=tmp_path / "worktree2",
        )
        r2 = nr.NightlyRunner(cfg2)
        r2.run()
        # run 2's own appends failed (typed, recorded) — its markers never landed
        assert r2._marker_failures
        assert all(mf["status"] != nr.APPEND_OK for mf in r2._marker_failures)
        # run 1's markers are STILL readable in the shared sink...
        assert nr.MARK_START in shared.read_text()
        # ...but run 2's contract is scoped to run 2 -> NOT met, NO false UP ping
        assert ping2.up_calls(_PING_URL) == []
        assert ping2.fail_calls()
    finally:
        os.chmod(shared, stat.S_IWRITE | stat.S_IREAD)


def test_completion_eval_exception_forces_down_ping_and_releases_lock(tmp_path, monkeypatch):
    """Reviewer finding 3: a TOCTOU exception inside the completion evaluation
    (report/marker races away) must NOT skip the ping or leak the lock, and must
    NEVER leave the run looking green — it routes to an explicit DOWN ping."""
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    ping = PingRecorder()
    cfg = _make_config(tmp_path, _child_writes_report(wt_report), ping=ping)

    def _boom(*a, **k):
        raise RuntimeError("toctou: report vanished mid-evaluation")

    monkeypatch.setattr(nr, "evaluate_completion_contract", _boom)
    nr.NightlyRunner(cfg).run()
    assert ping.up_calls(_PING_URL) == []  # never an UP ping after an eval error
    assert ping.fail_calls()  # DOWN ping fired instead
    assert not cfg.lock_path.exists()  # lock released despite the exception


# ---------------------------------------------------------------------------
# completion contract re-reads durable evidence from disk (item 8)
# ---------------------------------------------------------------------------
_TEST_RUN_TAG = "[run=fixture-run]"


def _write_contract_fixture(
    tmp_path, *, start=True, end=True, report=True, manifest=True, transcript=True, tag=_TEST_RUN_TAG
):
    ml = tmp_path / "markers.log"
    if start:
        nr.append_line(ml, f"==== ts {nr.MARK_START} (runner) {tag} ====")
    if end:
        nr.append_line(ml, f"==== ts {nr.MARK_END} (exit 0) {tag} ====")
    rep = tmp_path / "r.md"
    if report:
        rep.write_text("# AUDIT report\n\nrun SHA: abcdef12\n", encoding="utf-8")
    mf = tmp_path / "manifest.json"
    if manifest:
        mf.write_text("{}", encoding="utf-8")
    tr = tmp_path / "t.log"
    if transcript:
        tr.write_text("some transcript output\n", encoding="utf-8")
    return mf, rep, ml, tr


def test_contract_met_when_all_present(tmp_path):
    mf, rep, ml, tr = _write_contract_fixture(tmp_path)
    c = nr.evaluate_completion_contract(mf, rep, ml, tr, "abcdef1234", _good_child(), _TEST_RUN_TAG)
    assert c.met and c.status == "met" and c.missing_artifacts == []


@pytest.mark.parametrize(
    "drop,klass",
    [
        ("start", nr.ARTIFACT_START_MARKER),
        ("end", nr.ARTIFACT_END_MARKER),
        ("report", nr.ARTIFACT_REPORT),
        ("manifest", nr.ARTIFACT_MANIFEST),
        ("transcript", nr.ARTIFACT_TRANSCRIPT),
    ],
)
def test_contract_not_met_when_each_artifact_missing(tmp_path, drop, klass):
    kwargs = {"start": True, "end": True, "report": True, "manifest": True, "transcript": True}
    kwargs[drop] = False
    mf, rep, ml, tr = _write_contract_fixture(tmp_path, **kwargs)
    c = nr.evaluate_completion_contract(mf, rep, ml, tr, "abcdef1234", _good_child(), _TEST_RUN_TAG)
    assert not c.met
    assert klass in c.missing_artifacts
    assert c.status in ("partial", "failed")


def test_contract_child_nonzero_is_failed(tmp_path):
    mf, rep, ml, tr = _write_contract_fixture(tmp_path)
    child = nr.ChildResult(exit_code=1, timed_out=False, duration_sec=1.0)
    c = nr.evaluate_completion_contract(mf, rep, ml, tr, "abcdef1234", child, _TEST_RUN_TAG)
    assert not c.met
    assert nr.ARTIFACT_CHILD_EXIT in c.missing_artifacts


def test_contract_scoped_to_run_tag_ignores_prior_run_markers(tmp_path):
    # The sink is append-only across nights: night-1 markers must NEVER satisfy
    # a DIFFERENT run's contract (reviewer finding 1, unit-level).
    mf, rep, ml, tr = _write_contract_fixture(tmp_path, tag="[run=NIGHT1]")
    c = nr.evaluate_completion_contract(mf, rep, ml, tr, "abcdef1234", _good_child(), "[run=NIGHT2]")
    assert not c.met
    assert nr.ARTIFACT_START_MARKER in c.missing_artifacts
    assert nr.ARTIFACT_END_MARKER in c.missing_artifacts


def test_contract_missing_run_sha_is_a_reason(tmp_path):
    # reviewer finding 2: a None run_sha (workspace rev-parse failed) must FAIL
    # report_ok, not silently skip the SHA-grounding check.
    mf, rep, ml, tr = _write_contract_fixture(tmp_path)
    c = nr.evaluate_completion_contract(mf, rep, ml, tr, None, _good_child(), _TEST_RUN_TAG)
    assert not c.met
    assert nr.ARTIFACT_REPORT in c.missing_artifacts
    assert any("SHA unavailable" in r for r in c.report_reasons)


def test_structural_report_check_missing_sha_fails():
    import tempfile

    d = Path(tempfile.mkdtemp())
    rep = d / "r.md"
    rep.write_text("# AUDIT report body\n", encoding="utf-8")
    ok, reasons = nr.structural_report_check(rep, None)
    assert ok is False
    assert any("SHA unavailable" in r for r in reasons)


# ---------------------------------------------------------------------------
# item 1 — dead-fallback fix: blank/whitespace AUDIT_WORKTREE_DIR -> fallback
# ---------------------------------------------------------------------------
def test_worktree_env_absent_uses_local_appdata_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("AUDIT_WORKTREE_DIR", raising=False)
    cfg = nr.build_production_config(tmp_path)
    assert cfg.audit_worktree == nr._local_appdata_worktree()  # v1.6 named falsifier


def test_worktree_env_empty_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_WORKTREE_DIR", "")
    cfg = nr.build_production_config(tmp_path)
    assert cfg.audit_worktree == nr._local_appdata_worktree()


def test_worktree_env_whitespace_uses_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_WORKTREE_DIR", "   ")
    cfg = nr.build_production_config(tmp_path)
    assert cfg.audit_worktree == nr._local_appdata_worktree()


def test_worktree_env_set_is_honoured(tmp_path, monkeypatch):
    target = tmp_path / "explicit-wt"
    monkeypatch.setenv("AUDIT_WORKTREE_DIR", str(target))
    cfg = nr.build_production_config(tmp_path)
    assert cfg.audit_worktree == target


def test_worktree_env_padded_value_is_stripped(tmp_path, monkeypatch):
    # reviewer finding 4: use the STRIPPED value for the Path, not the raw
    # padded one (a padded path would resolve to a bogus location).
    target = tmp_path / "explicit-wt"
    monkeypatch.setenv("AUDIT_WORKTREE_DIR", f"   {target}   ")
    cfg = nr.build_production_config(tmp_path)
    assert cfg.audit_worktree == target


def test_local_appdata_fallback_dir_is_created_by_marker_stamp(tmp_path):
    # _ensure_worktree_marker creates the fallback dir when the runner owns it.
    target = tmp_path / "does-not-exist-yet"
    assert not target.exists()
    nr._ensure_worktree_marker(target)
    assert target.exists()
    assert (target / nr.AUDIT_WORKTREE_MARKER).exists()


# ---------------------------------------------------------------------------
# item 2/3/5 — geometry safety (REFUSE typed)
# ---------------------------------------------------------------------------
def test_geometry_refuses_worktree_equals_operator(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    with pytest.raises(nr.WorktreeSafetyError):
        nr.verify_worktree_geometry(op, op)


def test_geometry_refuses_worktree_inside_operator(tmp_path):
    op = tmp_path / "operator"
    (op / "sub").mkdir(parents=True)
    with pytest.raises(nr.WorktreeSafetyError):
        nr.verify_worktree_geometry(op, op / "sub")


def test_geometry_refuses_worktree_equals_cwd(tmp_path, monkeypatch):
    op = tmp_path / "operator"
    op.mkdir()
    workdir = tmp_path / "here"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    with pytest.raises(nr.WorktreeSafetyError):
        nr.verify_worktree_geometry(op, Path("."))


def test_geometry_allows_disjoint_sibling(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    wt = tmp_path / "audit-wt"
    resolved = nr.verify_worktree_geometry(op, wt)
    assert resolved == wt.resolve()


def test_refresh_refuses_when_worktree_equals_operator(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    with pytest.raises(nr.WorktreeSafetyError):
        nr.refresh_audit_worktree(op, op, "origin", "main", FakeGit())


def test_refresh_refuses_reuse_without_ownership_marker(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    wt = tmp_path / "audit-wt"
    (wt / ".git").mkdir(parents=True)  # looks like a worktree, but NO ownership marker
    with pytest.raises(nr.WorktreeSafetyError):
        nr.refresh_audit_worktree(op, wt, "origin", "main", FakeGit())


def test_refresh_refuses_create_over_nonempty_unowned_dir(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    wt = tmp_path / "audit-wt"
    wt.mkdir()
    (wt / "someones-data.txt").write_text("do not clobber me", encoding="utf-8")
    with pytest.raises(nr.WorktreeSafetyError):
        nr.refresh_audit_worktree(op, wt, "origin", "main", FakeGit())


def test_refresh_reuses_owned_worktree_with_marker(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    wt = tmp_path / "audit-wt"
    (wt / ".git").mkdir(parents=True)
    (wt / nr.AUDIT_WORKTREE_MARKER).write_text("owned", encoding="utf-8")
    git = FakeGit()
    info = nr.refresh_audit_worktree(op, wt, "origin", "main", git)
    assert info.error is None or "fetch failed" not in info.error
    verbs = git.verbs()
    assert "checkout" in verbs and "reset" in verbs  # destructive refresh ran on the owned worktree


def test_run_destructive_git_refuses_operator_target(tmp_path):
    op = tmp_path / "operator"
    op.mkdir()
    called = {"n": 0}

    def spy(args):
        called["n"] += 1
        return ""

    with pytest.raises(nr.WorktreeSafetyError):
        nr.run_destructive_git(spy, op, op, ["-C", str(op), "reset", "--hard", "deadbeef"])
    assert called["n"] == 0  # never reached the git call


def test_full_run_refused_when_audit_equals_operator(tmp_path):
    argv = _child_writes_report(tmp_path / "operator" / "audit" / "reports" / "2026-07-18.md")
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping, audit_worktree=tmp_path / "operator")
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 1
    assert ping.up_calls(_PING_URL) == []
    art = (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md")
    assert art.exists()
    assert "WorktreeSafetyError" in art.read_text()


# ---------------------------------------------------------------------------
# REAL GIT — disposable-worktree lifecycle + operator preservation
# ---------------------------------------------------------------------------
def test_successful_disposable_worktree_run_real_git(tmp_path):
    op, sha = _make_git_operator(tmp_path)
    ping = PingRecorder()
    cfg = _real_git_config(op, tmp_path, ping=ping)
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 0, _marker_text(cfg)
    worktree = cfg.audit_worktree
    assert (worktree / ".git").exists()  # a real detached worktree
    assert (worktree / nr.AUDIT_WORKTREE_MARKER).exists()  # runner-owned
    # detached HEAD pinned to the resolved origin/main SHA
    head = _git(worktree, "rev-parse", "HEAD").strip()
    assert head == sha
    # report copied back + contract met -> UP ping
    assert (op / "audit" / "reports" / "2026-07-19.md").exists()
    assert ping.up_calls(_PING_URL) == [(_PING_URL, None)]


def test_operator_dirty_preserved_byte_for_byte_real_git(tmp_path):
    op, sha = _make_git_operator(tmp_path)
    dirty = op / "tracked.txt"
    dirty.write_text("DIRTY UNCOMMITTED WORKING-TREE EDIT\n", encoding="utf-8")
    before_bytes = dirty.read_bytes()
    tracked = [f for f in _git(op, "ls-files").splitlines() if f]
    inv_before = {f: (op / f).read_bytes() for f in tracked}

    cfg = _real_git_config(op, tmp_path)
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 0, _marker_text(cfg)

    # the operator's dirty working file is BYTE-FOR-BYTE unchanged (the old bug
    # ran `git reset --hard` against it and reverted it).
    assert dirty.read_bytes() == before_bytes
    # tracked-file inventory unchanged (runner only adds untracked outputs)
    inv_after = {f: (op / f).read_bytes() for f in tracked}
    assert inv_after == inv_before
    # git still sees the working-tree modification (it was never reset away)
    status = _git(op, "status", "--porcelain")
    assert any(line.endswith("tracked.txt") and "M" in line[:2] for line in status.splitlines())


# ---------------------------------------------------------------------------
# broker snapshot module (GET-only, masking, scrub, error states)
# ---------------------------------------------------------------------------
def test_broker_snapshot_masks_account_and_scrubs_creds():
    env = {"ALPACA_API_KEY": "SECRETKEY123", "ALPACA_SECRET_KEY": "SECRETVAL456", "ALPACA_PAPER": "false"}

    def fake_get(url, headers, params=None):
        if url.endswith("/v2/account"):
            return 200, {"id": "uuid-xyz", "account_number": "211900084", "status": "ACTIVE",
                         "equity": "2067.86", "options_buying_power": "500", "options_trading_level": 3}
        if url.endswith("/v2/clock"):
            return 200, {"is_open": False, "timestamp": "2026-07-18T00:00:00Z"}
        if url.endswith("/v2/calendar"):
            return 200, [{"date": "2026-07-18"}]
        if url.endswith("/v2/positions"):
            return 200, []
        if url.endswith("/v2/orders"):
            return 200, []
        return 404, None

    snap = bs.build_snapshot(env=env, http_get=fake_get)
    assert snap["available"] is True
    assert snap["account"]["account_number"] == "*****0084"  # masked
    assert "uuid-xyz" not in __import__("json").dumps(snap)  # UUID never included
    assert "SECRETKEY123" not in __import__("json").dumps(snap)
    assert "SECRETVAL456" not in __import__("json").dumps(snap)
    assert snap["base_url"] == bs.LIVE_BASE


def test_broker_snapshot_error_state_on_http_failure():
    env = {"ALPACA_API_KEY": "AKFAKEKEY1234567890", "ALPACA_SECRET_KEY": "SKFAKESECRET0987654321"}

    def fake_get(url, headers, params=None):
        return 500, None

    snap = bs.build_snapshot(env=env, http_get=fake_get)
    assert snap["available"] is False
    assert snap["error"] and "HTTP 500" in snap["error"]


def test_broker_snapshot_missing_creds_unavailable():
    snap = bs.build_snapshot(env={}, http_get=lambda *a, **k: (200, {}))
    assert snap["available"] is False
    assert "not set" in snap["error"]


def test_broker_snapshot_write_atomic(tmp_path):
    out = tmp_path / "snap.json"
    bs.write_snapshot(str(out), env={}, http_get=lambda *a, **k: (200, {}))
    assert out.exists()
    import json

    data = json.loads(out.read_text())
    assert data["available"] is False


# ---------------------------------------------------------------------------
# no-secret-logging assertion across artifacts
# ---------------------------------------------------------------------------
def test_no_secret_in_manifest_or_markers(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    secret = "TOPSECRET_ALPACA_VALUE_xyz"
    env = dict(os.environ)
    env["ALPACA_SECRET_KEY"] = secret
    cfg = _make_config(tmp_path, _child_writes_report(wt_report))
    cfg.child_env = env
    nr.NightlyRunner(cfg).run()
    manifest_txt = (cfg.audit_worktree / "audit" / "preflight-manifest.json").read_text()
    assert secret not in manifest_txt
    assert secret not in _marker_text(cfg)
