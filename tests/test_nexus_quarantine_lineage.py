"""Read-only published quarantine lineage, with verified parent-order matches."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app.nexus_domains import (
    QUARANTINE_PREVIEW_LIMIT,
    quarantine_lineage_sql,
    normalize_quarantine_lineage,
    domain_quarantine_lineage,
)
from olist_agentic.copilot.queries import assert_read_only


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()


def payment_row(**overrides):
    row = {
        "published_run": "published-123",
        "dataset": "payments",
        "source_record_id": "payments:314",
        "rule_id": "payments.accepted_parent",
        "failure_reason": "Accepted parent missing: orders",
        "action": "QUARANTINE",
        "original_order_id": "olist-order-abc",
        "parent_source_record_id": "orders:15",
        "parent_rule_ids": "orders.delivered_time",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("dataset", [
    "payments", "order_items", "reviews", "orders",
    "customers", "products", "sellers", "geolocation", "translation",
])
def test_lineage_query_select_only_run_scoped_and_bounded(dataset):
    sql = quarantine_lineage_sql(dataset)
    # General AI SQL has no access to raw source JSON. Fixed app SQL limits
    # reads to the approved scalar order_id under an allowlisted dataset.
    # The general LLM guard intentionally permits only SELECT statements.
    # This fixed, code-owned application query uses a read-only CTE. Keep the
    # model SQL guard unchanged and validate the CTE's restricted shape here.
    assert sql.startswith("WITH parent_orders AS (SELECT ")
    safe_sql = sql.replace("original_values", "approved_order_id_json")
    assert ";" not in safe_sql and "--" not in safe_sql and "/*" not in safe_sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|MERGE|COPY|GRANT|REVOKE|EXECUTE)\b", safe_sql, re.I)
    assert safe_sql.count(" SELECT ") >= 1
    assert "workspace.olist_agentic_quality.quarantine" in sql
    assert "workspace.olist_agentic_quality.published_run" in sql
    assert "p.run_id = q.run_id" in sql
    assert f"q.dataset = '{dataset}'" in sql
    assert "q.action = 'QUARANTINE'" in sql
    assert f"LIMIT {QUARANTINE_PREVIEW_LIMIT}" in sql
    assert "SELECT q.original_values" not in sql
    assert "q.original_values AS" not in sql
    assert "customer_id" not in sql
    assert "payment_value" not in sql
    if dataset in ("payments", "order_items", "reviews"):
        assert "po.run_id = q.run_id" in sql
        assert "po.original_order_id = get_json_object(q.original_values, '$.order_id')" in sql
    else:
        assert "LEFT JOIN parent_orders po" not in sql
    with pytest.raises(ValueError):
        quarantine_lineage_sql("payments'; DROP TABLE x")


def test_payments_cascade_verified_from_recorded_reason_and_same_run_parent():
    data = normalize_quarantine_lineage("payments", [payment_row()])
    assert data["published_run"] == "published-123"
    assert data["verified_parent_matches"] == 1
    assert data["record_preview"][0] == {
        "source_record_id": "payments:314",
        "original_order_id": "olist-order-abc",
        "rule_id": "payments.accepted_parent",
        "failure_reason": "Accepted parent missing: orders",
        "action": "QUARANTINE",
        "recorded_accepted_parent_reason": True,
        "parent_order_exclusion_verified": True,
        "parent_order_source_record_id": "orders:15",
        "parent_order_rule_ids": ["orders.delivered_time"],
    }
    assert "same-run matching quarantined parent" in data["note"]


def test_recorded_cascade_without_parent_match_is_not_presented_as_verified():
    data = normalize_quarantine_lineage(
        "payments", [payment_row(parent_source_record_id=None, parent_rule_ids=None)]
    )
    item = data["record_preview"][0]
    assert item["recorded_accepted_parent_reason"]
    assert not item["parent_order_exclusion_verified"]
    assert item["parent_order_source_record_id"] is None
    assert item["parent_order_rule_ids"] == []
    assert data["verified_parent_matches"] == 0


def test_direct_quarantine_does_not_infer_parent_cascade():
    data = normalize_quarantine_lineage(
        "orders", [payment_row(
            dataset="orders", source_record_id="orders:15",
            rule_id="orders.delivered_time",
            failure_reason="Missing delivery timestamp",
            original_order_id="olist-order-abc",
            parent_source_record_id=None, parent_rule_ids=None,
        )]
    )
    assert not data["record_preview"][0]["parent_order_exclusion_verified"]
    assert not data["record_preview"][0]["recorded_accepted_parent_reason"]


def test_unrelated_rule_with_parent_match_not_verified_as_accepted_parent():
    data = normalize_quarantine_lineage(
        "payments", [payment_row(rule_id="payments.unique_key")]
    )
    item = data["record_preview"][0]
    assert not item["recorded_accepted_parent_reason"]
    assert not item["parent_order_exclusion_verified"]


@pytest.mark.parametrize("bad", [
    payment_row(dataset="reviews"),
    payment_row(action="WARN"),
    payment_row(source_record_id=""),
    payment_row(rule_id=""),
])
def test_unexpected_quarantine_rows_fail_closed(bad):
    with pytest.raises(RuntimeError):
        normalize_quarantine_lineage("payments", [bad])


def test_conflicting_run_ids_fail_closed():
    with pytest.raises(RuntimeError):
        normalize_quarantine_lineage(
            "payments", [payment_row(), payment_row(published_run="other-run")]
        )


def test_zero_rows_does_not_invent_lineage():
    output = normalize_quarantine_lineage("payments", [])
    assert output["record_preview"] == []
    assert output["verified_parent_matches"] == 0
    assert output["published_run"] is None


def test_read_only_app_route_and_bounded_evidence(monkeypatch):
    from app import main
    seen = []
    def execute(sql):
        seen.append(sql)
        return [payment_row()]
    monkeypatch.setattr(main, "sql_query", execute)
    result = domain_quarantine_lineage("payments")
    assert len(seen) == 1
    assert result["verified_parent_matches"] == 1
    assert result["source"][0] == "workspace.olist_agentic_quality.quarantine"


def test_sql_error_is_503_not_a_fabricated_dependency(monkeypatch):
    from app import main
    def fail(sql):
        raise RuntimeError("Databricks query denied")
    monkeypatch.setattr(main, "sql_query", fail)
    with pytest.raises(HTTPException) as exc:
        domain_quarantine_lineage("payments")
    assert exc.value.status_code == 503
    assert "No dependency is inferred" in exc.value.detail


def test_frontend_shows_lineage_only_for_nonzero_quarantined_source_rows():
    assert 'id="domainLineageTools"' in HTML
    assert 'id="domainLineageOpen"' in HTML
    assert 'id="domainLineagePanel"' in HTML
    assert 'id="domainLineageRecords"' in HTML
    assert "const hasQuarantine=e.distinct_quarantined_source_rows>0;" in HTML
    assert "inspectQuarantineLineage(domainContractData.dataset,domainLineagePublishedRun)" in HTML
    assert "evidence.published_run&&evidence.published_run!==runId" in HTML
    assert "record.recorded_accepted_parent_reason" in HTML
    assert "record.parent_order_exclusion_verified" in HTML
    assert "parent_order_source_record_id" in HTML
    assert "View quarantine lineage" in HTML
    assert "document.createElement('div')" in HTML
    assert "parent.appendChild(card)" in HTML
    assert "record.original_values" not in HTML
    assert "++domainLineageSequence" in HTML
    assert '<iframe id="nativeDashboard"' in HTML


def test_nexus_script_still_valid_javascript(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable")
    path = tmp_path / "nexus.js"
    path.write_text(HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0])
    res = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
