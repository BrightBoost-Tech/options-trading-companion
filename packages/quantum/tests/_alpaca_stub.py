"""Canonical ``alpaca`` provisioning for the test suite — the single source of
truth that ends the sys.modules stub-leak class (Lane D root fix).

BACKGROUND
----------
Historically ~70 test modules each did, at *import* (collection) time:

    import sys, types
    sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
    sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
    sys.modules.setdefault("alpaca.trading.requests",
                           types.ModuleType("alpaca.trading.requests"))

with **inconsistent** attribute coverage (some added
``GetPortfolioHistoryRequest``, most did not) and **no teardown**. Because
``dict.setdefault`` only writes when the key is *absent*, the FIRST test
module collected won the race and its (often bare) stub shadowed the real,
installed ``alpaca-py`` for the whole interpreter. A later victim doing a lazy
``from alpaca.trading.requests import GetPortfolioHistoryRequest`` then failed
or succeeded **purely on collection order** — green in default alphabetical
order, red under a different order or when a production module gained a new
module-level alpaca import (the PR #1362 red; the merged mitigation was a
function-local import as victim self-defense — a symptom patch, not this root
fix).

``alpaca-py`` is a DECLARED dependency (``packages/quantum/requirements.txt``:
``alpaca-py>=0.28.0``) and is installed in CI and locally. The correct fix is
therefore to make the REAL package authoritative before any test module runs,
and to fall back to a COMPLETE, consistent stub only when the package is
genuinely absent (a dev box without it). This module owns that decision.

USAGE
-----
* ``ensure_alpaca()`` — call at module import time (before importing production
  code that lazily imports alpaca) or, preferably, once from the suite conftest
  so collection order can never matter. Idempotent and thread-safe.
* ``alpaca_modules_isolated()`` — context manager that snapshots the exact
  ``alpaca*`` sys.modules entries and restores them on ANY exit (success,
  assertion failure, exception). Use it for a test that must *temporarily*
  swap the alpaca surface with a behavioural stub without leaking to later
  tests.
* ``real_alpaca_available()`` — whether the real package is importable on disk,
  independent of any stub currently occupying sys.modules.

This module deliberately provides NO autouse fixture: it must not mask a
legitimate production import-order bug. It only guarantees that the declared
third-party dependency is canonical.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.util
import sys
import threading
import types

# Sentinel stamped onto every module object THIS helper fabricates, so a stub
# is always distinguishable from the real package (which carries a real
# ``__spec__`` with a file origin instead).
_MARKER = "__otc_test_alpaca_stub__"

# Every alpaca submodule the repository imports anywhere (tests + production),
# so a stub fallback is COMPLETE regardless of which submodule a later import
# reaches for. Ordered parents-before-children so attribute wiring is valid.
_CANONICAL_SUBMODULES = (
    "alpaca",
    "alpaca.trading",
    "alpaca.trading.requests",
    "alpaca.trading.enums",
    "alpaca.trading.client",
    "alpaca.data",
    "alpaca.data.requests",
    "alpaca.data.timeframe",
    "alpaca.data.historical",
)

_lock = threading.RLock()


def _alpaca_keys() -> list[str]:
    return [k for k in sys.modules if k == "alpaca" or k.startswith("alpaca.")]


def _is_our_stub(mod: object) -> bool:
    return getattr(mod, _MARKER, False) is True


def _looks_like_stub(mod: object) -> bool:
    """A real alpaca module exposes a ``__spec__`` with a concrete file origin.
    A bare ``types.ModuleType("alpaca")`` shim (ours or a legacy per-file one)
    does not, so it is identifiable without importing anything."""
    if mod is None:
        return False
    if _is_our_stub(mod):
        return True
    spec = getattr(mod, "__spec__", None)
    return spec is None or getattr(spec, "origin", None) in (None, "namespace")


def _current_alpaca_is_stub() -> bool:
    root = sys.modules.get("alpaca")
    if root is None:
        return False
    return _looks_like_stub(root)


def _evict_alpaca() -> None:
    for name in _alpaca_keys():
        del sys.modules[name]


# ── complete stub fallback (only used when alpaca-py is genuinely absent) ──


class _StubModel:
    """kwargs-capturing placeholder for any alpaca request/model/enum symbol.

    Constructed positional args are retained on ``_args`` and every keyword is
    exposed as an attribute, so a no-alpaca environment behaves identically to
    the real pydantic models for the fields our tests read (e.g.
    ``GetPortfolioHistoryRequest(period="1W").period == "1W"``).
    """

    def __init__(self, *args, **kwargs):
        self._args = args
        self.__dict__.update(kwargs)


def _make_stub_getattr(modname: str):
    _cache: dict[str, type] = {}

    def __getattr__(attr: str):
        # Never fabricate dunders — let isinstance/pickle/inspect probes fail
        # naturally rather than receive a bogus class.
        if attr.startswith("__") and attr.endswith("__"):
            raise AttributeError(attr)
        cls = _cache.get(attr)
        if cls is None:
            cls = type(attr, (_StubModel,), {"__module__": modname})
            _cache[attr] = cls
        return cls

    return __getattr__


def _install_complete_stub() -> None:
    for name in _CANONICAL_SUBMODULES:
        mod = types.ModuleType(name)
        setattr(mod, _MARKER, True)
        # Make each node a package so ``import alpaca.x.y`` resolves even if a
        # submodule is not pre-listed; the pre-listed ones are already cached.
        mod.__path__ = []  # type: ignore[attr-defined]
        mod.__getattr__ = _make_stub_getattr(name)  # PEP 562
        sys.modules[name] = mod
    # Wire parent -> child attribute references (alpaca.trading, etc.).
    for name in _CANONICAL_SUBMODULES:
        if "." in name:
            parent, _, child = name.rpartition(".")
            setattr(sys.modules[parent], child, sys.modules[name])


def real_alpaca_available() -> bool:
    """Whether the REAL alpaca-py package is importable on disk, independent of
    any stub currently shadowing it in ``sys.modules``."""
    with _lock:
        saved: dict[str, object] = {}
        if _current_alpaca_is_stub():
            saved = {k: sys.modules.pop(k) for k in _alpaca_keys()}
        try:
            spec = importlib.util.find_spec("alpaca")
            return spec is not None and getattr(spec, "origin", None) not in (
                None,
                "namespace",
            )
        except (ImportError, ModuleNotFoundError, ValueError):
            return False
        finally:
            for k, v in saved.items():
                sys.modules.setdefault(k, v)


def ensure_alpaca() -> str:
    """Guarantee a canonical, COMPLETE ``alpaca`` package in ``sys.modules``.

    Returns ``"real"`` when the installed alpaca-py package is authoritative,
    or ``"stub"`` when it is genuinely absent and a complete stub was
    installed. Idempotent and thread-safe. Callers should invoke this BEFORE
    importing production code that imports alpaca (lazily or eagerly).
    """
    with _lock:
        root = sys.modules.get("alpaca")
        # Fast path: a real alpaca is already canonical.
        if root is not None and not _looks_like_stub(root):
            return "real"
        # A stub / bare shim is shadowing (or nothing is present). Drop any
        # shadow so the real package can bind fresh, then prefer the real one.
        if root is not None:
            _evict_alpaca()
        try:
            for name in _CANONICAL_SUBMODULES:
                importlib.import_module(name)
            return "real"
        except ImportError:
            # Real package genuinely unavailable — install the complete stub.
            _evict_alpaca()
            _install_complete_stub()
            return "stub"


@contextlib.contextmanager
def alpaca_modules_isolated():
    """Snapshot the exact ``alpaca*`` ``sys.modules`` entries, yield, then
    restore them on ANY exit — normal return, assertion failure, or exception.

    Any ``alpaca*`` key added inside the block is removed on exit and any key
    that existed before is restored to its exact prior object, so a test that
    needs a temporary behavioural alpaca stub cannot leak it to later tests.
    """
    saved = {k: sys.modules[k] for k in _alpaca_keys()}
    try:
        yield
    finally:
        for k in _alpaca_keys():
            if k not in saved:
                del sys.modules[k]
        for k, v in saved.items():
            sys.modules[k] = v
