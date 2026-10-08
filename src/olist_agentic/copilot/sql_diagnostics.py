"""Sanitized Databricks SQL execution diagnostics for an App frontend.

Raw Databricks errors can contain SQL and object identifiers. Keep full details in
App Logs; return an actionable classification without leaking raw server messages.
"""
from __future__ import annotations


def sql_failure_category(status: object) -> str:
    error = getattr(status, "error", None)
    code = str(getattr(error, "error_code", "") or "").upper()
    message = str(getattr(error, "message", "") or "").upper()
    combined = code + " " + message
    if any(x in combined for x in ("PERMISSION_DENIED", "INSUFFICIENT_PRIVILEGES",
                                    "INSUFFICIENT_PERMISSIONS", "UNAUTHORIZED", "ACCESS_DENIED",
                                    "NOT_AUTHORIZED")):
        return "PERMISSION_DENIED"
    if any(x in combined for x in ("TABLE_OR_VIEW_NOT_FOUND", "OBJECT_NOT_FOUND",
                                    "SCHEMA_NOT_FOUND", "CATALOG_NOT_FOUND")):
        return "OBJECT_NOT_FOUND"
    if any(x in combined for x in ("UNRESOLVED_COLUMN", "COLUMN_NOT_FOUND", "UNRESOLVED_FIELD")):
        return "UNKNOWN_COLUMN"
    if any(x in combined for x in ("SYNTAX_ERROR", "PARSE_SYNTAX_ERROR")):
        return "SQL_SYNTAX"
    if any(x in combined for x in ("TIMEOUT", "TIMED_OUT", "CANCELED", "CANCELLED")):
        return "EXECUTION_INTERRUPTED"
    return "SQL_EXECUTION_FAILED"


def sql_failure_guidance(category: str) -> str:
    return {
        "PERMISSION_DENIED":
            "The App's service principal may need USE CATALOG, USE SCHEMA, and SELECT permissions on the governed data. Check App Logs.",
        "OBJECT_NOT_FOUND":
            "An expected published table or view was not found or is not visible to the App identity. Check App Logs.",
        "UNKNOWN_COLUMN":
            "A Copilot SQL template references a column that is not available in the deployed schema. Check App Logs.",
        "SQL_SYNTAX":
            "A Copilot SQL template was rejected by Databricks SQL. Check App Logs.",
        "EXECUTION_INTERRUPTED":
            "The SQL query was interrupted or exceeded its wait limit. Check App Logs.",
        "SQL_EXECUTION_FAILED":
            "Databricks SQL returned a failure. Review the App Logs for its error code and message.",
    }.get(category, "Check App Logs.")
