"""Regression tests for the run-grounded Data Constellation inspector."""
from pathlib import Path
import re
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app.nexus_domains import (
    UI_DOMAIN_NAMES, contract_payload, domain_governance, governance_sql,
    normalize_governance, resolve_domain,
)
from olist_agentic.copilot.queries import assert_read_only


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text(encoding="utf-8")
CSS = HTML.split("<style>", 1)[1].split("</style>", 1)[0]


def test_nine_ui_domains_match_actual_source_registry():
    assert set(UI_DOMAIN_NAMES) == {
        "orders", "customers", "items", "payments", "reviews",
        "products", "sellers", "geo", "translations",
    }
    assert len(set(UI_DOMAIN_NAMES.values())) == 9
    assert resolve_domain("items") == "order_items"
    assert resolve_domain("geo") == "geolocation"
    assert resolve_domain("translations") == "translation"


@pytest.mark.parametrize("bad", [
    "unknown", "orders' OR 1=1", "../orders", "ORDERS", "olists_orders",
    "orders; DROP TABLE x", "", "source_dictionary",
])
def test_domain_lookup_is_strict_allowlist(bad):
    with pytest.raises(HTTPException) as exc:
        resolve_domain(bad)
    assert exc.value.status_code == 404


def test_relationships_keys_and_grains_from_registry_not_inferred():
    items = contract_payload("items")
    assert items["dataset"] == "order_items"
    assert items["candidate_key"] == ["order_id", "order_item_id"]
    assert "One numbered item" in items["grain"]
    links = {(x["from_dataset"], x["from_key"], x["to_dataset"], x["to_key"])
             for x in items["relationships"]}
    assert ("order_items", "order_id", "orders", "order_id") in links
    assert ("order_items", "product_id", "products", "product_id") in links
    assert ("order_items", "seller_id", "sellers", "seller_id") in links
    assert "join" in items["caution"].lower() or "Multiple" in items["context"]

    geo = contract_payload("geo")
    assert geo["candidate_key"] == []
    assert geo["relationships"] == []
    assert "not a live execution trace" in geo["relationship_scope"]

    customers = contract_payload("customers")
    assert "persistent identity" in customers["grain"]


def test_bounded_sql_only_from_approved_governance_objects():
    for dataset in UI_DOMAIN_NAMES.values():
        fields, quality = governance_sql(dataset)
        for sql in (fields, quality):
            assert_read_only(sql)
            assert f"'{dataset}'" in sql
            assert "LIMIT 100" in sql
            assert "workspace.olist_governance" in sql
        assert "workspace.olist_agentic_quality.published_run" in quality
        assert "r.run_id = p.run_id" in quality
        assert "COUNT(DISTINCT q.source_record_id)" in quality
    with pytest.raises(ValueError):
        governance_sql("orders' OR 1=1")


def test_observed_rule_results_not_confused_with_documented_rule_definitions():
    evidence = normalize_governance("orders", [
        {"dataset": "orders", "column_name": "order_id",
         "business_definition": "Order ID", "recommended_use": "Join key",
         "avoid_use": "Not a revenue field"}
    ], [
        {"rule_id": "orders.delivered_time", "business_name": "Delivery date",
         "plain_english_description": "Delivered orders need a delivered date",
         "action": "QUARANTINE", "observed_status": "FAILED",
         "records_failed": "8", "published_run": "run-1",
         "distinct_quarantined": "8"},
        {"rule_id": "orders.schema", "business_name": "Schema",
         "plain_english_description": "Exact columns",
         "action": "FAIL", "observed_status": "PASSED",
         "records_failed": "0", "published_run": "run-1",
         "distinct_quarantined": "8"},
        {"rule_id": "orders.example", "business_name": "Extra rule",
         "plain_english_description": "Metadata not yet evaluated",
         "action": "WARN", "observed_status": None,
         "records_failed": None, "published_run": "run-1",
         "distinct_quarantined": "8"},
    ])
    assert evidence["published_run"] == "run-1"
    assert evidence["rule_definitions"] == 3
    assert evidence["observed_failed_definitions"] == 1
    assert evidence["unobserved_definitions"] == 1
    assert evidence["distinct_quarantined_source_rows"] == 8
    assert evidence["rules"][0]["rule_id"] == "orders.delivered_time"
    assert evidence["rules"][-1]["observed_status"] == "PASSED" or evidence["rules"][-1]["observed_status"] is None
    assert evidence["source"][0] == "workspace.olist_governance.source_dictionary"


