import sys
import os
import inspect
import importlib.util

# Ensure packages can be imported
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

HANDLER_MODULES = [
    "packages.quantum.jobs.handlers.midday_scan",
    "packages.quantum.jobs.handlers.morning_brief",
    "packages.quantum.jobs.handlers.plaid_backfill_history",
    "packages.quantum.jobs.handlers.universe_sync",
    "packages.quantum.jobs.handlers.weekly_report",
]

def verify_handler(module_name):
    try:
        # Import module
        module = importlib.import_module(module_name)

        # Check for run function
        if not hasattr(module, 'run'):
            return False, "Missing 'run' function"

        run_func = module.run
        if not callable(run_func):
            return False, "'run' is not callable"

        # Inspect signature
        sig = inspect.signature(run_func)
        params = sig.parameters

        # Check payload param (first arg)
        if len(params) < 1:
             return False, "Signature missing 'payload' argument"

        # Check ctx param
        if 'ctx' not in params:
             # It is acceptable if it has **kwargs, but prompt specifically asked for ctx=None
             # However, let's stick to checking if ctx exists and is optional.
             return False, "Signature missing 'ctx' argument"

        ctx_param = params['ctx']
        if ctx_param.default == inspect.Parameter.empty:
            return False, "'ctx' argument must be optional (have a default value)"

        return True, "OK"

    except ImportError as e:
        return False, f"ImportError: {e}"
    except Exception as e:
        return False, f"Exception: {e}"

def main():
    print("Verifying handlers contract...")
    all_passed = True
    for mod_name in HANDLER_MODULES:
        success, message = verify_handler(mod_name)
        status = "PASS" if success else "FAIL"
        print(f"[{status}] {mod_name}: {message}")
        if not success:
            all_passed = False

    if all_passed:
        print("\nAll handlers passed verification.")
        sys.exit(0)
    else:
        print("\nSome handlers failed verification.")
        sys.exit(1)

if __name__ == "__main__":
    main()
