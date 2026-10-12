import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "dashboard/src/Olist_Agentic_Operations_Control_Tower.lvdash.json"

def test_dashboard_source_json_structure_and_references():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    datasets = {d["name"] for d in dashboard["datasets"]}
    assert datasets == {"orders", "metric_baseline", "rule_results", "quarantine", "dictionary", "state_delivery_rates", "quality_snapshot", "failed_rule_chart", "quarantine_dataset_counts", "metric_unit_counts"}
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



def test_all_historical_months_are_included_and_sparse_coverage_is_disclosed():
    dashboard = json.loads(SPEC.read_text(encoding="utf-8"))
    datasets = {d["name"]: "".join(d["queryLines"]) for d in dashboard["datasets"]}
    assert "orders_trend_through_aug_2018" not in datasets
    assert "WHERE purchase_date < DATE '2018-09-01'" not in datasets["orders"]
    ops = next(p for p in dashboard["pages"] if p["name"] == "operations")
    widgets = {row["widget"]["name"]: row["widget"] for row in ops["layout"]}
    assert widgets["ops_monthly_orders"]["queries"][0]["query"]["datasetName"] == "orders"
    assert widgets["ops_state"]["queries"][0]["query"]["datasetName"] == "orders"
    assert "Sep 2018 (16 orders), Oct 2018 (4)" in "".join(
        widgets["ops_intro"]["multilineTextboxSpec"]["lines"]
    )
    assert "Final-month coverage may be incomplete" in "".join(
        widgets["ops_intro"]["multilineTextboxSpec"]["lines"]
    )



def test_native_worldlink_palette_is_used_without_affecting_sql_metrics():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    theme = dash["uiSettings"]["theme"]
    assert theme["selectionColor"]["light"] == "#EE2D3D"
    assert theme["canvasBackgroundColor"]["light"] == "#F5F8FF"
    assert theme["widgetBackgroundColor"]["light"] == "#FFFFFF"
    assert theme["visualizationColors"][:4] == [
        "#287DC2", "#EE2D3D", "#602CF3", "#C10D68"
    ]
    assert theme["fontFamily"] == "Roboto"
    assert theme["widgetHeaderAlignment"] == "LEFT"
    ops = next(p for p in dash["pages"] if p["name"] == "operations")
    assert len(ops["layout"]) == 11
    assert "Sep 2018 (16 orders), Oct 2018 (4)" in "".join(
        next(w["widget"]["multilineTextboxSpec"]["lines"]
             for w in ops["layout"] if w["widget"]["name"] == "ops_intro")
    )


def test_quality_page_has_distinct_rule_and_quarantine_visualizations():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    datasets = {d["name"]: "".join(d["queryLines"]) for d in dash["datasets"]}
    assert "r.records_failed > 0" in datasets["failed_rule_chart"]
    assert "workspace.olist_agentic_quality.published_run" in datasets["failed_rule_chart"]
    assert "COUNT(DISTINCT q.source_record_id)" in datasets["quarantine_dataset_counts"]
    assert "workspace.olist_agentic_quality.published_run" in datasets["quarantine_dataset_counts"]

    quality = next(p for p in dash["pages"] if p["name"] == "quality")
    widgets = {x["widget"]["name"]: x["widget"] for x in quality["layout"]}
    for name in ("quality_pass_score", "quality_rule_failures", "quality_quarantined",
                 "quality_rules", "quality_quarantine", "quality_failed_rule_chart",
                 "quality_quarantine_chart", "quality_interpretation"):
        assert name in widgets

    failures = widgets["quality_failed_rule_chart"]
    assert failures["spec"]["widgetType"] == "bar"
    assert failures["spec"]["encodings"]["x"]["displayName"] == "Failed Rule Evaluations"
    assert failures["spec"]["encodings"]["y"]["displayName"] == "Governed Rule"
    mapping = {x["value"]: x["color"]
               for x in failures["spec"]["encodings"]["color"]["scale"]["mappings"]}
    assert mapping == {"QUARANTINE": "#EE2D3D", "WARN": "#E39B2C"}
    assert "not distinct quarantined" in failures["spec"]["frame"]["description"]

    q = widgets["quality_quarantine_chart"]
    assert q["spec"]["encodings"]["y"]["displayName"] == "Distinct Source Rows"
    assert q["queries"][0]["query"]["datasetName"] == "quarantine_dataset_counts"
    text = "".join(widgets["quality_interpretation"]["multilineTextboxSpec"]["lines"])
    assert "Failed evaluations" in text
    assert "distinct quarantined source rows" in text


