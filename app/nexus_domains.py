"""Read-only, evidence-grounded source-domain explorer for the NEXUS UI.

Source contracts and relationships are derived from the project registry,
not inferred from an illustration. Runtime governance observations are queried
only from the published run. No arbitrary SQL or user-selected table names.
"""
from __future__ import annotations

import logging
import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

from olist_agentic.domain.sources import RELATIONSHIPS, SOURCES
from olist_agentic.domain.rules import RULES
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
FAILED_RECORD_TABLE = "workspace.olist_agentic_quality.dq_failed_records"
MAX_FAILED_RECORD_PREVIEW = 20


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


def failed_record_preview_sql(dataset: str, rule_id: str) -> str:
    """Verified published-run rule failures only, never raw source payloads.

    Both SQL literals are selected from our code-owned source/rule registries,
    never interpolated from arbitrary user text. The SQL itself is SELECT-only.
    """
    if dataset not in SOURCES:
        raise ValueError("Unknown source dataset")
    if not any(r.dataset == dataset and r.rule_id == rule_id for r in RULES):
        raise HTTPException(status_code=404, detail="Rule not registered for this domain")
    # Only project-approved fields are extracted from the row JSON. Never
    # SELECT or return original_values itself: source rows may contain PII.
    order_fields = ""
    if dataset == "orders":
        order_fields = (
            ", get_json_object(f.original_values, '$.order_id') AS original_order_id"
        )
        if rule_id == "orders.lifecycle":
            order_fields += (
                ", get_json_object(f.original_values, '$.order_purchase_timestamp') AS purchased_at"
                ", get_json_object(f.original_values, '$.order_approved_at') AS approved_at"
                ", get_json_object(f.original_values, '$.order_delivered_carrier_date') AS carrier_handoff_at"
                ", get_json_object(f.original_values, '$.order_delivered_customer_date') AS delivered_at"
            )
    return (
        "SELECT p.run_id AS published_run, r.dataset, r.rule_id, "
        "r.action AS rule_action, r.records_failed AS failed_evaluations, "
        "f.source_record_id, f.failure_reason, f.action AS record_action "
        f"{order_fields} "
        f"FROM {RESULT_TABLE} r "
        f"JOIN {PUBLISHED_TABLE} p ON r.run_id = p.run_id "
        f"LEFT JOIN {FAILED_RECORD_TABLE} f "
        "ON f.run_id = r.run_id AND f.rule_id = r.rule_id AND f.dataset = r.dataset "
        f"WHERE r.dataset = '{dataset}' AND r.rule_id = '{rule_id}' "
        "AND r.status = 'FAILED' "
        f"ORDER BY f.source_record_id LIMIT {MAX_FAILED_RECORD_PREVIEW}"
    )


def failed_record_sample_sql(dataset: str, rule_id: str) -> str:
    """Published-run per-rule sampled source identifiers.

    The quality engine persists up to 10 exact flagged source-record IDs in
    dq_rule_results.sample_failed_identifiers at evaluation time. This remains
    useful if the more detailed dq_failed_records table isn't available to
    the Databricks App's service principal.
    """
    if dataset not in SOURCES:
        raise ValueError("Unknown source dataset")
    if not any(r.dataset == dataset and r.rule_id == rule_id for r in RULES):
        raise HTTPException(status_code=404, detail="Rule not registered for this domain")
    return (
        "SELECT p.run_id AS published_run, r.dataset, r.rule_id, "
        "r.action AS rule_action, r.records_failed AS failed_evaluations, "
        "r.sample_failed_identifiers "
        f"FROM {RESULT_TABLE} r "
        f"JOIN {PUBLISHED_TABLE} p ON r.run_id = p.run_id "
        f"WHERE r.dataset = '{dataset}' AND r.rule_id = '{rule_id}' "
        "AND r.status = 'FAILED' LIMIT 1"
    )


