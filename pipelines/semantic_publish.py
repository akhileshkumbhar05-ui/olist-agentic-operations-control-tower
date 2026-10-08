"""Create Phase 2 semantic assets without modifying the original POC data.

This publisher creates:
- workspace.olist_semantic.v_published_orders (standard view)
- workspace.olist_semantic.mv_order_operations (metric view)

Requires a runtime/warehouse that supports Unity Catalog metric views and
CREATE VIEW WITH METRICS LANGUAGE YAML syntax.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MV_YAML = ROOT / "dashboard" / "metric_views" / "mv_order_operations.yaml"
PUBLISHED_ORDERS_SQL = ROOT / "sql" / "semantic" / "01_published_orders.sql"

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def identifier(s: str) -> str:
    if not IDENT.fullmatch(s):
        raise ValueError(f"Unsafe Databricks SQL identifier: {s!r}")
    return s


def statements(catalog: str = "workspace", prefix: str = "olist") -> list[str]:
    """Pure-Python, no-Spark SQL generation; validates all write destinations."""
    catalog = identifier(catalog)
    prefix = identifier(prefix)
    schema = f"{prefix}_semantic"
    # Files are reviewed POC assets with fixed source identifiers. Generic
    # multi-catalog parameterization is intentionally NOT supported yet.
    if catalog != "workspace" or prefix != "olist":
        raise ValueError("Current semantic assets use fixed workspace.olist_agentic_* sources and workspace.olist_semantic targets; only defaults are supported.")
    base = PUBLISHED_ORDERS_SQL.read_text(encoding="utf-8")
    setup = [
        s.strip() for s in re.sub(r"(?m)^--[^\n]*\n", "", base).split(";")
        if s.strip()
    ]
    if len(setup) != 2:
        raise ValueError("Unexpected number of SQL setup statements.")
    yaml = MV_YAML.read_text(encoding="utf-8")
    if "$$" in yaml:
        raise ValueError("Metric-view definition cannot contain the $$ SQL delimiter.")
    metric_view = (
        f"CREATE OR REPLACE VIEW {catalog}.{schema}.mv_order_operations "
        f"WITH METRICS LANGUAGE YAML AS\n$$\n{yaml.rstrip()}\n$$"
    )
    return setup + [metric_view]


def publish(spark) -> dict[str, str]:
    sql = statements()
    for statement in sql:
        spark.sql(statement)
    return {
        "published_orders": "workspace.olist_semantic.v_published_orders",
        "metric_view": "workspace.olist_semantic.mv_order_operations",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    generated = statements()
    if args.dry_run:
        for i, statement in enumerate(generated, 1):
            print(f"-- Statement {i}\n{statement};\n")
        return

    from pyspark.sql import SparkSession

    print(publish(SparkSession.builder.getOrCreate()))


if __name__ == "__main__":
    main()
