"""Native PySpark quality execution; only rule summaries collect to the driver."""
import json
import pandas as pd
from olist_agentic.domain.rules import RULES
from olist_agentic.etl.quality_engine import FAILURE_COLUMNS, readiness, quality_score


def predicate(rule, tables):
    from pyspark.sql import functions as F, Window
    df = tables[rule.dataset]
    cols = list(rule.columns)
    c = F.col(cols[0])
    if rule.kind == "required":
        condition = c.isNull() | (c == "")
        for name in cols[1:]:
            condition = condition | F.col(name).isNull() | (F.col(name) == "")
    elif rule.kind == "unique":
        df = df.withColumn("_key_count", F.count(F.lit(1)).over(Window.partitionBy(*cols)))
        condition = F.col("_key_count") > 1
        for name in cols:
            condition = condition & F.col(name).isNotNull()
    elif rule.kind == "fk":
        df = df.join(tables[rule.parent].select(F.col(rule.parent_key).alias("_parent_key")).distinct(), c == F.col("_parent_key"), "left")
        condition = c.isNotNull() & F.col("_parent_key").isNull()
    elif rule.kind in {"number", "timestamp"}:
        sql_type = "double" if rule.kind == "number" else "timestamp"
        parsed = F.expr(f"try_cast(`{cols[0]}` as {sql_type})")
        condition = c.isNotNull() & parsed.isNull()
        if rule.kind == "number":
            condition = condition | F.isnan(parsed) | (F.abs(parsed) == float("inf"))
    elif rule.kind == "domain":
        condition = c.isNull() | ~c.isin(list(rule.values))
    elif rule.kind in {"nonnegative", "range"}:
        n = F.expr(f"try_cast(`{cols[0]}` as double)")
        condition = n < 0 if rule.kind == "nonnegative" else (n < float(rule.values[0])) | (n > float(rule.values[1]))
    elif rule.kind == "delivered_required":
        condition = (F.col("order_status") == "delivered") & c.isNull()
    elif rule.kind == "lifecycle":
        condition = F.lit(False)
        for left, right in zip(cols, cols[1:]):
            condition = condition | (F.expr(f"try_cast(`{left}` as timestamp)") > F.expr(f"try_cast(`{right}` as timestamp)"))
        condition = (F.col("order_status") == "delivered") & condition
    elif rule.kind == "reconciliation":
        item = tables["order_items"].groupBy("order_id").agg(F.sum(F.expr("try_cast(price as double) + try_cast(freight_value as double)")).alias("_item_amount"))
        pay = tables["payments"].groupBy("order_id").agg(F.sum(F.expr("try_cast(payment_value as double)")).alias("_pay_amount"))
        df = df.join(item, "order_id", "left").join(pay, "order_id", "left")
        condition = F.abs(F.col("_item_amount") - F.col("_pay_amount")) > 0.010001
    else:
        raise ValueError(rule.kind)
    return df.filter(condition).select(*tables[rule.dataset].columns)


def evaluate_spark(tables, run_id, timestamp, rules=RULES):
    from functools import reduce
    from pyspark.sql import functions as F
    from pyspark.sql.types import StructType, StructField, StringType
    schema = StructType([StructField(col, StringType(), True) for col in FAILURE_COLUMNS])
    spark = next(iter(tables.values())).sparkSession
    results, failure_frames, excluded = [], [], {ds: [] for ds in tables}
    counts = {ds: df.count() for ds, df in tables.items()}
    for rule in rules:
        if not rule.active_flag:
            continue
        original = tables[rule.dataset]
        # Raw engine input contains source_record_id plus original columns only.
        source_columns = [c for c in original.columns if c != "source_record_id"]
        error = ""
        if rule.kind == "schema":
            count = int(set(source_columns) != set(rule.columns))
            bad = original if count else original.limit(0)
            evaluated, status = 1, "FAILED" if count else "PASSED"
        else:
            evaluated = counts[rule.dataset]
            try:
                bad = predicate(rule, tables)
                count = bad.count()
                status = "FAILED" if count else "PASSED"
            except Exception as exc:
                count, status, error = 0, "ERROR", type(exc).__name__
                bad = original  # Safe failure: exclude entire entity, block publication.
        effective_action = "FAIL" if status == "ERROR" else rule.action
        if status == "ERROR":
            evaluated = 0
        ids = [r.source_record_id for r in bad.select("source_record_id").limit(10).collect()]
        results.append({**rule.record(), "run_id": run_id, "execution_timestamp": timestamp,
                        "records_evaluated": evaluated, "records_failed": count,
                        "failure_percentage": 100 * count / evaluated if evaluated else 0.0,
                        "status": status, "error_message": error, "sample_failed_identifiers": json.dumps(ids)})
        if count or status == "ERROR":
            payload = bad.select(F.lit(run_id).alias("run_id"), F.lit(rule.dataset).alias("dataset"),
                "source_record_id", F.lit(rule.rule_id).alias("rule_id"), F.lit(rule.rule_name).alias("rule_name"),
                F.lit(rule.severity).alias("severity"), F.lit(effective_action).alias("action"),
                F.lit(error or rule.description or rule.rule_name).alias("failure_reason"),
                F.lit(timestamp).alias("quarantine_timestamp"),
                F.to_json(F.struct(*[F.col(c) for c in source_columns])).alias("original_values"))
            failure_frames.append(payload)
            if rule.action in {"QUARANTINE", "FAIL"} or status == "ERROR":
                excluded[rule.dataset].append(bad.select("source_record_id"))
    failures = reduce(lambda a, b: a.unionByName(b), failure_frames) if failure_frames else spark.createDataFrame([], schema)
    quarantine = failures.filter(F.col("action").isin("QUARANTINE", "FAIL"))
    accepted = {}
    scorecard = []
    result_frame = pd.DataFrame(results)
    for ds, original in tables.items():
        rejects = reduce(lambda a, b: a.unionByName(b), excluded[ds]).distinct() if excluded[ds] else original.select("source_record_id").limit(0)
        accepted[ds] = original.join(rejects, "source_record_id", "left_anti")
        rejected = rejects.count()
        r = result_frame[result_frame.dataset.eq(ds)]
        scorecard.append({"run_id": run_id, "dataset": ds, "quality_score": quality_score(r), "readiness": readiness(r),
                          "rules_executed": len(r), "rules_failed": int(r.status.eq("FAILED").sum()),
                          "source_records": counts[ds], "accepted_records": counts[ds] - rejected, "quarantined_records": rejected})
    return result_frame, failures, quarantine, pd.DataFrame(scorecard), accepted
