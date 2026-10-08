from olist_agentic.copilot.queries import Context, route, statements, assert_read_only
from olist_agentic.copilot.engine import prepare, fallback_answer, retrieve_knowledge
import pytest


def test_routing_and_state_contract():
    assert route("Why did 32 records get quarantined and can I trust GMV?", Context()) == "HYBRID"
    assert route("Compare late delivery rates in RJ and SP", Context()) == "ANALYTICS"
    assert route("What does source field mean?", Context()) == "KNOWLEDGE"
    with pytest.raises(ValueError):
        Context(state="RJ' OR 1=1")
    with pytest.raises(ValueError):
        Context(start_date="2026-13-31")


def test_sql_uses_eligible_denominator_and_is_read_only():
    q = statements("Compare RJ and SP late deliveries", Context(), "ANALYTICS")
    sql = q["state_delivery"]
    assert "delivery_eligible" in sql
    assert "customer_state IN ('RJ','SP')" in sql
    assert "NULLIF(SUM(CASE WHEN delivery_eligible" in sql
    for v in q.values():
        assert_read_only(v)
    with pytest.raises(ValueError):
        assert_read_only("DROP TABLE workspace.olist_gold.fact_orders")


def test_published_run_grounding_and_governance_retrieval():
    pub = [{"run_id": "abc123", "readiness": "WARNING", "quality_score": 99.98,
            "quarantined_records": 32, "failed_rules": 5}]
    def db(sql):
        if "dq_run_summary" in sql:
            return pub
        if "metric_dictionary" in sql:
            return [{"metric_id": "gmv", "metric_name": "Delivered Item GMV",
                     "business_definition": "Accepted delivered item price"}]
        return []
    evidence = prepare("What does GMV mean and can I trust quality?", Context(), db)
    assert evidence["route"] == "HYBRID"
    assert evidence["published_run"] == "abc123"
    assert "WARNING" in fallback_answer("question", evidence)
    assert any(x["id"] == "gmv" for x in evidence["knowledge"])


def test_filters_applied_before_aggregation():
    context = Context(state="RJ", start_date="2017-01-01", end_date="2018-12-31")
    q = statements("Compare São Paulo delivery", context, "ANALYTICS")["state_delivery"]
    assert "customer_state IN ('RJ')" in q
    assert "purchase_date >= DATE '2017-01-01'" in q


def test_missing_published_snapshot_fails_closed():
    with pytest.raises(ValueError, match="one published"):
        prepare("How is data quality?", Context(), lambda sql: [])
