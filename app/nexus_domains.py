"""Read-only, evidence-grounded source-domain explorer for the NEXUS UI.

Source contracts and relationships are derived from the project registry,
not inferred from an illustration. Runtime governance observations are queried
only from the published run. No arbitrary SQL or user-selected table names.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from olist_agentic.domain.sources import RELATIONSHIPS, SOURCES
from olist_agentic.governance.semantics import SOURCE_NOTES

logger = logging.getLogger(__name__)
router = APIRouter()

# UI aliases are explicit; source/governance dataset identifiers are the
# registry keys, never untrusted request strings.
UI_DOMAIN_NAMES = {
    "orders": "orders",
    "customers": "customers",
    "items": "order_items",
    "payments": "payments",
    "reviews": "reviews",
    "products": "products",
    "sellers": "sellers",
    "geo": "geolocation",
    "translations": "translation",
}
PUBLIC_LABELS = {
    "orders": "Orders", "customers": "Customers", "order_items": "Order Items",
    "payments": "Payments", "reviews": "Reviews", "products": "Products",
    "sellers": "Sellers", "geolocation": "Geolocation",
    "translation": "Category Translation",
}
SOURCE_TABLE = "workspace.olist_governance.source_dictionary"
RULE_TABLE = "workspace.olist_governance.dq_rules"
RESULT_TABLE = "workspace.olist_agentic_quality.dq_rule_results"
PUBLISHED_TABLE = "workspace.olist_agentic_quality.published_run"
QUARANTINE_TABLE = "workspace.olist_agentic_quality.quarantine"


def resolve_domain(domain: str) -> str:
    if domain not in UI_DOMAIN_NAMES:
        raise HTTPException(status_code=404, detail="Unknown source domain")
    dataset = UI_DOMAIN_NAMES[domain]
    if dataset not in SOURCES:
        raise RuntimeError("NEXUS source registry is inconsistent")
    return dataset


def contract_payload(domain: str) -> dict:
    dataset = resolve_domain(domain)
    source = SOURCES[dataset]
    relationships = [
        {
            "from_dataset": left, "from_key": left_col,
            "to_dataset": right, "to_key": right_col,
        }
        for left, left_col, right, right_col in RELATIONSHIPS
        if dataset in (left, right)
    ]
    context, caution = SOURCE_NOTES[dataset]
    return {
        "domain": domain,
        "dataset": dataset,
        "label": PUBLIC_LABELS[dataset],
        "source_file": source.filename,
        "grain": source.grain,
        "candidate_key": list(source.key),
        "expected_columns": list(source.columns),
        "context": context,
        "caution": caution,
        "relationships": relationships,
        "metadata_origin": "src/olist_agentic/domain/sources.py; src/olist_agentic/governance/semantics.py",
        "relationship_scope": (
            "Documented logical relationships, not a live execution trace or "
            "proof of physical join cardinality."
        ),
    }


def governance_sql(dataset: str) -> tuple[str, str]:
    """Only allowlisted registry dataset names become SQL literals."""
    if dataset not in SOURCES:
        raise ValueError("Unknown source dataset")
    # SQL literal is an exact registry key (not user-supplied SQL).
    source_fields = (
        "SELECT dataset, column_name, business_definition, "
        "recommended_use, avoid_use "
        f"FROM {SOURCE_TABLE} WHERE dataset = '{dataset}' "
        "ORDER BY column_name LIMIT 100"
    )
    # The source rule catalog documents what a rule means. Its left-joined,
    # run-scoped result proves which rule actually passed or failed.
    # The scalar quarantine count is distinct SOURCE records and is not
    # interchangeable with rule-failure evaluations.
    quality = (
        "SELECT g.rule_id, g.business_name, "
        "g.plain_english_description, g.action, "
        "r.status AS observed_status, r.records_failed, p.run_id AS published_run, "
        "(SELECT COUNT(DISTINCT q.source_record_id) "
        f"FROM {QUARANTINE_TABLE} q "
        f"JOIN {PUBLISHED_TABLE} current_run ON current_run.run_id = q.run_id "
        f"WHERE q.dataset = '{dataset}') AS distinct_quarantined "
        f"FROM {RULE_TABLE} g CROSS JOIN {PUBLISHED_TABLE} p "
        f"LEFT JOIN {RESULT_TABLE} r "
        "ON r.rule_id = g.rule_id AND r.run_id = p.run_id "
        f"WHERE g.dataset = '{dataset}' ORDER BY g.rule_id LIMIT 100"
    )
    return source_fields, quality


def normalize_governance(dataset: str, fields: list[dict], rules: list[dict]) -> dict:
    if not rules:
        raise RuntimeError("Expected run-scoped governed rule definitions")
    run_ids = {str(r.get("published_run")) for r in rules if r.get("published_run")}
    if len(run_ids) != 1:
        raise RuntimeError("Expected one published run in dataset quality evidence")
    if any(str(row.get("dataset", "")) != dataset for row in fields):
        raise RuntimeError("Unexpected source dictionary dataset in SQL response")

    quarantine_values = {int(row["distinct_quarantined"])
                         for row in rules if row.get("distinct_quarantined") is not None}
    if len(quarantine_values) != 1:
        raise RuntimeError("Missing or inconsistent run-scoped quarantine result")

    # Do not interpret rules missing evaluation rows as PASSED.
    normalized_rules = [{
        "rule_id": str(r.get("rule_id") or ""),
        "business_name": str(r.get("business_name") or ""),
        "description": str(r.get("plain_english_description") or ""),
        "action": str(r.get("action") or ""),
        "observed_status": (str(r["observed_status"]) if r.get("observed_status") is not None else None),
        "failed_evaluations": (int(r["records_failed"]) if r.get("records_failed") is not None else None),
    } for r in rules]
    normalized_rules.sort(key=lambda r: (
        0 if r["observed_status"] == "FAILED" else 1, r["rule_id"]
    ))
    normalized_fields = [{
        "column_name": str(row.get("column_name") or ""),
        "business_definition": str(row.get("business_definition") or ""),
        "recommended_use": str(row.get("recommended_use") or ""),
        "avoid_use": str(row.get("avoid_use") or ""),
    } for row in fields]
    return {
        "dataset": dataset,
        "published_run": next(iter(run_ids)),
        "source": [SOURCE_TABLE, RULE_TABLE, RESULT_TABLE, QUARANTINE_TABLE, PUBLISHED_TABLE],
        "fields": normalized_fields,
        "rules": normalized_rules,
        "rule_definitions": len(normalized_rules),
        "observed_failed_definitions": sum(1 for r in normalized_rules if r["observed_status"] == "FAILED"),
        "unobserved_definitions": sum(1 for r in normalized_rules if r["observed_status"] is None),
        "distinct_quarantined_source_rows": next(iter(quarantine_values)),
        "note": (
            "Rule definitions are governance metadata. FAILED status and failed "
            "evaluations are recorded for the published run. Distinct quarantined "
            "source records are a separate measure; dataset lineage does not "
            "prove the cause of every downstream exclusion."
        ),
    }


@router.get("/api/nexus/domains/{domain}")
def source_contract(domain: str):
    return contract_payload(domain)


@router.get("/api/nexus/domains/{domain}/governance")
def domain_governance(domain: str):
    dataset = resolve_domain(domain)
    from app.main import sql_query
    field_sql, quality_sql = governance_sql(dataset)
    try:
        fields = sql_query(field_sql)
        rules = sql_query(quality_sql)
        return normalize_governance(dataset, fields, rules)
    except Exception as exc:
        logger.exception("NEXUS governed domain inspection failed for %s", dataset)
        raise HTTPException(
            status_code=503,
            detail="Published governance evidence temporarily unavailable; source contracts remain accessible.",
        ) from exc
