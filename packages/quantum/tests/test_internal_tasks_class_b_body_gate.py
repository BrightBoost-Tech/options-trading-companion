"""Class-prevention test for Class B (silent body-drop on CLI-exposed
internal endpoints).

**The class:** when an internal_tasks endpoint is exposed via the CLI
(scripts/run_signed_task.py TASKS catalog) AND calls
``enqueue_job_run``, its FastAPI signature MUST accept a request body.
Otherwise the CLI's ``payload={"force_rerun": true}`` is silently
dropped at the signature boundary; the kwarg never reaches
``enqueue_job_run``; idempotency-key collision blocks dispatch when
a same-day terminal-state row exists.

**Scope decision (Option A — CLI-catalog intersection):**

The first design pass tried "all enqueue_job_run callers must accept
Body" but produced 5 false positives (intraday_risk_monitor,
day_orchestrator, promotion_check, heartbeat, phase2_precheck) —
all scheduler-only endpoints not exposed via CLI. They aren't subject
to the bug class because nothing external sends them a body.

Option A scopes enforcement to the CROSS of two sets:
- Endpoint URL appears in ``scripts/run_signed_task.py`` ``TASKS``
  catalog (i.e., something can plausibly POST to it with a body)
- Function body calls ``enqueue_job_run`` (i.e., the dispatch
  bug class is operative)

This precisely matches the threat model. Scheduler-only enqueue
callers are auto-exempt; CLI-exposed enqueue callers are gated.
Adding a new CLI-exposed endpoint that calls enqueue → automatically
subject to the gate without code change here, because the catalog
intersection is recomputed each run.

**History:**
- PR #905: original Class B fix (iv_daily_refresh +
  daily_progression_eval body-drop)
- PR #909 (#71 Tier 1): extended fix to 3 more CLI-exposed endpoints
- PR #913 (#71 Tier 3): grep gate for Class A (legacy enqueue imports)
- PR #916: H9 doctrine codified Class B candidate
- THIS PR: AST gate for Class B
"""

import ast
import unittest
from pathlib import Path
from typing import Optional, Set


# Path resolution: this file lives at packages/quantum/tests/, and we
# need both packages/quantum/internal_tasks.py and scripts/run_signed_task.py.
_TESTS_DIR = Path(__file__).resolve().parent
_QUANTUM_ROOT = _TESTS_DIR.parent           # packages/quantum/
_REPO_ROOT = _QUANTUM_ROOT.parent.parent    # repo root

INTERNAL_TASKS_PATH = _QUANTUM_ROOT / "internal_tasks.py"
CLI_SCRIPT_PATH = _REPO_ROOT / "scripts" / "run_signed_task.py"

# Variable name in scripts/run_signed_task.py
TASKS_CATALOG_VARIABLE = "TASKS"

# Function whose presence in an endpoint body marks it as enqueue-calling.
ENQUEUE_FUNCTION_NAME = "enqueue_job_run"

# Annotations that are NOT Body parameters — auxiliary FastAPI types.
_NON_BODY_ANNOTATIONS = frozenset({
    "Request", "BackgroundTasks", "Response", "WebSocket",
})

# Annotations that are primitives — those would be query/path params,
# not body. (Bodies typed as primitives are atypical; if seen, treat as
# non-body to avoid false positives.)
_PRIMITIVE_ANNOTATIONS = frozenset({
    "str", "int", "bool", "float", "bytes",
})


# ─────────────────────────────────────────────────────────────────────
# Step 1: Parse the CLI catalog to learn which URL paths are exposed.
# ─────────────────────────────────────────────────────────────────────


def _extract_cli_url_paths() -> Set[str]:
    """Parse scripts/run_signed_task.py and return the set of URL paths
    in the TASKS catalog.

    Catalog shape (verified at write time):

        TASKS = {
            "task_name": {
                "path": "/some/url",
                "scope": ...,
                ...
            },
            ...
        }

    Single top-level Assign; outer dict literal with string keys; values
    are dict literals containing a "path" key with a string-literal
    value. If this shape changes, this function needs an update.
    """
    source = CLI_SCRIPT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    paths: Set[str] = set()

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == TASKS_CATALOG_VARIABLE
            for t in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            continue

        for entry_value in node.value.values:
            if not isinstance(entry_value, ast.Dict):
                continue
            for k, v in zip(entry_value.keys, entry_value.values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "path"
                    and isinstance(v, ast.Constant)
                    and isinstance(v.value, str)
                ):
                    paths.add(v.value)

    return paths


# ─────────────────────────────────────────────────────────────────────
# Step 2: Parse internal_tasks.py for endpoints + their classification.
# ─────────────────────────────────────────────────────────────────────


