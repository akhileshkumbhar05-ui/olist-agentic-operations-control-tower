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
from olist_agentic.copilot.agent import run_agent, TOOL_SOURCES, summarize_failed_rule_definitions, MAX_QUESTION_CHARS
from olist_agentic.copilot.semantic_search import search_governance
from olist_agentic.copilot.tracing import trace_span, set_span_attributes

logger = logging.getLogger(__name__)

app = FastAPI(title="Olist Agentic Operations Control Tower", version="0.3.0")


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
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
    # system.ai.* names are Unity Gateway model services, NOT classic serving
    # endpoints. DatabricksOpenAI defaults to /serving-endpoints; override
    # the base URL to Unity Gateway's MLflow-compatible Responses API.
    # Keep the App service principal's WorkspaceClient for OAuth (no PAT).
    workspace = client()
    gateway_url = workspace.config.host.rstrip("/") + "/ai-gateway/mlflow/v1"
    return DatabricksOpenAI(workspace_client=workspace, base_url=gateway_url)


def semantic_query(question: str) -> list[dict]:
    index = os.getenv("DATABRICKS_GOVERNANCE_SEARCH_INDEX", "").strip()
    if not index:
        raise RuntimeError("Olist governance AI Search resource has not been configured")
    return search_governance(client(), index, question)


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
    with trace_span("olist.ask", "CHAIN", {"endpoint": "/api/ask"}) as span:
        result = _ask(body)
        set_span_attributes(span, {"generation": result["generation"],
                                   "route": result["route"]})
        return result


def _ask(body: AskRequest):

    try:
        context = Context(page=body.page, visual=body.visual, state=body.state,
                          start_date=body.start_date, end_date=body.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    model_service = os.getenv("DATABRICKS_MODEL_SERVICE", "").strip()
    semantic_enabled = bool(os.getenv("DATABRICKS_GOVERNANCE_SEARCH_INDEX", "").strip())
    if model_service:
        try:
            result = run_agent(
                body.question, context, sql_query, gateway_model_client(), model_service,
                search_knowledge=semantic_query if semantic_enabled else None,
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
    sql_tools = evidence["sql_tools"]
    sql_rows = evidence["tools"]
    # Explicit source provenance is required for the fallback to remain
    # auditable; a correct answer cannot be mistaken for successful LLM use.
    sources = sorted({source for tool in sql_tools
                      for source in TOOL_SOURCES[tool]})
    verified_metrics = []
    for row in sql_rows.get("gmv_summary", []):
        if row.get("delivered_item_gmv_brl") is not None:
            from decimal import Decimal
            amount = Decimal(str(row["delivered_item_gmv_brl"]))
            verified_metrics.append({
                "name": "Delivered-item GMV",
                "display": f"BRL {amount:,.2f}",
                "source": "workspace.olist_semantic.v_published_orders",
            })
    quality = (summarize_failed_rule_definitions(sql_rows["failed_rules"])
               if "failed_rules" in sql_rows else None)
    return {"answer": answer,
            "generation": ("deterministic_fallback_agent_error"
                           if model_service else "deterministic_template"),
            "route": evidence["route"], "published_run": evidence["published_run"],
            "context": evidence["context"],
            "evidence": {"tool_names": sql_tools,
                         "model_selected_tools": [],
                         "sources": sources,
                         "knowledge": evidence["knowledge"],
                         "retrieval_mode": "lexical_only",
                         "retrieval_trigger": "not_used",
                         "verified_quality_summary": quality,
                         "verified_metrics": verified_metrics,
                         "limitations": evidence["limitations"]}}



@app.get("/api/config")
def config():
    # Explicitly allow only a Databricks workspace URL supplied via configuration.
    import urllib.parse
    def approved(name: str) -> str:
        value = os.getenv(name, "")
        p = urllib.parse.urlparse(value)
        valid = (p.scheme == "https" and bool(p.hostname) and
                 (p.hostname.endswith(".cloud.databricks.com") or
                  p.hostname.endswith(".azuredatabricks.net") or
                  p.hostname.endswith(".gcp.databricks.com")))
        return value if valid else ""
    dashboard_url = approved("DATABRICKS_DASHBOARD_URL")
    embed_url = approved("DATABRICKS_DASHBOARD_EMBED_URL")
    return {"dashboard_url": dashboard_url, "dashboard_embed_url": embed_url,
            "genie_backup_available": bool(dashboard_url),
            "model_configured": bool(os.getenv("DATABRICKS_MODEL_SERVICE")),
            "semantic_search_configured": bool(os.getenv("DATABRICKS_GOVERNANCE_SEARCH_INDEX"))}


# Optional alternate frontend: the existing '/' route and all APIs stay unchanged.
from app.nexus_api import router as nexus_router
app.include_router(nexus_router)


@app.get("/nexus", response_class=HTMLResponse, include_in_schema=False)
def nexus_home():
    return (ROOT / "app" / "static" / "nexus.html").read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
