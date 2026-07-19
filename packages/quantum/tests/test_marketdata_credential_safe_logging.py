"""Credential-safe market-data logging (v1.7 A9,
F-A9-MARKETDATA-CREDENTIAL-PREFIX-LOG).

Two confirmed leak sites on the market-data hot paths were fixed and are
pinned here against reintroduction. NO real credential value appears in this
module — every secret used is SYNTHETIC.

  1. ``market_data_truth_layer._fetch_alpaca_options_snapshots`` interpolated
     an 8-char prefix of the Alpaca key-ID into an INFO log that fires on
     every RTH scan/MTM/monitor. It must now emit only a constant, non-secret
     message.
  2. ``market_data.PolygonService.get_recent_quote_with_meta`` stored
     ``str(e)[:120]`` of a request exception into ``meta['msg_snippet']``
     unredacted. A requests exception can embed the request URL, whose query
     string carries ``apiKey=<secret>`` — it must be redacted BEFORE storage.

Each caplog/redaction test is written to FAIL against the pre-fix source and
PASS after. A targeted source-scan test fails if credential-slicing
(``key[:N]``) or an unredacted ``str(e)`` snippet is reintroduced at these
sites.
"""

import logging
import re

from unittest.mock import MagicMock

import pytest
import requests

from packages.quantum.market_data import PolygonService
from packages.quantum.services.market_data_truth_layer import (
    MarketDataTruthLayer,
)

# ---------------------------------------------------------------------------
# SYNTHETIC secrets only — never a real credential fragment.
# Chosen so their first-4 / first-8 slices are distinctive tokens that could
# not collide with any legitimate log content (symbols, statuses, counts).
# ---------------------------------------------------------------------------
SYNTH_ALPACA_KEY_ID = "ZZSYNTHKEYID0000AAAABBBBCCCCDDDD"      # 32 chars
SYNTH_ALPACA_SECRET = "ZZSYNTHSECRET9999WWWWXXXXYYYYZZZZ"     # 32 chars
SYNTH_POLYGON_KEY = "ZZSYNTHPOLYGONKEY12345678abcdef0"       # 32 chars

_OPT_SYMBOL = "O:AAPL260116C00150000"


def _key_slices(secret):
    """The substrings a leak would expose: first-4, first-8, and the whole
    value. If NONE of these appear in a log/field, no fragment leaked."""
    return (secret[:4], secret[:8], secret)


def _assert_no_secret(text, secret, where):
    for frag in _key_slices(secret):
        assert frag not in text, (
            f"synthetic secret fragment {frag!r} leaked in {where}"
        )


# ===========================================================================
# 1. Alpaca options-snapshot path — constant message, no key prefix logged.
# ===========================================================================
def _fake_alpaca_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {}
    resp.text = ""
    bare = _OPT_SYMBOL.removeprefix("O:")
    resp.json.return_value = {
        "snapshots": {
            bare: {
                "latestQuote": {"bp": 1.00, "ap": 1.20},
                "latestTrade": {"p": 1.10},
            }
        }
    }
    return resp


def test_alpaca_snapshot_never_logs_key_prefix(monkeypatch, caplog):
    monkeypatch.setenv("ALPACA_API_KEY", SYNTH_ALPACA_KEY_ID)
    monkeypatch.setenv("ALPACA_SECRET_KEY", SYNTH_ALPACA_SECRET)

    layer = MarketDataTruthLayer(api_key="synthetic-md-key")
    layer.session = MagicMock()
    layer.session.get.return_value = _fake_alpaca_response()

    with caplog.at_level(logging.DEBUG):
        results = layer._fetch_alpaca_options_snapshots([_OPT_SYMBOL])

    # The injected snapshot must have been reached (non-vacuous log check).
    assert layer.session.get.call_count == 1

    # No emitted log record may contain ANY fragment of either credential.
    for record in caplog.records:
        msg = record.getMessage()
        _assert_no_secret(msg, SYNTH_ALPACA_KEY_ID, f"log {record.name!r}")
        _assert_no_secret(msg, SYNTH_ALPACA_SECRET, f"log {record.name!r}")

    # Regression: the constant, non-secret "credentials configured" message
    # still fires on the credentials-present branch.
    all_logs = " | ".join(r.getMessage() for r in caplog.records)
    assert "Alpaca option-data credentials configured" in all_logs
    # Regression: pricing still works — the snapshot was parsed.
    assert _OPT_SYMBOL in results
    assert results[_OPT_SYMBOL]["quote"]["mid"] == pytest.approx(1.10)


# ===========================================================================
# 2. Polygon exception-snippet redaction.
# ===========================================================================
def _polygon_service():
    svc = PolygonService(api_key=SYNTH_POLYGON_KEY)
    svc.session = MagicMock()
    return svc


