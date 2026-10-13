"""Regression for a resilient, evidence-labelled failed-record drill-down."""
from pathlib import Path
import json

import pytest
from fastapi import HTTPException

from app.nexus_domains import (
    failed_record_sample_sql,
    failed_rule_records,
    normalize_failed_record_sample,
)
from olist_agentic.copilot.queries import assert_read_only


def sample_row(**updates):
    row = {
        "published_run": "published-run",
        "dataset": "orders",
        "rule_id": "orders.lifecycle",
        "rule_action": "WARN",
        "failed_evaluations": 1373,
        "sample_failed_identifiers": '["source-1", "source-2"]',
    }
    row.update(updates)
    return row


def test_fallback_sample_query_is_published_scoped_and_allowlisted():
    sql = failed_record_sample_sql("orders", "orders.lifecycle")
    assert_read_only(sql)
    assert "workspace.olist_agentic_quality.dq_rule_results" in sql
    assert "workspace.olist_agentic_quality.published_run" in sql
    assert "r.status = 'FAILED'" in sql
    assert "sample_failed_identifiers" in sql
    assert "r.dataset = 'orders'" in sql
    assert "r.rule_id = 'orders.lifecycle'" in sql
    assert "dq_failed_records" not in sql
    assert "LIMIT 1" in sql

    with pytest.raises(HTTPException) as exc:
        failed_record_sample_sql("payments", "orders.lifecycle")
    assert exc.value.status_code == 404


def test_fallback_retrieves_actual_published_identifiers_not_fabricated_details(monkeypatch):
    from app import main
    statements = []

    def query(statement):
        assert_read_only(statement)
        statements.append(statement)
        if "dq_failed_records" in statement:
            raise RuntimeError("PERMISSION_DENIED: SELECT unavailable for App identity")
        if "sample_failed_identifiers" in statement:
            return [sample_row()]
        raise AssertionError("Unexpected statement")

    monkeypatch.setattr(main, "sql_query", query)
    result = failed_rule_records("orders", "orders.lifecycle")
    assert len(statements) == 2
    assert result["preview_source"] == "published_rule_result_sample"
    assert result["published_run"] == "published-run"
    assert result["failed_evaluations"] == 1373
    assert result["configured_action"] == "WARN"
    assert result["preview_limit"] == 10
    assert result["record_preview"] == [
        {"source_record_id": "source-1", "failure_reason": "", "record_action": "WARN"},
        {"source_record_id": "source-2", "failure_reason": "", "record_action": "WARN"},
    ]
    assert "Individual failure reasons" in result["limitations"]
    assert all("dq_failed_records" not in table for table in result["source"])


def test_detailed_records_still_have_priority_when_accessible(monkeypatch):
    from app import main
    statements = []

    def query(statement):
        statements.append(statement)
        assert "dq_failed_records" in statement
        return [{
            "published_run": "published-run", "dataset": "orders",
            "rule_id": "orders.lifecycle", "rule_action": "WARN",
            "failed_evaluations": "1373",
            "source_record_id": "one", "failure_reason": "Lifecycle chronology",
            "record_action": "WARN",
        }]
    monkeypatch.setattr(main, "sql_query", query)
    result = failed_rule_records("orders", "orders.lifecycle")
    assert len(statements) == 1
    assert result["preview_source"] == "detailed_failed_records"
    assert result["record_preview"][0]["failure_reason"] == "Lifecycle chronology"
    assert result["preview_limit"] == 20


def test_empty_published_sample_never_invents_an_identifier():
    result = normalize_failed_record_sample(
        "orders", "orders.lifecycle", [sample_row(sample_failed_identifiers="[]")])
    assert result["record_preview"] == []
    assert result["failed_evaluations"] == 1373


@pytest.mark.parametrize("raw", [
    None, "not a json document", '{"id":1}',
    "[true]", '["a",null]', "[] trailing",
    json.dumps([str(x) for x in range(11)]),
])
def test_corrupt_published_samples_fail_closed(raw):
    with pytest.raises((RuntimeError, json.JSONDecodeError)):
        normalize_failed_record_sample(
            "orders", "orders.lifecycle", [sample_row(sample_failed_identifiers=raw)])


def test_wrong_run_or_dataset_never_leaks_samples():
    with pytest.raises(RuntimeError):
        normalize_failed_record_sample(
            "orders", "orders.lifecycle", [sample_row(dataset="products")])


def test_fallback_failure_is_explicit_not_a_fake_zero(monkeypatch):
    from app import main

    def fail(_sql):
        raise RuntimeError("Both tables blocked")

    monkeypatch.setattr(main, "sql_query", fail)
    with pytest.raises(HTTPException) as err:
        failed_rule_records("orders", "orders.lifecycle")
    assert err.value.status_code == 503
    assert "Neither detailed failed records nor published rule-result samples" in err.value.detail


def test_client_labels_provenance_and_keeps_no_raw_payload():
    html = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()
    assert "Published rule-result ID sample · individual failure reasons unavailable" in html
    assert "Detailed failed-record evidence · record reasons available" in html
    assert "evidence.preview_source==='published_rule_result_sample'" in html
    assert "document.createElement('article')" in html
    assert "evidence.published_run!==runId" in html
