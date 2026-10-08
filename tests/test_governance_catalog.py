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


def test_curated_definitions_are_complete_and_non_placeholder():
    from olist_agentic.governance.semantics import FIELD_DETAILS
    for dataset, source in SOURCES.items():
        assert set(FIELD_DETAILS[dataset]) == set(source.columns)
    for row in source_dictionary_records():
        assert "Source field " not in row["business_definition"]
        assert row["business_definition"].strip()
        assert row["recommended_use"].strip()
        assert row["avoid_use"].strip()


def test_rule_failure_conditions_are_specific_and_action_explainable():
    for row in dq_rule_records():
        assert row["failure_condition"]
        assert row["failure_condition"] != row["business_name"]
        assert row["action"] in {"WARN", "QUARANTINE", "FAIL"}
        assert row["why_this_action"].strip()


def test_all_rules_have_explicit_metric_or_asset_impact():
    from olist_agentic.governance.catalog import rule_metric_impact_records
    impacts = rule_metric_impact_records()
    assert {row["rule_id"] for row in impacts} == {r.rule_id for r in RULES}
    assert all(row["impact_type"] in {
        "PUBLICATION_BLOCK", "POTENTIAL_EXCLUSION", "QUALITY_WARNING", "NO_DIRECT_KPI_EFFECT"
    } for row in impacts)
    assert all(row["evidence_status"] == "POTENTIAL_DEPENDENCY_NOT_OBSERVED_DELTA" for row in impacts)


def test_warnings_cannot_claim_exclusion():
    from olist_agentic.governance.catalog import rule_metric_impact_records
    actions = {rule.rule_id: rule.action for rule in RULES}
    for row in rule_metric_impact_records():
        if actions[row["rule_id"]] == "WARN":
            assert row["impact_type"] in {"QUALITY_WARNING", "NO_DIRECT_KPI_EFFECT"}
            assert row["impact_direction"] == "no_direct_row_exclusion"


def test_known_rule_rationale_is_curated():
    rows = {row["rule_id"]: row for row in dq_rule_records()}
    assert "timestamp" in rows["orders.delivered_time"]["plain_english_description"].lower()
    assert "accounting" in rows["orders.payment_reconciliation"]["why_this_action"].lower()
    assert "portuguese" in rows["products.fk_product_category_name"]["downstream_effect"].lower()


def test_source_contracts_serialize_expected_columns():
    from olist_agentic.governance.catalog import source_contract_records
    contracts = source_contract_records()
    assert len(contracts) == len(SOURCES)
    assert all(row["expected_columns"] for row in contracts)
