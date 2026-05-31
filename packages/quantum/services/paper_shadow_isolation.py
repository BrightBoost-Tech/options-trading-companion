"""Paper-shadow executor — ISOLATION FOUNDATION (Phase 1a).

This module is the safety-critical isolation core that a future paper-shadow
EXECUTOR (Phase 1b) will ride on. It contains NO executor logic, opens NO
positions, and places NO orders. It provides exactly three things:

1. The ``paper_shadow`` routing_mode tag (canonical constant) — set ONLY by
   the future executor on its own dedicated PAPER-account portfolio. The 3
   live management jobs exclude this tag (additive, no-op when off),
   EXTENDING the existing ``shadow_only`` exclusion precedent (not a parallel
   mechanism — H13).
2. A dedicated PAPER broker client builder — constructs an
   ``AlpacaClient(paper=True, …)`` from DEDICATED paper credentials in a
   separate env var, NEVER the global ``get_alpaca_client()`` (which reads the
   worker's LIVE env). FAILS CLOSED if the paper creds are absent.
3. The PA3I8CYLXBOS account guard — confirms an order route targets the paper
   account before any submission, and aborts otherwise.

Account-isolation invariant (Direction 1): an executor order can only ever
reach the paper account, because (a) the client is built with ``paper=True``
against the paper endpoint, (b) a live key against the paper endpoint fails
auth (fail-safe, not a live order), (c) the dedicated paper creds are distinct
from the live keys, and (d) the guard aborts unless the broker reports
account_number == PA3I8CYLXBOS.

Flag: ``PAPER_SHADOW_EXECUTOR_ENABLED`` (default OFF). In Phase 1a nothing
runs regardless; the flag is the gate Phase 1b/2 hang off.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid importing the broker module at load time
    from packages.quantum.brokers.alpaca_client import AlpacaClient
    from packages.quantum.brokers.execution_router import ExecutionRouter


# ── Canonical isolation tag ───────────────────────────────────────────────
# The routing_mode value carried by the paper-shadow executor's dedicated
# PAPER portfolio. The 3 live jobs exclude portfolios with this value. The
# string is also inlined at each live-job filter site (mirroring how
# "shadow_only" is inlined there); this constant is the documented canonical
# definition and the value the executor (Phase 1b) and tests reference.
PAPER_SHADOW_ROUTING_MODE = "paper_shadow"

# The ONLY Alpaca account the executor may ever touch. Belt-and-suspenders to
# the paper=True client construction.
PAPER_ACCOUNT_NUMBER = "PA3I8CYLXBOS"

# Dedicated PAPER credentials — SEPARATE from the worker's live
# ALPACA_API_KEY / ALPACA_SECRET_KEY. Phase-1b prerequisite; Phase 1a fails
# closed without them (and its tests use mocks, so 1a is validatable now).
PAPER_API_KEY_ENV = "ALPACA_PAPER_API_KEY"
PAPER_SECRET_KEY_ENV = "ALPACA_PAPER_SECRET_KEY"

# Feature flag — default OFF.
FLAG_ENV = "PAPER_SHADOW_EXECUTOR_ENABLED"


class PaperShadowConfigError(RuntimeError):
    """Raised when the dedicated paper credentials are absent — the executor
    cannot construct a client and FAILS CLOSED (never falls back to the live
    client)."""


class PaperShadowAccountMismatch(RuntimeError):
    """Raised by the account guard when the broker reports any account other
    than PA3I8CYLXBOS — the executor aborts before placing any order."""


def is_enabled() -> bool:
    """True only when PAPER_SHADOW_EXECUTOR_ENABLED is explicitly truthy.
    Default OFF. Nothing in Phase 1a runs regardless of this flag."""
    return os.environ.get(FLAG_ENV, "0").strip().lower() in ("1", "true", "yes", "on")


def build_paper_client() -> "AlpacaClient":
    """Construct a DEDICATED paper ``AlpacaClient`` from the dedicated paper
    credentials. FAILS CLOSED (raises ``PaperShadowConfigError``) if either
    credential env var is absent — the executor must never fall back to the
    global ``get_alpaca_client()`` (live env).

    The client is built with ``paper=True`` and the dedicated paper key pair,
    so it can only authenticate against the paper endpoint.
    """
    api_key = os.environ.get(PAPER_API_KEY_ENV)
    secret_key = os.environ.get(PAPER_SECRET_KEY_ENV)
    if not api_key or not secret_key:
        raise PaperShadowConfigError(
            f"Paper-shadow executor requires dedicated paper credentials in "
            f"{PAPER_API_KEY_ENV} / {PAPER_SECRET_KEY_ENV}. They are absent — "
            f"failing closed (the executor never falls back to the live client)."
        )
    # Imported here (not at module load) so importing this module is cheap and
    # cycle-free for the live job handlers that reference only the constant.
    from packages.quantum.brokers.alpaca_client import AlpacaClient

    return AlpacaClient(api_key=api_key, secret_key=secret_key, paper=True)


def assert_paper_account(client: "AlpacaClient") -> str:
    """Pre-order account guard. Confirms the broker reports account_number ==
    PA3I8CYLXBOS; raises ``PaperShadowAccountMismatch`` otherwise (the caller
    aborts WITHOUT placing an order). Returns the confirmed account number.

    Uses ``get_account_number()`` (the human-readable account number, e.g.
    'PA3I8CYLXBOS' paper vs '211900084' live) — distinct from
    ``get_account()['account_id']`` (the UUID).
    """
    account_number = client.get_account_number()
    if account_number != PAPER_ACCOUNT_NUMBER:
        raise PaperShadowAccountMismatch(
            f"Paper-shadow account guard: broker reports account_number="
            f"{account_number!r}, expected {PAPER_ACCOUNT_NUMBER!r}. Aborting — "
            f"NO order placed. (An executor order must only ever reach the "
            f"paper account.)"
        )
    return account_number


def build_guarded_paper_router(supabase=None) -> "ExecutionRouter":
    """Build an ``ExecutionRouter`` wired to the DEDICATED paper client, with
    the account guard already verified. This is the single entry point a future
    executor (Phase 1b) uses to obtain an order route — one that can ONLY
    target the paper account.

    Construction order is the safety order:
      1. build_paper_client() — fails closed without dedicated paper creds.
      2. assert_paper_account() — aborts unless the broker is PA3I8CYLXBOS.
      3. ExecutionRouter(alpaca_client=<paper client>) — injects the paper
         client so the router's ``alpaca`` property NEVER falls back to the
         global live ``get_alpaca_client()``.
    """
    client = build_paper_client()
    assert_paper_account(client)
    from packages.quantum.brokers.execution_router import ExecutionRouter

    return ExecutionRouter(supabase=supabase, alpaca_client=client)