def normalize_failed_record_sample(dataset: str, rule_id: str, rows: list[dict]) -> dict:
    """Return only authentic IDs saved in the published-run quality result."""
    if len(rows) != 1:
        raise RuntimeError("Expected exactly one published-run failed rule")
    row = rows[0]
    run_id = str(row.get("published_run") or "")
    if (not run_id or row.get("dataset") != dataset or
            row.get("rule_id") != rule_id):
        raise RuntimeError("Unexpected published sample provenance")
    count = int(row["failed_evaluations"])
    if count <= 0:
        raise RuntimeError("Published failure has no failed evaluations")
    raw = row.get("sample_failed_identifiers")
    parsed = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(parsed, list) or len(parsed) > 10:
        raise RuntimeError("Invalid or unexpectedly large published sample")
    if any(not isinstance(item, (str, int)) or isinstance(item, bool) for item in parsed):
        raise RuntimeError("Invalid published source record identifier")
    items = [str(item) for item in parsed]
    if len(items) > count:
        raise RuntimeError("Published sample exceeds recorded failure count")
    return {
        "dataset": dataset,
        "rule_id": rule_id,
        "published_run": run_id,
        "configured_action": str(row.get("rule_action") or ""),
        "failed_evaluations": count,
        "record_preview": [{
            "source_record_id": record_id,
            "failure_reason": "",
            "record_action": str(row.get("rule_action") or ""),
        } for record_id in items],
        "preview_limit": 10,
        "preview_source": "published_rule_result_sample",
        "source": [RESULT_TABLE, PUBLISHED_TABLE],
        "limitations": (
            "These are sample identifiers persisted during rule evaluation. "
            "Individual failure reasons from dq_failed_records were not retrieved. "
            "The recorded rule action does not prove an individual record was "
            "excluded: WARN findings remain unless another rule quarantines them."
        ),
    }



# The lifecycle rule in domain/rules.py evaluates consecutive known events.
# Source timestamps lack an agreed timezone, so compare their recorded local
# values only; never convert them to UTC or infer business causation.
LIFECYCLE_STAGES = (
    ("purchased_at", "Purchase"),
    ("approved_at", "Approval"),
    ("carrier_handoff_at", "Carrier handoff"),
    ("delivered_at", "Customer delivery"),
)


def _recorded_time(value: object) -> str | None:
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # No UTC conversion: historical Olist timestamps do not establish a zone.
    if parsed.tzinfo is not None:
        return None
    return text


def recorded_lifecycle_evidence(row: dict) -> dict:
    """Retain only allowed timestamps and verified adjacent-order violations."""
    stages = []
    for column, label in LIFECYCLE_STAGES:
        stages.append({
            "field": column,
            "label": label,
            "value": _recorded_time(row.get(column)),
        })
    problems = []
    for earlier, later in zip(stages, stages[1:]):
        left, right = earlier["value"], later["value"]
        if left is None or right is None:
            continue
        if datetime.fromisoformat(left) > datetime.fromisoformat(right):
            problems.append({
                "earlier_stage": earlier["label"],
                "earlier_time": left,
                "later_stage": later["label"],
                "later_time": right,
                "explanation": (
                    f"{later['label']} ({right}) is recorded before "
                    f"{earlier['label']} ({left})."
                ),
            })
    return {"recorded_timestamps": stages, "chronology_violations": problems}


def _failed_record_example(dataset: str, rule_id: str, row: dict) -> dict:
    record = {
        "source_record_id": str(row["source_record_id"]),
        "failure_reason": str(row.get("failure_reason") or ""),
        "record_action": str(row.get("record_action") or ""),
    }
    if dataset == "orders":
        original_id = row.get("original_order_id")
        if original_id:
            record["original_order_id"] = str(original_id)
        if rule_id == "orders.lifecycle" and any(
            field in row for field, _ in LIFECYCLE_STAGES
        ):
            record.update(recorded_lifecycle_evidence(row))
    return record


