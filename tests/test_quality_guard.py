"""Run-scoped quality answer checks: never treat definition rows as failures."""
from olist_agentic.copilot.quality_guard import validate_quality_answer
from olist_agentic.copilot.agent import run_agent
from olist_agentic.copilot.queries import Context
from test_agent import FakeModelClient, model_item, response


def observations():
    return {
        "publication": [{
            "run_id": "published-id", "failed_rules": 5,
            "quarantined_records": 32, "readiness": "WARNING",
        }],
        "failed_rules": [
            {"rule_id": "orders.delivered_time", "action": "QUARANTINE",
             "records_failed": 8},
            {"rule_id": "orders.lifecycle", "action": "WARN", "records_failed": 19},
            {"rule_id": "products.category", "action": "WARN", "records_failed": 10},
            {"rule_id": "orders.payment_reconciliation", "action": "WARN", "records_failed": 9},
            {"rule_id": "products.category_fk", "action": "WARN", "records_failed": 2},
        ],
        "quarantine_breakdown": [
            {"dataset": name, "distinct_quarantined": 8}
            for name in ("orders", "order_items", "payments", "reviews")
        ],
        "rule_dictionary": [
            {"rule_id": "orders.delivered_time", "action": "QUARANTINE"},
            {"rule_id": "orders.required_key", "action": "QUARANTINE"},
            {"rule_id": "reviews.unique_key", "action": "QUARANTINE"},
        ],
        "gmv_summary": [{"verified_gmv_display": "BRL 13,220,248.93"}],
    }


def test_repair_false_warn_only_and_unfailed_dictionary_cause():
    wrong = (
        "32 quarantined records failed orders.required_key and "
        "reviews.unique_key. All 5 WARN rules failed. "
        "BRL 13,220,248.93 is not revenue."
    )
    answer, status = validate_quality_answer(wrong, observations())
    assert status == "sql_verified_quality_repair"
    assert "5 failed rule definitions" in answer
    assert "1 QUARANTINE" in answer and "4 WARN" in answer
    assert "orders.delivered_time: 8 failed rule evaluations" in answer
    assert "orders: 8" in answer
    assert "order_items: 8" in answer
    assert "payments: 8" in answer
    assert "reviews: 8" in answer
    assert "BRL 13,220,248.93" in answer
    assert "not audited revenue" in answer
    assert "WARN-level" in answer
    assert "orders.required_key" not in answer
    assert "reviews.unique_key" not in answer


def test_repair_missing_actual_quarantine_rule_even_with_correct_totals():
    wrong = ("32 distinct quarantined rows and 1 QUARANTINE rule plus "
             "4 WARN rules. BRL 13,220,248.93 is not revenue.")
    answer, status = validate_quality_answer(wrong, observations())
    assert status == "sql_verified_quality_repair"
    assert "orders.delivered_time" in answer


def test_allow_correct_qualified_model_narrative():
    correct = ("In the published run there are 32 distinct quarantined source "
               "records. One rule failed with action 1 QUARANTINE: "
               "orders.delivered_time. There were 4 WARN rules. "
               "BRL 13,220,248.93 is merchandise value, not accounting revenue "
               "or a financial audit. WARN impact is not independently ruled out.")
    answer, status = validate_quality_answer(correct, observations())
    assert status == "verified_model_answer"
    assert answer == correct


def test_dictionary_is_not_an_authority_for_actual_failures():
    wrong = ("32 distinct quarantined records. One rule was 1 QUARANTINE: "
             "orders.delivered_time, plus 4 WARN rules. "
             "reviews.unique_key caused the exclusions. "
             "BRL 13,220,248.93 is not revenue.")
    answer, status = validate_quality_answer(wrong, observations())
    assert status == "sql_verified_quality_repair"
    assert "reviews.unique_key" not in answer


def test_inconsistent_publication_report_is_disclosed_not_invented():
    data = observations()
    data["failed_rules"] = data["failed_rules"][:1]
    answer, status = validate_quality_answer("32 records, 5 WARN rules.", data)
    assert status == "sql_verified_quality_repair"
    assert "reports 5 failed rule definitions" in answer
    assert "returned 1" in answer
    assert "does not reconcile" in answer


def test_live_agent_path_replaces_false_claims_without_second_model_request():
    def sql(query):
        source = observations()
        if "dq_run_summary" in query:
            return source["publication"]
        if "dq_rule_results" in query:
            return source["failed_rules"]
        if "quarantine q" in query:
            return source["quarantine_breakdown"]
        if "AS delivered_item_gmv_brl" in query:
            return [{"delivered_item_gmv_brl": "13220248.93",
                     "delivered_orders": 96470, "accepted_orders": 99433}]
        if "metric_dictionary" in query:
            return [{"metric_id": "gmv"}]
        if "dq_rules LIMIT" in query:
            return source["rule_dictionary"]
        return []

    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "failed_rules"})]),
        response(text="32 quarantined source rows because all 5 WARN rules "
                      "failed orders.required_key and reviews.unique_key. "
                      "BRL 13,220,248.93 is not revenue."),
        response(text="32 quarantined source rows because 5 WARN rules failed; "
                      "BRL 13,220,248.93 is not revenue."),
    ])
    result = run_agent(
        "Why were records quarantined, and can I trust GMV?",
        Context(), sql, model, "system.ai.gpt-oss-120b",
    )
    assert result["evidence"]["answer_validation"] == "sql_verified_quality_repair"
    assert "orders.delivered_time" in result["answer"]
    assert "4 WARN" in result["answer"]
    assert "5 WARN" not in result["answer"]
    assert "gmv_summary" in result["evidence"]["tool_names"]
    assert len(model.requests) == 3


def test_reject_double_count_contradictions():
    wrong = ("32 distinct quarantined source rows, including 1 QUARANTINE "
             "orders.delivered_time. There were 4 WARN rules, actually "
             "5 WARN rules. BRL 13,220,248.93 is not revenue.")
    answer, status = validate_quality_answer(wrong, observations())
    assert status == "sql_verified_quality_repair"
    assert "5 WARN rules" not in answer


def test_accepted_model_answer_is_not_rewritten_when_quality_is_supported():
    correct = ("32 quarantined source rows. One of the 5 failed definitions was "
               "1 QUARANTINE rule orders.delivered_time; the rest were 4 WARN rules. "
               "BRL 13,220,248.93 is not recognized revenue. "
               "Warnings could affect the published GMV.")
    answer, status = validate_quality_answer(correct, observations())
    assert status == "verified_model_answer"
    assert answer == correct
