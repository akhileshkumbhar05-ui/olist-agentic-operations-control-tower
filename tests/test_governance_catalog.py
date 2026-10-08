from olist_agentic.domain.metrics import METRICS
from olist_agentic.domain.rules import RULES
from olist_agentic.domain.sources import SOURCES
from olist_agentic.governance.catalog import (
    all_catalogs,
    dashboard_visual_records,
    dq_rule_records,
    metric_dictionary_records,
    source_dictionary_records,
)


def test_phase1_domain_counts_are_preserved():
    assert len(SOURCES) == 9
    assert len(RULES) == 88
    assert len(METRICS) == 13


def test_every_quality_rule_is_explainable():
    rows = dq_rule_records()
    assert len(rows) == len(RULES)
    required = {
        "business_name",
        "plain_english_description",
        "business_reason",
        "why_this_action",
        "downstream_effect",
        "example_failure",
    }
    for row in rows:
        assert all(str(row[field]).strip() for field in required)


def test_every_source_column_has_dictionary_entry():
    rows = source_dictionary_records()
    expected = sum(len(source.columns) for source in SOURCES.values())
    assert len(rows) == expected
    assert len({(row["dataset"], row["column_name"]) for row in rows}) == expected


def test_every_metric_has_governed_dictionary_entry():
    rows = metric_dictionary_records()
    assert len(rows) == len(METRICS)
    assert {row["metric_id"] for row in rows} == {metric.metric_id for metric in METRICS}


def test_dashboard_visuals_have_agent_semantics():
    for row in dashboard_visual_records():
        assert row["business_question"]
        assert row["default_interpretation"]
        assert row["caveat"]
        assert row["agent_instruction"]


def test_all_governance_tables_are_declared():
    assert set(all_catalogs()) == {
        "dq_rules",
        "source_dictionary",
        "source_contracts",
        "metric_dictionary",
        "rule_metric_impact",
        "table_catalog",
        "lineage_edges",
        "dashboard_visual_catalog",
    }
