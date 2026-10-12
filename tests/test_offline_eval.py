import json
from pathlib import Path

from evals.offline_eval import score


CASES = json.loads((Path(__file__).parents[1] / "evals" / "cases.json").read_text())


def test_quality_case_detects_conflated_rule_and_record_counts():
    case = next(item for item in CASES if item["id"] == "quality_distinctions")
    response = {
        "generation": "agentic_tool_calling",
        "route": "HYBRID", "answer": "32 distinct source records; 5 WARN rules.",
        "evidence": {
            "tool_names": case["required_tools"], "sources": case["required_sources"],
            "verified_quality_summary": {"failed_rule_definitions": 5,
                                         "rule_definitions_by_action": {"QUARANTINE": 1, "WARN": 4}},
        },
    }
    assert "forbidden_answer_term:5 WARN rules" in score(case, response)


def test_canonical_gmv_needs_answer_and_verified_metric():
    case = next(item for item in CASES if item["id"] == "gmv_definition")
    response = {
        "generation": "agentic_tool_calling",
        "route": "ANALYTICS",
        "answer": "Delivered GMV is BRL 13,220,248.93, excluding freight; it is not revenue.",
        "evidence": {"tool_names": case["required_tools"],
                     "sources": case["required_sources"],
                     "verified_metrics": [{"display": "BRL 13,220,248.93"}]},
    }
    assert score(case, response) == []
    response["evidence"]["verified_metrics"] = []
    assert "canonical_gmv_evidence" in score(case, response)



def test_unicode_currency_spacing_is_not_a_false_negative():
    case = next(item for item in CASES if item["id"] == "gmv_definition")
    response = {
        "generation": "agentic_tool_calling",
        "route": "ANALYTICS",
        "answer": ("Delivered Gross Merchandise Value: BRL\u202f13,220,248.93. "
                   "Freight is excluded; this is not accounting revenue."),
        "evidence": {
            "tool_names": case["required_tools"],
            "sources": case["required_sources"],
            "verified_metrics": [{"display": "BRL 13,220,248.93"}],
        },
    }
    assert score(case, response) == []


def test_go_to_market_hallucination_is_caught_despite_unicode_hyphen():
    case = next(item for item in CASES if item["id"] == "gmv_definition")
    response = {
        "generation": "agentic_tool_calling",
        "route": "ANALYTICS",
        "answer": ("Delivered GMV (go\u2011to\u2011market value) is BRL\u202f13,220,248.93. "
                   "It excludes freight and is not recognized revenue."),
        "evidence": {
            "tool_names": case["required_tools"],
            "sources": case["required_sources"],
            "verified_metrics": [{"display": "BRL 13,220,248.93"}],
        },
    }
    assert score(case, response) == ["forbidden_answer_term:go-to-market value"]



def test_numerically_correct_fallback_fails_agentic_evaluation():
    case = next(item for item in CASES if item["id"] == "delivery_denominator")
    response = {
        "generation": "deterministic_fallback_agent_error",
        "route": "ANALYTICS",
        "answer": ("RJ 12.11% late, SP 4.49% late; "
                   "the rates use eligible deliveries, not orders."),
        "evidence": {
            "tool_names": case["required_tools"],
            "sources": case["required_sources"],
        },
    }
    assert score(case, response) == ["generation"]



def test_freight_case_requires_model_selected_search_and_formula():
    case = next(item for item in CASES if item["id"] == "governance_retrieval")
    response = {
        "generation": "agentic_tool_calling",
        "route": "KNOWLEDGE",
        "answer": ("Delivered freight is accepted item freight in BRL, "
                   "formula sum(freight_value) where is_delivered; "
                   "freight is separate from GMV."),
        "evidence": {
            "tool_names": ["publication", "metric_dictionary"],
            "sources": ["workspace.olist_governance.metric_dictionary"],
            "model_selected_tools": ["search_governance_knowledge", "metric_dictionary"],
            "retrieval_mode": "ai_search_hybrid",
            "retrieval_trigger": "model_selected",
        },
    }
    assert score(case, response) == []
    response["evidence"]["model_selected_tools"] = ["metric_dictionary"]
    response["evidence"]["retrieval_trigger"] = "evidence_guard"
    assert score(case, response) == ["retrieval_trigger", "model_selected_tools"]


def test_freight_case_requires_explicit_formula():
    case = next(item for item in CASES if item["id"] == "governance_retrieval")
    response = {
        "generation": "agentic_tool_calling", "route": "KNOWLEDGE",
        "answer": "Freight in BRL is reported separately from GMV.",
        "evidence": {
            "tool_names": case["required_tools"],
            "sources": case["required_sources"],
            "model_selected_tools": ["search_governance_knowledge"],
            "retrieval_mode": "ai_search_hybrid",
            "retrieval_trigger": "model_selected",
        },
    }
    assert score(case, response) == ["missing_answer_term:sum(freight_value)"]
