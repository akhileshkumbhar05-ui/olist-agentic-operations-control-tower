import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "dashboard/src/Olist_Agentic_Operations_Control_Tower.lvdash.json"

def test_dashboard_source_json_structure_and_references():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    datasets = {d["name"] for d in dashboard["datasets"]}
    assert datasets == {"orders", "metric_baseline", "rule_results", "quarantine", "dictionary", "state_delivery_rates", "quality_snapshot"}
    assert len(dashboard["pages"]) == 3
    names = set()
    for page in dashboard["pages"]:
        assert page["layout"]
        for item in page["layout"]:
            name = item["widget"]["name"]
            assert name not in names
            names.add(name)
            pos = item["position"]
            assert pos["x"] >= 0 and pos["y"] >= 0
            assert pos["x"] + pos["width"] <= 6
            for query in item["widget"].get("queries", []):
                assert query["query"]["datasetName"] in datasets

def test_dashboard_uses_published_run_and_governance_not_raw():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    queries = "\n".join(" ".join(d["queryLines"]) for d in dashboard["datasets"])
    assert "workspace.olist_semantic.v_published_orders" in queries
    assert "workspace.olist_semantic.mv_order_operations" in queries
    assert "workspace.olist_governance.dq_rules" in queries
    assert "workspace.olist_agentic_quality.published_run" in queries
    assert "workspace.olist_agentic_bronze" not in queries
    assert "workspace.olist_bronze" not in queries
    assert "original_values" not in queries


def test_table_widgets_use_current_lakeview_spec_and_headers_have_breaks():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    tables = []
    for page in dash["pages"]:
        for item in page["layout"]:
            widget = item["widget"]
            if widget.get("spec", {}).get("widgetType") == "table":
                tables.append(widget)
                assert widget["spec"]["version"] == 2
                assert all("fieldName" in col and "displayName" in col
                           for col in widget["spec"]["encodings"]["columns"])
            if "multilineTextboxSpec" in widget and len(widget["multilineTextboxSpec"]["lines"]) > 1:
                assert widget["multilineTextboxSpec"]["lines"][0].endswith("\n\n")
    assert len(tables) == 3


def test_dashboard_rates_use_eligible_deliveries():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    state_sql = "".join(next(d["queryLines"] for d in dash["datasets"] if d["name"] == "state_delivery_rates"))
    assert "NULLIF(SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END), 0)" in state_sql
    assert "AS eligible_deliveries" in state_sql
    ops = next(p for p in dash["pages"] if p["name"] == "operations")
    assert len(ops["layout"]) >= 10
