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


def test_gmv_summary_is_scoped_and_read_only():
    context = Context(state="RJ", start_date="2018-01-01")
    q = statements("Can I trust delivered GMV?", context, "HYBRID")
    assert "gmv_summary" in q
    sql = q["gmv_summary"]
    assert "FROM workspace.olist_semantic.v_published_orders" in sql
    assert "customer_state IN ('RJ')" in sql
    assert "purchase_date >= DATE '2018-01-01'" in sql
    assert "item_gmv" in sql and "is_delivered" in sql
    assert_read_only(sql)
    assert "gmv_summary" not in statements("Compare RJ and SP late deliveries", Context(), "ANALYTICS")


def test_gmv_trust_fallback_answers_question_not_state_rankings():
    def db(sql):
        if "dq_run_summary" in sql:
            return [{"run_id": "snapshot", "readiness": "WARNING",
                     "quality_score": 99.9805, "quarantined_records": 32,
                     "failed_rules": 5}]
        if "GROUP BY customer_state" in sql:
            return [{"customer_state": "SP", "late_deliveries": 1820,
                     "eligible_deliveries": 40494}]
        if "AS delivered_item_gmv_brl" in sql:
            return [{"delivered_item_gmv_brl": "13220248.93", "delivered_orders": 96470,
                     "accepted_orders": 99433}]
        if "dq_rule_results" in sql:
            return [{"rule_id": "orders.delivered_time", "action": "QUARANTINE",
                     "records_failed": 8, "plain_english_description":
                     "Delivered orders require a delivered timestamp.",
                     "downstream_effect": "Dependent child records are excluded."}]
        if "quarantine q" in sql:
            return [{"dataset": "orders", "distinct_quarantined": 8}]
        return []
    question = "Why were records quarantined, and can I trust the delivered GMV?"
    evidence = prepare(question, Context(), db)
    answer = fallback_answer(question, evidence)
    assert "BRL 13,220,248.93" in answer
    assert "not accounting revenue" in answer
    assert "orders.delivered_time" in answer
    assert "Trust assessment: WARNING" in answer
    assert "SP: 1,820" not in answer
    assert "**" not in answer


def test_delivery_comparison_fallback_uses_eligible_delivery_denominator():
    def db(sql):
        if "dq_run_summary" in sql:
            return [{"run_id": "snapshot", "readiness": "WARNING",
                     "quality_score": 99.98, "quarantined_records": 32,
                     "failed_rules": 5}]
        if "GROUP BY customer_state" in sql:
            return [{"customer_state": "SP", "late_deliveries": 1820,
                     "eligible_deliveries": 40494},
                    {"customer_state": "RJ", "late_deliveries": 1495,
                     "eligible_deliveries": 12350}]
        return []
    q = "Compare late delivery rates for RJ and SP"
    result = fallback_answer(q, prepare(q, Context(), db))
    assert "SP: 1,820 late out of 40,494 eligible deliveries (4.49% late)" in result
    assert "RJ: 1,495 late out of 12,350 eligible deliveries (12.11% late)" in result
    assert "7.62 percentage points" in result
    assert "No matching governance text" not in result
