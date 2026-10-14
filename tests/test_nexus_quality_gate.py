"""Live Quality Gate rule-level governance: scoped SQL, correctness, UI interaction."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi import HTTPException

from app.nexus_quality import (
    QUALITY_RULE_SQL, QUALITY_QUARANTINE_SQL, normalize_quality_gate, quality_gate,
)
from olist_agentic.domain.rules import RULES
from olist_agentic.copilot.queries import assert_read_only


RUN = "published-test-run"
FAILURES = {
    "orders.lifecycle": 1373,
    "products.category": 610,
    "orders.payment_reconciliation": 303,
    "products.fk_product_category_name": 13,
    "orders.delivered_time": 8,
}
IMPACT = {
    "orders": 8, "order_items": 8, "payments": 8, "reviews": 8,
}
HTML = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()


def test_fixed_quality_queries_are_read_only_and_run_scoped():
    for sql in (QUALITY_RULE_SQL, QUALITY_QUARANTINE_SQL):
        assert_read_only(sql)
        assert "workspace.olist_agentic_quality.published_run" in sql
        assert "LIMIT " in sql
    assert "r.run_id = p.run_id" in QUALITY_RULE_SQL
    assert "g.rule_id" in QUALITY_RULE_SQL
    assert "r.status AS observed_status" in QUALITY_RULE_SQL
    assert "r.records_failed" in QUALITY_RULE_SQL
    assert "g.action" in QUALITY_RULE_SQL
    assert "q.run_id = p.run_id" in QUALITY_QUARANTINE_SQL
    assert "q.action = 'QUARANTINE'" in QUALITY_QUARANTINE_SQL
    assert "COUNT(DISTINCT q.source_record_id)" in QUALITY_QUARANTINE_SQL
    assert "original_values" not in QUALITY_RULE_SQL + QUALITY_QUARANTINE_SQL


def rule_rows(run=RUN):
    rows = []
    for r in RULES:
        status = "FAILED" if r.rule_id in FAILURES else "PASSED"
        rows.append({
            "published_run": run, "rule_id": r.rule_id,
            "dataset": r.dataset, "business_name": r.rule_name,
            "plain_english_description": r.description or r.rule_name,
            "action": r.action, "severity": r.severity,
            "observed_status": status,
            "failed_evaluations": FAILURES.get(r.rule_id, 0),
        })
    return rows


def quarantine_rows(run=RUN):
    return [
        {"published_run": run, "dataset": dataset, "distinct_excluded_rows": count}
        for dataset, count in IMPACT.items()
    ]


def test_expected_88_controls_reconcile_with_published_sample_run():
    assert len(RULES) == 88
    result = normalize_quality_gate(rule_rows(), quarantine_rows())
    assert result["published_run"] == RUN
    assert result["scope"] == "BRAZIL_ALL_STATES"
    assert result["rule_definitions"] == result["observed_evaluations"] == 88
    assert (result["passed_definitions"], result["failed_definitions"]) == (83, 5)
    assert result["failed_warn_definitions"] == 4
    assert result["failed_quarantine_definitions"] == 1
    assert result["unobserved_definitions"] == 0
    assert result["error_definitions"] == 0
    assert result["skipped_definitions"] == 0
    assert result["failed_evaluations_total"] == 2307
    assert result["distinct_quarantined_source_rows"] == 32
    assert all(result["quarantine_by_dataset"][ds] == 8 for ds in IMPACT)
    assert len([r for r in result["rules"] if r["observed_status"] == "FAILED"]) == 5
    lifecycle = next(r for r in result["rules"] if r["rule_id"] == "orders.lifecycle")
    assert lifecycle["observed_status"] == "FAILED"
    assert lifecycle["failed_evaluations"] == 1373
    assert lifecycle["action"] == "WARN"


def test_unobserved_rule_is_never_claimed_passed():
    rows = rule_rows()
    rows[0]["observed_status"] = None
    rows[0]["failed_evaluations"] = None
    result = normalize_quality_gate(rows, quarantine_rows())
    assert result["unobserved_definitions"] == 1
    assert result["observed_evaluations"] == 87
    assert result["rules"][0]["observed_status"] is None


def test_duplicate_rule_definitions_fail_closed():
    rows = rule_rows()
    rows.append(dict(rows[0]))
    with pytest.raises(RuntimeError, match="duplicated"):
        normalize_quality_gate(rows, quarantine_rows())


def test_mixed_published_runs_fail_closed():
    rows = rule_rows()
    rows[-1]["published_run"] = "other-published-run"
    with pytest.raises(RuntimeError, match="one published run"):
        normalize_quality_gate(rows, quarantine_rows())


def test_quarantine_different_run_is_rejected():
    with pytest.raises(RuntimeError, match="does not match"):
        normalize_quality_gate(rule_rows(), quarantine_rows(run="old-run"))


def test_quality_failure_with_no_evaluations_is_invalid():
    rows = rule_rows()
    rule = next(row for row in rows if row["rule_id"] == "orders.delivered_time")
    rule["failed_evaluations"] = 0
    with pytest.raises(RuntimeError, match="requires observed"):
        normalize_quality_gate(rows, quarantine_rows())


def test_no_rows_do_not_turn_into_a_healthy_snapshot():
    with pytest.raises(RuntimeError, match="unavailable"):
        normalize_quality_gate([], [])


def test_api_executes_only_approved_published_sql(monkeypatch):
    from app import main
    statements = []
    def sql_query(statement):
        statements.append(statement)
        if statement == QUALITY_RULE_SQL:
            return rule_rows()
        if statement == QUALITY_QUARANTINE_SQL:
            return quarantine_rows()
        pytest.fail("Unexpected SQL statement")
    monkeypatch.setattr(main, "sql_query", sql_query)
    result = quality_gate()
    assert statements == [QUALITY_RULE_SQL, QUALITY_QUARANTINE_SQL]
    assert result["failed_definitions"] == 5
    assert result["distinct_quarantined_source_rows"] == 32


def test_api_sql_permission_failure_returns_503_not_static_success(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "sql_query", lambda _sql: (_ for _ in ()).throw(
        RuntimeError("PERMISSION_DENIED")
    ))
    with pytest.raises(HTTPException) as err:
        quality_gate()
    assert err.value.status_code == 503
    assert "no statuses inferred" in err.value.detail


def test_ui_scope_matrix_selected_rule_actions_and_impacts():
    for id in ("qualityWorkspace", "qualityRuleList", "qualityDetail", "qualityPreview",
               "qualityRecords", "qualityImpact", "qualityRefresh", "qualityTip"):
        assert f'id="{id}"' in HTML
    assert "fetch('/api/nexus/quality-gate'" in HTML
    assert ".content.quality-mode .cohort-switch{display:none}" in HTML
    assert "if(name==='quality'){selectState('ALL');loadQualityGate()}" in HTML
    assert "current==='quality'" in HTML
    assert "const rules=qualityData?.rules||[]" in HTML
    assert "const color=!rule?'#56788e':rule.observed_status==='FAILED'" in HTML
    assert "qualityNearestRule(ev)" in HTML
    assert "qualitySelect(r.rule_id,true)" in HTML
    assert "qualityFailedFilter" in HTML and "qualityAllFilter" in HTML
    assert "qualityPreviewFor(rule)" in HTML
    assert "renderFailedRecordEvidence($('qualityRecords'),record,evidence,i)" in HTML
    assert "investigateFailedRule(rule,qualityData.published_run,rule.dataset)" in HTML
    assert "qualityOpenSource(dataset)" in HTML
    assert "No matching published-run" not in HTML


def test_native_dashboard_and_existing_source_inspector_preserved():
    assert '<iframe id="nativeDashboard"' in HTML
    assert "id=\"domainInspector\"" in HTML
    assert "fetch('/api/nexus/domains/'+domain+'/governance'" in HTML
    assert "source_domain:selectedDomain" in HTML


def test_canvas_script_syntax_still_valid(tmp_path):
    if not shutil.which("node"):
        pytest.skip("Node not available")
    path = tmp_path / "nexus.js"
    path.write_text(HTML.rsplit("<script>", 1)[1].split("</script>", 1)[0])
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

def test_shared_kpi_strip_shows_passed_controls_on_all_nexus_workspaces():
    """The headline ratio denotes passes, not the number of evaluated rules."""
    assert 'id="nexusKpiLabel4">Controls passed</div>' in HTML
    assert 'id="nexusKpiValue4">83 / 88</div>' in HTML
    assert 'id="nexusKpiNote4">5 failed definitions</div>' in HTML
    assert "put('nexusKpiLabel4',uf==='ALL'?'Controls passed':'Late delivery rate')" in HTML
    assert "qualityData?.passed_definitions ?? 83" in HTML
    assert "qualityData?.rule_definitions ?? 88" in HTML
    assert "qualityData?.failed_definitions ?? 5" in HTML
    assert "put('nexusKpiValue4',data.passed_definitions+' / '+data.rule_definitions)" in HTML
    assert "put('nexusKpiNote4',data.failed_definitions+' failed definitions')" in HTML
    assert "put('nexusKpiValue4',data.observed_evaluations+' / '+data.rule_definitions)" not in HTML
    assert "percent(row?.late_delivery_rate_pct)" in HTML  # State-scoped KPI remains unchanged.