def normalize_failed_record_preview(dataset: str, rule_id: str, rows: list[dict]) -> dict:
    """Keep rule evaluations distinct from example failed source records."""
    if not rows:
        raise HTTPException(status_code=404, detail="Rule has no failure in the active published run")
    valid = {
        (str(row.get("published_run")), str(row.get("dataset")),
         str(row.get("rule_id")), str(row.get("rule_action")),
         int(row["failed_evaluations"]))
        for row in rows
    }
    if len(valid) != 1:
        raise RuntimeError("Inconsistent published failure evidence")
    run_id, observed_dataset, observed_rule, action, evaluations = next(iter(valid))
    if observed_dataset != dataset or observed_rule != rule_id or not run_id or run_id == "None":
        raise RuntimeError("Unexpected rule or published run in record preview")
    if evaluations <= 0:
        raise RuntimeError("Expected positive failed-evaluation count for FAILED rule")
    sample = [_failed_record_example(dataset, rule_id, row)
              for row in rows if row.get("source_record_id") is not None]
    return {
        "dataset": dataset,
        "rule_id": rule_id,
        "published_run": run_id,
        "configured_action": action,
        "failed_evaluations": evaluations,
        "record_preview": sample,
        "preview_limit": MAX_FAILED_RECORD_PREVIEW,
        "preview_source": "detailed_failed_records",
        "source": [RESULT_TABLE, FAILED_RECORD_TABLE, PUBLISHED_TABLE],
        "limitations": (
            "This is a bounded preview of rule-flagged source records, not an "
            "export of original row JSON. Where available, only approved "
            "business identifiers and lifecycle timestamps are exposed. Rule evaluations "
            "may overlap; WARN findings are not automatically excluded. "
            "Downstream cascade quarantine is recorded separately."
        ),
    }


@router.get("/api/nexus/domains/{domain}/failed-rules/{rule_id}/records")
def failed_rule_records(domain: str, rule_id: str):
    dataset = resolve_domain(domain)
    statement = failed_record_preview_sql(dataset, rule_id)
    from app.main import sql_query
    try:
        rows = sql_query(statement)
        return normalize_failed_record_preview(dataset, rule_id, rows)
    except HTTPException:
        raise
    except Exception:
        # The detailed failure table can be unavailable to the App identity
        # even when run-scoped rule results are readable. Never label these
        # rule-level samples as individually verified failure reasons.
        logger.warning(
            "Detailed failed-record preview unavailable for %s/%s; "
            "trying published rule-result samples", dataset, rule_id,
            exc_info=True,
        )
    try:
        return normalize_failed_record_sample(
            dataset, rule_id, sql_query(failed_record_sample_sql(dataset, rule_id))
        )
    except Exception as exc:
        logger.exception("NEXUS published failed-record samples also unavailable for %s", dataset)
        raise HTTPException(
            status_code=503,
            detail="Neither detailed failed records nor published rule-result samples are available.",
        ) from exc


# Read-only explanations of actual quarantine entries. A child record's
# recorded accepted_parent rule establishes the pipeline's reason for
# exclusion; matching a separately quarantined parent business order in the
# SAME published run provides corroborating lineage.
QUARANTINE_PREVIEW_LIMIT = 20
ORDER_CHILD_DATASETS = frozenset(("payments", "order_items", "reviews"))


def quarantine_lineage_sql(dataset: str) -> str:
    if dataset not in SOURCES:
        raise ValueError("Unknown source dataset")
    child = dataset in ORDER_CHILD_DATASETS
    business_id = (
        "get_json_object(q.original_values, '$.order_id')"
        if child or dataset == "orders" else "CAST(NULL AS STRING)"
    )
    parent_projection = (
        "po.parent_source_record_id, po.parent_rule_ids"
        if child else
        "CAST(NULL AS STRING) AS parent_source_record_id, "
        "CAST(NULL AS STRING) AS parent_rule_ids"
    )
    parent_join = (
        "LEFT JOIN parent_orders po ON po.run_id = q.run_id "
        "AND po.original_order_id = get_json_object(q.original_values, '$.order_id') "
        if child else ""
    )
    # These are explicit per-table, per-run SQL statements, not model-authored
    # SQL. Only two scalar fields are projected from the stored JSON: order_id
    # and the parent order_id used for the verified join. Neither source row's
    # raw original_values nor customer or payment data leaves Databricks.
    return (
        "WITH parent_orders AS ("
        "SELECT run_id, get_json_object(original_values, '$.order_id') AS original_order_id, "
        "MIN(source_record_id) AS parent_source_record_id, "
        "array_join(sort_array(collect_set(rule_id)), ', ') AS parent_rule_ids "
        f"FROM {QUARANTINE_TABLE} "
        "WHERE dataset = 'orders' AND action = 'QUARANTINE' "
        "AND get_json_object(original_values, '$.order_id') IS NOT NULL "
        "GROUP BY run_id, get_json_object(original_values, '$.order_id')"
        ") "
        "SELECT p.run_id AS published_run, q.dataset, q.source_record_id, "
        "q.rule_id, q.failure_reason, q.action, "
        f"{business_id} AS original_order_id, {parent_projection} "
        f"FROM {QUARANTINE_TABLE} q "
        f"JOIN {PUBLISHED_TABLE} p ON p.run_id = q.run_id "
        f"{parent_join}"
        f"WHERE q.dataset = '{dataset}' AND q.action = 'QUARANTINE' "
        "ORDER BY q.source_record_id, q.rule_id "
        f"LIMIT {QUARANTINE_PREVIEW_LIMIT}"
    )


