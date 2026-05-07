"""Feature flags shared across services.

Per-call env reads (not module-level constants) so flips take effect
without a process restart and tests can monkey-patch.
"""

import os


def is_iv_rank_none_routing_enabled() -> bool:
    """#115 PR-B routing flag.

    When OFF (default), iv_rank fallbacks at consumer sites use the
    pre-existing silent ``or 50.0`` shape — preserves all behavior in
    place at the time PR-A shipped. When ON, consumers route None
    iv_rank values through explicit semantics:

    - Scanner flags candidates with ``iv_rank_quality="missing"`` and
      ranks them below clean candidates (`options_scanner.py`).
    - Regime engine routes None through a no-IV-signal classification
      path that uses realized vol instead of fabricating a 50.0
      percentile (`analytics/regime_engine_v3.py`).

    Flip via the ``IV_RANK_NONE_ROUTING_ENABLED`` env var. Operator
    pre-flip checklist lives in ``docs/backlog.md`` #115 entry.
    """
    return os.getenv("IV_RANK_NONE_ROUTING_ENABLED", "0").lower() in (
        "1", "true", "yes",
    )
