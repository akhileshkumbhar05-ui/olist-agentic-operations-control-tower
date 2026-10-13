"""Read-only, published-run failed-rule drill-down and UI regression tests."""
import json
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app.nexus_domains import (
    MAX_FAILED_RECORD_PREVIEW, failed_record_preview_sql,
    failed_rule_records, normalize_failed_record_preview,
)
from olist_agentic.copilot.queries import assert_read_only


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()
CSS = HTML.split("<style>", 1)[1].split("</style>", 1)[0]


@pytest.mark.parametrize("dataset,rule_id,action,count", [
    ("orders", "orders.lifecycle", "WARN", 1373),
    ("orders", "orders.payment_reconciliation", "WARN", 303),
    ("products", "products.category", "WARN", 610),
    ("products", "products.fk_product_category_name", "WARN", 13),
    ("orders", "orders.delivered_time", "QUARANTINE", 8),
])
def test_sample_queries_scope_failed_rule_and_published_run(
    dataset, rule_id, action, count
):
    sql = failed_record_preview_sql(dataset, rule_id)
    assert_read_only(sql.replace("f.original_values", "f.approved_json_scalars"))
    assert f"r.dataset = '{dataset}'" in sql
    assert f"r.rule_id = '{rule_id}'" in sql
    assert "r.status = 'FAILED'" in sql
    assert "JOIN workspace.olist_agentic_quality.published_run p" in sql
    assert "LEFT JOIN workspace.olist_agentic_quality.dq_failed_records f" in sql
    assert "f.run_id = r.run_id" in sql
    assert "f.dataset = r.dataset" in sql
    assert "f.rule_id = r.rule_id" in sql
    # Only approved JSON scalar extracts are permitted, never a raw payload.
    assert "f.original_values AS" not in sql
    assert "SELECT f.original_values" not in sql
    if dataset == "orders":
        assert "get_json_object(f.original_values, '$.order_id') AS original_order_id" in sql
        if rule_id == "orders.lifecycle":
            assert "AS purchased_at" in sql
            assert "AS approved_at" in sql
            assert "AS carrier_handoff_at" in sql
            assert "AS delivered_at" in sql
        else:
            assert "AS approved_at" not in sql
    else:
        assert "get_json_object" not in sql
    assert f"LIMIT {MAX_FAILED_RECORD_PREVIEW}" in sql
    assert MAX_FAILED_RECORD_PREVIEW == 20


@pytest.mark.parametrize("dataset,rule_id", [
    ("orders", "payments.unique_key"),
    ("orders", "orders.not_a_real_rule"),
    ("orders", "orders.lifecycle' OR 1=1"),
    ("products", "products.category; DROP TABLE x"),
])
def test_unregistered_rule_is_rejected_before_running_sql(dataset, rule_id):
    with pytest.raises(HTTPException) as err:
        failed_record_preview_sql(dataset, rule_id)
    assert err.value.status_code == 404


def test_no_arbitrary_dataset_sql():
    with pytest.raises(ValueError):
        failed_record_preview_sql("orders'; DROP TABLE x", "orders.lifecycle")


def _row(**kwargs):
    return {
        "published_run": "verified-run",
        "dataset": "orders",
        "rule_id": "orders.lifecycle",
        "rule_action": "WARN",
        "failed_evaluations": 1373,
        "source_record_id": "source-record-0042",
        "failure_reason": "Lifecycle timestamp order violation",
        "record_action": "WARN",
        "original_values": '{"private": "DO_NOT_RETURN"}',
        **kwargs,
    }


def test_normalized_record_preview_omits_original_payload_and_preserves_semantics():
    row = _row()
    result = normalize_failed_record_preview("orders", "orders.lifecycle", [row])
    assert result["configured_action"] == "WARN"
    assert result["failed_evaluations"] == 1373
    assert result["published_run"] == "verified-run"
    assert result["record_preview"] == [{
        "source_record_id": "source-record-0042",
        "failure_reason": "Lifecycle timestamp order violation",
        "record_action": "WARN",
    }]
    assert "DO_NOT_RETURN" not in json.dumps(result)
    assert "WARN findings are not automatically excluded" in result["limitations"]
    assert result["preview_limit"] == 20


