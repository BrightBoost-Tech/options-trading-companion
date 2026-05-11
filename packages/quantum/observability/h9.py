"""H9 wrapper-drift exemption decorator.

The Slot 1 AST gate (``test_h9_wrapper_drift_gate.py``) flags functions
that look like side-effect wrappers but lack verification calls in their
body. This module provides the inline escape hatch.

For functions that LEGITIMATELY look like wrappers but don't fit the H9
convention (pure reads, fire-and-forget, side-effect-IS-return-value),
decorate with ``@h9_exempt(reason=...)`` and the gate skips them.

The YAML allow-list at ``packages/quantum/tests/h9_allow_list.yml`` is
the alternative escape hatch — use the YAML for legacy code being
migrated; use the decorator when the exemption is intrinsic to the
function's design.

See ``docs/loud_error_doctrine.md`` H9 section for the convention.
"""

from functools import wraps
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable[..., object])

_MIN_REASON_LEN = 10


def h9_exempt(reason: str) -> Callable[[F], F]:
    """Mark a function as exempt from H9 wrapper-drift AST gate checks.

    The reason must be specific enough to survive code review (no
    ``"TODO"`` or ``""``). Reviewer should challenge any new
    ``@h9_exempt`` addition; the exemption list should shrink over
    time, not grow.

    The decorator is a no-op at runtime — it just stamps a string
    attribute that the AST gate reads at CI time.

    Parameters
    ----------
    reason
        Concrete explanation of why this function doesn't need H9
        verification. Must be ≥10 characters.

    Examples
    --------
    >>> @h9_exempt(reason="pure read; no side effects")
    ... def get_account_summary(user_id):
    ...     return {"status": "ok", "data": ...}
    """
    if not isinstance(reason, str) or len(reason.strip()) < _MIN_REASON_LEN:
        raise ValueError(
            f"@h9_exempt requires a specific reason string of at least "
            f"{_MIN_REASON_LEN} characters; got: {reason!r}. The "
            f"decorator survives code review only if the rationale is "
            f"specific."
        )

    def decorator(func: F) -> F:
        # The AST gate detects this attribute via static inspection,
        # not via runtime introspection — so the assignment IS the
        # contract. ``wraps`` is for stack-trace cleanliness.
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            return func(*args, **kwargs)

        wrapper.__h9_exempt__ = reason  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator
