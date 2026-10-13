"""Published-run quality control matrix for the custom NEXUS Quality Gate.

The source registry and native AI/BI dashboard are not modified. The Quality
Gate reads the active run's actual rule outcomes and distinct quarantine rows.
Never interpret a configured rule as an observed failure.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException

from olist_agentic.domain.sources import SOURCES

from app.nexus_domains import (
    PUBLISHED_TABLE, RULE_TABLE, RESULT_TABLE, QUARANTINE_TABLE,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Explicitly bounded read-only fixed application SQL. Rule definitions come
# from Unity Catalog, their status from the same published run pointer.
QUALITY_RULE_SQL = (
    "SELECT p.run_id AS published_run, g.rule_id, g.dataset, "
    "g.business_name, g.plain_english_description, g.action, g.severity, "
    "r.status AS observed_status, r.records_failed AS failed_evaluations "
    f"FROM {RULE_TABLE} g CROSS JOIN {PUBLISHED_TABLE} p "
    f"LEFT JOIN {RESULT_TABLE} r ON r.rule_id = g.rule_id "
    "AND r.run_id = p.run_id ORDER BY g.dataset, g.rule_id LIMIT 200"
)

QUALITY_QUARANTINE_SQL = (
    "SELECT p.run_id AS published_run, q.dataset, "
    "COUNT(DISTINCT q.source_record_id) AS distinct_excluded_rows "
    f"FROM {QUARANTINE_TABLE} q "
    f"JOIN {PUBLISHED_TABLE} p ON q.run_id = p.run_id "
    "WHERE q.action = 'QUARANTINE' "
    "GROUP BY p.run_id, q.dataset ORDER BY q.dataset LIMIT 30"
)

_ALLOWED_STATUS = frozenset(("PASSED", "FAILED", "ERROR", "SKIPPED"))


def normalize_quality_gate(rule_rows: list[dict], quarantine_rows: list[dict]) -> dict:
    if not rule_rows:
        raise RuntimeError("Published rule evaluations are unavailable")
    ids = {str(row.get("published_run") or "") for row in rule_rows}
    if "" in ids or len(ids) != 1:
        raise RuntimeError("The quality matrix must refer to one published run")
    run_id = next(iter(ids))
    seen = set()
    rules = []
    for row in rule_rows:
        key = str(row.get("rule_id") or "")
        dataset = str(row.get("dataset") or "")
        status = row.get("observed_status")
        if not key or key in seen or dataset not in SOURCES:
            raise RuntimeError("Rule IDs are invalid, duplicated, or not registered")
        if status is not None and status not in _ALLOWED_STATUS:
            raise RuntimeError("Unknown published rule status")
        seen.add(key)
        count = row.get("failed_evaluations")
        count = int(count) if count is not None else None
        if count is not None and count < 0:
            raise RuntimeError("Negative rule violation count")
        if status == "FAILED" and (count is None or count <= 0):
            raise RuntimeError("A FAILED definition requires observed violations")
        rules.append({
            "rule_id": key,
            "dataset": dataset,
            "business_name": str(row.get("business_name") or ""),
            "description": str(row.get("plain_english_description") or ""),
            "action": str(row.get("action") or ""),
            "severity": str(row.get("severity") or ""),
            "observed_status": status,
            "failed_evaluations": count,
        })

    quarantined = {dataset: 0 for dataset in SOURCES}
    for row in quarantine_rows:
        if row.get("published_run") != run_id:
            raise RuntimeError("Quarantine evidence does not match the published run")
        dataset = str(row.get("dataset") or "")
        if dataset not in quarantined:
            raise RuntimeError("Unregistered dataset in quarantine evidence")
        count = int(row["distinct_excluded_rows"])
        if count < 0 or quarantined[dataset] != 0:
            raise RuntimeError("Invalid duplicate quarantine evidence")
        quarantined[dataset] = count

    counts = {state: sum(r["observed_status"] == state for r in rules)
              for state in _ALLOWED_STATUS}
    unobserved = sum(r["observed_status"] is None for r in rules)
    failures = [r for r in rules if r["observed_status"] == "FAILED"]
    return {
        "published_run": run_id,
        "scope": "BRAZIL_ALL_STATES",
        "source": [RULE_TABLE, RESULT_TABLE, QUARANTINE_TABLE, PUBLISHED_TABLE],
        "rule_definitions": len(rules),
        "observed_evaluations": len(rules) - unobserved,
        "passed_definitions": counts["PASSED"],
        "failed_definitions": counts["FAILED"],
        "error_definitions": counts["ERROR"],
        "skipped_definitions": counts["SKIPPED"],
        "unobserved_definitions": unobserved,
        "failed_quarantine_definitions": sum(r["action"] == "QUARANTINE" for r in failures),
        "failed_warn_definitions": sum(r["action"] == "WARN" for r in failures),
        "failed_evaluations_total": sum(r["failed_evaluations"] or 0 for r in failures),
        "quarantine_by_dataset": quarantined,
        "distinct_quarantined_source_rows": sum(quarantined.values()),
        "rules": rules,
        "note": (
            "This is the entire national published snapshot, independent of the "
            "NEXUS Brazil-state selector and embedded dashboard filters. A failed "
            "rule definition can have many failed evaluations; quarantined rows "
            "are distinct excluded source records, including dependent cascades. "
            "WARN findings do not themselves exclude source records."
        ),
    }


@router.get("/api/nexus/quality-gate")
def quality_gate():
    from app.main import sql_query
    try:
        rules = sql_query(QUALITY_RULE_SQL)
        quarantine = sql_query(QUALITY_QUARANTINE_SQL)
        return normalize_quality_gate(rules, quarantine)
    except Exception as exc:
        logger.exception("NEXUS quality matrix unavailable for published run")
        raise HTTPException(
            status_code=503, detail="Published quality evidence unavailable; no statuses inferred."
        ) from exc
