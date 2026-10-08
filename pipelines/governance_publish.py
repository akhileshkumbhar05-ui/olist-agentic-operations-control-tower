"""Publish governed semantic metadata to a dedicated Unity Catalog schema.

Run on Databricks Serverless with a Spark session, never against a production catalog
without reviewing the proposed destination. This writer touches ONLY the dedicated
governance schema and never mutates Phase 1 raw, Bronze, Silver, Gold or Quality data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from olist_agentic.config import Config
from olist_agentic.governance.catalog import all_catalogs


IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsupported UC identifier: {value!r}")
    return value


def validate_catalogs() -> dict[str, int]:
    catalogs = all_catalogs()
    if not catalogs:
        raise ValueError("No governance assets were generated.")
    for name, records in catalogs.items():
        if not records:
            raise ValueError(f"Governance table {name} has no records.")
        columns = set(records[0])
        if any(set(record) != columns for record in records):
            raise ValueError(f"Nonuniform metadata columns in {name}.")
    return {name: len(records) for name, records in catalogs.items()}


def publish(spark, config: Config) -> dict[str, int]:
    catalog = _safe_identifier(config.catalog)
    schema = _safe_identifier(config.schema("governance"))
    validate_catalogs()
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS `{catalog}`.`{schema}`")

    counts = {}
    for name, records in all_catalogs().items():
        table_name = _safe_identifier(name)
        table = f"`{catalog}`.`{schema}`.`{table_name}`"
        frame = spark.createDataFrame(records)
        # Only metadata tables are overwritten. No Phase 1 schema/table is targeted.
        (
            frame.write.format("delta")
            .mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(f"{catalog}.{schema}.{table_name}")
        )
        spark.sql(
            f"ALTER TABLE {table} SET TBLPROPERTIES "
            "('olist.logical_owner'='Data Governance', "
            "'olist.classification'='internal governance metadata', "
            "'olist.purpose'='BI, Genie and Agentic Copilot semantics')"
        )
        counts[name] = len(records)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=Config.from_env().catalog)
    parser.add_argument("--schema-prefix", default=Config.from_env().schema_prefix)
    parser.add_argument("--dry-run", action="store_true", help="Validate and print intended writes without importing Spark")
    args = parser.parse_args()
    config = Config(catalog=args.catalog, schema_prefix=args.schema_prefix)
    _safe_identifier(config.catalog)
    _safe_identifier(config.schema("governance"))
    counts = validate_catalogs()
    if args.dry_run:
        print(json.dumps({
            "mode": "DRY_RUN",
            "schema": f"{config.catalog}.{config.schema('governance')}",
            "tables": counts,
        }, indent=2))
        return

    from pyspark.sql import SparkSession

    print(json.dumps({
        "mode": "PUBLISH",
        "schema": f"{config.catalog}.{config.schema('governance')}",
        "tables": counts,
    }, indent=2))
    print(json.dumps(publish(SparkSession.builder.getOrCreate(), config), indent=2))


if __name__ == "__main__":
    main()
