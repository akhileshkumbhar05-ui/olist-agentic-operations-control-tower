"""Validate quality explanations against runtime SQL observations, not rule dictionaries.

Retrieved governance text documents definitions, but does NOT establish that a
rule failed in the currently published run. Any answer lacking a verifiable
action/cause breakdown is replaced with an explicit SQL-backed explanation.
No model call, arbitrary SQL, or unvalidated value is used by this module.
"""
from __future__ import annotations

import re
from decimal import Decimal


_WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
          6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _mentions_count_and_action(answer: str, count: int, action: str) -> bool:
    """Accept ordinary phrasing, including 'four WARN rules' and 'WARN: 4'."""
    label = r"warn(?:ing)?s?" if action == "WARN" else r"quarantin(?:e|ing)"
    quantities = [str(count)]
    if count in _WORDS:
        quantities.append(_WORDS[count])
    n = "(?:" + "|".join(re.escape(x) for x in quantities) + ")"
    return bool(
        re.search(rf"\b{n}\s+(?:(?:failed|quality|rule|rules|level)[ -]+){{0,3}}{label}\b", answer, re.I)
        or re.search(rf"\b{label}\s+(?:(?:failed|quality|rule|rules|level)[ -]+){{0,3}}{n}\b", answer, re.I)
    )


def _list_failed_rules(observations: dict) -> list[dict]:
    """Actual run-scoped FAILED rows, never the complete rule dictionary."""
    return list(observations.get("failed_rules") or [])


def _is_consistent(answer: str, observations: dict) -> bool:
    failed = _list_failed_rules(observations)
    pub = (observations.get("publication") or [{}])[0]
    quarantine = observations.get("quarantine_breakdown") or []
    if not failed or not quarantine or not pub:
        return False
    if re.search(r"\b(?:is guaranteed correct|warnings cannot affect gmv|go-to-market value)\b", answer, re.I):
        return False
    if int(pub.get("failed_rules") or 0) != len(failed):
        # Incomplete rule result cannot justify a full-run cause claim.
        return False
    if not re.search(rf"\b{int(pub.get('quarantined_records') or 0):,}\b", answer):
        return False
    by_action = {}
    for rule in failed:
        action = str(rule.get("action") or "UNKNOWN").upper()
        by_action[action] = by_action.get(action, 0) + 1
    for action in ("QUARANTINE", "WARN"):
        n = by_action.get(action, 0)
        if n and not _mentions_count_and_action(answer, n, action):
            return False

    # Reject explicit contradictory counts even if the response also includes
    # the correct number elsewhere (e.g. "5 WARN rules ... 4 WARN rules").
    quantities = r"(?:\\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)"
    modifiers = r"(?:(?:failed|quality|rule|rules|level)[ -]+){0,3}"
    labels = r"(warn(?:ing)?s?|quarantin(?:e|ing))"
    for found in re.finditer(rf"\\b({quantities})\\s+{modifiers}{labels}\\b", answer, re.I):
        raw, label = found.group(1).lower(), found.group(2).lower()
        count = int(raw) if raw.isdigit() else next((n for n, word in _WORDS.items() if word == raw), -1)
        action = "WARN" if label.startswith("warn") else "QUARANTINE"
        if count != by_action.get(action, 0):
            return False
    # Every rule claimed as an observed quarantine cause MUST occur in the
    # run-scoped failed results with action=QUARANTINE.
    quarantine_ids = [str(row.get("rule_id") or "") for row in failed
                      if str(row.get("action") or "").upper() == "QUARANTINE"]
    if any(rid and rid.lower() not in answer.lower() for rid in quarantine_ids):
        return False
    failed_ids = {str(row.get("rule_id") or "").lower() for row in failed}
    for definition in observations.get("rule_dictionary") or []:
        rid = str(definition.get("rule_id") or "").lower()
        if rid and rid not in failed_ids and rid in answer.lower():
            return False
    # An answer that claims unobserved parse, duplicate, or key rule failures
    # should not be passed through, even without their full rule IDs.
    nonfailed_prefixes = ("required_key", "unique_key", "parse_")
    if any(token in answer.lower() for token in nonfailed_prefixes):
        actual_ids = " ".join(failed_ids)
        if not any(token in actual_ids for token in nonfailed_prefixes):
            return False
    # For GMV questions, do not accept rephrased or missing numeric evidence.
    gmv_rows = observations.get("gmv_summary") or []
    if gmv_rows and gmv_rows[0].get("verified_gmv_display"):
        if gmv_rows[0]["verified_gmv_display"] not in answer:
            return False
        if "not" not in answer.lower() or "revenue" not in answer.lower():
            return False
    return True


