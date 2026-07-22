"""Read-only Alpaca broker snapshot — the headless (MCP-absent) fallback.

WHY THIS EXISTS
---------------
The nightly audit runs as `claude -p` under Windows Task Scheduler. In that
headless session the Alpaca MCP server does NOT surface (documented reality —
see audit/v5-prompt.md STATE block and every recent report's run-limitation
header). The audit is therefore "broker-blind": it can read Supabase and
Railway but not broker truth (equity, OBP, positions, the broker clock).

This module produces a read-only broker snapshot BEFORE Claude starts and
drops it into the audit worktree, so the headless audit has a *secondary*
broker-truth source when the MCP is absent.

SAFETY CONTRACT (absolute)
--------------------------
- GET verbs ONLY. This module imports NO order-placing code (not the
  AlpacaClient class, whose `submit_option_order` / `cancel_order` /
  `close_position` methods live on the same object). It talks to Alpaca over
  raw HTTP GET so that no order method is even reachable in its call graph.
- Credentials are read from the environment and used ONLY as request headers.
  They are NEVER written to the snapshot, logged, or returned. A final assert
  fails loud if any credential substring appears in the serialized snapshot.
- CREDENTIAL SOURCE (F-RUNNER-BROKER-CREDS): the runner is launched by Windows
  Task Scheduler via audit/run-nightly.cmd — an unattended session whose process
  env carries NONE of the Alpaca creds (those live only in the Railway worker
  env). The interactive helpers scripts/win/load_env.{cmd,ps1} DO source creds
  from gitignored local ``.env`` files, but the scheduled task never runs them,
  so for two nights the snapshot was cred-less and broker-blind. This module now
  loads the SAME sanctioned local ``.env`` files itself (``load_local_broker_
  creds``), filling only MISSING creds and only the Alpaca allowlist. Those
  files are gitignored (``.gitignore``: ``.env`` / ``.env.*``, only
  ``.env.example`` tracked), so this code never places a secret in the repo, the
  logs, the manifest, or the snapshot. An operator may also point
  ``AUDIT_BROKER_CREDS_FILE`` at an explicit creds file (the VALUE is a path,
  never a secret).
- The account number is MASKED (last 4 only); the account UUID (`id`) is never
  requested. No account identifiers leave this module in the clear.
- Trust level is SECONDARY to the Alpaca MCP (recorded in the snapshot). It is
  a fallback for when MCP is absent, never an override of it.

FAILURE MODE (H9 — never fabricate)
-----------------------------------
On any failure (no creds, HTTP error, network error) the snapshot carries an
explicit `error` string and `available: false`. It never fabricates an equity
number or a flat book. The audit reads `available`/`error` and downgrades any
broker-dependent claim to a labeled hypothesis, exactly as it does today.
"""
from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# Alpaca REST bases. The account under audit is the LIVE margin account
# (211900084); ALPACA_PAPER=false selects it. Paper base is included only so a
# misconfigured env fails safe against the paper endpoint, never live orders
# (this module never places orders on either).
LIVE_BASE = "https://api.alpaca.markets"
PAPER_BASE = "https://paper-api.alpaca.markets"

# Fields copied verbatim from each broker object. Deliberately explicit
# allowlists — never spread the raw broker dict (it can carry identifiers).
_ACCOUNT_FIELDS = (
    "status",
    "equity",
    "last_equity",
    "cash",
    "buying_power",
    "options_buying_power",
    "options_trading_level",
    "options_approved_level",
    "pattern_day_trader",
)
_POSITION_FIELDS = (
    "symbol",
    "asset_class",
    "qty",
    "side",
    "market_value",
    "unrealized_pl",
    "cost_basis",
)
_ORDER_FIELDS = (
    "id",  # order UUID — not an account identifier
    "symbol",
    "status",
    "side",
    "qty",
    "order_type",
    "time_in_force",
    "submitted_at",
    "filled_at",
    "canceled_at",
)

HttpGet = Callable[[str, Dict[str, str], Optional[Dict[str, Any]]], "tuple[int, Any]"]


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _mask_account(num: Optional[str]) -> Optional[str]:
    """Mask an account number to '****NNNN' (last four only)."""
    if not num:
        return None
    s = str(num)
    if len(s) <= 4:
        return "*" * len(s)
    return ("*" * (len(s) - 4)) + s[-4:]


def _default_http_get(
    url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
) -> "tuple[int, Any]":
    """Default GET transport. Imported lazily so the module loads without
    `requests` present (CI/Linux, or a bare python) — a missing `requests`
    then surfaces as an explicit snapshot error, never an import crash."""
    import requests  # noqa: PLC0415 — intentional lazy import

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    body: Any = None
    if resp.content:
        try:
            body = resp.json()
        except ValueError:
            body = None
    return resp.status_code, body


