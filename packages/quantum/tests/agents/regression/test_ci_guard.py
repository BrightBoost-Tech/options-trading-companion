import os
import pytest

def test_ci_strict_mode_enforced():
    """
    Guard test to ensure that CI never runs with UPDATE_FIXTURES=1.
    If this environment variable is set in CI, this test will fail,
    preventing accidental fixture updates from passing as 'success'.
    """
    if os.environ.get("UPDATE_FIXTURES") == "1":
        # We only want to fail if we are strictly in a CI environment,
        # or we can fail generally if the user ran 'pytest' on the whole suite
        # while accidentally having the variable set.
        #
        # For safety, we fail if the variable is set at all, effectively
        # preventing 'run all tests' from silently updating fixtures unless
        # the user specifically targeted the regression suite.
        #
        # However, if the user explicitly wants to update fixtures, they will
        # run the specific regression tests. This test is part of the regression
        # suite folder, so it would run too.
        #
        # To avoid blocking the valid use case (running the update script),
        # we can check if we are in a known CI environment.

        is_ci = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

        if is_ci:
            pytest.fail("UPDATE_FIXTURES=1 is detected in CI environment! This is forbidden.")
