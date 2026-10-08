from pipelines.independent_etl import ETLConfig
from pipelines.foundation_job import plan
from olist_agentic.domain.rules import RULES
from olist_agentic.domain.sources import SOURCES


def test_independent_namespaces_and_source_counts():
    c = ETLConfig()
    assert c.schema("bronze") == "olist_agentic_bronze"
    assert c.schema("silver") == "olist_agentic_silver"
    assert c.schema("gold") == "olist_agentic_gold"
    assert c.schema("quality") == "olist_agentic_quality"
    assert c.table("gold", "fact_orders") == "workspace.olist_agentic_gold.fact_orders"
    assert str(c.volume_path) == "/Volumes/workspace/olist_agentic_bronze/raw"
    assert len(SOURCES) == 9
    assert len(RULES) == 88


def test_old_poc_prefix_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        ETLConfig(prefix="olist")
    with pytest.raises(ValueError):
        ETLConfig(prefix="olist_agentic_gold")
    with pytest.raises(ValueError):
        ETLConfig(catalog="workspace; DROP SCHEMA old")


def test_rule_records_are_serializable():
    row = RULES[0].record()
    assert row["rule_id"]
    assert row["columns"].startswith("[")


def test_foundation_does_not_depend_on_old_poc_tables():
    p = plan()
    assert p["read_only_dependencies"] == []
    assert all("olist_agentic_" in name for name in p["write_schemas"])
    assert p["steps"] == [
        "independent_etl",
        "governance_publish",
        "semantic_publish",
        "semantic_validation",
    ]


def test_audit_finalizer_rejects_invalid_status_and_run_ids():
    from pipelines.independent_etl import finalize_audit, ETLConfig
    import pytest

    class FakeSpark:
        def sql(self, statement):
            raise AssertionError("Should never write for invalid inputs")

    with pytest.raises(ValueError):
        finalize_audit(FakeSpark(), ETLConfig(), "invalid", "SUCCEEDED")
    with pytest.raises(ValueError):
        finalize_audit(FakeSpark(), ETLConfig(), "a" * 32, "RUNNING")


def test_audit_finalizer_targets_only_agentic_quality():
    from pipelines.independent_etl import finalize_audit, ETLConfig

    class FakeSpark:
        statements = []
        def sql(self, statement):
            self.statements.append(statement)

    spark = FakeSpark()
    finalize_audit(spark, ETLConfig(), "a" * 32, "SUCCEEDED")
    assert len(spark.statements) == 1
    assert "workspace.olist_agentic_quality.pipeline_run_audit" in spark.statements[0]
    assert "status = 'STAGED'" in spark.statements[0]
