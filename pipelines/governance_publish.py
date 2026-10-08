"""Publish governed semantic metadata to the dedicated Unity Catalog governance schema."""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from olist_agentic.config import Config
from olist_agentic.governance.catalog import all_catalogs


def publish(spark, config: Config) -> dict[str, int]:
    schema = config.schema("governance")
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {config.catalog}.{schema}")

    counts: dict[str, int] = {}
    for name, records in all_catalogs().items():
        if not records:
            continue
        frame = spark.createDataFrame(records)
        table = config.table("governance", name)
        (
            frame.write.format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(table)
        )
        spark.sql(
            f"ALTER TABLE {table} SET TBLPROPERTIES "
            "('olist.logical_owner'='Data Governance', "
            "'olist.classification'='internal governance metadata', "
            "'olist.purpose'='BI, Genie and Agentic Copilot semantics')"
        )
        counts[name] = frame.count()

    return counts


if __name__ == "__main__":
    from pyspark.sql import SparkSession

    result = publish(SparkSession.builder.getOrCreate(), Config.from_env())
    print(result)