# ---------------------------------------------------------------------------
# credential loading — the sanctioned LOCAL secret source
# ---------------------------------------------------------------------------
# Only these keys are ever read out of a local file — an allowlist, never a
# general dotenv import, so an unrelated secret in the file is never touched.
_CRED_KEYS = ("ALPACA_API_KEY", "ALPACA_SECRET_KEY", "ALPACA_PAPER")
_CRED_FILE_ALLOWLIST = frozenset(_CRED_KEYS)

# Sanctioned local env-file locations, relative to the operator repo root, in
# priority order (first file that supplies a given key wins). Mirrors
# scripts/win/load_env.cmd so the runner reads exactly what the operator's
# interactive shell already reads. All are gitignored — never committed.
_DEFAULT_ENV_FILE_RELPATHS = (
    ".env.local",
    ".env",
    os.path.join("packages", "quantum", ".env.local"),
    os.path.join("packages", "quantum", ".env"),
)

# Env var an operator may set to point at an explicit creds file (overrides the
# default search entirely). The VALUE is a path, never a secret.
CREDS_FILE_ENV_VAR = "AUDIT_BROKER_CREDS_FILE"


def _parse_cred_file(path: str) -> Dict[str, str]:
    """Parse KEY=VALUE lines from a dotenv-style file, returning ONLY the
    allowlisted Alpaca cred keys.

    NEVER raises (a missing/unreadable/malformed file → ``{}``) and NEVER logs a
    value. Comment (``#``) and blank lines are skipped, an optional ``export``
    prefix and surrounding quotes are stripped (matching load_env.{cmd,ps1}),
    and any line without ``=`` is ignored.
    """
    out: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if name not in _CRED_FILE_ALLOWLIST:
            continue
        value = value.strip().strip('"').strip("'")
        out.setdefault(name, value)  # first occurrence within a file wins
    return out


def load_local_broker_creds(
    env: Dict[str, str],
    repo_root: Optional[str] = None,
    files: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, str], Dict[str, Any]]:
    """Return ``(merged_env, status)``.

    Fills MISSING Alpaca creds into a COPY of ``env`` from the sanctioned local
    ``.env`` files (or from an explicit ``AUDIT_BROKER_CREDS_FILE`` path when that
    var is set in ``env``). Precedence: a cred already present (non-empty) in
    ``env`` is NEVER overridden — matching load_env's "only set if not already
    defined" semantics, so a real env cred always wins over a stale file.

    The returned ``status`` is a NO-SECRET provenance dict: key NAMES, file
    paths, and booleans only, NEVER a credential VALUE. It is safe to serialize
    into the snapshot / preflight manifest.

    Absence stays typed-unavailable, loudly: when no file supplies a missing cred
    the merged env simply lacks it, ``build_snapshot`` then returns
    ``available=false``, and this status records ``loaded_from=None`` +
    ``keys_injected=[]`` so a broker-blind run is diagnosable — it never
    fabricates a cred and never lets a load failure read as success.
    """
    merged = dict(env)
    override = (merged.get(CREDS_FILE_ENV_VAR) or "").strip()
    if files is not None:
        candidates = [str(f) for f in files]
    elif override:
        candidates = [override]
    elif repo_root:
        candidates = [str(Path(repo_root) / rel) for rel in _DEFAULT_ENV_FILE_RELPATHS]
    else:
        candidates = []

    files_checked: List[str] = []
    file_creds: Dict[str, str] = {}   # key -> value (first file wins)
    file_source: Dict[str, str] = {}  # key -> path that supplied it
    for path in candidates:
        files_checked.append(path)
        if not os.path.isfile(path):
            continue
        for k, v in _parse_cred_file(path).items():
            if v and k not in file_creds:
                file_creds[k] = v
                file_source[k] = path

    keys_injected: List[str] = []
    loaded_from: Optional[str] = None
    for k in _CRED_KEYS:
        cur = merged.get(k)
        if (cur is None or str(cur).strip() == "") and k in file_creds:
            merged[k] = file_creds[k]
            keys_injected.append(k)
            if loaded_from is None and k in ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"):
                loaded_from = file_source[k]

    status: Dict[str, Any] = {
        "mechanism": (
            "explicit AUDIT_BROKER_CREDS_FILE" if override
            else "sanctioned local .env files" if candidates
            else "none (no repo_root / no override)"
        ),
        "override_env_var_set": bool(override),
        "env_had_api_key": bool((env.get("ALPACA_API_KEY") or "").strip()),
        "env_had_secret_key": bool((env.get("ALPACA_SECRET_KEY") or "").strip()),
        "files_checked": files_checked,          # paths only, never secrets
        "keys_injected": sorted(keys_injected),  # NAMES only, never values
        "loaded_from": loaded_from,              # a path, never a secret
        "creds_present_after_load": bool(
            (merged.get("ALPACA_API_KEY") or "").strip()
            and (merged.get("ALPACA_SECRET_KEY") or "").strip()
        ),
        "note": (
            "Creds are used ONLY as headers for read-only GETs and are NEVER "
            "written to this snapshot. Provide them via a gitignored local .env "
            f"(repo root or packages/quantum/) or point {CREDS_FILE_ENV_VAR} at "
            "a file. Absent creds keep the snapshot available=false — "
            "broker-dependent audit claims must stay labeled unavailable."
        ),
    }
    return merged, status


