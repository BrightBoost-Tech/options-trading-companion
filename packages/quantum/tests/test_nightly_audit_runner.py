"""Tests for the nightly-audit reliability runner (audit/runner/).

The runner lives outside packages/quantum, so we load it (and its broker
snapshot sibling) by file path — this keeps the tests independent of package
layout and pytest import mode, and works identically on Linux CI (the runner is
written to import cleanly there; every Windows-only call is deferred behind a
sys.platform guard).

Coverage (per the Lane-1 task):
  - duplicate-run lock
  - child killed mid-run  -> failure artifact + NO ping
  - timeout -> terminate -> kill
  - stale-checkout detection (fetch failure marks workspace stale)
  - missing MCP -> broker snapshot fallback marker present
  - malformed / missing report -> failure artifact + NO ping
  - end marker ALWAYS written (happy path AND failure path)
  - broker snapshot: masking, error state, credential scrub
  - happy path -> contract met + ping sent
"""
import importlib.util
import os
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


class PingRecorder:
    def __init__(self, rc=0):
        self.calls = []
        self.rc = rc

    def __call__(self, url):
        self.calls.append(url)
        return self.rc


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


def _make_config(
    tmp_path: Path,
    child_argv,
    *,
    report_date="2026-07-18",
    git=None,
    ping=None,
    ping_url="http://ping.example/uuid",
    snapshot_writer=None,
    timeout_sec=90 * 60,
):
    operator = tmp_path / "operator"
    worktree = tmp_path / "worktree"
    (operator / "audit" / "reports").mkdir(parents=True, exist_ok=True)
    (worktree / "audit" / "reports").mkdir(parents=True, exist_ok=True)
    audit_dir = operator / "audit"
    return nr.RunnerConfig(
        operator_repo=operator,
        audit_worktree=worktree,
        report_date=report_date,
        child_argv=child_argv,
        child_cwd=worktree,
        cron_log=audit_dir / "cron.log",
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


def _cron_text(cfg) -> str:
    return cfg.cron_log.read_text(encoding="utf-8") if cfg.cron_log.exists() else ""


# ---------------------------------------------------------------------------
# SingleInstanceLock
# ---------------------------------------------------------------------------
def test_lock_acquire_and_reclaim_stale(tmp_path):
    lp = tmp_path / ".lock"
    a = nr.SingleInstanceLock(lp, pid=1111)
    assert a.acquire() is True
    # overwrite with a definitely-dead PID so the next acquirer reclaims it
    lp.write_text("999999999", encoding="utf-8")
    c = nr.SingleInstanceLock(lp, pid=2222)
    assert c.acquire() is True  # reclaimed the stale lock
    c.release()
    assert not lp.exists()


def test_duplicate_run_lock_blocks_second_runner(tmp_path):
    cfg = _make_config(tmp_path, _child_writes_report(tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"))
    # Pre-acquire the lock with a live PID (this process) so the runner sees a
    # duplicate and aborts.
    held = nr.SingleInstanceLock(cfg.lock_path, pid=os.getpid())
    assert held.acquire()
    try:
        rc = nr.NightlyRunner(cfg).run()
        assert rc == 3  # duplicate-run exit code
        assert "ABORTED" in _cron_text(cfg)
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
    # report copied back to operator checkout
    assert (cfg.operator_repo / "audit" / "reports" / "2026-07-18.md").exists()
    # manifest + snapshot produced
    assert (cfg.audit_worktree / "audit" / "preflight-manifest.json").exists()
    assert (cfg.audit_worktree / "audit" / "broker-snapshot.json").exists()
    # end marker + contract-met + ping
    txt = _cron_text(cfg)
    assert "nightly-audit start" in txt
    assert "nightly-audit end (exit 0)" in txt
    assert "success ping sent" in txt
    assert ping.calls == [cfg.ping_url]
    # no failure artifact
    assert not (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


# ---------------------------------------------------------------------------
# child killed mid-run -> failure artifact, no ping
# ---------------------------------------------------------------------------
def test_child_nonzero_exit_writes_failure_artifact_and_withholds_ping(tmp_path):
    # child exits non-zero and writes NO report (simulates a mid-run kill)
    argv = [sys.executable, "-c", "import sys; print('dying'); sys.exit(137)"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    rc = nr.NightlyRunner(cfg).run()
    assert rc == 137
    txt = _cron_text(cfg)
    assert "nightly-audit end (exit 137)" in txt  # end marker ALWAYS written
    assert "success ping sent" not in txt
    assert "WITHHELD" in txt
    assert ping.calls == []  # ping withheld
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


# ---------------------------------------------------------------------------
# timeout -> terminate -> kill
# ---------------------------------------------------------------------------
def test_timeout_terminates_and_kills_child(tmp_path):
    # child sleeps far longer than the timeout and ignores SIGTERM briefly
    argv = [sys.executable, "-c", "import time; time.sleep(60)"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping, timeout_sec=1)
    cfg.grace_sec = 2
    rc = nr.NightlyRunner(cfg).run()
    assert rc != 0
    txt = _cron_text(cfg)
    assert "exceeded" in txt  # timeout path logged
    assert "nightly-audit end" in txt  # end marker written despite timeout
    assert ping.calls == []  # no report -> contract not met -> no ping
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()


def test_spawn_and_monitor_reports_timed_out(tmp_path):
    argv = [sys.executable, "-c", "import time; time.sleep(30)"]
    res = nr.spawn_and_monitor(
        argv,
        cwd=tmp_path,
        transcript_path=tmp_path / "t.log",
        cron_log=tmp_path / "cron.log",
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
# malformed / missing report -> failure artifact + no ping
# ---------------------------------------------------------------------------
def test_malformed_report_fails_structural_check(tmp_path):
    # child exits 0 but writes a report with the wrong header
    bad = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    src = (
        "import sys,os; p=sys.argv[1]\n"
        "os.makedirs(os.path.dirname(p),exist_ok=True)\n"
        "open(p,'w').write('not an audit header at all')\n"
    )
    argv = [sys.executable, "-c", src, str(bad)]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    rc = nr.NightlyRunner(cfg).run()
    # child exited 0 but report is malformed -> contract not met
    txt = _cron_text(cfg)
    assert "nightly-audit end (exit 0)" in txt
    assert ping.calls == []
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()
    del rc


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
    # nonexistent interpreter path -> spawn raises inside run(); finally must
    # still write the end marker and a failure artifact.
    argv = ["this-binary-does-not-exist-xyz", "--nope"]
    ping = PingRecorder()
    cfg = _make_config(tmp_path, argv, ping=ping)
    rc = nr.NightlyRunner(cfg).run()
    assert "nightly-audit end" in _cron_text(cfg)
    assert ping.calls == []
    assert (cfg.operator_repo / "audit" / "ALERT-2026-07-18-runner.md").exists()
    del rc


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
def test_no_secret_in_manifest_or_cron(tmp_path):
    wt_report = tmp_path / "worktree" / "audit" / "reports" / "2026-07-18.md"
    secret = "TOPSECRET_ALPACA_VALUE_xyz"
    env = dict(os.environ)
    env["ALPACA_SECRET_KEY"] = secret
    cfg = _make_config(tmp_path, _child_writes_report(wt_report))
    cfg.child_env = env
    nr.NightlyRunner(cfg).run()
    manifest_txt = (cfg.audit_worktree / "audit" / "preflight-manifest.json").read_text()
    assert secret not in manifest_txt
    assert secret not in _cron_text(cfg)