def test_governance_page_explains_and_charts_dictionary_without_replacing_it():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    gov = next(p for p in dash["pages"] if p["name"] == "governance")
    widgets = {x["widget"]["name"]: x["widget"] for x in gov["layout"]}
    for name in ("gov_population", "gov_calculation", "gov_caveats",
                 "gov_metric_units", "gov_readme", "gov_dictionary"):
        assert name in widgets
    units = widgets["gov_metric_units"]
    assert units["spec"]["widgetType"] == "pie"
    assert units["spec"]["encodings"]["angle"]["fieldName"] == "metric_count"
    assert units["spec"]["encodings"]["color"]["fieldName"] == "metric_unit"
    assert units["queries"][0]["query"]["datasetName"] == "metric_unit_counts"
    sql = "".join(next(ds["queryLines"] for ds in dash["datasets"]
                       if ds["name"] == "metric_unit_counts"))
    assert "workspace.olist_governance.metric_dictionary" in sql
    assert "COUNT(*)" in sql
    glossary = widgets["gov_dictionary"]
    assert glossary["spec"]["widgetType"] == "table"
    assert glossary["queries"][0]["query"]["datasetName"] == "dictionary"


def test_all_dashboard_widget_positions_are_nonoverlapping():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    for page in dash["pages"]:
        items = page["layout"]
        for i, a in enumerate(items):
            pa = a["position"]
            for b in items[i + 1:]:
                pb = b["position"]
                overlaps = (pa["x"] < pb["x"] + pb["width"]
                            and pb["x"] < pa["x"] + pa["width"]
                            and pa["y"] < pb["y"] + pb["height"]
                            and pb["y"] < pa["y"] + pa["height"])
                assert not overlaps, (page["name"],
                                      a["widget"]["name"], b["widget"]["name"])


def test_executive_quality_and_governance_have_compact_layout_and_percentage_units():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    pages = {p["name"]: {w["widget"]["name"]: w for w in p["layout"]} for p in dash["pages"]}
    quality = pages["quality"]
    score = quality["quality_pass_score"]["widget"]["spec"]["encodings"]["value"]
    assert score["format"]["type"] == "number-plain"
    assert score["format"]["decimalPlaces"] == {"type": "exact", "places": 2}
    assert score["formatTemplate"] == "{{@formatted}}%"
    assert quality["quality_interpretation"]["position"]["height"] == 2
    assert quality["quality_failed_rule_chart"]["position"]["y"] == 6
    assert quality["quality_rules"]["position"]["y"] == 12
    assert quality["quality_quarantine"]["position"]["y"] == 22
    governance = pages["governance"]
    for name in ("gov_population", "gov_calculation", "gov_caveats"):
        assert governance[name]["position"]["height"] == 2
    assert governance["gov_metric_units"]["position"]["height"] == 6
    assert governance["gov_dictionary"]["position"]["y"] == 10