def build_snapshot(
    env: Optional[Dict[str, str]] = None,
    http_get: Optional[HttpGet] = None,
    now_fn: Optional[Callable[[], datetime.datetime]] = None,
    base_url: Optional[str] = None,
    repo_root: Optional[str] = None,
    load_creds: bool = True,
) -> Dict[str, Any]:
    """Build the read-only broker snapshot dict. Never raises for broker/network
    failures — those become an explicit `error` + `available: false`.

    When ``load_creds`` is true (default) any MISSING Alpaca creds are filled
    from the sanctioned local ``.env`` files under ``repo_root`` (or an explicit
    ``AUDIT_BROKER_CREDS_FILE`` path in ``env``); an already-present env cred is
    never overridden. The no-secret provenance is recorded in
    ``snapshot['creds_source']``.
    """
    env = env if env is not None else dict(os.environ)
    http_get = http_get or _default_http_get
    now_fn = now_fn or _utcnow

    cred_status: Optional[Dict[str, Any]] = None
    if load_creds:
        env, cred_status = load_local_broker_creds(env, repo_root=repo_root)

    key = env.get("ALPACA_API_KEY", "") or ""
    secret = env.get("ALPACA_SECRET_KEY", "") or ""
    paper = str(env.get("ALPACA_PAPER", "false")).lower() in ("true", "1")
    base = base_url or (PAPER_BASE if paper else LIVE_BASE)

    snapshot: Dict[str, Any] = {
        "generated_at": now_fn().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": f"alpaca REST GET ({'paper' if paper else 'live'})",
        "base_url": base,
        "trust": (
            "SECONDARY to the Alpaca MCP. Read-only broker GET, used only when "
            "the MCP is absent (headless). Broker still outranks DB/Railway per "
            "doctrine; this is a static point-in-time capture, so verify against "
            "MCP if it is available."
        ),
        "available": False,
        "error": None,
        "creds_source": cred_status,  # NO-SECRET provenance (names + paths only)
        "account": None,
        "clock": None,
        "calendar": None,
        "positions": None,
        "orders": None,
    }

    if not key or not secret:
        snapshot["error"] = (
            "ALPACA_API_KEY / ALPACA_SECRET_KEY not set for the runner — broker "
            "snapshot unavailable (broker-blind for this run). Provide them via a "
            "gitignored local .env (repo root or packages/quantum/) or point "
            f"{CREDS_FILE_ENV_VAR} at a creds file; the runner reads it read-only "
            "for GET-only broker truth. Never commit the secret."
        )
        return snapshot

    headers = {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "accept": "application/json",
    }

    def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        code, body = http_get(base + path, headers, params)
        if code != 200:
            raise RuntimeError(f"GET {path} -> HTTP {code}")
        return body

    try:
        acct = _get("/v2/account") or {}
        snapshot["account"] = {
            "account_number": _mask_account(acct.get("account_number")),
            **{f: acct.get(f) for f in _ACCOUNT_FIELDS},
        }
        snapshot["clock"] = _get("/v2/clock")
        today = now_fn().strftime("%Y-%m-%d")
        snapshot["calendar"] = _get("/v2/calendar", {"start": today, "end": today})
        positions = _get("/v2/positions") or []
        snapshot["positions"] = [
            {f: p.get(f) for f in _POSITION_FIELDS} for p in positions
        ]
        orders = _get(
            "/v2/orders", {"status": "all", "limit": 50, "direction": "desc"}
        ) or []
        snapshot["orders"] = [{f: o.get(f) for f in _ORDER_FIELDS} for o in orders]
        snapshot["available"] = True
    except Exception as exc:  # noqa: BLE001 — deliberately broad; never crash the run
        snapshot["error"] = f"{type(exc).__name__}: {exc}"
        snapshot["available"] = False

    # Fail-loud credential scrub: no key/secret substring may appear anywhere in
    # the serialized snapshot. This guards against a future field addition that
    # accidentally echoes a header. The length guard (>= 8) avoids false
    # positives from pathologically short test creds matching common substrings
    # (real Alpaca keys/secrets are 20+ chars).
    blob = json.dumps(snapshot)
    if key and len(key) >= 8 and key in blob:
        raise AssertionError("API key leaked into broker snapshot — refusing to write")
    if secret and len(secret) >= 8 and secret in blob:
        raise AssertionError("API secret leaked into broker snapshot — refusing to write")
    return snapshot


def write_snapshot(path: str, **kwargs: Any) -> Dict[str, Any]:
    """Build and atomically write the snapshot JSON to `path`. Returns the dict."""
    snapshot = build_snapshot(**kwargs)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2, sort_keys=True)
    os.replace(tmp, path)
    return snapshot


if __name__ == "__main__":  # pragma: no cover - manual smoke
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "broker-snapshot.json"
    snap = write_snapshot(out)
    print(f"broker snapshot written to {out}: available={snap['available']} error={snap['error']}")