def _extract_router_prefix(tree: ast.Module) -> str:
    """Return the prefix passed to APIRouter(prefix=...) at module top
    level. Empty string if no prefix is set."""
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "router"
            for t in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                if isinstance(kw.value.value, str):
                    return kw.value.value
    return ""


def _decorator_post_path(decorator: ast.expr) -> Optional[str]:
    """If decorator is @router.post('/path', ...), return '/path'. Else None."""
    if not isinstance(decorator, ast.Call):
        return None
    func = decorator.func
    if not isinstance(func, ast.Attribute):
        return None
    if not isinstance(func.value, ast.Name):
        return None
    if func.value.id != "router" or func.attr != "post":
        return None
    if not decorator.args:
        return None
    first_arg = decorator.args[0]
    if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
        return first_arg.value
    return None


def _function_calls_enqueue(func_node: ast.AST) -> bool:
    """Walk function body for any Call to ``enqueue_job_run``."""
    for node in ast.walk(func_node):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        if isinstance(called, ast.Name) and called.id == ENQUEUE_FUNCTION_NAME:
            return True
        if isinstance(called, ast.Attribute) and called.attr == ENQUEUE_FUNCTION_NAME:
            return True
    return False


def _annotation_name(node: Optional[ast.expr]) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Subscript):
        return _annotation_name(node.value)
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _arg_accepts_body(arg: ast.arg, default: Optional[ast.expr]) -> bool:
    """Heuristic: does this arg shape accept a request body?

    Errs toward false-positive tolerance — ambiguous shapes count as
    Body-accepting. Better to miss a regression than block legit code;
    code review catches the rest.

    Acceptable shapes:
    - Default is ``Body(...)`` call (explicit FastAPI Body declaration)
    - Annotation is ``dict`` / ``Dict[...]`` / ``Optional[Dict[...]]``
    - Annotation is a custom uppercase-named class (likely a Pydantic
      model FastAPI auto-treats as body)

    Unacceptable shapes:
    - Annotation in NON_BODY_ANNOTATIONS (Request, BackgroundTasks, ...)
    - Annotation is a primitive (str, int, bool, ...) — those are
      query/path params, not body
    - Default is ``Depends(...)`` (auth dep, not body)
    """
    if isinstance(default, ast.Call):
        if isinstance(default.func, ast.Name) and default.func.id == "Body":
            return True
        # Depends(), Query(), Path(), Header(), Cookie() — explicitly NOT body
        if isinstance(default.func, ast.Name) and default.func.id in {
            "Depends", "Query", "Path", "Header", "Cookie", "Form", "File",
        }:
            return False

    name = _annotation_name(arg.annotation)
    if not name:
        return False

    if name in _NON_BODY_ANNOTATIONS:
        return False

    if name in {"dict", "Dict"}:
        return True

    if name in {"Optional", "Union"} and isinstance(arg.annotation, ast.Subscript):
        # Look inside the subscript for the actual type.
        # ast.Subscript.slice is the inner expression in Python 3.9+.
        inner = arg.annotation.slice
        # For Optional[X], slice is X. For Union[X, Y], slice is a Tuple.
        if isinstance(inner, ast.Tuple):
            inner_names = [_annotation_name(elt) for elt in inner.elts]
        else:
            inner_names = [_annotation_name(inner)]
        for inner_name in inner_names:
            if inner_name in {"dict", "Dict"}:
                return True
            if inner_name in _NON_BODY_ANNOTATIONS:
                continue
            if (
                inner_name
                and inner_name not in _PRIMITIVE_ANNOTATIONS
                and inner_name[0].isupper()
            ):
                return True
        return False

    if name in _PRIMITIVE_ANNOTATIONS:
        return False

    # Custom uppercase class name — likely Pydantic model.
    if name and name[0].isupper():
        return True

    return False


def _function_accepts_body(func_node: ast.AST) -> bool:
    """Check if any parameter in the signature accepts a Body."""
    if not isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False

    args = func_node.args
    n_args = len(args.args)
    n_defaults = len(args.defaults)
    arg_defaults: list = [None] * (n_args - n_defaults) + list(args.defaults)

    for arg, default in zip(args.args, arg_defaults):
        if _arg_accepts_body(arg, default):
            return True

    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if _arg_accepts_body(arg, default):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