def test_nullable_preview_maintains_failed_rule_without_inventing_identifiers():
    result = normalize_failed_record_preview(
        "orders", "orders.lifecycle", [
            _row(source_record_id=None, failure_reason=None)
        ]
    )
    assert result["failed_evaluations"] == 1373
    assert result["record_preview"] == []


def test_inconsistent_run_fails_closed():
    rows = [_row(), _row(published_run="other-run")]
    with pytest.raises(RuntimeError, match="Inconsistent"):
        normalize_failed_record_preview("orders", "orders.lifecycle", rows)


def test_no_observed_failure_is_not_misreported_as_zero_records():
    with pytest.raises(HTTPException) as err:
        normalize_failed_record_preview("orders", "orders.lifecycle", [])
    assert err.value.status_code == 404


def test_route_executes_only_read_only_bounded_source_id_query(monkeypatch):
    from app import main
    executed = []

    def fake_sql(statement):
        assert_read_only(statement.replace("f.original_values", "f.approved_json_scalars"))
        executed.append(statement)
        return [_row()]

    monkeypatch.setattr(main, "sql_query", fake_sql)
    result = failed_rule_records("orders", "orders.lifecycle")
    assert len(executed) == 1
    assert result["rule_id"] == "orders.lifecycle"
    assert result["failed_evaluations"] == 1373
    assert result["record_preview"][0]["record_action"] == "WARN"


def test_no_query_for_rule_that_belongs_to_another_source(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "sql_query", lambda _sql: pytest.fail("SQL must not run"))
    with pytest.raises(HTTPException) as error:
        failed_rule_records("payments", "orders.lifecycle")
    assert error.value.status_code == 404


def test_sql_error_returns_503_without_fake_records(monkeypatch):
    from app import main

    def unavailable(_statement):
        raise RuntimeError("permissions refused")

    monkeypatch.setattr(main, "sql_query", unavailable)
    with pytest.raises(HTTPException) as error:
        failed_rule_records("orders", "orders.lifecycle")
    assert error.value.status_code == 503
    assert "Neither detailed failed records nor published rule-result samples" in error.value.detail


def test_ui_failed_summary_record_drilldown_and_ai_actions():
    for key in ("domainFailedRules", "domainFailureList", "domainRulePreview",
                "domainPreviewRecords", "domainPreviewStatus", "domainPreviewClose"):
        assert f'id="{key}"' in HTML
    assert "filter(r=>r.observed_status==='FAILED')" in HTML
    assert "b.failed_evaluations" in HTML
    assert "View affected records" in HTML
    assert "Explain with AI" in HTML
    assert "inspectFailedRuleRecords(rule,e.published_run,e.dataset)" in HTML
    assert "investigateFailedRule(rule,e.published_run,e.dataset)" in HTML
    assert "encodeURIComponent(rule.rule_id)" in HTML
    assert "evidence.published_run!==runId" in HTML
    assert "++domainPreviewSequence" in HTML
    assert "domainRulePrompt='For the active published Olist run '" in HTML
    assert "const questionScope=selectedDomain||question===domainRulePrompt?'ALL'" in HTML
    assert "domainInvestigationPrompt='';domainPromptDomain=null" in HTML
    assert "document.createElement('article')" in HTML
    assert "innerHTML=evidence" not in HTML
    assert ".domain-rule-preview[hidden]{display:none}" in CSS


def test_native_dashboard_and_existing_investigator_are_unchanged():
    assert '<iframe id="nativeDashboard"' in HTML
    assert "body:JSON.stringify({question,page:'operations',visual:'overview',state:questionScope,source_domain:selectedDomain})" in HTML
    assert "renderAgentAnswer(data.answer)" in HTML
    assert "fetch('/api/ask'" in HTML


def test_nexus_script_syntax_with_node(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js not available")
    js = HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    tmp = tmp_path / "nexus.js"
    tmp.write_text(js, encoding="utf-8")
    result = subprocess.run(["node", "--check", str(tmp)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