def test_polygon_exception_redacts_raw_configured_key(caplog):
    """str(e) that embeds the configured api_key verbatim (the requests
    exception shape, apiKey within the 120-char snippet window) is redacted
    before it reaches meta/logs.

    Pre-fix (``meta['msg_snippet'] = str(e)[:120]``) this snippet contained
    the synthetic key verbatim → ``_assert_no_secret`` FAILS; post-fix it is
    redacted → PASSES.
    """
    svc = _polygon_service()
    # apiKey lands well within the first 120 chars — the regression window.
    leaky = (
        "ConnectionError to https://api.polygon.io/v2/last/nbbo/SPY?"
        f"apiKey={SYNTH_POLYGON_KEY} (Max retries exceeded)"
    )
    assert leaky.index(SYNTH_POLYGON_KEY) < 120  # guard: within the leak window
    svc.session.get.side_effect = requests.exceptions.ConnectionError(leaky)

    with caplog.at_level(logging.DEBUG):
        quote, meta = svc.get_recent_quote_with_meta(_OPT_SYMBOL)

    assert meta["error_type"] == "exception"
    snippet = meta["msg_snippet"]
    _assert_no_secret(snippet, SYNTH_POLYGON_KEY, "meta['msg_snippet']")
    assert "[REDACTED]" in snippet
    # Empty quote on failure — pricing behaviour unchanged.
    assert quote["price"] is None
    for record in caplog.records:
        _assert_no_secret(record.getMessage(), SYNTH_POLYGON_KEY, "log")


def test_polygon_verbose_exception_never_leaks_even_beyond_window(caplog):
    """Defence-in-depth: even the verbose requests ConnectionError shape
    (apiKey near the END of a long message) must never leak — redaction runs
    BEFORE truncation, so the stored snippet cannot contain the secret."""
    svc = _polygon_service()
    leaky = (
        "HTTPSConnectionPool(host='api.polygon.io', port=443): Max retries "
        f"exceeded with url: /v3/quotes/{_OPT_SYMBOL}?limit=1&order=desc&"
        f"sort=timestamp&apiKey={SYNTH_POLYGON_KEY} (Caused by ...)"
    )
    svc.session.get.side_effect = requests.exceptions.ConnectionError(leaky)

    _, meta = svc.get_recent_quote_with_meta(_OPT_SYMBOL)

    _assert_no_secret(meta["msg_snippet"], SYNTH_POLYGON_KEY, "meta['msg_snippet']")


def test_polygon_exception_redacts_apikey_query_param_when_not_verbatim(caplog):
    """Defence-in-depth: even when the key in the URL is NOT byte-identical to
    self.api_key (e.g. URL-encoded), the ``apiKey=<value>`` query param is
    stripped by the regex redaction."""
    svc = _polygon_service()
    # A DIFFERENT secret-shaped value in the query string (simulates
    # URL-encoding / a rotated in-flight value) — the ``.replace`` on
    # self.api_key would NOT catch this; only the apiKey= regex does.
    other_secret = "ZZOTHERSECRET%2Bvalue%2Fabc123XYZ"
    leaky = (
        "HTTPSConnectionPool(host='api.polygon.io', port=443): Max retries "
        f"exceeded with url: /v2/last/nbbo/SPY?apiKey={other_secret} (Caused)"
    )
    svc.session.get.side_effect = requests.exceptions.ConnectionError(leaky)

    _, meta = svc.get_recent_quote_with_meta("SPY")

    snippet = meta["msg_snippet"]
    assert other_secret not in snippet
    assert "apiKey=[REDACTED]" in snippet


# ===========================================================================
# 3. Targeted source-scan — fails if credential-slicing or an unredacted
#    exception snippet is reintroduced at these market-data logging sites.
# ===========================================================================
# Matches ``<var-containing-key/secret/token/apikey>[:N]`` — the prefix-slice
# leak shape (whitespace-tolerant).
_KEY_SLICE_RE = re.compile(
    r"(?:key|secret|token|apikey|api_key)\w*\s*\[\s*[-:]?\s*\d+\s*[:]?\s*\]",
    re.IGNORECASE,
)
# The exact pre-fix vulnerable Polygon line.
_UNREDACTED_SNIPPET = 'meta["msg_snippet"] = str(e)[:120]'


def _module_source(module):
    with open(module.__file__, "r", encoding="utf-8") as fh:
        return fh.read()


def _code_lines(src):
    """Source lines with trailing/standalone comments stripped, so the scan
    inspects executable code and not the doc comments that describe the leak
    (which legitimately mention ``apiKey=<secret>`` and ``key_id``)."""
    out = []
    for line in src.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        code = line.split("#", 1)[0]
        out.append(code)
    return "\n".join(out)


def test_no_credential_slicing_in_truth_layer_logging():
    import packages.quantum.services.market_data_truth_layer as m

    code = _code_lines(_module_source(m))
    hits = _KEY_SLICE_RE.findall(code)
    assert not hits, f"credential-slice pattern reintroduced: {hits}"
    # The specific pre-fix key-ID interpolation must not return.
    assert "key_id={" not in code
    assert "alpaca_key[:" not in code
    assert "alpaca_secret[:" not in code


def test_no_unredacted_exception_snippet_in_market_data():
    import packages.quantum.market_data as m

    code = _code_lines(_module_source(m))
    hits = _KEY_SLICE_RE.findall(code)
    assert not hits, f"credential-slice pattern reintroduced: {hits}"
    # The exact pre-fix unredacted-snippet line must not return.
    assert _UNREDACTED_SNIPPET not in code
    # The exception handler must carry a redaction sentinel.
    assert "[REDACTED]" in code
    assert "apiKey=" in code  # the regex-redaction target is present