def normalize_quarantine_lineage(dataset: str, rows: list[dict]) -> dict:
    if dataset not in SOURCES:
        raise ValueError("Unknown source dataset")
    if len(rows) > QUARANTINE_PREVIEW_LIMIT:
        raise RuntimeError("Quarantine preview exceeded bounded limit")
    run_ids = {str(row.get("published_run") or "") for row in rows}
    if "" in run_ids or len(run_ids) > 1:
        raise RuntimeError("Quarantine preview lacks a single published-run provenance")
    child = dataset in ORDER_CHILD_DATASETS
    items = []
    for row in rows:
        if row.get("dataset") != dataset or row.get("action") != "QUARANTINE":
            raise RuntimeError("Unexpected dataset or action in quarantine evidence")
        source_id = str(row.get("source_record_id") or "")
        rule_id = str(row.get("rule_id") or "")
        if not source_id or not rule_id:
            raise RuntimeError("Missing source identifier or quarantine rule")
        accepted_parent_reason = (
            child and rule_id == f"{dataset}.accepted_parent"
            and str(row.get("failure_reason") or "").strip() == "Accepted parent missing: orders"
        )
        original_order_id = str(row.get("original_order_id") or "")
        parent_id = str(row.get("parent_source_record_id") or "")
        confirmed_parent = (
            bool(accepted_parent_reason and original_order_id and parent_id)
        )
        items.append({
            "source_record_id": source_id,
            "original_order_id": original_order_id or None,
            "rule_id": rule_id,
            "failure_reason": str(row.get("failure_reason") or ""),
            "action": "QUARANTINE",
            "recorded_accepted_parent_reason": accepted_parent_reason,
            "parent_order_exclusion_verified": confirmed_parent,
            "parent_order_source_record_id": parent_id if confirmed_parent else None,
            "parent_order_rule_ids": (
                [part.strip() for part in str(row.get("parent_rule_ids") or "").split(",")
                 if part.strip()] if confirmed_parent else []
            ),
        })
    return {
        "dataset": dataset,
        "published_run": next(iter(run_ids)) if run_ids else None,
        "record_preview": items,
        "preview_limit": QUARANTINE_PREVIEW_LIMIT,
        "verified_parent_matches": sum(r["parent_order_exclusion_verified"] for r in items),
        "source": [QUARANTINE_TABLE, PUBLISHED_TABLE],
        "note": (
            "Only rows actually present in the active published run's quarantine "
            "table appear. An accepted_parent failure_reason proves the recorded "
            "cascade policy; a same-run matching quarantined parent order independently "
            "corroborates that order's exclusion. Without a matching parent, "
            "the cause remains recorded but the parent linkage is not independently "
            "verified. Results are a bounded sample, not an all-record export."
        ),
    }


@router.get("/api/nexus/domains/{domain}/quarantine-lineage")
def domain_quarantine_lineage(domain: str):
    dataset = resolve_domain(domain)
    from app.main import sql_query
    try:
        return normalize_quarantine_lineage(dataset, sql_query(quarantine_lineage_sql(dataset)))
    except Exception as exc:
        logger.exception("NEXUS published quarantine lineage unavailable for %s", dataset)
        raise HTTPException(
            status_code=503,
            detail="Published quarantine lineage currently unavailable. No dependency is inferred.",
        ) from exc
