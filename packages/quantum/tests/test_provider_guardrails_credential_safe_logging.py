"""Credential-safe @guardrail exception logging (v1.7 V17-5,
F-V17-5-GUARDRAIL-EXCEPTION-CREDENTIAL-LOG).

The ``@guardrail`` decorator (packages/quantum/services/provider_guardrails.py)
wraps every Polygon call. Each Polygon request URL carries ``apiKey=<secret>``
in its query string, so on a requests exception ``str(last_exception)`` embeds
that URL verbatim. Pre-fix the decorator's retries-exhausted path logged that
raw string (``logger.error``), interpolated it into the alert ``message``, and
stored ``str(last_exception)[:500]`` in the alert metadata — leaking the key.

This is the SAME class as the fixed ``market_data.py`` exception-snippet site.
These tests pin the redaction against reintroduction. NO real credential value
appears in this module — every secret used is SYNTHETIC.
"""

import logging
import re

from unittest.mock import MagicMock

import pytest

from packages.quantum.services.provider_guardrails import guardrail


# ---------------------------------------------------------------------------
# SYNTHETIC secrets only — never a real credential fragment. Chosen so their
# first-4 / first-8 slices are distinctive tokens that cannot collide with any
# legitimate log content (symbols, statuses, counts).
# ---------------------------------------------------------------------------
SYNTH_POLYGON_KEY = "ZZSYNTHPOLYGONKEY12345678abcdef0"   # 32 chars


def _key_slices(secret):
    """The substrings a leak would expose: first-4, first-8, and the whole
    value. If NONE appear in a log/field, no fragment leaked."""
    return (secret[:4], secret[:8], secret)


def _assert_no_secret(text, secret, where):
    text = text or ""
    for frag in _key_slices(secret):
        assert frag not in text, (
            f"synthetic secret fragment {frag!r} leaked in {where}: {text!r}"
        )


@pytest.fixture
def armed_supabase(monkeypatch):
    """Pre-arm the shared admin singleton with a controlled mock and reset the
    per-provider breakers so prior tests don't pollute."""
    from packages.quantum.observability import alerts
    supabase_mock = MagicMock()
    monkeypatch.setattr(alerts, "_ADMIN_SUPABASE", supabase_mock)
    monkeypatch.setattr(alerts, "_ADMIN_INIT_ATTEMPTED", True)

    from packages.quantum.services.provider_guardrails import _BREAKERS
    _BREAKERS.clear()
    yield supabase_mock
    _BREAKERS.clear()


def _last_alert_record(supabase_mock):
    return supabase_mock.table.return_value.insert.call_args.args[0]


class _FakePolygon:
    """Minimal stand-in for PolygonService: carries a configured ``api_key``
    (the verbatim-redaction target) and a guardrailed method that raises a
    requests-style exception whose str() embeds the leaky URL."""

    def __init__(self, exc):
        self.api_key = SYNTH_POLYGON_KEY
        self._exc = exc

    @guardrail(provider="polygon", max_retries=0, backoff_base=0.01, fallback=None)
    def fetch(self, symbol):
        raise self._exc


# ===========================================================================
# 1. apiKey=<secret> query-param in the exception URL is redacted everywhere.
# ===========================================================================
def test_retries_exhausted_redacts_apikey_query_param(armed_supabase, caplog):
    leaky = RuntimeError(
        "ConnectionError to https://api.polygon.io/v2/last/nbbo/SPY?"
        f"apiKey={SYNTH_POLYGON_KEY} (Max retries exceeded)"
    )
    svc = _FakePolygon(leaky)

    with caplog.at_level(logging.DEBUG):
        result = svc.fetch("SPY")

    assert result is None  # fallback unchanged

    record = _last_alert_record(armed_supabase)
    assert record["alert_type"] == "polygon_retries_exhausted"

    # Alert message, stored error_message, AND the emitted log line: all
    # redacted, none carries any fragment of the synthetic key.
    _assert_no_secret(record["message"], SYNTH_POLYGON_KEY, "alert message")
    _assert_no_secret(
        record["metadata"]["error_message"], SYNTH_POLYGON_KEY, "metadata error_message"
    )
    assert "[REDACTED]" in record["metadata"]["error_message"]
    for r in caplog.records:
        _assert_no_secret(r.getMessage(), SYNTH_POLYGON_KEY, f"log {r.name!r}")
    logged = " | ".join(r.getMessage() for r in caplog.records)
    assert "[REDACTED]" in logged


