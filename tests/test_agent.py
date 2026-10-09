"""Contract tests for bounded Olist model-driven tool calling.

No Databricks API or live LLM is called by these tests.
"""
from types import SimpleNamespace
import json
import pytest

from olist_agentic.copilot.agent import run_agent, TOOL_SOURCES, _needs_state_delivery, summarize_failed_rule_definitions
from olist_agentic.copilot.queries import Context


def model_item(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        type="function_call", name=name, arguments=json.dumps(arguments),
        call_id=call_id, model_dump=lambda exclude_none=True: {
            "type": "function_call", "name": name,
            "arguments": json.dumps(arguments), "call_id": call_id,
        },
    )


class FakeModelClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []
        self.responses = self

    def create(self, **kw):
        self.requests.append(kw)
        if not self.outputs:
            raise AssertionError("Unexpected extra model request")
        return self.outputs.pop(0)


def response(items=(), text=""):
    return SimpleNamespace(output=list(items), output_text=text)


def fake_sql(sql):
    if "dq_run_summary" in sql:
        return [{
            "run_id": "published-id", "readiness": "WARNING",
            "quality_score": 99.9805, "failed_rules": 5,
            "quarantined_records": 32, "critical_failures": 0
        }]
    if "GROUP BY customer_state" in sql:
        return [
            {"customer_state": "RJ", "late_deliveries": 1495,
             "eligible_deliveries": 12350},
            {"customer_state": "SP", "late_deliveries": 1820,
             "eligible_deliveries": 40494},
        ]
    if "AS delivered_item_gmv_brl" in sql:
        return [{"delivered_item_gmv_brl": "13220248.93",
                 "delivered_orders": 96470, "accepted_orders": 99433}]
    if "dq_rule_results" in sql:
        return [{"rule_id": "orders.delivered_time", "action": "QUARANTINE",
                 "records_failed": 8}]
    if "quarantine q" in sql:
        return [{"dataset": "orders", "distinct_quarantined": 8}]
    if "metric_dictionary" in sql:
        return [{"metric_id": "gmv", "business_definition":
                 "Delivered merchandise value, not revenue"}]
    return []


def test_model_selects_sql_tool_and_synthesizes():
    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "state_delivery"})]),
        response(text="RJ is 12.11% late and SP is 4.49% late. "
                      "Source: workspace.olist_semantic.v_published_orders"),
    ])
    result = run_agent("Compare late delivery rates for RJ and SP",
                       Context(), fake_sql, model, "system.ai.gpt-oss-120b")
    assert result["evidence"]["model_selected_tools"] == ["state_delivery"]
    assert result["evidence"]["tool_names"] == ["publication", "state_delivery"]
    assert "workspace.olist_semantic.v_published_orders" in result["evidence"]["sources"]
    assert len(model.requests) == 2
    assert model.requests[0]["model"] == "system.ai.gpt-oss-120b"
    assert model.requests[0]["tools"][0]["type"] == "function"
    assert any(x.get("type") == "function_call_output"
               for x in model.requests[1]["input"])


def test_unrequested_mandatory_hybrid_evidence_fetched_before_final():
    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "gmv_summary"})]),
        response(text="Premature unsupported answer"),
        response(text="Delivered GMV is BRL 13,220,248.93, "
                      "with 32 source rows quarantined. "
                      "Source: workspace.olist_semantic.v_published_orders"),
    ])
    result = run_agent("Why were records quarantined, and can I trust delivered GMV?",
                       Context(), fake_sql, model, "system.ai.gpt-oss-120b")
    assert "gmv_summary" in result["evidence"]["model_selected_tools"]
    assert {"failed_rules", "quarantine_breakdown", "metric_dictionary"} <= set(
        result["evidence"]["tool_names"])
    assert result["answer"] != "Premature unsupported answer"
    assert len(model.requests) == 3
    assert "using ONLY the verified evidence" in model.requests[2]["input"][-1]["content"]


def test_unknown_model_tool_does_not_execute_sql():
    seen = []
    def sql(statement):
        seen.append(statement)
        return fake_sql(statement)
    model = FakeModelClient([
        response([model_item("delete_all", {"tool": "publication"})]),
    ])
    with pytest.raises(ValueError, match="unsupported function"):
        run_agent("Compare RJ and SP", Context(), sql, model, "system.ai.gpt-oss-120b")
    assert len(seen) == 1  # only the required publication lookup


def test_no_model_tool_call_not_reported_as_agentic():
    model = FakeModelClient([response(text="This is a plausible unsourced answer")])
    with pytest.raises(RuntimeError, match="did not actually invoke"):
        run_agent("Hello", Context(), fake_sql, model, "system.ai.gpt-oss-120b")


def test_requires_approved_gateway_model():
    with pytest.raises(ValueError, match="approved Unity Gateway"):
        run_agent("Hello", Context(), fake_sql, None, "external.example-model")


def test_model_tool_allowlist_covers_reviewed_sql_templates():
    assert "publication" in TOOL_SOURCES
    assert set(TOOL_SOURCES) == {
        "publication", "state_delivery", "gmv_summary",
        "failed_rules", "quarantine_breakdown",
        "metric_dictionary", "rule_dictionary", "source_dictionary",
    }