def _verified_explanation(observations: dict) -> str:
    pub = (observations.get("publication") or [{}])[0]
    failed = _list_failed_rules(observations)
    actions = {}
    for rule in failed:
        name = str(rule.get("action") or "UNKNOWN").upper()
        actions[name] = actions.get(name, 0) + 1
    total = int(pub.get("failed_rules") or 0)
    breakdown = ", ".join(f"{count} {action}" for action, count in
                          sorted(actions.items())) or "no detailed rule results"
    lines = [
        f"Published run {pub.get('run_id', 'unknown')} — SQL-verified quality findings.",
        f"The published summary reports {total} failed rule definitions. The run-scoped "
        f"failed-rules query returned {len(failed)}: {breakdown}. "
        "These are rule definitions, not distinct failed source records.",
    ]
    causes = [r for r in failed if str(r.get("action") or "").upper() == "QUARANTINE"]
    if causes:
        lines.append("Actual failed QUARANTINE rule(s), from dq_rule_results:")
        for r in causes:
            rid = str(r.get("rule_id") or "unknown")
            count = int(r.get("records_failed") or 0)
            # Governance metadata may contain untrusted text. Use rule identity,
            # action and numeric runtime evidence; omit unrelated definitions.
            lines.append(f"- {rid}: {count} failed rule evaluations.")
            explanation = " ".join(str(r.get("plain_english_description") or "").split())
            if explanation:
                lines.append(f"  Governed rule description: {explanation[:260]}.")
    else:
        lines.append("No failed QUARANTINE rule is present in the returned rule results.")
    parts = []
    for row in observations.get("quarantine_breakdown") or []:
        parts.append(f"{row.get('dataset')}: {int(row.get('distinct_quarantined') or 0)}")
    if parts:
        lines.append(f"The publication reports {int(pub.get('quarantined_records') or 0)} "
                     "distinct quarantined source records; counts by dataset: "
                     + ", ".join(parts) + ".")
    if len(failed) != total:
        lines.append("The detailed rule count does not reconcile to the published "
                     "summary; investigate that discrepancy before asserting a complete cause breakdown.")
    lines.append("The full governance rule dictionary describes possible failure "
                 "conditions, not which rules actually failed in this run. "
                 "Rule evaluations may overlap; dependent-row impact should be "
                 "verified using lineage before claiming exact causation.")
    if actions.get("WARN"):
        lines.append(f"{actions['WARN']} WARN rule definitions failed. WARN-level "
                     "records remain in published facts, and their metric impact "
                     "has not been independently ruled out.")
    rows = observations.get("gmv_summary") or []
    if rows:
        r = rows[0]
        amount = r.get("verified_gmv_display")
        if not amount and r.get("delivered_item_gmv_brl") is not None:
            amount = f"BRL {Decimal(str(r['delivered_item_gmv_brl'])):,.2f}"
        if amount:
            lines.append(f"Delivered Item GMV: {amount}, computed from the accepted "
                         "published order facts in the selected query scope. It excludes "
                         "freight and is not audited revenue or recognized accounting revenue.")
    lines.append("Trust assessment: the reported metrics follow the published governed "
                 "definitions and exclusion policy; this is not an independent financial "
                 "audit or a guarantee that remaining WARN-level anomalies have zero impact.")
    lines.append("Evidence: workspace.olist_agentic_quality.dq_rule_results, "
                 "workspace.olist_agentic_quality.quarantine, "
                 "workspace.olist_agentic_quality.dq_run_summary"
                 + (", workspace.olist_semantic.v_published_orders." if rows else "."))
    return "\n\n".join(lines)


def validate_quality_answer(answer: str, observations: dict) -> tuple[str, str]:
    """Return (answer, validation status), never pass contradictory quality claims."""
    if _is_consistent(answer, observations):
        return answer, "verified_model_answer"
    return _verified_explanation(observations), "sql_verified_quality_repair"
