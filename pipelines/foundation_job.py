"""Orchestrated independent Phase 2 ETL, governance and semantic publication.

--apply executes the source-to-Gold pipeline in isolated olist_agentic_* schemas.
Neither code nor write paths target Phase 1 data tables.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__ if "__file__" in globals() else __import__("inspect").currentframe().f_code.co_filename).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from olist_agentic.config import Config
from pipelines.governance_publish import validate_catalogs, publish as publish_governance
from pipelines.semantic_publish import statements, publish as publish_semantic
from pipelines.independent_etl import ETLConfig, execute as execute_etl


def plan() -> dict:
    """Validate static metadata and SQL generation without accessing Databricks."""
    counts = validate_catalogs()
    sql_statements = statements()
    if len(sql_statements) != 3:
        raise ValueError("Unexpected semantic deployment plan")
    return {
        "mode": "DRY_RUN",
        "governance_schema": "workspace.olist_governance",
        "governance_tables": counts,
        "semantic_schema": "workspace.olist_semantic",
        "semantic_objects": [
            "workspace.olist_semantic.v_published_orders",
            "workspace.olist_semantic.mv_order_operations",
        ],
        "write_schemas": ["workspace.olist_agentic_bronze", "workspace.olist_agentic_silver", "workspace.olist_agentic_gold", "workspace.olist_agentic_quality"],
        "read_only_dependencies": [],
        "steps": ["independent_etl", "governance_publish", "semantic_publish", "semantic_validation"],
    }


def _single_scalar(spark, sql: str):
    rows = spark.sql(sql).collect()
    if len(rows) != 1 or len(rows[0]) != 1:
        raise ValueError("Expected one scalar result for smoke test")
    return rows[0][0]


def deploy(spark) -> dict:
    """Publish only new governance and semantic assets; verify key source KPIs."""
    etl_audit = execute_etl(spark, ETLConfig())
    current_run = _single_scalar(
        spark,
        "SELECT run_id FROM workspace.olist_agentic_quality.published_run",
    )
    if not current_run:
        raise ValueError("No Phase 1 published snapshot exists; do not deploy")
    expected_orders = _single_scalar(
        spark,
        f"SELECT COUNT(*) FROM workspace.olist_agentic_gold.fact_orders "
        f"WHERE pipeline_run_id = '{current_run}'",
    )
    if int(expected_orders) != 99433:
        raise ValueError(
            "Source snapshot differs from validated POC baseline "
            f"(observed {expected_orders}; expected 99433); halt and investigate"
        )

    governance_counts = publish_governance(
        spark,
        Config(catalog="workspace", schema_prefix="olist"),
    )
    semantic_objects = publish_semantic(spark)

    semantic_count = _single_scalar(
        spark,
        "SELECT COUNT(*) FROM workspace.olist_semantic.v_published_orders",
    )
    if int(semantic_count) != int(expected_orders):
        raise ValueError(
            f"Published-orders view count mismatch: {semantic_count} vs {expected_orders}"
        )

    metric_values = spark.sql(
        "SELECT MEASURE(total_orders) AS total_orders, "
        "MEASURE(delivered_orders) AS delivered_orders, "
        "MEASURE(gmv) AS gmv, "
        "MEASURE(late_rate) AS late_rate "
        "FROM workspace.olist_semantic.mv_order_operations"
    ).first()
    if metric_values is None:
        raise ValueError("Metric view returned no values")
    measured = {
        "total_orders": int(metric_values["total_orders"]),
        "delivered_orders": int(metric_values["delivered_orders"]),
        "gmv": float(metric_values["gmv"]),
        "late_rate": float(metric_values["late_rate"]),
    }
    expected = {
        "total_orders": 99433,
        "delivered_orders": 96470,
        "gmv": 13220248.93,
        "late_rate": 6.7731,
    }
    tolerances = {
        "total_orders": 0,
        "delivered_orders": 0,
        "gmv": 0.01,
        "late_rate": 0.001,
    }
    for metric, value in measured.items():
        if abs(value - expected[metric]) > tolerances[metric]:
            raise ValueError(
                f"Semantic KPI mismatch: {metric}: observed {value}, "
                f"validated {expected[metric]}"
            )

    return {
        "status": "PASSED",
        "source_published_run": str(current_run),
        "etl_audit": etl_audit,
        "published_governance_tables": governance_counts,
        "published_semantic_objects": semantic_objects,
        "smoke_test_metrics": measured,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--dry-run", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print(json.dumps(plan(), indent=2))
        return

    from pyspark.sql import SparkSession

    print(json.dumps(deploy(SparkSession.builder.getOrCreate()), indent=2))


if __name__ == "__main__":
    main()
