import pytest
import os
import re
from packages.quantum.models import UpgradeCapability

def test_frontend_backend_capability_alignment():
    """
    Contract test to ensure that the Frontend UpgradeCapability enum
    matches the Backend UpgradeCapability enum.
    """
    # 1. Get Backend Capabilities (canonical source)
    backend_caps = {e.value for e in UpgradeCapability}

    # 2. Read Frontend File
    # This test is in packages/quantum/tests/
    # The FE file is in apps/web/lib/capabilities.ts

    current_dir = os.path.dirname(os.path.abspath(__file__))
    # Go up: tests -> quantum -> packages -> root
    repo_root = os.path.abspath(os.path.join(current_dir, "../../.."))
    fe_path = os.path.join(repo_root, "apps/web/lib/capabilities.ts")

    assert os.path.exists(fe_path), f"Frontend capabilities file not found at {fe_path}"

    with open(fe_path, "r") as f:
        content = f.read()

    # 3. Parse Frontend Enum
    # Looking for: export enum UpgradeCapability { ... }
    match = re.search(r"export enum UpgradeCapability\s*{([^}]+)}", content, re.DOTALL)
    assert match, "Could not find UpgradeCapability enum in frontend file"

    enum_body = match.group(1)

    # Extract values: NAME = "VALUE"
    # This regex looks for: = "SOME_VALUE" or = 'SOME_VALUE'
    frontend_caps = set(re.findall(r'=\s*["\']([^"\']+)["\']', enum_body))

    # 4. Compare
    missing_in_fe = backend_caps - frontend_caps
    extra_in_fe = frontend_caps - backend_caps

    # Detailed error messages
    errors = []
    if missing_in_fe:
        errors.append(f"Frontend is missing capabilities defined in Backend: {missing_in_fe}")
    if extra_in_fe:
        errors.append(f"Frontend has capabilities not defined in Backend: {extra_in_fe}")

    assert not errors, "\n".join(errors)