def test_hybrid_five_sequential_tools_forces_grounded_synthesis():
    """Regression: multi-tool question must not fail on the old 3-round cap."""
    selected = ["gmv_summary", "failed_rules", "quarantine_breakdown",
                "metric_dictionary", "rule_dictionary"]
    outputs = [
        response([model_item(
            "fetch_governed_evidence", {"tool": tool}, call_id=f"call-{i}")])
        for i, tool in enumerate(selected)
    ]
    outputs.append(response(
        text="32 distinct quarantined source rows, five failed rule definitions; "
             "delivered item GMV is BRL 13,220,248.93, not audited revenue. "
             "Sources: workspace.olist_agentic_quality.quarantine and "
             "workspace.olist_semantic.v_published_orders."
    ))
    model = FakeModelClient(outputs)
    q = ("Why were 32 source records quarantined, and can I trust delivered "
         "GMV despite data-quality failures? Explain published quality rules.")
    result = run_agent(q, Context(), fake_sql, model, "system.ai.gpt-oss-120b")

    assert result["evidence"]["model_selected_tools"] == selected
    assert {"publication", "gmv_summary", "failed_rules",
            "quarantine_breakdown", "metric_dictionary", "rule_dictionary"} <= set(
                result["evidence"]["tool_names"])
    assert "state_delivery" not in result["evidence"]["tool_names"]
    assert "not audited revenue" in result["answer"]
    assert len(model.requests) == 6
    assert "tools" not in model.requests[-1]  # forced, no further tool calls
    assert "verified evidence" in model.requests[-1]["input"][-1]["content"]
    first_available = model.requests[0]["tools"][0]["parameters"]["properties"]["tool"]["enum"]
    assert "state_delivery" not in first_available
    assert "source_dictionary" not in first_available
    assert "publication" not in first_available


def test_hybrid_final_without_required_evidence_retrieves_it_first():
    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "quarantine_breakdown"})]),
        response(text="I could guess a total from memory"),
        response(text="The rules quarantined 32 source records; the scoped "
                      "delivered-item GMV comes from workspace.olist_semantic.v_published_orders."),
    ])
    result = run_agent("Why were records quarantined and can I trust delivered GMV?",
                       Context(), fake_sql, model, "system.ai.gpt-oss-120b")
    assert len(model.requests) == 3
    assert {"failed_rules", "metric_dictionary", "gmv_summary"} <= set(
        result["evidence"]["tool_names"])
    assert result["answer"] != "I could guess a total from memory"



@pytest.mark.parametrize("question, expected", [
    ("Can I trust delivered GMV despite quality failures?", False),
    ("What is the rule-record quality pass rate?", False),
    ("Why were 32 source records quarantined, and can I trust delivered GMV despite these data-quality failures?", False),
    ("Compare late-delivery rates for RJ and SP", True),
    ("Compare late delivery rates for Rio de Janeiro and São Paulo", True),
    ("How many deliveries were late?", True),
    ("Show delivery rates across customer states", True),
])
def test_state_delivery_intent_uses_whole_words(question, expected):
    assert _needs_state_delivery(question) is expected



def test_model_can_combine_semantic_search_with_approved_sql_tools():
    """The model decides when to retrieve documents and query SQL facts."""
    retrieved = []
    def semantic(question):
        retrieved.append(question)
        return [{
            "id": "rule:orders.delivered_time",
            "source": "workspace.olist_governance.dq_rules",
            "text": "Delivered orders missing a delivery timestamp are quarantined.",
            "retrieval": "ai_search_hybrid",
        }]
    model = FakeModelClient([
        response([
            model_item("search_governance_knowledge",
                       {"question": "missing delivered timestamp quarantine rules"},
                       call_id="search-1"),
            model_item("fetch_governed_evidence", {"tool": "failed_rules"},
                       call_id="sql-1"),
        ]),
        response(text="The delivery timestamp rule quarantines invalid rows. "
                      "Source: workspace.olist_governance.dq_rules."),
        response(text="The 8 invalid orders are excluded from published facts. "
                      "Source: workspace.olist_governance.dq_rules."),
    ])
    result = run_agent(
        "Why were orders missing delivery timestamps quarantined?",
        Context(), fake_sql, model, "system.ai.gpt-oss-120b",
        search_knowledge=semantic,
    )
    assert retrieved == ["missing delivered timestamp quarantine rules"]
    assert "search_governance_knowledge" in result["evidence"]["model_selected_tools"]
    assert "failed_rules" in result["evidence"]["model_selected_tools"]
    assert result["evidence"]["retrieval_mode"] == "ai_search_hybrid"
    assert result["evidence"]["retrieval_trigger"] == "model_selected"
    assert result["evidence"]["knowledge"][0]["id"] == "rule:orders.delivered_time"
    assert "workspace.olist_governance.dq_rules" in result["evidence"]["sources"]
    assert {x["name"] for x in model.requests[0]["tools"]} == {
        "fetch_governed_evidence", "search_governance_knowledge",
    }
    assert any(x.get("call_id") == "search-1" and
               x.get("type") == "function_call_output"
               for x in model.requests[1]["input"])


