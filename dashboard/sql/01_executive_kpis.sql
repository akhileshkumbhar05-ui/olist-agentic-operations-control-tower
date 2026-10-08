-- Business KPIs from the published metric view. Values in BRL, rates in percentage points.
SELECT
  MEASURE(total_orders) AS total_orders,
  MEASURE(delivered_orders) AS delivered_orders,
  MEASURE(cancelled_orders) AS cancelled_orders,
  MEASURE(gmv) AS delivered_item_gmv_brl,
  MEASURE(freight) AS delivered_freight_brl,
  MEASURE(aov) AS average_delivered_order_value_brl,
  MEASURE(on_time_rate) AS on_time_delivery_pct,
  MEASURE(late_rate) AS late_delivery_pct,
  MEASURE(delivery_days) AS avg_delivery_days,
  MEASURE(delay_days) AS avg_late_delay_days,
  MEASURE(review_score) AS avg_latest_review_score,
  MEASURE(negative_review_rate) AS negative_review_pct
FROM workspace.olist_semantic.mv_order_operations