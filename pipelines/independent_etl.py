"""Independent Phase 2 Medallion ETL.

All writes are scoped to olist_agentic_*; existing Phase 1 olist_* data tables
are read-only and NEVER targeted by this module.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]

from olist_agentic.domain.sources import SOURCES
from olist_agentic.domain.rules import RULES
from olist_agentic.etl.acquire import land
from olist_agentic.etl.spark_quality import evaluate_spark
from olist_agentic.etl.quality_engine import readiness, quality_score
from olist_agentic.etl.spark_models import standardize_spark, gold_spark

SAFE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def safe_name(value: str) -> str:
    if not SAFE.fullmatch(value):
        raise ValueError(f"Unsafe UC identifier: {value!r}")
    return value


class ETLConfig:
    """Deliberately disallows the Phase 1 schema prefix."""
    def __init__(self, catalog="workspace", prefix="olist_agentic", volume="raw"):
        self.catalog = safe_name(catalog)
        self.prefix = safe_name(prefix)
        self.volume = safe_name(volume)
        if self.prefix != "olist_agentic":
            raise ValueError("Independent ETL requires schema prefix olist_agentic")
    def schema(self, layer):
        if layer not in ("bronze", "silver", "gold", "quality"):
            raise ValueError(layer)
        return f"{self.prefix}_{layer}"
    def table(self, layer, name):
        return f"{self.catalog}.{self.schema(layer)}.{safe_name(name)}"
    @property
    def volume_path(self):
        return Path(f"/Volumes/{self.catalog}/{self.schema('bronze')}/{self.volume}")


def metadata_frame(spark, frame):
    from pyspark.sql.types import StructType, StructField, StringType, LongType, DoubleType, BooleanType
    fields = []
    for column in frame:
        dtype = frame[column].dtype
        typ = BooleanType() if pd.api.types.is_bool_dtype(dtype) else LongType() if pd.api.types.is_integer_dtype(dtype) else DoubleType() if pd.api.types.is_float_dtype(dtype) else StringType()
        fields.append(StructField(column, typ, True))
    rows = []
    for values in frame.itertuples(index=False, name=None):
        converted = []
        for value, field in zip(values, fields):
            if pd.isna(value):
                converted.append(None)
            elif isinstance(field.dataType, StringType):
                converted.append(str(value))
            elif isinstance(field.dataType, LongType):
                converted.append(int(value))
            elif isinstance(field.dataType, DoubleType):
                converted.append(float(value))
            else:
                converted.append(bool(value))
        rows.append(converted)
    return spark.createDataFrame(rows, StructType(fields))


def execute(spark, config: ETLConfig, source: Path | None = None):
    from functools import reduce
    from pyspark.sql import functions as F
    config = ETLConfig(config.catalog, config.prefix, config.volume)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    run_id = uuid.uuid4().hex
    started = datetime.now(timezone.utc).isoformat()
    audit = {
        "run_id": run_id, "status": "RUNNING", "started_at": started,
        "batch_start": "source inception", "batch_end": "full historical snapshot",
        "data_label": "REAL OLIST", "records_received": 0, "records_processed": 0,
        "accepted_records": 0, "quarantined_records": 0, "failed_checks": 0,
        "error_message": "", "latest_source_event": "", "ended_at": "",
        "duration_seconds": 0.0,
    }

    def append(layer, name, df):
        df.write.format("delta").mode("append").option("mergeSchema", "true").saveAsTable(config.table(layer, name))

    def save_audit():
        table = config.table("quality", "pipeline_run_audit")
        frame = metadata_frame(spark, pd.DataFrame([audit]))
        if spark.catalog.tableExists(table):
            frame.createOrReplaceTempView("agentic_audit_update")
            spark.sql(f"MERGE INTO {table} t USING agentic_audit_update s ON t.run_id = s.run_id WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")
        else:
            frame.write.format("delta").saveAsTable(table)

    for layer in ("bronze", "silver", "gold", "quality"):
        spark.sql(f"CREATE SCHEMA IF NOT EXISTS {config.catalog}.{config.schema(layer)}")
    spark.sql(f"CREATE VOLUME IF NOT EXISTS {config.catalog}.{config.schema('bronze')}.{config.volume}")
    save_audit()
    try:
        land(config.volume_path, source)
        tables = {}
        for ds, spec in SOURCES.items():
            raw = spark.read.option("header", True).option("inferSchema", False).option("multiLine", True).option("escape", '"').option("mode", "FAILFAST").csv(str(config.volume_path / spec.filename))
            raw = raw.withColumn("source_record_id", F.concat(F.lit(f"{ds}:"), F.monotonically_increasing_id().cast("string")))
            tables[ds] = raw
        for ds, raw in tables.items():
            append("bronze", ds, raw.withColumn("pipeline_run_id", F.lit(run_id))
                .withColumn("ingestion_timestamp", F.lit(started))
                .withColumn("source_file", F.lit(SOURCES[ds].filename))
                .withColumn("simulated_batch_id", F.lit("full"))
                .withColumn("simulated_batch_start", F.lit("source inception"))
                .withColumn("simulated_batch_end", F.lit("full")))
        tables = {
            ds: spark.table(config.table("bronze", ds))
                .filter(F.col("pipeline_run_id") == run_id)
                .drop("pipeline_run_id", "ingestion_timestamp", "source_file",
                      "simulated_batch_id", "simulated_batch_start", "simulated_batch_end")
            for ds in SOURCES
        }
        results, failures, quarantine, scorecard, accepted = evaluate_spark(tables, run_id, started)
        audit["records_received"] = int(scorecard.source_records.sum())
        audit["records_processed"] = audit["records_received"]
        audit["failed_checks"] = int(results.status.eq("FAILED").sum())
        state = readiness(results)
        silver, cascades = standardize_spark(accepted) if state != "BLOCKED" else ({}, [])
        extras = []
        for ds, parent, frame in cascades:
            count = frame.count()
            if count:
                original = tables[ds].join(frame.select("source_record_id"), "source_record_id", "left_semi")
                extras.append(original.select(
                    F.lit(run_id).alias("run_id"), F.lit(ds).alias("dataset"),
                    "source_record_id", F.lit(f"{ds}.accepted_parent").alias("rule_id"),
                    F.lit("Accepted parent integrity").alias("rule_name"),
                    F.lit("HIGH").alias("severity"), F.lit("QUARANTINE").alias("action"),
                    F.lit(f"Accepted parent missing: {parent}").alias("failure_reason"),
                    F.lit(started).alias("quarantine_timestamp"),
                    F.to_json(F.struct(*[F.col(c) for c in SOURCES[ds].columns])).alias("original_values")
                ))
                scorecard.loc[scorecard.dataset.eq(ds), "accepted_records"] -= count
                scorecard.loc[scorecard.dataset.eq(ds), "quarantined_records"] += count
                scorecard.loc[scorecard.dataset.eq(ds), "readiness"] = "WARNING"
        if extras:
            extra = reduce(lambda a, b: a.unionByName(b), extras)
            failures, quarantine = failures.unionByName(extra), quarantine.unionByName(extra)
            if state == "READY":
                state = "WARNING"
        unique_quarantined = quarantine.select("dataset", "source_record_id").distinct().count()
        audit["quarantined_records"] = unique_quarantined
        audit["accepted_records"] = audit["records_received"] - unique_quarantined
        summary = {
            "run_id": run_id, "readiness": state,
            "quality_score": quality_score(results),
            "quarantined_records": unique_quarantined, "failed_rules": audit["failed_checks"],
            "data_label": "REAL OLIST", "execution_timestamp": started,
            "critical_failures": int(((results.severity == "CRITICAL") & (results.status == "FAILED")).sum()),
        }
        for name, frame in {
            "dq_rule_results": results, "dq_dataset_scorecard": scorecard,
            "dq_run_summary": pd.DataFrame([summary])
        }.items():
            append("quality", name, metadata_frame(spark, frame))
        append("quality", "dq_failed_records", failures)
        append("quality", "quarantine", quarantine)
        if state == "BLOCKED":
            audit["status"] = "BLOCKED"
            audit["error_message"] = "A required quality gate failed; existing published Gold snapshot is preserved."
        else:
            for ds, frame in silver.items():
                append("silver", ds, frame.withColumn("pipeline_run_id", F.lit(run_id)))
            governed = {
                ds: spark.table(config.table("silver", ds))
                    .filter(F.col("pipeline_run_id") == run_id).drop("pipeline_run_id")
                for ds in silver
            }
            gold = gold_spark(governed)
            for name, frame in gold.items():
                append("gold", name, frame.withColumn("pipeline_run_id", F.lit(run_id)))
            pointer_table = config.table("quality", "published_run")
            pointer = metadata_frame(spark, pd.DataFrame([{"run_id": run_id}]))
            pointer.write.format("delta").mode("overwrite").saveAsTable(pointer_table)
            audit["status"] = "SUCCEEDED"
            audit["latest_source_event"] = str(
                governed["orders"].agg(F.max("order_purchase_timestamp")).first()[0]
            )
    except Exception as exc:
        audit["status"] = "FAILED"
        audit["error_message"] = f"{type(exc).__name__}: {str(exc)[:500]}"
        raise
    finally:
        audit["ended_at"] = datetime.now(timezone.utc).isoformat()
        audit["duration_seconds"] = (
            pd.Timestamp(audit["ended_at"]) - pd.Timestamp(started)
        ).total_seconds()
        save_audit()
    if audit["status"] == "BLOCKED":
        raise RuntimeError(audit["error_message"])
    return audit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="workspace")
    parser.add_argument("--prefix", default="olist_agentic")
    parser.add_argument("--volume", default="raw")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    config = ETLConfig(args.catalog, args.prefix, args.volume)
    if args.dry_run:
        print(json.dumps({
            "mode": "DRY_RUN",
            "write_schemas": [f"{config.catalog}.{config.schema(x)}" for x in ("bronze", "silver", "gold", "quality")],
            "raw_volume": str(config.volume_path),
            "source_files": len(SOURCES),
            "rules": len(RULES),
            "old_poc_mutated": False,
        }, indent=2))
        return
    from pyspark.sql import SparkSession
    print(json.dumps(execute(SparkSession.builder.getOrCreate(), config), indent=2))


if __name__ == "__main__":
    main()
