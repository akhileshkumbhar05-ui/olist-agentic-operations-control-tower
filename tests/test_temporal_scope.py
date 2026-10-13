"""Regression: explicit purchase-date questions cannot produce all-time GMV."""
from pathlib import Path

import pytest

from olist_agentic.copilot.time_scope import explicit_calendar_period
from olist_agentic.copilot.queries import Context, statements, assert_read_only


@pytest.mark.parametrize("question, expected", [
    ("How much revenue did the state of SP generate in July 2019?",
     ("2019-07-01", "2019-07-31")),
    ("Show GMV in February 2020", ("2020-02-01", "2020-02-29")),
    ("Show GMV in Feb 2019", ("2019-02-01", "2019-02-28")),
    ("What is the delivered-item GMV for July 12, 2018?",
     ("2018-07-12", "2018-07-12")),
    ("What was GMV on 2018-07-12?", ("2018-07-12", "2018-07-12")),
    ("Show delivered GMV for 2019-07", ("2019-07-01", "2019-07-31")),
    ("Show total GMV in 2019", ("2019-01-01", "2019-12-31")),
    ("Show delivered GMV by state", None),
])
def test_explicit_calendar_period(question, expected):
    assert explicit_calendar_period(question) == expected


@pytest.mark.parametrize("question", [
    "Compare delivered GMV in July 2018 and July 2019",
    "Show sales from 2017 through 2018",
    "What was GMV last month?",
    "Show fiscal 2018 revenue",
    "What was revenue in February 2019 and 2018?",
    "Show delivered GMV for February 30, 2019",
])
def test_ambiguous_periods_fail_closed(question):
    with pytest.raises(ValueError):
        explicit_calendar_period(question)


def test_period_sql_applies_date_and_state_not_national_all_time():
    period = explicit_calendar_period("How much revenue did state SP generate in July 2019?")
    context = Context(state="SP", start_date=period[0], end_date=period[1])
    sql = statements("How much revenue did state SP generate in July 2019?", context, "ANALYTICS")
    for tool in ("gmv_summary", "state_delivery"):
        assert "purchase_date >= DATE '2019-07-01'" in sql[tool]
        assert "purchase_date <= DATE '2019-07-31'" in sql[tool]
        assert "customer_state IN ('SP')" in sql[tool]
        assert_read_only(sql[tool])


def test_app_declares_sql_coverage_guard_and_exposes_time_receipt():
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text()
    html = (root / "app/static/nexus.html").read_text()
    assert "period = (explicit_calendar_period(body.question)" in main
    assert "empty_cohort = no_data_for_period(body.question, context)" in main
    assert "if empty_cohort is not None:" in main
    assert 'FROM workspace.olist_semantic.v_published_orders ' in main
    assert '"answer_validation": "sql_verified_empty_cohort"' in main
    assert "data.context?.start_date" in html
    assert "Purchase-date filter" in html


def test_runtime_empty_cohort_returns_no_data_not_old_gmv(monkeypatch):
    pytest.importorskip("fastapi")
    from app import main as appmain

    executed_sql = []
    def query(sql):
        executed_sql.append(sql)
        return [{"run_id": "run-verified", "matching_orders": "0"}]

    monkeypatch.setattr(appmain, "sql_query", query)
    monkeypatch.setattr(appmain, "run_agent",
                        lambda *args, **kwargs: pytest.fail("Model must not be called for empty scope"))
    monkeypatch.setenv("DATABRICKS_MODEL_SERVICE", "system.ai.gpt-oss-120b")
    result = appmain._ask(appmain.AskRequest(
        question="How much revenue did the state of SP generate in July 2019?",
        state="SP"))
    assert result["generation"] == "deterministic_no_matching_period"
    assert result["context"]["start_date"] == "2019-07-01"
    assert result["context"]["end_date"] == "2019-07-31"
    assert result["published_run"] == "run-verified"
    assert result["evidence"]["answer_validation"] == "sql_verified_empty_cohort"
    assert "No accepted Olist orders" in result["answer"]
    assert "5,066,562.98" not in result["answer"]
    assert len(executed_sql) == 1
    assert "customer_state = 'SP'" in executed_sql[0]
    assert "purchase_date >= DATE '2019-07-01'" in executed_sql[0]
    assert "purchase_date <= DATE '2019-07-31'" in executed_sql[0]


def test_nonempty_period_preserves_live_agent_and_dates(monkeypatch):
    pytest.importorskip("fastapi")
    from app import main as appmain

    monkeypatch.setattr(appmain, "sql_query", lambda sql: [
        {"run_id": "run-verified", "matching_orders": "37"}])
    invoked = []
    def agent(question, context, *args, **kwargs):
        invoked.append((question, context))
        return {"answer": "Scoped delivered-item GMV", "published_run": "run-verified",
                "route": "ANALYTICS", "evidence": {}}
    monkeypatch.setattr(appmain, "run_agent", agent)
    monkeypatch.setattr(appmain, "gateway_model_client", lambda: object())
    monkeypatch.setenv("DATABRICKS_MODEL_SERVICE", "system.ai.gpt-oss-120b")
    result = appmain._ask(appmain.AskRequest(
        question="How much revenue did SP generate in July 2018?", state="SP"))
    assert result["generation"] == "agentic_tool_calling"
    assert invoked[0][1].start_date == "2018-07-01"
    assert invoked[0][1].end_date == "2018-07-31"


def test_calendar_scope_conflict_returns_validation_error(monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import HTTPException
    from app import main as appmain
    with pytest.raises(HTTPException) as err:
        appmain._ask(appmain.AskRequest(
            question="How much revenue in July 2019?",
            start_date="2018-07-01", end_date="2018-07-31"))
    assert err.value.status_code == 422
