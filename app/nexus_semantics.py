"""Read-only semantic contracts, documented dependencies and SQL metric verification.

The dashboard, metric registry, Unity Catalog tables and published snapshot stay
untouched. This endpoint distinguishes governed glossary definitions, project-
registered conceptual edges, and independently executed publication-scoped SQL.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, HTTPException

from olist_agentic.domain.metrics import METRICS

logger = logging.getLogger(__name__)
router = APIRouter()

PUBLISHED = "workspace.olist_agentic_quality.published_run"
VIEW = "workspace.olist_semantic.v_published_orders"
DICTIONARY = "workspace.olist_governance.metric_dictionary"
EDGES = "workspace.olist_governance.lineage_edges"

METRIC_IDS = frozenset(m.metric_id for m in METRICS)

METRIC_DICTIONARY_SQL = (
    "SELECT metric_id, metric_name, business_definition, formula_description, "
    "grain, population, inclusions, exclusions, unit, owner, source_object, "
    f"quality_dependency, known_caveat FROM {DICTIONARY} "
    "ORDER BY metric_name LIMIT 30"
)
METRIC_EDGE_SQL = (
    "SELECT metric_id, source_asset, target_asset, relationship_type, description "
    f"FROM {EDGES} WHERE metric_id <> '' ORDER BY metric_id LIMIT 100"
)

# numerator, denominator, display operation, source component names.
# Values are computed at accepted ORDER GRAIN, never by joining child fact rows.
CALCULATIONS = {
    "total_orders": (
        "COUNT(*)", "CAST(NULL AS BIGINT)", "count",
        "Accepted orders", None,
    ),
    "delivered_orders": (
        "SUM(CASE WHEN is_delivered THEN 1 ELSE 0 END)",
        "CAST(NULL AS BIGINT)", "count", "Delivered orders", None,
    ),
    "cancelled_orders": (
        "SUM(CASE WHEN is_cancelled THEN 1 ELSE 0 END)",
        "CAST(NULL AS BIGINT)", "count", "Cancelled orders", None,
    ),
    "gmv": (
        "SUM(CASE WHEN is_delivered THEN COALESCE(item_gmv,0) ELSE 0 END)",
        "CAST(NULL AS BIGINT)", "amount",
        "Delivered item prices, BRL", None,
    ),
    "freight": (
        "SUM(CASE WHEN is_delivered THEN COALESCE(freight_value,0) ELSE 0 END)",
        "CAST(NULL AS BIGINT)", "amount", "Delivered freight, BRL", None,
    ),
    "aov": (
        "SUM(CASE WHEN is_delivered THEN COALESCE(item_gmv,0) ELSE 0 END)",
        "SUM(CASE WHEN is_delivered AND item_count > 0 THEN 1 ELSE 0 END)",
        "average", "Delivered item GMV, BRL", "Delivered orders with accepted items",
    ),
    "on_time_rate": (
        "SUM(CASE WHEN delivery_eligible AND NOT is_late THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END)",
        "percentage", "Eligible on-time deliveries", "All eligible deliveries",
    ),
    "late_rate": (
        "SUM(CASE WHEN delivery_eligible AND is_late THEN 1 ELSE 0 END)",
        "SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END)",
        "percentage", "Eligible late deliveries", "All eligible deliveries",
    ),
    "delivery_days": (
        "SUM(CASE WHEN is_delivered AND delivery_days >= 0 THEN delivery_days ELSE 0 END)",
        "SUM(CASE WHEN is_delivered AND delivery_days >= 0 THEN 1 ELSE 0 END)",
        "average", "Total nonnegative delivery days", "Delivered orders with valid durations",
    ),
    "delay_days": (
        "SUM(CASE WHEN delivery_eligible AND is_late THEN delay_days ELSE 0 END)",
        "SUM(CASE WHEN delivery_eligible AND is_late AND delay_days IS NOT NULL THEN 1 ELSE 0 END)",
        "average", "Total delay days among late eligible deliveries",
        "Late eligible deliveries with recorded delay",
    ),
    "review_score": (
        "SUM(COALESCE(review_score,0))",
        "COUNT(review_score)", "average", "Sum of latest accepted review scores",
        "Accepted orders with a scored review",
    ),
    "negative_review_rate": (
        "SUM(CASE WHEN review_score <= 2 THEN 1 ELSE 0 END)",
        "COUNT(review_score)", "percentage", "Latest reviews with score 1 or 2",
        "Latest reviews with a score",
    ),
    "repeat_customer_rate": (
        "SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)",
        "COUNT(*)", "percentage", "Persistent customers with multiple accepted orders",
        "Persistent customers with an accepted order",
    ),
}
if set(CALCULATIONS) != METRIC_IDS:
    raise RuntimeError("Metric SQL allowlist does not match governed metric registry")


def metric_sql(metric_id: str) -> str:
    if metric_id not in METRIC_IDS:
        raise HTTPException(status_code=404, detail="Unregistered metric")
    numerator, denominator, operation, _, _ = CALCULATIONS[metric_id]
    if metric_id == "repeat_customer_rate":
        derived_source = (
            "(SELECT customer_unique_id, COUNT(*) AS order_count "
            f"FROM {VIEW} WHERE customer_unique_id IS NOT NULL "
            "GROUP BY customer_unique_id) customer_cohorts"
        )
    else:
        derived_source = VIEW

    if operation in ("amount", "count"):
        value = "a.numerator"
    else:
        multiplier = "100.0 * " if operation == "percentage" else ""
        value = f"({multiplier}a.numerator / NULLIF(a.denominator,0))"
    return (
        "SELECT p.run_id AS published_run, a.numerator, a.denominator, "
        f"CAST(ROUND({value}, 4) AS DECIMAL(28,4)) AS verified_value "
        f"FROM {PUBLISHED} p CROSS JOIN ("
        f"SELECT {numerator} AS numerator, {denominator} AS denominator "
        f"FROM {derived_source}"
        ") a LIMIT 1"
    )


def normalize_dictionary(rows: list[dict], edges: list[dict], edge_verified: bool) -> dict:
    if not rows:
        raise RuntimeError("Metric dictionary returned no governed definitions")
    seen = set()
    metrics = []
    for row in rows:
        mid = str(row.get("metric_id") or "")
        if mid not in METRIC_IDS or mid in seen:
            raise RuntimeError("Unexpected or duplicated metric dictionary ID")
        seen.add(mid)
        metrics.append({
            key: str(row.get(key) or "")
            for key in ("metric_id", "metric_name", "business_definition",
                        "formula_description", "grain", "population", "inclusions",
                        "exclusions", "unit", "owner", "source_object",
                        "quality_dependency", "known_caveat")
        })
    # Do not quietly present only some definitions as the full registry.
    if seen != METRIC_IDS:
        raise RuntimeError("Governed metric dictionary is incomplete")
    lineage = []
    for row in edges:
        mid = str(row.get("metric_id") or "")
        if mid not in seen:
            continue
        lineage.append({
            key: str(row.get(key) or "")
            for key in ("metric_id", "source_asset", "target_asset",
                        "relationship_type", "description")
        })
    return {
        "scope": "NATIONAL_PUBLISHED_SNAPSHOT",
        "metrics": metrics,
        "documented_edges": lineage,
        "edge_registry_accessible": edge_verified,
        "definition_source": DICTIONARY,
        "edge_source": EDGES if edge_verified else None,
        "query_source": VIEW,
        "lineage_qualification": (
            "Documented edges are project governance registry metadata, NOT "
            "automatically discovered Unity Catalog runtime lineage. "
            "A verified SQL result is independently computed from the "
            "active quality-gated published-order view, nationwide."
        ),
    }


def _decimal(value: object, label: str, *, nullable: bool = False) -> Decimal | None:
    if value is None or str(value).strip() == "":
        if nullable:
            return None
        raise RuntimeError(f"Missing SQL {label}")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise RuntimeError(f"Invalid SQL {label}") from exc
    if not parsed.is_finite():
        raise RuntimeError(f"Nonfinite SQL {label}")
    return parsed


def normalize_metric_result(metric_id: str, rows: list[dict]) -> dict:
    if metric_id not in METRIC_IDS:
        raise HTTPException(status_code=404, detail="Unregistered metric")
    if len(rows) != 1:
        raise RuntimeError("Expected one verified metric row")
    row = rows[0]
    run_id = str(row.get("published_run") or "")
    if not run_id:
        raise RuntimeError("Metric verification is missing the published run")
    numerator = _decimal(row.get("numerator"), "numerator")
    denominator = _decimal(row.get("denominator"), "denominator", nullable=True)
    verified = _decimal(row.get("verified_value"), "verified value", nullable=True)
    _, _, operation, numerator_label, denominator_label = CALCULATIONS[metric_id]
    if operation in ("amount", "count"):
        if denominator is not None or verified is None:
            raise RuntimeError("Unexpected count/amount metric components")
    else:
        if denominator is None:
            raise RuntimeError("Rate/average denominator missing")
        if denominator <= 0 and verified is not None:
            raise RuntimeError("Zero-denominator metric must have NULL value")
        if denominator > 0 and verified is None:
            raise RuntimeError("Verified ratio unexpectedly NULL")
    if operation == "count" and numerator != numerator.to_integral_value():
        raise RuntimeError("Count verification is not integral")
    if numerator < 0 and operation in ("percentage", "count"):
        raise RuntimeError("Negative metric count")
    return {
        "metric_id": metric_id,
        "published_run": run_id,
        "scope": "NATIONAL_PUBLISHED_SNAPSHOT",
        "grain": "One accepted order",
        "verified_value": str(verified) if verified is not None else None,
        "numerator": str(numerator),
        "denominator": str(denominator) if denominator is not None else None,
        "numerator_label": numerator_label,
        "denominator_label": denominator_label,
        "operation": operation,
        "sql_evidence_source": VIEW,
        "run_pointer_source": PUBLISHED,
        "not_accounting_revenue": metric_id in ("gmv", "freight", "aov"),
        "limitations": (
            "The metric value and its arithmetic components were calculated by "
            "approved read-only SQL on the published accepted-order view. "
            "The selected metric's business definition, eligibility, caveat and "
            "exclusions remain governed by the separate dictionary. "
            "Results are historical (2016–2018), not live sales or "
            "independently audited accounting revenue."
        ),
    }


@router.get("/api/nexus/semantic-contracts")
def semantic_contracts():
    from app.main import sql_query
    try:
        rows = sql_query(METRIC_DICTIONARY_SQL)
        try:
            edges = sql_query(METRIC_EDGE_SQL)
            edge_access = True
        except Exception:
            logger.warning("NEXUS metric lineage registry unavailable; show no invented edges", exc_info=True)
            edges = []
            edge_access = False
        return normalize_dictionary(rows, edges, edge_access)
    except Exception as exc:
        logger.exception("NEXUS governed semantic dictionary unavailable")
        raise HTTPException(
            status_code=503,
            detail="Governed metric dictionary unavailable; no definitions invented."
        ) from exc


@router.get("/api/nexus/semantic-contracts/{metric_id}/verify")
def verify_semantic_metric(metric_id: str):
    sql = metric_sql(metric_id)
    from app.main import sql_query
    try:
        rows = sql_query(sql)
        return normalize_metric_result(metric_id, rows)
    except Exception as exc:
        logger.exception("NEXUS metric verification query unavailable: %s", metric_id)
        raise HTTPException(
            status_code=503,
            detail="Published metric verification unavailable; no value inferred."
        ) from exc
