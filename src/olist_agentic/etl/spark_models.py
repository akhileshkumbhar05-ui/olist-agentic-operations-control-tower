"""Native Spark transformations, keeping facts at documented grains."""
from olist_agentic.domain.sources import SOURCES


def standardize_spark(tables):
    from pyspark.sql import functions as F
    silver = {}
    for ds, df in tables.items():
        for col in SOURCES[ds].numeric:
            df = df.withColumn(col, F.col(col).cast("double"))
        for col in SOURCES[ds].timestamps:
            df = df.withColumn(col, F.col(col).cast("timestamp"))
        silver[ds] = df
    cascades = []
    for child, fk, parent, pk in [("orders", "customer_id", "customers", "customer_id"), ("order_items", "order_id", "orders", "order_id"), ("order_items", "product_id", "products", "product_id"), ("order_items", "seller_id", "sellers", "seller_id"), ("payments", "order_id", "orders", "order_id"), ("reviews", "order_id", "orders", "order_id")]:
        df = silver[child]
        keys = silver[parent].select(F.col(pk).alias("_parent_key")).distinct()
        rejected = df.join(keys, F.col(fk) == F.col("_parent_key"), "left_anti")
        cascades.append((child, parent, rejected))
        silver[child] = df.join(keys, F.col(fk) == F.col("_parent_key"), "left_semi")
    geo = silver["geolocation"]
    canonical = geo.groupBy("geolocation_zip_code_prefix").agg(F.median("geolocation_lat").alias("geolocation_lat"), F.median("geolocation_lng").alias("geolocation_lng"), F.count("*").alias("observation_count"))
    from pyspark.sql import Window
    for field in ("geolocation_city", "geolocation_state"):
        modes = geo.filter(F.col(field).isNotNull()).groupBy("geolocation_zip_code_prefix", field).count()
        w = Window.partitionBy("geolocation_zip_code_prefix").orderBy(F.desc("count"), F.asc(field))
        modes = modes.withColumn("_rn", F.row_number().over(w)).filter("_rn = 1").select("geolocation_zip_code_prefix", field)
        canonical = canonical.join(modes, "geolocation_zip_code_prefix", "left")
    silver["geolocation"] = canonical
    return silver, cascades


def assert_spark_grain(df, keys):
    from pyspark.sql import functions as F
    condition = F.lit(False)
    for key in keys:
        condition = condition | F.col(key).isNull()
    if df.filter(condition).limit(1).count() or df.groupBy(*keys).count().filter("count > 1").limit(1).count():
        raise ValueError(f"Broken grain: {keys}")


def gold_spark(silver):
    spark = silver["orders"].sparkSession
    for ds, df in silver.items():
        df.createOrReplaceTempView(f"s_{ds}")
    fact = spark.sql("""
      WITH items AS (SELECT order_id, sum(price) item_gmv, sum(freight_value) freight_value,
          count(*) item_count, count(distinct seller_id) seller_count FROM s_order_items GROUP BY order_id),
      payments AS (SELECT order_id, sum(payment_value) payment_total, count(*) payment_count FROM s_payments GROUP BY order_id),
      reviews_ranked AS (SELECT order_id, review_score, row_number() OVER
          (PARTITION BY order_id ORDER BY review_answer_timestamp DESC NULLS LAST, review_id DESC) rn FROM s_reviews)
      SELECT o.*, c.customer_unique_id, c.customer_state, i.item_gmv, i.freight_value, i.item_count, i.seller_count,
          p.payment_total, p.payment_count, r.review_score, cast(cast(o.order_purchase_timestamp as date) as string) purchase_date,
          o.order_status = 'delivered' is_delivered, o.order_status = 'canceled' is_cancelled,
          o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND o.order_estimated_delivery_date IS NOT NULL delivery_eligible,
          coalesce(o.order_status = 'delivered' AND cast(o.order_delivered_customer_date as date)
            > cast(o.order_estimated_delivery_date as date), false) is_late,
          CASE WHEN o.order_status = 'delivered' AND o.order_delivered_customer_date >= o.order_purchase_timestamp
            THEN cast(unix_timestamp(o.order_delivered_customer_date) - unix_timestamp(o.order_purchase_timestamp) as double) / 86400.0 END delivery_days,
          CASE WHEN o.order_status = 'delivered' AND o.order_delivered_customer_date IS NOT NULL
            AND o.order_estimated_delivery_date IS NOT NULL
            THEN greatest(datediff(o.order_delivered_customer_date, o.order_estimated_delivery_date), 0) END delay_days
      FROM s_orders o LEFT JOIN s_customers c ON o.customer_id = c.customer_id
        LEFT JOIN items i ON o.order_id = i.order_id LEFT JOIN payments p ON o.order_id = p.order_id
        LEFT JOIN reviews_ranked r ON o.order_id = r.order_id AND r.rn = 1
    """)
    assert_spark_grain(fact, ["order_id"])
    if fact.count() != silver["orders"].count():
        raise ValueError("Order row count mismatch")
    fact.createOrReplaceTempView("g_fact_orders")
    item = spark.sql("""
      SELECT i.*, p.product_category_name, t.product_category_name_english,
        coalesce(t.product_category_name_english, p.product_category_name, 'Unknown') category,
        o.purchase_date, o.customer_state, o.order_status, o.delivery_eligible, o.is_late,
        o.delivery_days, o.delay_days, o.review_score
      FROM s_order_items i JOIN s_products p ON i.product_id = p.product_id
        LEFT JOIN s_translation t ON p.product_category_name = t.product_category_name
        JOIN g_fact_orders o ON i.order_id = o.order_id
    """)
    assert_spark_grain(item, ["order_id", "order_item_id"])
    if item.count() != silver["order_items"].count():
        raise ValueError("Item row count mismatch")
    return {"fact_orders": fact, "fact_order_items": item, "dim_customer": silver["customers"],
            "dim_product": silver["products"], "dim_seller": silver["sellers"], "dim_geography": silver["geolocation"]}
