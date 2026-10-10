import json
from pathlib import Path

from evals.offline_eval import score


CASES = json.loads((Path(__file__).parents[1] / "evals" / "cases.json").read_text())


def test_quality_case_detects_conflated_rule_and_record_counts():
    case = next(item for item in CASES if item["id"] == "quality_distinctions")
    response = {
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
        "route": "ANALYTICS",
        "answer": "Delivered GMV is BRL 13,220,248.93, excluding freight; it is not revenue.",
        "evidence": {"tool_names": case["required_tools"],
                     "sources": case["required_sources"],
                     "verified_metrics": [{"display": "BRL 13,220,248.93"}]},
    }
    assert score(case, response) == []
    response["evidence"]["verified_metrics"] = []
    assert "canonical_gmv_evidence" in score(case, response)
