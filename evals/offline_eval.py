"""Score saved /api/ask responses without contacting Databricks or a model.

JSONL input: one object per line with `id` and `response` (the API JSON body).
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path

CASES = Path(__file__).with_name("cases.json")


def normalized_text(value: str) -> str:
    """Normalize presentation whitespace and Unicode hyphen variants for text checks."""
    value = unicodedata.normalize("NFKC", value)
    for char in ("‐", "‑", "‒", "–", "—", "−"):
        value = value.replace(char, "-")
    return " ".join(value.split()).casefold()


def score(case: dict, response: dict) -> list[str]:
    failures = []
    evidence = response.get("evidence") or {}
    answer = normalized_text(str(response.get("answer") or ""))
    if case.get("expected_generation") and response.get("generation") != case["expected_generation"]:
        failures.append("generation")
    if response.get("route") != case["expected_route"]:
        failures.append("route")
    if not set(case["required_tools"]) <= set(evidence.get("tool_names") or []):
        failures.append("required_tools")
    if not set(case["required_sources"]) <= set(evidence.get("sources") or []):
        failures.append("required_sources")
    for term in case.get("required_answer_terms", []):
        if normalized_text(term) not in answer:
            failures.append("missing_answer_term:" + term)
    for term in case.get("forbidden_answer_terms", []):
        if normalized_text(term) in answer:
            failures.append("forbidden_answer_term:" + term)
    expected_quality = case.get("expected_quality_summary")
    if expected_quality:
        actual = evidence.get("verified_quality_summary") or {}
        for key, value in expected_quality.items():
            if actual.get(key) != value:
                failures.append("quality_summary:" + key)
    if case.get("expected_retrieval_mode") and case["expected_retrieval_mode"] != evidence.get("retrieval_mode"):
        failures.append("retrieval_mode")
    if case.get("expected_retrieval_trigger") and case["expected_retrieval_trigger"] != evidence.get("retrieval_trigger"):
        failures.append("retrieval_trigger")
    if not set(case.get("required_model_selected_tools", [])) <= set(evidence.get("model_selected_tools") or []):
        failures.append("model_selected_tools")
    if case["id"] == "gmv_definition":
        metrics = evidence.get("verified_metrics") or []
        if not any(m.get("display") == "BRL 13,220,248.93" for m in metrics):
            failures.append("canonical_gmv_evidence")
    return failures


def evaluate(responses: dict[str, dict], cases: list[dict]) -> dict[str, list[str]]:
    return {case["id"]: (score(case, responses[case["id"]])
                         if case["id"] in responses else ["missing_response"])
            for case in cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("responses", type=Path, help="Saved API response JSONL file")
    args = parser.parse_args()
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    responses = {}
    for line in args.responses.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            responses[item["id"]] = item["response"]
    results = evaluate(responses, cases)
    for case_id, failures in results.items():
        print(f"{case_id}: {'PASS' if not failures else 'FAIL ' + ', '.join(failures)}")
    print(f"Passed {sum(not failures for failures in results.values())}/{len(results)}")
    return int(any(results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
