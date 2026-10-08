-- Denominator is DISTINCT persistent customers in selected cohort.
-- For filtered dashboard contexts, apply filters inside scoped_orders first.
WITH scoped_orders AS (
  SELECT customer_unique_id
  FROM workspace.olist_semantic.v_published_orders
  WHERE customer_unique_id IS NOT NULL
), per_customer AS (
  SELECT customer_unique_id, COUNT(*) AS order_count
  FROM scoped_orders GROUP BY customer_unique_id
)
SELECT 100.0 * SUM(CASE WHEN order_count > 1 THEN 1 ELSE 0 END)
 / NULLIF(COUNT(*), 0) AS repeat_customer_rate_pct FROM per_customer