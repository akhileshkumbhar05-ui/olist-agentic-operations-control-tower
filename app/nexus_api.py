"""Read-only state KPI API for the optional NEXUS frontend.

All values are calculated from the existing published semantic view. No ETL,
governance table, dashboard specification, or legacy handler is modified.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

logger = logging.getLogger(__name__)
router = APIRouter()

# The domain inspector is independent of native dashboard/semantic KPI routes.
from app.nexus_domains import router as domain_router
router.include_router(domain_router)
# NEXUS Quality Gate: whole-run governance matrix (independent from source inspector).
from app.nexus_quality import router as quality_router
router.include_router(quality_router)
STATES = frozenset("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO".split())

# Static read-only SQL, no user-provided identifiers or raw table access.
# GROUPING distinguishes nationwide total from the state cohorts.
COHORT_SQL = """
SELECT
  CASE WHEN GROUPING(customer_state) = 1 THEN 'ALL'
       ELSE customer_state END AS state,
  COUNT(*) AS accepted_orders,
  SUM(CASE WHEN is_delivered THEN 1 ELSE 0 END) AS delivered_orders,
  CAST(ROUND(SUM(CASE WHEN is_delivered
      THEN COALESCE(item_gmv, 0) ELSE 0 END), 2) AS DECIMAL(20,2))
      AS delivered_item_gmv_brl,
  SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END)
      AS eligible_deliveries,
  SUM(CASE WHEN delivery_eligible AND is_late THEN 1 ELSE 0 END)
      AS late_deliveries,
  ROUND(100.0 * SUM(CASE WHEN delivery_eligible AND is_late
      THEN 1 ELSE 0 END) /
      NULLIF(SUM(CASE WHEN delivery_eligible THEN 1 ELSE 0 END), 0), 4)
      AS late_delivery_rate_pct
FROM workspace.olist_semantic.v_published_orders
GROUP BY GROUPING SETS ((), (customer_state))
""".strip()


def normalize_state_rows(rows: list[dict]) -> list[dict]:
    return [
        row for row in rows
        if isinstance(row, dict) and row.get("state") in STATES | {"ALL"}
    ]


@router.get("/api/nexus/state-kpis")
def state_kpis():
    # Import lazily to reuse the original working Databricks SDK client.
    from app.main import sql_query

    try:
        states = normalize_state_rows(sql_query(COHORT_SQL))
        if sum(row["state"] == "ALL" for row in states) != 1:
            raise RuntimeError("Expected one nationwide cohort")
        return {
            "source": "workspace.olist_semantic.v_published_orders",
            "scope": "current_published_run",
            "states": states,
        }
    except Exception as exc:
        logger.exception("NEXUS cohort SQL query failed")
        raise HTTPException(status_code=503, detail="Governed state KPIs temporarily unavailable") from exc


@router.get("/nexus/br_states_paths.json", include_in_schema=False)
def brazil_state_geometry():
    path = Path(__file__).resolve().parent / "static" / "br_states_paths.json"
    return FileResponse(path, media_type="application/json")
