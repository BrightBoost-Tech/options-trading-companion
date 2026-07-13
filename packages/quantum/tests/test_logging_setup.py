"""PR-0 (F-LOG-INFO-DROP) — boundary tests for process logging configuration.

§9 discipline: these tests exercise the REAL logging layer end-to-end — a real
StreamHandler writing to a real stream we can read back. No assertLogs (which
swaps handlers), no mock of the logging machinery: the defect being fixed was
"INFO records destroyed in-process before any handler", and only a captured
real stream can prove that class dead.
"""
import io
import logging
import unittest
from unittest.mock import patch

from packages.quantum.logging_setup import (
    _CONFIGURED_FLAG,
    NOISY_LOGGERS,
    setup_logging,
)


class _RootStateSnapshot:
    """Save/restore root logger state so these tests never leak configuration
    into (or inherit it from) the rest of the suite."""

    def __enter__(self):
        self.root = logging.getLogger()
        self.handlers = list(self.root.handlers)
        self.level = self.root.level
        self.flag = getattr(self.root, _CONFIGURED_FLAG, False)
        self.noisy_levels = {n: logging.getLogger(n).level for n in NOISY_LOGGERS}
        self.root.handlers = []
        if hasattr(self.root, _CONFIGURED_FLAG):
            setattr(self.root, _CONFIGURED_FLAG, False)
        return self

    def __exit__(self, *exc):
        self.root.handlers = self.handlers
        self.root.setLevel(self.level)
        setattr(self.root, _CONFIGURED_FLAG, self.flag)
        for n, lvl in self.noisy_levels.items():
            logging.getLogger(n).setLevel(lvl)
        return False


def _capture_stream() -> io.StringIO:
    """Point the handler setup_logging() installed at a StringIO and return it."""
    buf = io.StringIO()
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.stream = buf
    return buf


class TestSetupLogging(unittest.TestCase):
    def test_canary_emitted_through_real_handler(self):
        """The canary INFO line must reach the configured stream — the exact
        line whose presence in Railway proves the deploy (H8 read-back)."""
        with _RootStateSnapshot():
            fake_stdout = io.StringIO()
            with patch("sys.stdout", fake_stdout):
                configured = setup_logging()
            self.assertTrue(configured)
            self.assertIn("logging configured root=INFO", fake_stdout.getvalue())

    def test_app_module_info_reaches_stream(self):
        """A logger.info from an application module (the exact class that was
        being destroyed — a shadow-window marker) must land on the stream."""
        with _RootStateSnapshot():
            setup_logging()
            buf = _capture_stream()
            logging.getLogger(
                "packages.quantum.services.risk_basis_shadow"
            ).info("[RISK_BASIS_SHADOW] boundary-test consumer=test")
            self.assertIn("[RISK_BASIS_SHADOW] boundary-test", buf.getvalue())

    def test_idempotent_no_handler_stacking(self):
        with _RootStateSnapshot():
            self.assertTrue(setup_logging())
            n_handlers = len(logging.getLogger().handlers)
            self.assertFalse(setup_logging())
            self.assertFalse(setup_logging())
            self.assertEqual(len(logging.getLogger().handlers), n_handlers)

    def test_noisy_lib_info_suppressed_app_info_kept(self):
        """The denylist pins third-party INFO to WARNING without touching app
        loggers — noisy tunable, app evidence intact."""
        with _RootStateSnapshot():
            setup_logging()
            buf = _capture_stream()
            logging.getLogger("httpx").info("HTTP Request: GET https://x")
            logging.getLogger("rq").info("Job OK (noise)")
            logging.getLogger("packages.quantum.anything").info("app-evidence")
            out = buf.getvalue()
            self.assertNotIn("HTTP Request", out)
            self.assertNotIn("Job OK", out)
            self.assertIn("app-evidence", out)
            # WARNING+ from a pinned lib still passes (pin, not mute)
            logging.getLogger("httpx").warning("httpx-warning-passes")
            self.assertIn("httpx-warning-passes", buf.getvalue())

    def test_bad_level_env_falls_back_to_info(self):
        """A typo in OTC_LOG_LEVEL must not kill a worker — fall back to INFO."""
        with _RootStateSnapshot():
            with patch.dict("os.environ", {"OTC_LOG_LEVEL": "VERBOSEST"}):
                fake_stdout = io.StringIO()
                with patch("sys.stdout", fake_stdout):
                    self.assertTrue(setup_logging())
                self.assertIn("root=INFO", fake_stdout.getvalue())
            self.assertEqual(logging.getLogger().level, logging.INFO)


if __name__ == "__main__":
    unittest.main()
