import importlib
import pkgutil
import os
import inspect
from typing import Dict, Callable
import logging

# We will look for handlers in packages.quantum.jobs.handlers
HANDLERS_PACKAGE = "packages.quantum.jobs.handlers"

logger = logging.getLogger(__name__)

def discover_handlers() -> Dict[str, Callable]:
    """
    Scans the packages/quantum/jobs/handlers directory for modules defining:
      JOB_NAME = "..."
      def run(payload: dict, ctx=None) -> dict

    Returns:
        dict[job_name, callable]
    """
    handlers = {}

    # Locate the handlers directory relative to this file
    current_dir = os.path.dirname(__file__)
    handlers_dir = os.path.join(current_dir, "handlers")

    if not os.path.exists(handlers_dir):
        logger.warning(f"Handlers directory not found: {handlers_dir}")
        return handlers

    # Iterate over modules in the handlers package
    for module_info in pkgutil.iter_modules([handlers_dir]):
        module_name = f"{HANDLERS_PACKAGE}.{module_info.name}"

        try:
            module = importlib.import_module(module_name)

            # Check for JOB_NAME
            if not hasattr(module, "JOB_NAME"):
                continue

            job_name = getattr(module, "JOB_NAME")

            # Check for run function
            if not hasattr(module, "run") or not callable(getattr(module, "run")):
                logger.warning(f"Module {module_name} has JOB_NAME but no run() function. Skipping.")
                continue

            handler_func = getattr(module, "run")

            # Enforce Contract: def run(payload: dict, ctx=None)
            sig = inspect.signature(handler_func)
            params = sig.parameters

            # 1. Must accept 'payload'
            if "payload" not in params:
                logger.error(f"Handler {module_name} violates contract: missing 'payload' parameter. Skipping.")
                continue

            # 2. 'ctx' is optional but if present must have default
            if "ctx" in params:
                if params["ctx"].default == inspect.Parameter.empty:
                    logger.error(f"Handler {module_name} violates contract: 'ctx' parameter must have a default value (e.g. None). Skipping.")
                    continue

            if job_name in handlers:
                logger.warning(f"Duplicate job name detected: {job_name}. Overwriting previous handler.")

            handlers[job_name] = handler_func

        except Exception as e:
            logger.error(f"Failed to import job handler module {module_name}: {e}")
            continue

    return handlers
