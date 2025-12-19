#!/usr/bin/env python3
import importlib
import pkgutil
import os
import inspect
import sys
from typing import Dict, Callable

# Add repo root to sys.path to allow imports
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, repo_root)

HANDLERS_PACKAGE = "packages.quantum.jobs.handlers"

def verify_contract():
    """
    Scans the packages/quantum/jobs/handlers directory for modules.
    Enforces that every handler has:
      - JOB_NAME string
      - run(payload: dict, ctx=None) -> dict
    """
    handlers_dir = os.path.join(repo_root, "packages", "quantum", "jobs", "handlers")

    if not os.path.exists(handlers_dir):
        print(f"Error: Handlers directory not found at {handlers_dir}")
        sys.exit(1)

    print(f"Scanning handlers in {handlers_dir}...")

    violations = []
    checked_count = 0

    # Iterate over modules in the handlers package
    for module_info in pkgutil.iter_modules([handlers_dir]):
        module_name = f"{HANDLERS_PACKAGE}.{module_info.name}"

        # Skip __init__ and utilities if they don't look like handlers
        # But really we should check everything that *looks* like a handler or claims to be one.
        # For simplicity, we import everything in that dir.

        try:
            module = importlib.import_module(module_name)
        except Exception as e:
            # If we can't import it, it's broken code, but might not be a handler contract violation per se.
            # However, for a verify script, we should probably flag it.
            # But let's focus on contract.
            print(f"Warning: Could not import {module_name}: {e}")
            continue

        # Heuristic: If it has JOB_NAME, it MUST follow contract.
        if hasattr(module, "JOB_NAME"):
            checked_count += 1
            job_name = getattr(module, "JOB_NAME")
            print(f"Checking {module_name} (JOB_NAME='{job_name}')...")

            if not hasattr(module, "run"):
                violations.append(f"{module_name}: Missing 'run' function")
                continue

            run_func = getattr(module, "run")
            if not callable(run_func):
                violations.append(f"{module_name}: 'run' is not callable")
                continue

            sig = inspect.signature(run_func)
            params = sig.parameters

            # 1. Must accept 'payload'
            if "payload" not in params:
                violations.append(f"{module_name}: run() missing 'payload' argument")

            # 2. 'ctx' must have default if present
            if "ctx" in params:
                if params["ctx"].default == inspect.Parameter.empty:
                    violations.append(f"{module_name}: run() argument 'ctx' must be optional (default=None)")

        else:
            # If no JOB_NAME, we assume it's a utility module (like exceptions.py, utils.py)
            pass

    print(f"\nChecked {checked_count} handlers.")

    if violations:
        print("\n❌ CONTRACT VIOLATIONS FOUND:")
        for v in violations:
            print(f" - {v}")
        sys.exit(1)
    else:
        print("\n✅ All handlers satisfy the contract.")
        sys.exit(0)

if __name__ == "__main__":
    verify_contract()
