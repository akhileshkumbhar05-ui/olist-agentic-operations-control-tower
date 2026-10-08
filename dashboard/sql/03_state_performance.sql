-- Descriptive associations only: geographic differences do not prove causes.
SELECT customer_state,
  MEASURE(total_orders) AS total_orders,
  MEASURE(delivered_orders) AS delivered_orders,
  MEASURE(gmv) AS delivered_item_gmv_brl,
  MEASURE(late_rate) AS late_delivery_pct,
  MEASURE(on_time_rate) AS on_time_delivery_pct
FROM workspace.olist_semantic.mv_order_operations
GROUP BY customer_state
ORDER BY total_orders DESC