class TestExtractionSanity(unittest.TestCase):
    """Verify the CLI-catalog and internal_tasks parsing both produce
    non-empty, sensible inputs. Catches the case where one of the
    upstream files is restructured in a way that silently breaks
    extraction (which would otherwise produce a false-passing test
    with empty input)."""

    def test_cli_catalog_extracts_known_paths(self):
        paths = _extract_cli_url_paths()
        self.assertGreater(
            len(paths), 0,
            "Sanity check failed: extracted ZERO URL paths from CLI "
            "TASKS catalog. scripts/run_signed_task.py structure may "
            "have changed (refactor _extract_cli_url_paths) OR the "
            "catalog itself is empty.",
        )
        # All 5 known CLI-exposed internal endpoints must appear.
        # If any is missing, either the CLI was refactored OR the
        # extraction is buggy.
        for required in (
            "/internal/tasks/iv/daily-refresh",
            "/internal/tasks/progression/daily-eval",
            "/internal/tasks/alpaca/order-sync",
            "/internal/tasks/calibration/update",
            "/internal/tasks/autotune/walk-forward",
        ):
            self.assertIn(
                required, paths,
                f"Expected CLI catalog to contain {required!r}; "
                f"either CLI was restructured or extraction is buggy.",
            )

    def test_internal_tasks_router_prefix_present(self):
        """Internal router must be mounted under /internal/tasks for
        the CLI-catalog match to work."""
        tree = ast.parse(INTERNAL_TASKS_PATH.read_text(encoding="utf-8"))
        prefix = _extract_router_prefix(tree)
        self.assertEqual(
            prefix, "/internal/tasks",
            f"Expected internal_tasks router to mount at "
            f"'/internal/tasks'; got {prefix!r}. URL-path matching "
            f"in test_cli_exposed_endpoints_accept_body assumes this "
            f"prefix.",
        )


class TestClassBPreventionGate(unittest.TestCase):
    """The actual class-prevention gate. Asserts every CLI-exposed
    enqueue-calling endpoint accepts a Body parameter."""

    def test_cli_exposed_endpoints_accept_body(self):
        cli_paths = _extract_cli_url_paths()
        source = INTERNAL_TASKS_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        prefix = _extract_router_prefix(tree)

        violations: list = []
        gated_count = 0  # for sanity reporting

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            # Find the @router.post decorator path
            relative_path: Optional[str] = None
            for decorator in node.decorator_list:
                p = _decorator_post_path(decorator)
                if p is not None:
                    relative_path = p
                    break
            if relative_path is None:
                continue

            full_path = prefix + relative_path

            # Tolerance gate 1: only enforce on enqueue-calling endpoints.
            if not _function_calls_enqueue(node):
                continue

            # Tolerance gate 2: only enforce on CLI-exposed endpoints.
            if full_path not in cli_paths:
                continue

            gated_count += 1

            if not _function_accepts_body(node):
                violations.append(
                    f"  {node.name}() at line {node.lineno} "
                    f"(URL: {full_path})"
                )

        # Sanity: the gate must enforce on AT LEAST the 5 known
        # CLI-exposed endpoints. A gate that enforces on zero endpoints
        # would silently pass even a regression.
        self.assertGreaterEqual(
            gated_count, 5,
            f"Sanity check failed: gate enforced on {gated_count} "
            f"endpoint(s); expected at least 5 (the PR #905 + #909 "
            f"fixed endpoints). Either the matching logic is broken "
            f"OR endpoints have been deleted unexpectedly.",
        )

        if violations:
            self.fail(
                f"{len(violations)} CLI-exposed endpoint(s) in "
                f"internal_tasks.py call enqueue_job_run but don't "
                f"accept a Body parameter:\n"
                + "\n".join(violations)
                + "\n\nClass B bug shape: CLI sends `force_rerun` in "
                "the request body (via `--force-rerun` / `--force` "
                "flags in scripts/run_signed_task.py:770-775); FastAPI "
                "silently drops it because the signature lacks a body "
                "parameter; `enqueue_job_run` doesn't receive it; "
                "idempotency-key collision blocks dispatch when a "
                "same-day terminal-state row exists.\n\n"
                "Canonical fix (PR #905, #909):\n"
                "    body: Optional[Dict] = Body(default=None),\n"
                "    ...\n"
                "    force_rerun = bool((body or {}).get(\"force_rerun\", False))\n"
                "    return enqueue_job_run(\n"
                "        ...,\n"
                "        force_rerun=force_rerun,\n"
                "    )\n\n"
                "Doctrine: H9 in docs/loud_error_doctrine.md.\n"
                "Scheduler-only endpoints (heartbeat, phase2-precheck, "
                "intraday-monitor, day-orchestrator, promotion-check) "
                "are auto-exempt via the CLI-catalog intersection — "
                "they aren't subject to this bug class."
            )


if __name__ == "__main__":
    unittest.main()
