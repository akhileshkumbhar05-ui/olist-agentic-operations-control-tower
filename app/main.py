"""Lightweight FastAPI Databricks App serving read-only grounded analytics.

No model endpoint? Verified SQL and documented governance still work.
Genie remains available via the separately published AI/BI dashboard link.
"""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from functools import lru_cache

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from olist_agentic.copilot.queries import Context
from olist_agentic.copilot.engine import prepare, fallback_answer, model_answer
from olist_agentic.copilot.sql_diagnostics import sql_failure_category, sql_failure_guidance
from olist_agentic.copilot.agent import run_agent

logger = logging.getLogger(__name__)

app = FastAPI(title="Olist Agentic Operations Control Tower", version="0.3.0")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    page: str = "operations"
    visual: str = "overview"
    state: str = "ALL"
    start_date: str | None = None
    end_date: str | None = None


@lru_cache(maxsize=1)
def client():
    from databricks.sdk import WorkspaceClient
    return WorkspaceClient()


@lru_cache(maxsize=1)
def gateway_model_client():
    from databricks_openai import DatabricksOpenAI
    return DatabricksOpenAI(workspace_client=client())


def sql_query(statement: str) -> list[dict]:
    from databricks.sdk.service.sql import StatementState
    warehouse = os.environ.get("DATABRICKS_WAREHOUSE_ID")
    if not warehouse:
        raise RuntimeError("SQL warehouse resource has not been configured")
    result = client().statement_execution.execute_statement(
        warehouse_id=warehouse,
        statement=statement,
        wait_timeout="30s",
        row_limit=150,
    )
    if result.status and result.status.state != StatementState.SUCCEEDED:
        state = result.status.state
        category = sql_failure_category(result.status)
        err = getattr(result.status, "error", None)
        logger.error(
            "Olist SQL statement failed: statement_id=%s state=%s error_code=%s message=%s",
            getattr(result, "statement_id", "unknown"), state,
            getattr(err, "error_code", None),
            getattr(err, "message", None),
        )
        if state in (StatementState.PENDING, StatementState.RUNNING):
            raise RuntimeError("SQL_PENDING: The query was still running after the wait period. Check App Logs.")
        raise RuntimeError(f"{category}: {sql_failure_guidance(category)}")
    cols = [c.name for c in result.manifest.schema.columns] if result.manifest and result.manifest.schema else []
    raw = result.result.data_array if result.result else []
    return [{k: v for k, v in zip(cols, row)} for row in (raw or [])]


@app.get("/healthz")
def health():
    return {"status": "ok", "model_configured": bool(os.getenv("DATABRICKS_MODEL_SERVICE")),
            "warehouse_configured": bool(os.getenv("DATABRICKS_WAREHOUSE_ID")),
            "dashboard_configured": bool(os.getenv("DATABRICKS_DASHBOARD_URL"))}


@app.post("/api/ask")
def ask(body: AskRequest):

    try:
        context = Context(page=body.page, visual=body.visual, state=body.state,
                          start_date=body.start_date, end_date=body.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    model_service = os.getenv("DATABRICKS_MODEL_SERVICE", "").strip()
    if model_service:
        try:
            result = run_agent(
                body.question, context, sql_query, gateway_model_client(), model_service
            )
            return {"generation": "agentic_tool_calling", **result}
        except Exception:
            # Fail closed: never present an unverified model answer as grounded.
            # Full details stay in App Logs, not the user-facing response.
            logger.exception("Olist Unity Gateway agent failed; using deterministic SQL fallback")

    try:
        evidence = prepare(body.question, context, sql_query)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503,
                            detail=str(exc)) from exc

    answer = fallback_answer(body.question, evidence)
    return {"answer": answer,
            "generation": ("deterministic_fallback_model_unavailable"
                           if model_service else "deterministic_template"),
            "route": evidence["route"], "published_run": evidence["published_run"],
            "context": evidence["context"],
            "evidence": {"tool_names": evidence["sql_tools"],
                         "model_selected_tools": [],
                         "knowledge": evidence["knowledge"],
                         "limitations": evidence["limitations"]}}



@app.get("/api/config")
def config():
    # Explicitly allow only a Databricks workspace URL supplied via configuration.
    import urllib.parse
    value = os.getenv("DATABRICKS_DASHBOARD_URL", "")
    p = urllib.parse.urlparse(value)
    valid = (p.scheme == "https" and bool(p.hostname) and
             (p.hostname.endswith(".cloud.databricks.com") or
              p.hostname.endswith(".azuredatabricks.net") or
              p.hostname.endswith(".gcp.databricks.com")))
    return {"dashboard_url": value if valid else "", "genie_backup_available": valid,
            "model_configured": bool(os.getenv("DATABRICKS_SERVING_ENDPOINT"))}


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
