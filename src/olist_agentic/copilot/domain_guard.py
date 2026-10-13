"""Post-generation checks for source-domain answers.

The Databricks source dictionary and reviewed source registry support field
semantics, keys, and logical edges. They do NOT establish which quality rule
failed. Never present an unsupported observed failure as if run-scoped SQL
verified it. This guard does not modify the existing quality-answer guard.
"""
from __future__ import annotations

import re

from olist_agentic.domain.sources import SOURCES


_BAD_FORMAT = re.compile(r"(?m)^\s*\|?[^\n]*\|[^\n]*\|[^\n]*$")
_QUALITY_CLAIMS = re.compile(
    r"\b(?:quarantin\w*|failed\s+(?:quality\s+)?rules?|"
    r"rules?\s+fail\w*|duplicate\w*\s+(?:were\s+)?"
    r"(?:quarantin\w*|reject\w*)|unique_key|required_key|"
    r"parse_[a-z_]+|dq_rule_results)\b", re.I
)


def _readable_line(text: object) -> str:
    return " ".join(str(text or "").split())[:280]


def _source_domain_overview(source_contract: dict, observations: dict) -> str:
    dataset = source_contract["dataset"]
    fields = observations.get("source_dictionary") or []
    candidate = source_contract.get("candidate_key") or []
    rels = source_contract.get("relationships") or []
    lines = [
        f"## {source_contract.get('label', dataset)} — governed source overview",
        "",
        "## Record grain",
        _readable_line(source_contract.get("grain")),
        "",
        "## Candidate key",
        " + ".join(candidate) if candidate else
            "No unique candidate key is declared in the source registry.",
        "",
        "## Registered logical relationships",
    ]
    if rels:
        for rel in rels:
            lines.append(
                f"- {rel['from_dataset']}.{rel['from_key']} → "
                f"{rel['to_dataset']}.{rel['to_key']}"
            )
    else:
        lines.append(
            "No direct key relationship is registered for this domain. "
            "Do not infer joins from diagram proximity."
        )
    lines += [
        "",
        "## Governed field definitions",
    ]
    if fields:
        for row in fields[:16]:
            if row.get("dataset") not in (None, dataset):
                raise ValueError("Source dictionary contained a different dataset")
            field = _readable_line(row.get("column_name"))
            definition = _readable_line(row.get("business_definition"))
            good = _readable_line(row.get("recommended_use"))
            avoid = _readable_line(row.get("avoid_use"))
            lines.append(f"- **{field}** — {definition}. Use: {good}. Avoid: {avoid}.")
    else:
        lines.append(
            "The published source dictionary returned no matching fields. "
            "Do not substitute inferred definitions."
        )
    lines += [
        "",
        "## Interpretation and limitations",
        _readable_line(source_contract.get("context")),
        _readable_line(source_contract.get("caution")),
        ("The source registry documents data-quality contracts; this "
         "source-semantics answer did not verify run-scoped rule failures or "
         "quarantine causes. Use the Domain Inspector's separate published-run "
         "quality evidence to investigate those outcomes."),
        "",
        ("Sources: workspace.olist_governance.source_dictionary; "
         "reviewed Olist source contract "
         "(src/olist_agentic/domain/sources.py and "
         "src/olist_agentic/governance/semantics.py)."),
    ]
    return "\n".join(lines)


def validate_source_domain_answer(
    answer: str, source_contract: dict, observations: dict
) -> tuple[str, str]:
    """Keep sound agent explanations; replace unsafe or unreadable ones.

    This validation applies only to *explicit* domain-semantic handoffs.
    General quality investigations still use their existing run-scoped guard.
    """
    dataset = source_contract.get("dataset")
    if dataset not in SOURCES:
        raise ValueError("Source contract dataset is not allowlisted")
    keys = source_contract.get("candidate_key") or []
    links = source_contract.get("relationships") or []

    # A source-semantics question doesn't request a quality determination.
    # Without dataset-specific observed rule results, model statements about
    # quarantine must not be certified as truth by a source-dictionary lookup.
    safe = bool(answer.strip()) and not _QUALITY_CLAIMS.search(answer)
    # The narrow web drawer is intentionally not a Markdown table renderer.
    if _BAD_FORMAT.search(answer) or answer.count("|") >= 5:
        safe = False
    if not all(key in answer for key in keys):
        safe = False
    # Every logical edge in the registry is a documented link, not inferred
    # by the model. The report may simply omit edges; then restore them.
    for rel in links:
        edge = f"{rel['from_dataset']}.{rel['from_key']}"
        parent = f"{rel['to_dataset']}.{rel['to_key']}"
        if edge not in answer or parent not in answer:
            safe = False
            break

    if safe:
        return answer, "verified_source_semantics"
    return _source_domain_overview(source_contract, observations), "source_contract_repair"
