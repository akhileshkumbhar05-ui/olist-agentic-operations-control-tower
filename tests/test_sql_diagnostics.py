"""Regression coverage for safe SQL diagnostics and tool attribution."""
from types import SimpleNamespace
import pytest

from olist_agentic.copilot.sql_diagnostics import sql_failure_category, sql_failure_guidance
from olist_agentic.copilot.engine import prepare
from olist_agentic.copilot.queries import Context


@pytest.mark.parametrize("code,message,category", [
    ("PERMISSION_DENIED", "insufficient grants", "PERMISSION_DENIED"),
    ("", "[INSUFFICIENT_PRIVILEGES] SELECT denied", "PERMISSION_DENIED"),
    ("TABLE_OR_VIEW_NOT_FOUND", "missing view", "OBJECT_NOT_FOUND"),
    ("UNRESOLVED_COLUMN", "missing field", "UNKNOWN_COLUMN"),
    ("PARSE_SYNTAX_ERROR", "broken syntax", "SQL_SYNTAX"),
    ("", "", "SQL_EXECUTION_FAILED"),
])
def test_sql_failure_classification(code, message, category):
    status = SimpleNamespace(error=SimpleNamespace(error_code=code, message=message))
    assert sql_failure_category(status) == category
    assert sql_failure_guidance(category)


def test_sql_failure_identifies_tool_without_running_other_queries():
    def fail(_sql):
        raise RuntimeError("PERMISSION_DENIED: App service principal lacks SELECT")
    with pytest.raises(RuntimeError, match="tool 'publication'.*PERMISSION_DENIED"):
        prepare("Can I trust GMV and quarantine?", Context(), fail)
