"""Regression: the word 'orders' must not bypass source-domain validation."""
import json
from types import SimpleNamespace

import pytest

from app.nexus_domains import contract_payload
from olist_agentic.copilot.agent import run_agent
from olist_agentic.copilot.queries import Context, assert_read_only, route


def _domain_question(dataset: str) -> str:
    return (
        f"Explain the Olist {dataset} source dataset: its documented record grain, "
        "candidate key, registered join relationships, and important source "
        "dictionary fields with their recommended uses and caveats. "
        "Use the reviewed source contract and governed field dictionary as evidence; "
        "do not infer joins from the diagram. Focus on source semantics rather "
        "than pipeline-wide counts. Cite the sources."
    )


class ModelSelectingSourceDictionary:
    def __init__(self):
        self.requests = []
        self.responses = self

    def create(self, **request):
        self.requests.append(request)
        if len(self.requests) == 1:
            item = SimpleNamespace(
                type="function_call", call_id="call-1",
                name="fetch_governed_evidence",
                arguments=json.dumps({"tool": "source_dictionary"}),
                model_dump=lambda exclude_none=True: {
                    "type": "function_call", "call_id": "call-1",
                    "name": "fetch_governed_evidence",
                    "arguments": json.dumps({"tool": "source_dictionary"}),
                },
            )
            return SimpleNamespace(output=[item], output_text="")
        return SimpleNamespace(
            output=[],
            output_text="This is a source domain overview, see the dictionary.",
        )


@pytest.mark.parametrize(("domain", "dataset"), [
    ("orders", "orders"),
    ("items", "order_items"),
])
def test_orders_names_route_to_source_knowledge_guard(domain, dataset):
    question = _domain_question(dataset)
    # The old router classifies these as analytic due to the word 'order'.
    assert route(question, Context()) == "ANALYTICS"

    seen_sql = []
    def sql(statement):
        assert_read_only(statement)
        seen_sql.append(statement)
        if "dq_run_summary" in statement:
            return [{"run_id": "published-run-1",
                     "failed_rules": 5, "quarantined_records": 32}]
        if "source_dictionary" in statement:
            assert f"WHERE dataset = '{dataset}'" in statement
            return [{"dataset": dataset, "column_name": "order_id",
                     "business_definition": "Source order ID",
                     "recommended_use": "Join by order ID",
                     "avoid_use": "Do not treat as revenue"}]
        raise AssertionError("Unexpected SQL: " + statement)

    model = ModelSelectingSourceDictionary()
    result = run_agent(
        question, Context(), sql, model, "system.ai.gpt-oss-120b",
        source_contract=contract_payload(domain),
    )
    assert result["route"] == "KNOWLEDGE"
    assert result["evidence"]["source_domain"] == dataset
    assert result["evidence"]["model_selected_tools"] == ["source_dictionary"]
    assert result["evidence"]["tool_names"] == ["publication", "source_dictionary"]
    # The intentionally insufficient model answer must be replaced by the
    # source-contract validator, rather than marked 'not_applicable'.
    assert result["evidence"]["answer_validation"] == "source_contract_repair"
    assert "Record grain" in result["answer"]
    assert "Registered logical relationships" in result["answer"]
    assert len(seen_sql) == 2


def test_generic_orders_analytics_stays_analytics_without_domain_handoff():
    question = "How many orders were delivered in RJ?"
    assert route(question, Context(state="RJ")) == "ANALYTICS"
    # Regression contracts: only source-specific handoffs alter routing.
    model = ModelSelectingSourceDictionary()
    def sql(query):
        if "dq_run_summary" in query:
            return [{"run_id": "published-run-1"}]
        if "source_dictionary" in query:
            return [{"dataset": "orders"}]
        return []
    result = run_agent(
        question, Context(state="RJ"), sql, model, "system.ai.gpt-oss-120b"
    )
    assert result["route"] == "ANALYTICS"
    assert result["evidence"]["source_domain"] is None
    assert result["evidence"]["answer_validation"] == "not_applicable"


def test_explicit_quality_questions_still_route_to_trust_or_hybrid():
    assert route("Why did orders fail quality rules?", Context()) == "HYBRID"
    assert route("Which source rules failed?", Context()) == "TRUST"
