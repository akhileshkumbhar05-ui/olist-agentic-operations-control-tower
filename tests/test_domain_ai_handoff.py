"""Domain handoff must preserve real AI tool calls and source-specific grounding."""
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.nexus_domains import contract_payload
from olist_agentic.copilot.agent import run_agent
from olist_agentic.copilot.queries import Context, assert_read_only, route


QUESTION = (
    "Explain the Olist payments source dataset: its documented record grain, "
    "candidate key, registered join relationships, and important source "
    "dictionary fields with recommended uses and caveats."
)


class Model:
    def __init__(self):
        self.calls = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            call = SimpleNamespace(
                type="function_call",
                name="fetch_governed_evidence",
                arguments=json.dumps({"tool": "source_dictionary"}),
                call_id="call-1",
                model_dump=lambda exclude_none=True: {
                    "type": "function_call", "name": "fetch_governed_evidence",
                    "arguments": json.dumps({"tool": "source_dictionary"}),
                    "call_id": "call-1",
                },
            )
            return SimpleNamespace(output=[call], output_text="")
        return SimpleNamespace(
            output=[],
            output_text=(
                "Payments has one record per payment sequence with candidate key "
                "(order_id, payment_sequential). payments.order_id links to "
                "orders.order_id. Aggregate payment_value per order; it is not "
                "accounting revenue. Source: workspace.olist_governance.source_dictionary."
            ),
        )


def test_domain_investigation_preserves_focus_and_tools_and_avoids_global_quality_repair():
    assert route(QUESTION, Context()) == "KNOWLEDGE"
    contract = contract_payload("payments")
    model = Model()
    statements = []

    def sql(statement):
        assert_read_only(statement)
        statements.append(statement)
        if "dq_run_summary" in statement:
            return [{"run_id": "run-verified", "readiness": "WARNING",
                     "failed_rules": 5, "quarantined_records": 32}]
        if "source_dictionary" in statement:
            assert "WHERE dataset = 'payments'" in statement
            return [{"dataset": "payments", "column_name": "payment_value",
                     "business_definition": "Monetary value of one payment sequence",
                     "recommended_use": "Aggregate per order",
                     "avoid_use": "Not recognized revenue"}]
        raise AssertionError("Irrelevant SQL tool was executed")

    result = run_agent(
        QUESTION, Context(), sql, model, "system.ai.gpt-oss-120b",
        source_contract=contract,
    )
    assert result["answer"].startswith("Payments has one record per payment sequence")
    assert result["evidence"]["source_domain"] == "payments"
    assert result["evidence"]["answer_validation"] == "verified_source_semantics"
    assert result["evidence"]["model_selected_tools"] == ["source_dictionary"]
    assert result["evidence"]["tool_names"] == ["publication", "source_dictionary"]
    assert len(statements) == 2
    initial_prompt = model.calls[0]["input"][1]["content"]
    assert '"candidate_key": ["order_id", "payment_sequential"]' in initial_prompt
    assert '"to_dataset": "orders"' in initial_prompt
    assert "governed field dictionary" in initial_prompt
    assert "failed_rules" not in result["evidence"]["tool_names"]


def test_source_domain_only_may_be_validated_project_contract():
    model = Model()
    with pytest.raises(ValueError, match="allowlisted"):
        run_agent(
            QUESTION, Context(),
            lambda _: [{"run_id": "run-verified"}],
            model, "system.ai.gpt-oss-120b",
            source_contract={"dataset": "payments' OR 1=1"},
        )
    assert not model.calls


def test_generic_questions_retains_unfiltered_source_tool_template():
    from olist_agentic.copilot.queries import statements
    tools = statements(QUESTION + " GMV", Context(), "HYBRID")
    assert "WHERE dataset = 'payments'" not in tools["source_dictionary"]


def test_main_passes_verified_context_only_when_explicitly_requested(monkeypatch):
    from app import main

    def model(question, context, execute_sql, model_client, model_name,
              search_knowledge=None, source_contract=None):
        assert question == QUESTION
        assert source_contract is not None
        assert source_contract["dataset"] == "payments"
        assert source_contract["candidate_key"] == ["order_id", "payment_sequential"]
        return {"answer": "Payments semantics", "route": "KNOWLEDGE",
                "published_run": "run-verified", "context": {},
                "evidence": {"tool_names": ["source_dictionary"],
                             "source_domain": "payments"}}

    monkeypatch.setattr(main, "run_agent", model)
    monkeypatch.setattr(main, "gateway_model_client", lambda: object())
    monkeypatch.setenv("DATABRICKS_MODEL_SERVICE", "system.ai.gpt-oss-120b")
    result = main._ask(main.AskRequest(
        question=QUESTION, state="ALL", source_domain="payments"))
    assert result["generation"] == "agentic_tool_calling"
    assert result["evidence"]["source_domain"] == "payments"


def test_invalid_domain_returns_validation_error_not_a_warehouse_query(monkeypatch):
    from app import main
    monkeypatch.setattr(main, "run_agent",
                        lambda *a, **kw: pytest.fail("Cannot call model for unknown domain"))
    with pytest.raises(HTTPException) as raised:
        main._ask(main.AskRequest(
            question=QUESTION, source_domain="untrusted"))
    assert raised.value.status_code == 404


def test_ui_handoff_is_semantics_focused_while_quality_stays_in_inspector():
    from pathlib import Path
    html = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()
    assert "domainInvestigationPrompt='Explain the Olist '" in html
    assert "'Focus on source semantics rather than pipeline-wide counts." in html
    assert "source_domain:selectedDomain" in html
    assert "const selectedDomain=question===domainInvestigationPrompt?" in html
    assert "data.evidence?.source_domain" in html
    assert "/api/nexus/domains/'+domain+'/governance" in html
