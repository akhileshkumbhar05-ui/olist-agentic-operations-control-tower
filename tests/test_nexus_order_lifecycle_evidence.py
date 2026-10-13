"""Explain real order keys and recorded lifecycle inversions, without leaking row JSON."""
import json
from pathlib import Path

from app.nexus_domains import (
    failed_record_preview_sql, normalize_failed_record_preview,
    recorded_lifecycle_evidence, failed_rule_records,
)
from olist_agentic.copilot.queries import assert_read_only


def source_row(**overrides):
    result = {
        "published_run": "published-run",
        "dataset": "orders",
        "rule_id": "orders.lifecycle",
        "rule_action": "WARN",
        "failed_evaluations": 1373,
        "source_record_id": "orders:15",
        "failure_reason": "Check adjacent known events only for delivered orders.",
        "record_action": "WARN",
        "original_order_id": "dcb36b511fcac050b97cd5c05de84dc3",
        "purchased_at": "2018-06-07 19:03:12",
        "approved_at": "2018-06-12 23:31:02",
        "carrier_handoff_at": "2018-06-11 14:54:00",
        "delivered_at": "2018-06-21 15:34:32",
    }
    result.update(overrides)
    return result


def test_only_allowlisted_original_fields_are_selected_from_published_failure_json():
    sql = failed_record_preview_sql("orders", "orders.lifecycle")
    assert_read_only(sql)
    for field in ("order_id", "order_purchase_timestamp", "order_approved_at",
                  "order_delivered_carrier_date", "order_delivered_customer_date"):
        assert "'$." + field + "'" in sql
    assert "AS original_order_id" in sql
    assert "f.original_values AS" not in sql
    assert "SELECT f.original_values" not in sql
    assert "customer_id" not in sql and "customer_unique_id" not in sql
    assert "AND r.status = 'FAILED'" in sql
    assert "JOIN workspace.olist_agentic_quality.published_run p" in sql
    assert "LIMIT 20" in sql
    sql_other = failed_record_preview_sql("orders", "orders.payment_reconciliation")
    assert "AS original_order_id" in sql_other
    assert "AS purchased_at" not in sql_other
    sql_product = failed_record_preview_sql("products", "products.category")
    assert "get_json_object" not in sql_product


def test_order_15_inversion_detected_from_actual_recorded_values():
    e = normalize_failed_record_preview("orders", "orders.lifecycle", [source_row()])
    example = e["record_preview"][0]
    assert example["source_record_id"] == "orders:15"
    assert example["original_order_id"] == "dcb36b511fcac050b97cd5c05de84dc3"
    assert example["recorded_timestamps"] == [
        {"field": "purchased_at", "label": "Purchase", "value": "2018-06-07 19:03:12"},
        {"field": "approved_at", "label": "Approval", "value": "2018-06-12 23:31:02"},
        {"field": "carrier_handoff_at", "label": "Carrier handoff", "value": "2018-06-11 14:54:00"},
        {"field": "delivered_at", "label": "Customer delivery", "value": "2018-06-21 15:34:32"},
    ]
    assert len(example["chronology_violations"]) == 1
    assert example["chronology_violations"][0]["earlier_stage"] == "Approval"
    assert example["chronology_violations"][0]["later_stage"] == "Carrier handoff"
    assert example["chronology_violations"][0]["explanation"] == (
        "Carrier handoff (2018-06-11 14:54:00) is recorded before "
        "Approval (2018-06-12 23:31:02)."
    )


def test_missing_timestamps_are_unknown_not_invented():
    stages = recorded_lifecycle_evidence(source_row(
        approved_at=None, carrier_handoff_at="", delivered_at="not a date"
    ))
    assert stages["chronology_violations"] == []
    assert [x["value"] for x in stages["recorded_timestamps"]] == [
        "2018-06-07 19:03:12", None, None, None
    ]


def test_checks_adjacent_known_events_only():
    e = recorded_lifecycle_evidence(source_row(
        purchased_at="2018-07-01 12:00:00",
        approved_at=None,
        carrier_handoff_at="2018-06-30 12:00:00",
        delivered_at="2018-07-02 12:00:00",
    ))
    assert e["chronology_violations"] == []  # no skipping missing approval


def test_multiple_adjacent_inversions_are_reported_separately():
    e = recorded_lifecycle_evidence(source_row(
        purchased_at="2018-07-03 12:00:00",
        approved_at="2018-07-02 12:00:00",
        carrier_handoff_at="2018-07-01 12:00:00",
        delivered_at="2018-07-05 12:00:00",
    ))
    assert len(e["chronology_violations"]) == 2
    assert "Approval" in e["chronology_violations"][0]["explanation"]
    assert "Carrier handoff" in e["chronology_violations"][1]["explanation"]


def test_raw_source_row_payload_and_other_identifiers_never_returned():
    row = source_row(original_values=json.dumps({
        "customer_id": "SECRET_ID", "customer_unique_id": "HIDDEN_ID",
        "customer_zip_code_prefix": "12345", "order_id": "test"
    }))
    out = normalize_failed_record_preview("orders", "orders.lifecycle", [row])
    serialized = json.dumps(out)
    for forbidden in ("SECRET_ID", "HIDDEN_ID", "12345", "original_values", "customer_id"):
        assert forbidden not in serialized
    assert out["preview_source"] == "detailed_failed_records"


def test_other_order_rules_show_business_order_id_without_fabricating_timeline():
    out = normalize_failed_record_preview("orders", "orders.payment_reconciliation", [
        source_row(rule_id="orders.payment_reconciliation", original_order_id="order-abc")
    ])
    item = out["record_preview"][0]
    assert item["original_order_id"] == "order-abc"
    assert "recorded_timestamps" not in item
    assert "chronology_violations" not in item


def test_fallback_without_json_keeps_plain_internal_identifier():
    from app.nexus_domains import normalize_failed_record_sample
    out = normalize_failed_record_sample("orders", "orders.lifecycle", [{
        "published_run": "run-1", "dataset": "orders",
        "rule_id": "orders.lifecycle", "rule_action": "WARN",
        "failed_evaluations": 1373,
        "sample_failed_identifiers": '["orders:15"]'
    }])
    assert "original_order_id" not in out["record_preview"][0]
    assert "recorded_timestamps" not in out["record_preview"][0]


def test_route_exposes_verified_evidence_from_successful_sql(monkeypatch):
    from app import main
    queries = []
    def fake_sql(sql):
        assert_read_only(sql)
        queries.append(sql)
        return [source_row(original_values='{"secret":"DO_NOT_LEAK"}')]
    monkeypatch.setattr(main, "sql_query", fake_sql)
    out = failed_rule_records("orders", "orders.lifecycle")
    assert len(queries) == 1
    assert out["record_preview"][0]["original_order_id"] == "dcb36b511fcac050b97cd5c05de84dc3"
    assert "DO_NOT_LEAK" not in json.dumps(out)


def test_nexus_uses_safely_rendered_expandable_order_evidence():
    html = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()
    assert "function renderFailedRecordEvidence(parent,record,evidence,index)" in html
    assert "rows.forEach((record,index)=>renderFailedRecordEvidence(panel,record,evidence,index))" in html
    assert "Olist order ID: " in html
    assert "Internal source row: " in html
    assert "Chronology warning: " in html
    assert "record.chronology_violations" in html
    assert "record.recorded_timestamps" in html
    assert "if(index===0)card.open=true" in html
    assert "document.createElement('details')" in html
    assert ".domain-order-timeline{" in html
    assert "innerHTML=record" not in html
