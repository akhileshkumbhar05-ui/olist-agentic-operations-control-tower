"""Source-domain AI validation against reviewed contracts and governed fields."""
import json
from pathlib import Path
from types import SimpleNamespace

from app.nexus_domains import contract_payload
from olist_agentic.copilot.agent import run_agent
from olist_agentic.copilot.domain_guard import validate_source_domain_answer
from olist_agentic.copilot.queries import Context, assert_read_only


SOURCE_ROWS = [
    {
        "dataset": "payments",
        "column_name": "payment_sequential",
        "business_definition": "Sequence number for one payment within an order",
        "recommended_use": "Combine with order_id for the payment-grain key",
        "avoid_use": "Do not assume one payment per order",
    },
    {
        "dataset": "payments",
        "column_name": "payment_value",
        "business_definition": "Monetary amount of one payment sequence in BRL",
        "recommended_use": "Sum by order before reconciliation",
        "avoid_use": "Do not call payment value recognized revenue",
    },
]


def _contract():
    return contract_payload("payments")


def test_broken_markdown_table_and_invented_quality_claim_are_replaced():
    wrong = (
        "Payments has record grain one payment sequence. "
        "The composite key is order_id, payment_sequential. "
        "Join payments.order_id to orders.order_id.\n"
        "| Field | Definition | Use | Avoid |\n"
        "|---|---|---|---|\n"
        "| payment_value | Payment | per order | not revenue |\n"
        "payments.unique_key quarantines duplicates and these quarantined "
        "records remain in published facts."
    )
    answer, status = validate_source_domain_answer(
        wrong, _contract(), {"source_dictionary": SOURCE_ROWS}
    )
    assert status == "source_contract_repair"
    assert "payment_sequential" in answer
    assert "payments.order_id → orders.order_id" in answer
    assert "payment_value" in answer
    assert "Sum by order before reconciliation" in answer
    assert "quarantined records remain in published facts" not in answer
    assert "payments.unique_key quarantines duplicates" not in answer
    assert "did not verify run-scoped rule failures" in answer
    assert "|---|" not in answer


def test_unsupported_quality_claim_triggers_repair_even_without_table():
    wrong = (
        "Payments uses order_id and payment_sequential; "
        "payments.order_id → orders.order_id. "
        "Rule payments.unique_key failed and quarantined payments in this run."
    )
    answer, status = validate_source_domain_answer(
        wrong, _contract(), {"source_dictionary": SOURCE_ROWS}
    )
    assert status == "source_contract_repair"
    assert "Rule payments.unique_key failed" not in answer
    assert "governed field definitions" in answer.lower()


def test_well_grounded_agent_answer_is_preserved():
    valid = (
        "Payments have one record per order payment sequence. The "
        "candidate key is order_id and payment_sequential. Registered "
        "relationship: payments.order_id to orders.order_id. "
        "Aggregate payment_value to the order level before joining items. "
        "Source: workspace.olist_governance.source_dictionary."
    )
    answer, status = validate_source_domain_answer(
        valid, _contract(), {"source_dictionary": SOURCE_ROWS}
    )
    assert status == "verified_source_semantics"
    assert answer == valid


def test_omitted_registered_join_is_filled_in_from_registry():
    wrong = "Payments rows are keyed by order_id and payment_sequential."
    answer, status = validate_source_domain_answer(
        wrong, _contract(), {"source_dictionary": SOURCE_ROWS}
    )
    assert status == "source_contract_repair"
    assert "payments.order_id → orders.order_id" in answer


def test_source_domain_run_agent_repairs_wrong_model_claim_and_marks_evidence():
    class FakeModel:
        def __init__(self):
            self.calls = []
            self.responses = self

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if len(self.calls) == 1:
                item = SimpleNamespace(
                    type="function_call", call_id="call-1",
                    name="fetch_governed_evidence",
                    arguments='{"tool": "source_dictionary"}',
                    model_dump=lambda exclude_none=True: {
                        "type": "function_call", "call_id": "call-1",
                        "name": "fetch_governed_evidence",
                        "arguments": '{"tool": "source_dictionary"}',
                    },
                )
                return SimpleNamespace(output=[item], output_text="")
            return SimpleNamespace(
                output=[],
                output_text=(
                    "Payments uses candidate key order_id and payment_sequential, "
                    "joining payments.order_id to orders.order_id.\n"
                    "| Field | Description | Use |\n"
                    "|---|---|---|\n"
                    "| payment_value | Payment amount | per-order |\n"
                    "The payments.unique_key rule quarantines duplicates, "
                    "and quarantined records remain in published facts."
                ),
            )

    model = FakeModel()
    executed = []

    def sql(statement):
        assert_read_only(statement)
        executed.append(statement)
        if "dq_run_summary" in statement:
            return [{"run_id": "test-run", "failed_rules": 5,
                     "quarantined_records": 32}]
        if "source_dictionary" in statement:
            assert "WHERE dataset = 'payments'" in statement
            return SOURCE_ROWS
        raise AssertionError("Unnecessary tool was called")

    result = run_agent(
        "Explain the Olist payments source grain, candidate key, "
        "relationships and important dictionary fields.",
        Context(), sql, model, "system.ai.gpt-oss-120b",
        source_contract=_contract(),
    )
    assert len(model.calls) == 2
    assert result["evidence"]["model_selected_tools"] == ["source_dictionary"]
    assert result["evidence"]["answer_validation"] == "source_contract_repair"
    assert result["evidence"]["source_domain"] == "payments"
    assert result["evidence"]["tool_names"] == ["publication", "source_dictionary"]
    assert "workspace.olist_governance.source_dictionary" in result["answer"]
    assert "quarantined records remain in published facts" not in result["answer"]
    assert "|---|" not in result["answer"]
    assert len(executed) == 2


def test_receipt_explains_when_answer_was_repaired():
    html = (Path(__file__).resolve().parents[1] / "app/static/nexus.html").read_text()
    assert "['Source-domain validation',data.evidence?.answer_validation" in html
    assert "'Reviewed source contract · corrected'" in html
    assert "'Reviewed source contract · preserved AI response'" in html
