import sys
import os
import inspect
import importlib
import pkgutil
import logging

# Add the repository root to sys.path so we can import packages.quantum
repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(repo_root)

# Configure logging to stdout so we can see the registry errors
logging.basicConfig(level=logging.ERROR)

from packages.quantum.jobs.registry import discover_handlers, HANDLERS_PACKAGE

def verify_handlers():
    print("Verifying handler contracts...")

    # Get the "valid" handlers as per the registry
    valid_handlers = discover_handlers()

    # Locate the handlers directory
    # We can use the same logic as registry.py or just rely on the path
    handlers_dir = os.path.join(repo_root, "packages", "quantum", "jobs", "handlers")

    if not os.path.exists(handlers_dir):
        print(f"ERROR: Handlers directory not found at {handlers_dir}")
        sys.exit(1)

    failure_count = 0

    # Iterate over modules in the handlers package
    for module_info in pkgutil.iter_modules([handlers_dir]):
        module_name = f"{HANDLERS_PACKAGE}.{module_info.name}"

        try:
            module = importlib.import_module(module_name)

            # Skip modules without JOB_NAME (helpers, utils, etc)
            if not hasattr(module, "JOB_NAME"):
                continue

            job_name = getattr(module, "JOB_NAME")

            # Check if this job was accepted by registry
            if job_name in valid_handlers:
                print(f"[PASS] {module_info.name} ({job_name})")
            else:
                # It was rejected. Let's find out why (re-run checks)
                print(f"[FAIL] {module_info.name} ({job_name})")
                failure_count += 1

                if not hasattr(module, "run") or not callable(getattr(module, "run")):
                    print(f"       Reason: Missing 'run' function")
                    continue

                handler_func = getattr(module, "run")
                sig = inspect.signature(handler_func)
                params = sig.parameters

                if "payload" not in params:
                    print(f"       Reason: Missing 'payload' parameter")

                if "ctx" in params and params["ctx"].default == inspect.Parameter.empty:
                    print(f"       Reason: 'ctx' parameter missing default value")

        except Exception as e:
            print(f"[FAIL] {module_info.name}: Import/Runtime error: {e}")
            failure_count += 1

    if failure_count > 0:
        print(f"\nVerification FAILED. {failure_count} handler(s) violated the contract.")
        sys.exit(1)
    else:
        print("\nVerification PASSED. All handlers conform to contract.")
        sys.exit(0)

if __name__ == "__main__":
    verify_handlers()
