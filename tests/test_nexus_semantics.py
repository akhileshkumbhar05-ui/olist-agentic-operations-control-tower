"""Governed NEXUS semantic contracts and reproducible national SQL metrics."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app.nexus_semantics import (
    CALCULATIONS, DICTIONARY, EDGES, METRIC_IDS, METRIC_DICTIONARY_SQL,
    METRIC_EDGE_SQL, PUBLISHED, VIEW, metric_sql,
    normalize_dictionary, normalize_metric_result,
    semantic_contracts, verify_semantic_metric,
)
from olist_agentic.domain.metrics import METRICS
from olist_agentic.copilot.queries import assert_read_only


HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()


def dictionary_rows():
    return [{
        "metric_id": m.metric_id, "metric_name": m.name,
        "business_definition": m.definition, "formula_description": m.formula,
        "grain": m.grain, "population": m.assumption,
        "inclusions": "Accepted governed records satisfying the metric definition",
        "exclusions": m.exclusions, "unit": m.unit,
        "owner": m.owner, "source_object": m.source,
        "quality_dependency": "Current published run after quality gating",
        "known_caveat": m.assumption,
    } for m in METRICS]


def lineage_rows():
    return [{
        "metric_id": m.metric_id, "source_asset": "olist_gold.fact_orders",
        "target_asset": f"metric:{m.metric_id}",
        "relationship_type": "metric_definition",
        "description": m.definition,
    } for m in METRICS]


def verified_row(numerator="13220248.93", denominator=None, value="13220248.93"):
    return {
        "published_run": "active-run-1",
        "numerator": numerator,
        "denominator": denominator,
        "verified_value": value,
    }


def test_13_metrics_match_registry_and_have_fixed_executable_sql():
    assert len(METRICS) == 13
    assert len(METRIC_IDS) == 13
    assert set(CALCULATIONS) == METRIC_IDS


@pytest.mark.parametrize("metric_id", [m.metric_id for m in METRICS])
def test_metric_sql_is_fixed_read_only_and_pins_publication(metric_id):
    sql = metric_sql(metric_id)
    assert_read_only(sql)
    assert "FROM workspace.olist_agentic_quality.published_run p CROSS JOIN" in sql
    assert "workspace.olist_semantic.v_published_orders" in sql
    assert "a.numerator, a.denominator" in sql
    assert "AS verified_value" in sql
    assert sql.endswith("LIMIT 1")
    assert "original_values" not in sql
    assert "orders." not in sql  # No dynamic source table or child-row joins
    assert "customer_id" not in sql


def test_metric_sql_critical_numerators_match_existing_published_tools():
    gmv = metric_sql("gmv")
    assert "CASE WHEN is_delivered THEN COALESCE(item_gmv,0)" in gmv
    assert "freight_value" not in gmv
    late = metric_sql("late_rate")
    assert "delivery_eligible AND is_late" in late
    assert "SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END)" in late
    assert "100.0 * a.numerator / NULLIF(a.denominator,0)" in late
    aov = metric_sql("aov")
    assert "is_delivered AND item_count > 0" in aov
    repeat = metric_sql("repeat_customer_rate")
    assert "customer_unique_id IS NOT NULL" in repeat
    assert "GROUP BY customer_unique_id" in repeat
    assert "order_count > 1" in repeat
    assert "customer_id IS NOT NULL" not in repeat


def test_unregistered_metric_rejected_without_sql_injection():
    for value in ("gmv' OR 1=1", "gmv; DROP TABLE x", "UNKNOWN", ""):
        with pytest.raises(HTTPException) as error:
            metric_sql(value)
        assert error.value.status_code == 404


def test_governance_dictionary_and_lineage_queries_are_read_only_and_bounded():
    assert_read_only(METRIC_DICTIONARY_SQL)
    assert_read_only(METRIC_EDGE_SQL)
    assert "workspace.olist_governance.metric_dictionary" in METRIC_DICTIONARY_SQL
    assert "known_caveat" in METRIC_DICTIONARY_SQL
    assert "source_object" in METRIC_DICTIONARY_SQL
    assert "workspace.olist_governance.lineage_edges" in METRIC_EDGE_SQL
    assert "LIMIT 30" in METRIC_DICTIONARY_SQL
    assert "LIMIT 100" in METRIC_EDGE_SQL


def test_dictionary_metadata_and_edge_registry_are_qualified_not_runtime_lineage():
    data = normalize_dictionary(dictionary_rows(), lineage_rows(), True)
    assert data["scope"] == "NATIONAL_PUBLISHED_SNAPSHOT"
    assert len(data["metrics"]) == 13
    assert len(data["documented_edges"]) == 13
    assert data["query_source"] == VIEW
    assert data["definition_source"] == DICTIONARY
    assert data["edge_source"] == EDGES
    assert data["edge_registry_accessible"]
    assert "NOT automatically discovered Unity Catalog runtime lineage" in data["lineage_qualification"]
    assert all(e["relationship_type"] == "metric_definition" for e in data["documented_edges"])
    gmv = next(m for m in data["metrics"] if m["metric_id"] == "gmv")
    assert gmv["unit"] == "BRL"
    assert "recognized revenue" in gmv["known_caveat"]
    assert gmv["source_object"] == "gold.fact_orders"  # documented alias, not SQL result


def test_inaccessible_registry_does_not_invent_edges():
    out = normalize_dictionary(dictionary_rows(), [], False)
    assert out["edge_source"] is None
    assert out["documented_edges"] == []
    assert len(out["metrics"]) == 13


def test_missing_or_duplicate_dictionary_entries_fail_closed():
    with pytest.raises(RuntimeError, match="incomplete"):
        normalize_dictionary(dictionary_rows()[:-1], [], True)
    rows = dictionary_rows()
    rows[1]["metric_id"] = rows[0]["metric_id"]
    with pytest.raises(RuntimeError, match="duplicated"):
        normalize_dictionary(rows, [], True)
    with pytest.raises(RuntimeError, match="no governed definitions"):
        normalize_dictionary([], [], True)


def test_gmv_and_late_rate_results_contain_calculation_components():
    gmv = normalize_metric_result("gmv", [verified_row()])
    assert gmv["verified_value"] == "13220248.93"
    assert gmv["numerator"] == "13220248.93"
    assert gmv["denominator"] is None
    assert gmv["operation"] == "amount"
    assert gmv["not_accounting_revenue"] is True
    assert gmv["sql_evidence_source"] == VIEW
    assert gmv["published_run"] == "active-run-1"
    late = normalize_metric_result("late_rate", [
        verified_row(numerator="3269", denominator="48225", value="6.7786")
    ])
    assert late["verified_value"] == "6.7786"
    assert late["numerator_label"] == "Eligible late deliveries"
    assert late["denominator_label"] == "All eligible deliveries"
    assert late["denominator"] == "48225"
    assert late["not_accounting_revenue"] is False


@pytest.mark.parametrize("metric_id,numerator,denominator,value", [
    ("total_orders", "99433", None, "99433"),
    ("delivered_orders", "96470", None, "96470"),
    ("aov", "13220248.93", "91000", "145.2775"),
    ("late_rate", "1495", "12350", "12.1053"),
    ("negative_review_rate", "27", "100", "27.0000"),
    ("repeat_customer_rate", "251", "1000", "25.1000"),
    ("delivery_days", "6000", "300", "20.0000"),
    ("review_score", "350", "100", "3.5000"),
])
def test_metric_normalizer_preserves_observed_sql_without_recomputing(
    metric_id, numerator, denominator, value
):
    out = normalize_metric_result(
        metric_id, [verified_row(numerator, denominator, value)]
    )
    assert out["verified_value"] == value
    assert out["numerator"] == numerator
    assert out["denominator"] == denominator


def test_zero_denominator_returns_explicit_null_not_zero_or_infinity():
    result = normalize_metric_result("late_rate", [
        verified_row("0", "0", None)
    ])
    assert result["verified_value"] is None
    assert result["denominator"] == "0"
    with pytest.raises(RuntimeError, match="Zero-denominator"):
        normalize_metric_result("late_rate", [verified_row("0", "0", "0")])
    with pytest.raises(RuntimeError, match="unexpectedly NULL"):
        normalize_metric_result("late_rate", [verified_row("10", "100", None)])


def test_missing_publication_or_bad_numeric_data_fails_closed():
    with pytest.raises(RuntimeError, match="published run"):
        normalize_metric_result("gmv", [
            {**verified_row(), "published_run": ""}
        ])
    with pytest.raises(RuntimeError, match="Nonfinite"):
        normalize_metric_result("gmv", [verified_row(value="NaN")])
    with pytest.raises(RuntimeError, match="integral"):
        normalize_metric_result("total_orders", [verified_row("1.1", None, "1.1")])
    with pytest.raises(RuntimeError, match="one verified"):
        normalize_metric_result("gmv", [])


def test_api_contracts_and_verify_use_only_approved_sql(monkeypatch):
    from app import main
    executed = []
    def sql_query(statement):
        executed.append(statement)
        if statement == METRIC_DICTIONARY_SQL:
            return dictionary_rows()
        if statement == METRIC_EDGE_SQL:
            return lineage_rows()
        if statement == metric_sql("gmv"):
            return [verified_row()]
        pytest.fail("Unapproved SQL was submitted")
    monkeypatch.setattr(main, "sql_query", sql_query)
    dictionary = semantic_contracts()
    result = verify_semantic_metric("gmv")
    assert len(dictionary["metrics"]) == 13
    assert len(dictionary["documented_edges"]) == 13
    assert result["verified_value"] == "13220248.93"
    assert executed == [
        METRIC_DICTIONARY_SQL, METRIC_EDGE_SQL, metric_sql("gmv")
    ]


def test_optional_lineage_registry_query_can_fail_without_fabricating_edges(monkeypatch):
    from app import main
    def sql_query(statement):
        if statement == METRIC_DICTIONARY_SQL:
            return dictionary_rows()
        if statement == METRIC_EDGE_SQL:
            raise RuntimeError("lineage_edges permission denied")
        pytest.fail("Unexpected SQL")
    monkeypatch.setattr(main, "sql_query", sql_query)
    out = semantic_contracts()
    assert len(out["metrics"]) == 13
    assert not out["edge_registry_accessible"]
    assert not out["documented_edges"]


def test_core_dictionary_or_sql_failure_returns_503(monkeypatch):
    from app import main
    def fail(_statement):
        raise RuntimeError("PERMISSION_DENIED")
    monkeypatch.setattr(main, "sql_query", fail)
    with pytest.raises(HTTPException) as err:
        semantic_contracts()
    assert err.value.status_code == 503
    with pytest.raises(HTTPException) as err:
        verify_semantic_metric("gmv")
    assert err.value.status_code == 503


def test_html_has_accessible_metric_registry_scope_receipt_and_safe_rendering():
    for name in ("semanticWorkspace", "semanticCatalog", "semanticDefinition",
                 "semanticVerification", "semanticVerify", "semanticAsk",
                 "semanticNumerator", "semanticDenominator", "semanticEdges",
                 "semanticLineageQualification", "semanticFocus", "semanticStatus"):
        assert f'id="{name}"' in HTML
    assert ".content.semantic-mode .cohort-switch{display:none}" in HTML
    assert "if(name==='semantics'){selectState('ALL');loadSemanticContracts()}" in HTML
    assert "fetch('/api/nexus/semantic-contracts'" in HTML
    assert "'/verify'" in HTML
    assert "function semanticSelect(id)" in HTML
    assert "function verifySemanticMetric()" in HTML
    assert "function semanticFocusNode(index)" in HTML
    assert "semanticVerification?.verified_value" in HTML
    assert "semantics" in HTML
    assert "Documented registry edge:" in HTML
    assert "NOT independently captured Databricks runtime lineage" in HTML
    assert "original_values" not in HTML[HTML.index("function semanticMetric()"):HTML.index("function drawSemantic(")]
    assert "metric_id" in HTML
    assert "textContent=metric.metric_name" in HTML
    assert '<iframe id="nativeDashboard"' in HTML


def test_script_parses_with_node(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node.js is not installed")
    script = HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0]
    path = tmp_path / "nexus-semantic.js"
    path.write_text(script, encoding="utf-8")
    output = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert output.returncode == 0, output.stderr