# ===========================================================================
# 2. The configured secret is redacted verbatim even OUTSIDE a query param.
# ===========================================================================
def test_retries_exhausted_redacts_configured_secret_verbatim(armed_supabase):
    # Secret appears bare (not as apiKey=…) — only the verbatim pass catches it.
    leaky = RuntimeError(f"auth rejected for token {SYNTH_POLYGON_KEY} on host")
    svc = _FakePolygon(leaky)

    svc.fetch("SPY")

    record = _last_alert_record(armed_supabase)
    _assert_no_secret(
        record["metadata"]["error_message"], SYNTH_POLYGON_KEY, "metadata error_message"
    )
    assert "[REDACTED]" in record["metadata"]["error_message"]


# ===========================================================================
# 3. Redaction runs BEFORE the [:500] truncation — a key past char 500 is
#    still removed (defence-in-depth against the verbose requests shape).
# ===========================================================================
def test_redaction_runs_before_500_truncation(armed_supabase):
    filler = "x" * 600
    leaky = RuntimeError(
        f"HTTPSConnectionPool(host='api.polygon.io'): {filler} url: "
        f"/v2/last/nbbo/SPY?apiKey={SYNTH_POLYGON_KEY} (Caused by ...)"
    )
    svc = _FakePolygon(leaky)

    svc.fetch("SPY")

    record = _last_alert_record(armed_supabase)
    # The raw key sits well past char 500; had truncation preceded redaction it
    # would have been dropped by luck — but the FULL (pre-truncation) string is
    # redacted first, so the stored 500-char snippet cannot contain it.
    _assert_no_secret(
        record["metadata"]["error_message"], SYNTH_POLYGON_KEY, "metadata error_message"
    )


# ===========================================================================
# 4. Non-secret exception text is preserved (behaviour unchanged).
# ===========================================================================
def test_non_secret_exception_preserved(armed_supabase):
    @guardrail(provider="polygon", max_retries=0, backoff_base=0.01, fallback="FB")
    def fn(symbol):
        raise RuntimeError("boom no secret here")

    result = fn("AAPL")
    assert result == "FB"

    record = _last_alert_record(armed_supabase)
    assert "boom no secret here" in record["metadata"]["error_message"]
    assert record["metadata"]["error_class"] == "RuntimeError"
    assert "'AAPL'" in record["metadata"]["args"]  # args repr unchanged for non-secrets


# ===========================================================================
# 5. Normal (non-exception) provider behaviour is unchanged — no alert.
# ===========================================================================
def test_success_writes_no_alert(armed_supabase):
    @guardrail(provider="polygon", max_retries=2, backoff_base=0.01, fallback="FB")
    def fn():
        return "ok"

    assert fn() == "ok"
    armed_supabase.table.return_value.insert.assert_not_called()


# ===========================================================================
# 6. Targeted source-scan — fails if an unredacted str(last_exception) log /
#    alert site is reintroduced in the guardrail decorator.
# ===========================================================================
def _code_lines(src):
    """Source with comment lines / trailing comments stripped, so the scan
    inspects executable code — not the doc comments that legitimately mention
    ``apiKey=<secret>`` and ``str(exc)``."""
    out = []
    for line in src.splitlines():
        if line.lstrip().startswith("#"):
            continue
        out.append(line.split("#", 1)[0])
    return "\n".join(out)


def test_no_unredacted_exception_in_guardrail_source():
    import packages.quantum.services.provider_guardrails as m

    with open(m.__file__, "r", encoding="utf-8") as fh:
        code = _code_lines(fh.read())

    # The raw-exception interpolation shapes must not return.
    assert "{last_exception}" not in code, (
        "raw {last_exception} interpolated into a log/alert — reintroduced leak"
    )
    assert "str(last_exception)[:" not in code, (
        "raw str(last_exception)[:N] stored without redaction — reintroduced leak"
    )
    # The redaction helper and its sentinel/target must be present.
    assert "_redact_secrets" in code
    assert "[REDACTED]" in code
    assert "apiKey" in code.lower() or "api_key" in code
    # The vulnerable str(last_exception) may only appear wrapped in the redactor.
    for match in re.finditer(r"str\(last_exception\)", code):
        # find the enclosing logical line
        start = code.rfind("\n", 0, match.start()) + 1
        end = code.find("\n", match.end())
        line = code[start:end if end != -1 else None]
        assert "_redact_secrets" in line, (
            f"str(last_exception) not wrapped in _redact_secrets: {line!r}"
        )