def test_agent_requires_semantic_evidence_for_governance_question():
    """Guard against model finishing a governance answer without retrieval."""
    queries = []
    def semantic(question):
        queries.append(question)
        return [{"id": "metric:gmv",
                 "source": "workspace.olist_governance.metric_dictionary",
                 "text": "Delivered-item merchandise GMV excludes freight."}]
    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "gmv_summary"})]),
        response(text="Unverified model answer"),
        response(text="GMV is governed merchandise value, not audited revenue. "
                      "Source workspace.olist_governance.metric_dictionary."),
    ])
    result = run_agent(
        "Can I trust delivered GMV despite quality failures?",
        Context(), fake_sql, model, "system.ai.gpt-oss-120b",
        search_knowledge=semantic,
    )
    assert len(queries) == 1
    assert result["answer"] != "Unverified model answer"
    assert result["evidence"]["retrieval_mode"] == "ai_search_hybrid"
    assert result["evidence"]["retrieval_trigger"] == "evidence_guard"
    assert result["evidence"]["verified_metrics"][0]["display"] == "BRL 13,220,248.93"
    assert "metric:gmv" in {v["id"] for v in result["evidence"]["knowledge"]}
    assert "tools" not in model.requests[-1]


def test_model_cannot_supply_arbitrary_search_index_or_filters():
    calls = []
    def semantic(question):
        calls.append(question)
        return []
    model = FakeModelClient([
        response([model_item("search_governance_knowledge",
                             {"question": "rules", "index_name": "other"})]),
    ])
    with pytest.raises(ValueError, match="invalid search arguments"):
        run_agent("Why are orders quarantined?", Context(), fake_sql,
                  model, "system.ai.gpt-oss-120b", search_knowledge=semantic)
    assert calls == []



def test_gmv_display_uses_verified_decimal_not_floating_artifact():
    model = FakeModelClient([
        response([
            model_item("fetch_governed_evidence", {"tool": "gmv_summary"}, call_id="gmv-1"),
            model_item("fetch_governed_evidence", {"tool": "metric_dictionary"}, call_id="dict-1"),
        ]),
        response(text="The delivered item GMV is BRL 13,220,248.93. "
                      "Source workspace.olist_semantic.v_published_orders."),
    ])
    result = run_agent("What is the delivered GMV?", Context(),
                       fake_sql, model, "system.ai.gpt-oss-120b")
    assert result["evidence"]["verified_metrics"] == [
        {"name": "Delivered-item GMV", "display": "BRL 13,220,248.93",
         "source": "workspace.olist_semantic.v_published_orders"}
    ]
    assert any('"verified_gmv_display": "BRL 13,220,248.93"' in item.get("output", "")
               for item in model.requests[1]["input"]
               if item.get("type") == "function_call_output")
    assert result["evidence"]["retrieval_trigger"] == "not_used"



def test_quality_action_counts_do_not_conflate_warn_and_quarantine():
    failures = [
        {"rule_id": "orders.delivered_time", "action": "QUARANTINE", "records_failed": 8},
        {"rule_id": "orders.lifecycle", "action": "WARN", "records_failed": 10},
        {"rule_id": "products.category", "action": "WARN", "records_failed": 11},
        {"rule_id": "orders.payment_reconciliation", "action": "WARN", "records_failed": 12},
        {"rule_id": "products.fk_product_category_name", "action": "WARN", "records_failed": 13},
    ]
    summary = summarize_failed_rule_definitions(failures)
    assert summary["failed_rule_definitions"] == 5
    assert summary["rule_definitions_by_action"] == {"QUARANTINE": 1, "WARN": 4}
    assert summary["failed_rule_evaluations_by_action"] == {"QUARANTINE": 8, "WARN": 46}


def test_quality_breakdown_is_in_tool_output_and_evidence():
    def sql(statement):
        if "dq_rule_results" in statement:
            return [
                {"rule_id": "orders.delivered_time", "action": "QUARANTINE",
                 "records_failed": 8},
                {"rule_id": "orders.lifecycle", "action": "WARN",
                 "records_failed": 19},
            ]
        return fake_sql(statement)
    model = FakeModelClient([
        response([model_item("fetch_governed_evidence", {"tool": "failed_rules"})]),
        response(text="This answer lacks quarantine count evidence."),
        response(text="The rule definition breakdown includes one QUARANTINE "
                      "and one WARN failure; see workspace.olist_governance.dq_rules."),
    ])
    result = run_agent("Why were records quarantined?", Context(),
                       sql, model, "system.ai.gpt-oss-120b")
    assert result["evidence"]["verified_quality_summary"]["rule_definitions_by_action"] == {
        "QUARANTINE": 1, "WARN": 1,
    }
    tool_outputs = [x["output"] for x in model.requests[1]["input"]
                    if x.get("type") == "function_call_output"]
    assert any('"verified_quality_summary"' in x for x in tool_outputs)
