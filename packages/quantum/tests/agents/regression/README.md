# Regression Testing & Fixtures

This directory contains regression tests for agents and the agent runner. These tests rely on "golden" fixture files (JSON) located in the `fixtures/` subdirectory.

## Updating Fixtures

By default, tests run in **strict mode**. They will compare the current output against the existing fixture file. If the output differs, the test will fail.

**Fixture files are never automatically updated during a normal test run.**

To update the fixtures (e.g., after a logic change that affects output), you must explicitly opt-in by setting the environment variable `UPDATE_FIXTURES=1`.

### Helper Command

A helper script is available to run the regression tests in update mode:

```bash
./packages/quantum/scripts/update_fixtures.sh
```

Or manually:

```bash
export UPDATE_FIXTURES=1
pytest packages/quantum/tests/agents/regression
```

## CI/CD

In CI environments, `UPDATE_FIXTURES` should **never** be set. This ensures that any unintentional change in agent behavior causes a test failure, alerting the developer to the regression.