def test_operations_kpis_share_the_chart_cross_filter_dataset():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    ops = next(p for p in dash["pages"] if p["name"] == "operations")
    widgets = {item["widget"]["name"]: item["widget"] for item in ops["layout"]}
    expected = {
        "ops_orders": "Accepted Orders",
        "ops_delivered": "Delivered Orders",
        "ops_gmv": "Delivered Item GMV",
        "ops_late_rate": "Late Delivery Rate",
        "ops_on_time_rate": "On-Time Delivery Rate",
        "ops_negative_review": "Negative Review Rate",
    }
    for name, measure in expected.items():
        widget = widgets[name]
        query = widget["queries"][0]["query"]
        assert query["datasetName"] == "orders", name
        assert query["disaggregated"] is False, name
        alias = f"measure({measure})"
        assert query["fields"] == [
            {"name": alias, "expression": f"MEASURE(`{measure}`)"}
        ], name
        assert widget["spec"]["encodings"]["value"]["fieldName"] == alias
    for name in ("ops_state", "ops_late", "ops_state_rate", "ops_monthly_orders"):
        assert widgets[name]["queries"][0]["query"]["datasetName"] in {
            "orders", "state_delivery_rates"
        }
    for name in ("ops_state", "ops_late"):
        assert widgets[name]["queries"][0]["query"]["datasetName"] == "orders"
        assert widgets[name]["spec"]["encodings"]["x"]["fieldName"] == "customer_state"
    intro = "".join(widgets["ops_intro"]["multilineTextboxSpec"]["lines"])
    assert "Click a customer state" in intro
    assert "clear the selection" in intro


def test_filtered_kpi_measures_reaggregate_counts_and_use_weighted_denominators():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    ds = next(ds for ds in dash["datasets"] if ds["name"] == "orders")
    sql = "".join(ds["queryLines"])
    assert "FROM workspace.olist_semantic.v_published_orders" in sql
    assert "customer_state" in sql
    assert "GROUP BY 1,2,3" in sql
    assert "SUM(CASE WHEN review_score <= 2 THEN 1 ELSE 0 END) AS negative_reviews" in sql
    assert "SUM(CASE WHEN review_score IS NOT NULL THEN 1 ELSE 0 END) AS scored_reviews" in sql
    cols = {m["displayName"]: m["expression"] for m in ds["columns"]}
    assert cols == {
        "Accepted Orders": "SUM(`total_orders`)",
        "Delivered Orders": "SUM(`delivered_orders`)",
        "Delivered Item GMV": "SUM(`delivered_item_gmv`)",
        "Late Delivery Rate": (
            "100.0 * SUM(`late_orders`) / NULLIF(SUM(`eligible_deliveries`), 0)"
        ),
        "On-Time Delivery Rate": (
            "100.0 * (SUM(`eligible_deliveries`) - SUM(`late_orders`)) "
            "/ NULLIF(SUM(`eligible_deliveries`), 0)"
        ),
        "Negative Review Rate": (
            "100.0 * SUM(`negative_reviews`) / NULLIF(SUM(`scored_reviews`), 0)"
        ),
    }
    assert all("AVG(" not in expr for expr in cols.values())
    assert all("/ NULLIF(" in cols[key] for key in (
        "Late Delivery Rate", "On-Time Delivery Rate", "Negative Review Rate"
    ))
    # National measure view remains in place as an independent reference;
    # cross-filterable counters now use the published order-level source.
    base = next(ds for ds in dash["datasets"] if ds["name"] == "metric_baseline")
    assert "FROM workspace.olist_semantic.mv_order_operations" in "".join(base["queryLines"])


def test_filtered_kpi_percentage_formats_and_governance_pages_are_preserved():
    dash = json.loads(SPEC.read_text(encoding="utf-8"))
    ops = next(p for p in dash["pages"] if p["name"] == "operations")
    widgets = {item["widget"]["name"]: item["widget"] for item in ops["layout"]}
    for name in ("ops_late_rate", "ops_on_time_rate", "ops_negative_review"):
        value = widgets[name]["spec"]["encodings"]["value"]
        assert value["formatTemplate"] == "{{@formatted}}%"
        assert value["format"]["decimalPlaces"] == {"type": "exact", "places": 2}
    quality = next(p for p in dash["pages"] if p["name"] == "quality")
    governance = next(p for p in dash["pages"] if p["name"] == "governance")
    assert len(quality["layout"]) == 9
    assert len(governance["layout"]) == 7
    assert not any(x["widget"].get("queries", [{}])[0].get("query", {}).get("datasetName") == "orders"
                   for page in (quality, governance) for x in page["layout"])
