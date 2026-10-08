-- Purchase cohort trends. Historical data, NOT real-time operational activity.
SELECT purchase_month,
  MEASURE(total_orders) AS total_orders,
  MEASURE(delivered_orders) AS delivered_orders,
  MEASURE(gmv) AS delivered_item_gmv_brl,
  MEASURE(late_rate) AS late_delivery_pct
FROM workspace.olist_semantic.mv_order_operations
GROUP BY purchase_month
ORDER BY purchase_month