"""
Test that workflow_orchestrator has logger properly defined.

This test ensures that the NameError 'logger is not defined'
does not occur when importing or using the module.
"""

import pytest
import os


class TestWorkflowOrchestratorLogger:
    """Test logger is properly defined in workflow_orchestrator."""

    def test_logger_import_is_present(self):
        """Verify 'import logging' is in the file."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "import logging" in content, \
            "Expected 'import logging' in workflow_orchestrator.py"

    def test_logger_definition_is_present(self):
        """Verify logger = logging.getLogger(__name__) is in the file."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "logger = logging.getLogger(__name__)" in content, \
            "Expected 'logger = logging.getLogger(__name__)' in workflow_orchestrator.py"

    def test_logger_defined_before_first_use(self):
        """Verify logger is defined before it's used."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "workflow_orchestrator.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        logger_def_line = None
        first_logger_use_line = None

        for i, line in enumerate(lines):
            if "logger = logging.getLogger" in line and logger_def_line is None:
                logger_def_line = i

            if "logger." in line and first_logger_use_line is None:
                first_logger_use_line = i

        assert logger_def_line is not None, \
            "logger definition not found"

        assert first_logger_use_line is not None, \
            "No logger usage found (surprising for this file)"

        assert logger_def_line < first_logger_use_line, \
            f"logger defined at line {logger_def_line + 1} but used at line {first_logger_use_line + 1}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