def test_inconsistent_or_unverified_runtime_results_fail_closed():
    for rows in ([], [
        {"rule_id": "orders.schema", "published_run": "run-1",
         "distinct_quarantined": None},
    ], [
        {"rule_id": "orders.schema", "published_run": "run-1",
         "distinct_quarantined": "0"},
        {"rule_id": "orders.key", "published_run": "run-2",
         "distinct_quarantined": "0"},
    ]):
        with pytest.raises(RuntimeError):
            normalize_governance("orders", [], rows)


def test_governance_route_reuses_existing_read_only_databricks_client(monkeypatch):
    from app import main as main_app
    requests = []

    def db(sql):
        requests.append(sql)
        if "source_dictionary" in sql:
            return [{"dataset": "payments", "column_name": "payment_value",
                     "business_definition": "Payment", "recommended_use": "per order",
                     "avoid_use": "not revenue"}]
        return [{"rule_id": "payments.schema", "business_name": "Schema contract",
                 "plain_english_description": "Required columns", "action": "FAIL",
                 "observed_status": "PASSED", "records_failed": 0,
                 "published_run": "snapshot1", "distinct_quarantined": 0}]

    monkeypatch.setattr(main_app, "sql_query", db)
    result = domain_governance("payments")
    assert result["dataset"] == "payments"
    assert result["fields"][0]["column_name"] == "payment_value"
    assert result["rule_definitions"] == 1
    assert result["observed_failed_definitions"] == 0
    assert result["distinct_quarantined_source_rows"] == 0
    assert len(requests) == 2
    for q in requests:
        assert_read_only(q)


def test_runtime_query_failure_returns_503_not_fake_zero_quality(monkeypatch):
    from app import main as main_app
    monkeypatch.setattr(main_app, "sql_query",
                        lambda q: (_ for _ in ()).throw(RuntimeError("Warehouse inaccessible")))
    with pytest.raises(HTTPException) as exc:
        domain_governance("orders")
    assert exc.value.status_code == 503
    assert "temporarily unavailable" in exc.value.detail


def test_ui_canvas_selection_launches_real_inspector_and_ai_handoff():
    assert 'id="domainInspector" hidden' in HTML
    assert 'id="domainPicker"' in HTML
    assert 'id="domainAsk"' in HTML
    assert "else{inspectDomain(domains[idx],true);" in HTML
    assert "if(name==='network')inspectDomain('orders')" in HTML
    assert "fetch('/api/nexus/domains/'+domain" in HTML
    assert "fetch('/api/nexus/domains/'+domain+'/governance'" in HTML
    assert "openDrawer();" in HTML
    assert "domainInvestigationPrompt='For the Olist '" in HTML
    assert "const questionScope=question===domainInvestigationPrompt?'ALL':agentStateScope(question)" in HTML
    assert "document.createElement('div')" in HTML
    assert "domainRecord(" in HTML
    assert ".domain-inspector[hidden]{display:none}" in CSS
    assert '<iframe id="nativeDashboard"' in HTML
    assert "fetch('/api/ask'" in HTML


def test_nexus_javascript_syntax_if_node_available(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js unavailable; static UI checks still exercised")
    code = HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "nexus_ui_script.js"
    path.write_text(code, encoding="utf-8")
    subprocess.run(["node", "--check", str(path)], check=True, capture_output=True, text=True)
