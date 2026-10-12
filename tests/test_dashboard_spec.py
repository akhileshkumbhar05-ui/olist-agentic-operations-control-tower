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



def test_operations_axes_have_executive_labels_and_no_summed_percentage():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    ops = next(p for p in dashboard["pages"] if p["name"] == "operations")
    widgets = {item["widget"]["name"]: item["widget"] for item in ops["layout"]}
    labels = {
        "ops_state": ("Customer State", "Total Orders"),
        "ops_late": ("Customer State", "Late Deliveries"),
        "ops_state_rate": ("Customer State", "Late Delivery Rate (%)"),
        "ops_monthly_orders": ("Purchase Month", "Total Orders"),
    }
    for name, (x_label, y_label) in labels.items():
        encodings = widgets[name]["spec"]["encodings"]
        assert encodings["x"]["displayName"] == x_label
        assert encodings["y"]["displayName"] == y_label
    state_rate = widgets["ops_state_rate"]["queries"][0]["query"]
    assert state_rate["disaggregated"] is True
    assert next(field for field in state_rate["fields"] if field["name"] == "late_rate_pct")["expression"] == "`late_rate_pct`"
    assert widgets["ops_monthly_orders"]["spec"]["widgetType"] == "line"
    assert widgets["ops_monthly_orders"]["spec"]["encodings"]["x"]["scale"]["type"] == "temporal"


def test_operations_percent_kpis_show_percent_suffix():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    ops = next(p for p in dashboard["pages"] if p["name"] == "operations")
    widgets = {item["widget"]["name"]: item["widget"] for item in ops["layout"]}
    for name in ("ops_late_rate", "ops_on_time_rate", "ops_negative_review"):
        value = widgets[name]["spec"]["encodings"]["value"]
        assert value["format"]["type"] == "number-plain"
        assert value["formatTemplate"] == "{{@formatted}}%"



def test_sparse_trailing_months_excluded_only_from_monthly_trend():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    datasets = {d["name"]: "".join(d["queryLines"]) for d in dashboard["datasets"]}
    assert "orders_trend_through_aug_2018" in datasets
    assert "WHERE purchase_date < DATE '2018-09-01'" in datasets["orders_trend_through_aug_2018"]
    assert "WHERE purchase_date < DATE '2018-09-01'" not in datasets["orders"]
    ops = next(p for p in dashboard["pages"] if p["name"] == "operations")
    widgets = {row["widget"]["name"]: row["widget"] for row in ops["layout"]}
    assert widgets["ops_monthly_orders"]["queries"][0]["query"]["datasetName"] == "orders_trend_through_aug_2018"
    assert widgets["ops_state"]["queries"][0]["query"]["datasetName"] == "orders"
    assert "Sep (16 orders) and Oct (4 orders)" in "".join(widgets["ops_intro"]["multilineTextboxSpec"]["lines"])
