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
from pipelines.independent_etl import ETLConfig, execute as execute_etl, finalize_audit


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
    """Validate isolated staged data BEFORE advancing the publication pointer."""
    from pyspark.sql import functions as F
    config = ETLConfig()
    audit = execute_etl(spark, config, publish=False)
    run_id = audit["run_id"]
    if audit["status"] != "STAGED":
        raise ValueError(f"Independent ETL was not staged: {audit['status']}")
    fact = spark.table(config.table("gold", "fact_orders")).filter(F.col("pipeline_run_id") == run_id)
    count = fact.count()
    if count != 99433:
        raise ValueError(f"Staged order count mismatch: {count}, expected 99433")
    checks = fact.agg(
        F.sum(F.when(F.col("is_delivered"), 1).otherwise(0)).alias("delivered"),
        F.sum(F.when(F.col("is_delivered"), F.coalesce(F.col("item_gmv"), F.lit(0))).otherwise(0)).alias("gmv"),
        F.sum(F.when(F.col("delivery_eligible"), 1).otherwise(0)).alias("eligible"),
        F.sum(F.when(F.col("delivery_eligible") & F.col("is_late"), 1).otherwise(0)).alias("late")
    ).first()
    if checks["delivered"] != 96470 or abs(float(checks["gmv"]) - 13220248.93) > 0.01:
        raise ValueError(f"Staged KPI mismatch: {checks}")
    late_rate = 100.0 * checks["late"] / checks["eligible"]
    if abs(late_rate - 6.7731) > 0.001:
        raise ValueError(f"Staged late rate mismatch: {late_rate}")

    governance_counts = publish_governance(spark, Config(catalog="workspace", schema_prefix="olist"))
    # The semantic published-run view can be created with an empty pointer.
    pointer_table = config.table("quality", "published_run")
    if not spark.catalog.tableExists(pointer_table):
        spark.createDataFrame([], "run_id STRING").write.format("delta").saveAsTable(pointer_table)
    previous = [r["run_id"] for r in spark.table(pointer_table).select("run_id").collect()]
    if len(previous) > 1:
        raise ValueError("Multiple published-run pointer rows")
    semantic_objects = publish_semantic(spark)
    # Promote only after staging, governance, semantic DDL and staged KPI checks pass.
    spark.createDataFrame([(run_id,)], "run_id STRING").write.format("delta").mode("overwrite").saveAsTable(pointer_table)
    try:
        semantic_count = _single_scalar(spark, "SELECT COUNT(*) FROM workspace.olist_semantic.v_published_orders")
        if int(semantic_count) != count:
            raise ValueError(f"Published-orders view mismatch: {semantic_count} vs {count}")
        row = spark.sql(
            "SELECT MEASURE(total_orders) AS total_orders, "
            "MEASURE(delivered_orders) AS delivered_orders, MEASURE(gmv) AS gmv, "
            "MEASURE(late_rate) AS late_rate "
            "FROM workspace.olist_semantic.mv_order_operations"
        ).first()
        observed = {k: float(row[k]) for k in ("total_orders", "delivered_orders", "gmv", "late_rate")}
        target = {"total_orders": 99433, "delivered_orders": 96470, "gmv": 13220248.93, "late_rate": 6.7731}
        tolerance = {"total_orders": 0, "delivered_orders": 0, "gmv": 0.01, "late_rate": 0.001}
        for key in target:
            if abs(observed[key] - target[key]) > tolerance[key]:
                raise ValueError(f"Metric view mismatch for {key}: {observed[key]} vs {target[key]}")
    except Exception:
        finalize_audit(spark, config, run_id, "VALIDATION_FAILED")
        # Restore the prior pointer; a first-run failure reverts to no published run.
        if previous:
            spark.createDataFrame([(previous[0],)], "run_id STRING").write.format("delta").mode("overwrite").saveAsTable(pointer_table)
        else:
            spark.sql(f"DELETE FROM {pointer_table}")
        raise
    finalize_audit(spark, config, run_id, "SUCCEEDED")
    audit["status"] = "SUCCEEDED"
    return {
        "status": "PASSED", "published_run": run_id,
        "staged_etl_audit": audit, "governance": governance_counts,
        "semantic": semantic_objects, "metrics": observed,
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
