from pipelines.semantic_publish import statements


def test_semantic_publisher_targets_new_schema_only():
    sql = statements()
    assert len(sql) == 3
    assert "CREATE SCHEMA IF NOT EXISTS workspace.olist_semantic" in sql[0]
    assert "CREATE OR REPLACE VIEW workspace.olist_semantic.v_published_orders" in sql[1]
    assert "CREATE OR REPLACE VIEW workspace.olist_semantic.mv_order_operations" in sql[2]
    assert "WITH METRICS LANGUAGE YAML" in sql[2]
    assert "FROM workspace.olist_gold.fact_orders" in sql[1]
    assert "workspace.olist_quality.published_run" in sql[1]
    assert "CREATE OR REPLACE VIEW workspace.olist_gold." not in "\n".join(sql)


def test_metric_view_contains_12_governed_metrics():
    from olist_agentic.domain.metrics import METRICS
    text = statements()[2]
    metric_names = [m.metric_id for m in METRICS if m.metric_id != "repeat_customer_rate"]
    for metric in metric_names:
        assert f"name: {metric}" in text
    assert "name: repeat_customer_rate" not in text


def test_nondefault_catalog_or_prefix_cannot_accidentally_target_old_tables():
    import pytest
    with pytest.raises(ValueError):
        statements(catalog="production")
    with pytest.raises(ValueError):
        statements(prefix="other")
